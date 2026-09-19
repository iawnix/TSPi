from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from ts_agent.research import ResearchKernel
from ts_agent.research.web import ResearchWebError, handle_request, register_sources
from ts_agent.workspace import init_workspace


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
