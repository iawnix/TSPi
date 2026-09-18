from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = ROOT / "contracts" / "ts-web"


def _read_json(name: str) -> dict[str, object]:
    return json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))


def test_projection_contract_is_consumable_without_ts_agent_imports() -> None:
    request_schema = _read_json("workspace-request.schema.json")
    snapshot_schema = _read_json("workspace-snapshot.schema.json")
    error_schema = _read_json("error.schema.json")
    fixture = _read_json("workspace-snapshot.fixture.json")

    Draft202012Validator(request_schema).validate(
        {"schema_version": "ts-web-workspace-request/1", "workspace_id": "ws_fixture"}
    )
    Draft202012Validator(snapshot_schema).validate(fixture)
    Draft202012Validator(error_schema).validate(
        {"schema_version": "ts-web-error/1", "error": "workspace unavailable", "retryable": True}
    )


def test_projection_contract_rejects_private_provider_fields_and_unknown_request_fields() -> None:
    request_schema = _read_json("workspace-request.schema.json")
    snapshot_schema = _read_json("workspace-snapshot.schema.json")
    fixture = _read_json("workspace-snapshot.fixture.json")

    request_errors = list(
        Draft202012Validator(request_schema).iter_errors(
            {
                "schema_version": "ts-web-workspace-request/1",
                "workspace_id": "ws_fixture",
                "source_root": "/private/workspace",
            }
        )
    )
    assert request_errors

    changed_snapshot = json.loads(json.dumps(fixture))
    changed_snapshot["workspace"]["source_root"] = "/private/workspace"
    snapshot_errors = list(Draft202012Validator(snapshot_schema).iter_errors(changed_snapshot))
    assert snapshot_errors
