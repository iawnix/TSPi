from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PYTHON = ROOT / "packages" / "research-agent-contracts" / "python"
if str(CONTRACT_PYTHON) not in sys.path:
    sys.path.insert(0, str(CONTRACT_PYTHON))

from research_agent_contracts import ContractError, read_schema, schema_names, validate  # noqa: E402


def _valid(name: str) -> dict:
    digest = "sha256:" + "a" * 64
    if name == "agent_turn_request":
        return {
            "protocol": name, "version": 1, "request_id": "req_fixture",
            "workspace_id": "workspace_fixture", "session_id": "session_fixture", "input": "run task",
        }
    if name == "agent_turn_result":
        return {
            "protocol": name, "version": 1, "request_id": "req_fixture", "status": "completed",
            "output": {}, "provenance": {"producer": "fixture", "request_digest": digest},
        }
    if name == "research_turn_request":
        return {
            "protocol": name, "version": 1, "request_id": "request_fixture",
            "workspace_id": "workspace_fixture", "operation": "plan", "input": {},
        }
    if name == "research_turn_result":
        return {
            "protocol": name, "version": 1, "request_id": "req_fixture", "status": "completed",
            "output": {}, "provenance": {"producer": "fixture", "request_digest": digest},
        }
    if name == "tool_result":
        return {
            "protocol": name, "version": 1, "tool_name": "read_data", "tool_call_id": "call_fixture",
            "status": "ok", "output": {"value": 1},
        }
    if name == "tool_error":
        return {
            "protocol": name, "version": 1, "tool_name": "read_data", "tool_call_id": "call_fixture",
            "error_code": "invalid_input", "message": "fixture", "retryable": False,
            "failure_class": "validation",
        }
    if name == "capability_descriptor":
        return {
            "protocol": name, "version": 1, "capability_id": "fixture_read",
            "capability_version": "1", "kind": "analysis", "summary": "Fixture capability",
            "input_schema": {"type": "object"}, "output_schema": {"type": "object"},
            "supported_workspace_modes": ["light", "research"],
            "provider": {"provider_id": "fixture", "provider_version": "1", "descriptor_digest": digest},
        }
    if name == "notification_request":
        return {
            "protocol": name, "version": 1, "operation": "send",
            "event": "study_completed", "subject": "Fixture notification",
            "summary": "The fixture study completed.", "report_refs": [],
        }
    if name == "notification_result":
        return {
            "protocol": name, "version": 1, "operation": "send", "state": "sent",
            "receipt_ref": "reports/notifications/fixture.json", "external_side_effects": True,
        }
    return {
        "protocol": "artifact_manifest", "version": 1, "artifact_id": "art_fixture",
        "artifact_type": "text", "logical_ref": "nodes/node_1/outputs/result.json", "digest": digest,
        "size_bytes": 1,
        "producer": {"provider_id": "fixture", "provider_version": "1", "operation": "read_data", "operation_version": "1"},
        "provenance": {"input_artifacts": []},
    }


def test_contract_set_uses_only_underscore_protocol_names_and_is_self_describing() -> None:
    names = schema_names()
    assert names == (
        "agent_turn_request", "agent_turn_result",
        "research_turn_request", "research_turn_result", "tool_result", "tool_error",
        "capability_descriptor", "notification_request", "notification_result", "artifact_manifest",
    )
    assert all("." not in name and "-" not in name for name in names)
    for name in names:
        schema = read_schema(name)
        assert schema["$id"] == name
        validate(name, _valid(name))


def test_contract_validation_fails_closed_without_old_aliases() -> None:
    request = _valid("research_turn_request")
    request["protocol"] = "research.turn.request"
    with pytest.raises(ContractError, match="research_turn_request"):
        validate("research_turn_request", request)
    with pytest.raises(ContractError, match="unknown"):
        read_schema("research.turn.request")


def test_artifact_manifest_excludes_physical_path_and_requires_provenance() -> None:
    manifest = _valid("artifact_manifest")
    assert "path" not in manifest
    manifest["provenance"] = {}
    with pytest.raises(ContractError, match="input_artifacts"):
        validate("artifact_manifest", manifest)


def test_capability_descriptor_requires_explicit_workspace_mode_admission() -> None:
    descriptor = _valid("capability_descriptor")
    for modes in (None, [], ["light", "light"], ["sandbox"]):
        candidate = dict(descriptor)
        if modes is None:
            candidate.pop("supported_workspace_modes")
        else:
            candidate["supported_workspace_modes"] = modes
        with pytest.raises(ContractError, match="supported_workspace_modes"):
            validate("capability_descriptor", candidate)
