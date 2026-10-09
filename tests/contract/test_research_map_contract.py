from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from research_state.workspace_catalog import WorkspaceCatalog, WorkspaceCatalogError, workspace_id_for
from research_state.web import ResearchWebError, handle_request, register_sources
from research_state.workspace import admit_research_workspace, initialize_workspace


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = ROOT / "contracts" / "ts-web"


def _read_json(name: str) -> dict[str, object]:
    return json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))


def _provider_request(**values: object) -> dict[str, object]:
    return {
        "schema_version": "research-map-provider/1",
        "request_id": "contract-check",
        "operation": "catalog",
        "workspace_id": None,
        "route": None,
        "query": {},
        **values,
    }


def _init_workspace(root: Path, workspace_id: str | None = None) -> dict[str, object]:
    """Create the current canonical research workspace fixture."""

    identifier = workspace_id or f"workspace_{root.name}"
    manifest = initialize_workspace(root, identifier, "research")
    if manifest["state"] == "admission_pending":
        manifest = admit_research_workspace(root)
    return manifest


def test_research_map_transport_contracts_are_consistent() -> None:
    request_schema = _read_json("provider-request.schema.json")
    response_schema = _read_json("provider-response.schema.json")
    map_response_schema = _read_json("research-map-response.schema.json")
    error_schema = _read_json("error.schema.json")
    fixture = _read_json("research-map-response.fixture.json")

    for schema in (request_schema, response_schema, map_response_schema, error_schema):
        Draft202012Validator.check_schema(schema)
    Draft202012Validator(request_schema).validate(_provider_request())
    Draft202012Validator(map_response_schema).validate(fixture)
    response_validator = Draft202012Validator(
        response_schema,
        registry=Registry().with_resource(
            error_schema["$id"],
            Resource.from_contents(error_schema),
        ),
    )
    response_validator.validate(
        {
            "schema_version": "research-map-provider/1",
            "request_id": "contract-check",
            "ok": True,
            "payload": fixture,
        }
    )
    Draft202012Validator(error_schema).validate(
        {
            "schema_version": "research-map-error/1",
            "error": "workspace unavailable",
            "retryable": True,
        }
    )
    response_validator.validate(
        {
            "schema_version": "research-map-provider/1",
            "request_id": "contract-check",
            "ok": False,
            "error": {
                "schema_version": "research-map-error/1",
                "error": "workspace unavailable",
                "retryable": True,
            },
        }
    )


def test_research_map_contract_rejects_private_provider_fields() -> None:
    request_schema = _read_json("provider-request.schema.json")
    map_response_schema = _read_json("research-map-response.schema.json")
    fixture = _read_json("research-map-response.fixture.json")

    request = _provider_request(source_root="/private/workspace")
    assert list(Draft202012Validator(request_schema).iter_errors(request))

    fixture["workspace"]["source_root"] = "/private/workspace"
    assert list(Draft202012Validator(map_response_schema).iter_errors(fixture))


