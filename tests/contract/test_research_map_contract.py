from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from ts_agent.research import ResearchKernel
from ts_agent.research.registry import (
    reconcile_workspace_registry,
    workspace_id_for,
)
from ts_agent.research.web import ResearchWebError, handle_request, register_sources
from ts_agent.workspace import init_workspace
from ts_agent.workspace.identity import workspace_id as canonical_workspace_id


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
    init_workspace(workspace)
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
    assert payload["map"] == ResearchKernel(workspace).load().to_dict()
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


def test_workspace_discovery_supports_read_only_workspace_roots(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    init_workspace(workspace)
    (workspace / ".research-map.lock").unlink()
    workspace.chmod(0o555)
    try:
        rows = reconcile_workspace_registry(state_dir, [tmp_path])
    finally:
        workspace.chmod(0o755)
    assert [row["source_root"] for row in rows] == [str(workspace)]


def test_provider_serves_catalog_and_map_from_read_only_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    init_workspace(workspace)
    workspace_id = register_sources(state_dir, [workspace])[0]["workspace_id"]
    (workspace / ".research-map.lock").unlink()
    workspace.chmod(0o555)
    try:
        catalog = handle_request(state_dir, _provider_request())
        assert catalog["workspaces"][0]["available"] is True
        payload = handle_request(
            state_dir,
            _provider_request(operation="route", workspace_id=workspace_id, route="map"),
        )
        map_document = json.loads((workspace / "research_map.json").read_text(encoding="utf-8"))
        assert payload["map"]["map_id"] == map_document["map_id"]
    finally:
        workspace.chmod(0o755)


def test_registry_uses_canonical_workspace_identity(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    init_workspace(workspace)

    assert workspace_id_for(workspace) == canonical_workspace_id(workspace)
    registered = register_sources(state_dir, [workspace])[0]
    assert registered["workspace_id"] == canonical_workspace_id(workspace)
    catalog = handle_request(state_dir, _provider_request())
    assert catalog["workspaces"][0]["workspace_id"] == canonical_workspace_id(workspace)


def test_registry_keeps_path_id_fallback_for_uninitialized_directory(tmp_path: Path) -> None:
    source = tmp_path / "legacy"
    source.mkdir()
    expected = "ws_" + hashlib.sha256(str(source.resolve()).encode("utf-8")).hexdigest()[:12]
    assert workspace_id_for(source) == expected


def test_registry_migrates_short_path_id_and_keeps_legacy_route(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    state_dir = tmp_path / "state"
    init_workspace(workspace)
    state_dir.mkdir()
    legacy_id = "ws_" + hashlib.sha256(str(workspace.resolve()).encode("utf-8")).hexdigest()[:12]
    (state_dir / "workspaces.json").write_text(
        json.dumps({
            "schema_version": "research-web-registry/1",
            "workspaces": [{
                "workspace_id": legacy_id,
                "source_root": str(workspace.resolve()),
                "label": "legacy",
                "registered_at": "2026-01-01T00:00:00Z",
            }],
        }),
        encoding="utf-8",
    )

    rows = reconcile_workspace_registry(state_dir, [tmp_path])
    canonical = canonical_workspace_id(workspace)
    assert rows[0]["workspace_id"] == canonical
    assert legacy_id in rows[0]["legacy_workspace_ids"]
    persisted = json.loads((state_dir / "workspaces.json").read_text(encoding="utf-8"))
    assert persisted["workspaces"][0]["workspace_id"] == canonical
    assert legacy_id in persisted["workspaces"][0]["legacy_workspace_ids"]

    payload = handle_request(
        state_dir,
        _provider_request(operation="route", workspace_id=legacy_id, route="map"),
    )
    assert payload["workspace"]["workspace_id"] == canonical
    assert payload["map"]["map_id"] == canonical