def test_provider_map_route_returns_the_canonical_research_map(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _init_workspace(workspace)
    workspace_id = register_sources(state_dir, [workspace])[0]["workspace_id"]

    payload = handle_request(
        state_dir,
        _provider_request(
            operation="route",
            workspace_id=workspace_id,
            route="map",
        ),
    )

    Draft202012Validator(_read_json("research-map-response.schema.json")).validate(payload)
    assert payload["map"]["map_id"] == f"map_{workspace_id}"
    assert payload["map"]["revision"] == 0
    assert payload["map"]["phases"] == []
    assert "source_root" not in payload["workspace"]

    with pytest.raises(ResearchWebError, match="unknown workspace route"):
        handle_request(
            state_dir,
            _provider_request(
                operation="route",
                workspace_id=workspace_id,
                route="snapshot",
            ),
        )


def test_provider_serves_new_filesystem_research_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _init_workspace(workspace, "workspace_filesystem")

    workspace_id = register_sources(state_dir, [workspace])[0]["workspace_id"]
    assert workspace_id == "workspace_filesystem"
    catalog = handle_request(state_dir, _provider_request())
    assert catalog["workspaces"][0]["available"] is True
    payload = handle_request(
        state_dir,
        _provider_request(operation="route", workspace_id=workspace_id, route="map"),
    )

    Draft202012Validator(_read_json("research-map-response.schema.json")).validate(payload)
    assert payload["map"]["map_id"] == f"map_{workspace_id}"
    assert payload["map"]["revision"] == 0
    assert not (workspace / "research_map.json").exists()
    assert not (workspace / "research.db").exists()


def test_provider_does_not_expose_an_admission_pending_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _init_workspace(workspace)
    workspace_id = register_sources(state_dir, [workspace])[0]["workspace_id"]

    # Simulate the durable files during a Host admission transition.  The
    # registry may retain the row while the workspace is being admitted, but
    # the read-only Web boundary must not publish that internal state.
    manifest_path = workspace / "workspace_manifest.json"
    context_path = workspace / "research_map" / "context.json"
    liveness_path = workspace / "lifecycle" / "liveness.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    context = json.loads(context_path.read_text(encoding="utf-8"))
    liveness = json.loads(liveness_path.read_text(encoding="utf-8"))
    manifest["state"] = "admission_pending"
    context["lifecycle_state"] = "admission_pending"
    liveness["state"] = "admission_pending"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    context_path.write_text(json.dumps(context), encoding="utf-8")
    liveness_path.write_text(json.dumps(liveness), encoding="utf-8")

    with pytest.raises(ResearchWebError, match="unknown or invalid workspace id"):
        handle_request(
            state_dir,
            _provider_request(operation="route", workspace_id=workspace_id, route="map"),
        )


def test_provider_rejects_a_non_array_research_collection(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _init_workspace(workspace)
    context_path = workspace / "research_map" / "context.json"
    context = json.loads(context_path.read_text(encoding="utf-8"))
    context["attempts"] = {}
    context_path.write_text(json.dumps(context), encoding="utf-8")
    with pytest.raises(ValueError, match="workspace is not an initialized Research Agent workspace"):
        register_sources(state_dir, [workspace])


def test_workspace_discovery_supports_read_only_workspace_roots(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _init_workspace(workspace, "workspace_filesystem")
    workspace.chmod(0o555)
    try:
        rows = WorkspaceCatalog(tmp_path).list()
    finally:
        workspace.chmod(0o755)
    assert [row["source_root"] for row in rows] == [str(workspace)]


def test_provider_serves_catalog_and_map_from_read_only_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _init_workspace(workspace)
    workspace_id = register_sources(state_dir, [workspace])[0]["workspace_id"]
    workspace.chmod(0o555)
    try:
        catalog = handle_request(state_dir, _provider_request())
        assert catalog["workspaces"][0]["available"] is True
        payload = handle_request(
            state_dir,
            _provider_request(operation="route", workspace_id=workspace_id, route="map"),
        )
        context = json.loads((workspace / "research_map" / "context.json").read_text(encoding="utf-8"))
        assert payload["map"]["map_id"] == context["map_id"]
    finally:
        workspace.chmod(0o755)


def test_registry_uses_canonical_workspace_identity(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _init_workspace(workspace)

    assert workspace_id_for(workspace) == "workspace_workspace"
    registered = register_sources(state_dir, [workspace])[0]
    assert registered["workspace_id"] == "workspace_workspace"
    catalog = handle_request(state_dir, _provider_request())
    assert catalog["workspaces"][0]["workspace_id"] == "workspace_workspace"


def test_registry_keeps_path_id_fallback_for_uninitialized_directory(tmp_path: Path) -> None:
    source = tmp_path / "legacy"
    source.mkdir()
    with pytest.raises(ValueError, match="not an initialized Research Agent workspace"):
        workspace_id_for(source)


def test_catalog_does_not_import_an_obsolete_web_registry(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    _init_workspace(workspace)
    state_dir.mkdir()
    legacy = {"schema_version": "research-web-registry/1", "workspaces": [{
        "workspace_id": "ws_obsolete", "source_root": str(workspace), "label": "legacy"}]}
    path = state_dir / "workspaces.json"
    path.write_text(json.dumps(legacy))
    assert handle_request(state_dir, _provider_request())["workspaces"] == []
    with pytest.raises(ResearchWebError, match="unknown or invalid workspace id"):
        handle_request(state_dir, _provider_request(operation="route", workspace_id="ws_obsolete", route="map"))
    assert json.loads(path.read_text()) == legacy


def test_workspace_id_contract_agrees_across_exported_schemas_and_runtime():
    from tspi_foundation.protocol import WORKSPACE_ID_PATTERN

    shared = json.loads((ROOT / 'packages/tspi-foundation/tspi_foundation/protocol.json').read_text())
    schemas = [
        json.loads((ROOT / 'contracts/ts-web/provider-request.schema.json').read_text())['properties']['workspace_id'],
        json.loads((ROOT / 'contracts/ts-web/research-map-response.schema.json').read_text())['properties']['workspace']['properties']['workspace_id'],
    ]
    for schema in schemas:
        assert schema['pattern'] == shared['workspace_id']['pattern']
        validator = Draft202012Validator(schema)
        for value in ['project-a', 'a' * 80, 'A_1.2-3']:
            assert WORKSPACE_ID_PATTERN.fullmatch(value) and validator.is_valid(value)
        for value in ['a' * 81, 'project-a\n', 'project-a\r\n', '../project', 'a/b', '.hidden', 'a:b', '']:
            assert WORKSPACE_ID_PATTERN.fullmatch(value) is None and not validator.is_valid(value)


def test_workspace_doctor_checks_current_state_without_parsing_retired_files(tmp_path):
    from research_state.doctor import inspect_workspace

    workspace = tmp_path / 'workspace'
    _init_workspace(workspace)
    assert inspect_workspace(workspace)['valid'] is True
    obsolete = workspace / 'research.db'
    obsolete.write_bytes(b'unsupported storage: do not parse or repair')
    before = obsolete.read_bytes()
    result = inspect_workspace(workspace)
    assert result['valid'] is False
    assert any(row['code'] == 'unsupported_workspace_storage' for row in result['findings'])
    assert set(result['sources']) == {'manifest', 'context'}
    assert obsolete.read_bytes() == before
