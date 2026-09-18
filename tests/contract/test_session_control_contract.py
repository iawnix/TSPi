from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2] / "contracts" / "tspi-session-control" / "1"


def _schema(name: str) -> dict[str, object]:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_session_control_contract_covers_prompt_abort_queue_and_events() -> None:
    request = Draft202012Validator(_schema("session-control-request.schema.json"))
    response = Draft202012Validator(_schema("session-control-response.schema.json"))
    event = Draft202012Validator(_schema("session-event.schema.json"))
    base = {
        "schema_version": "tspi-session-control/1",
        "request_id": "phone-1",
        "session_id": "session-a",
    }
    request.validate({**base, "action": "prompt", "message": "hello"})
    request.validate({**base, "action": "abort", "operation_id": "op-1"})
    request.validate({**base, "action": "queue", "mode": "follow_up", "message": "later"})
    response.validate({**base, "action": "prompt", "accepted": True, "operation_id": "op-1", "error": None})
    response.validate({**base, "action": "queue", "accepted": True, "entry_id": "entry-1", "error": None})
    event.validate(
        {
            "schema_version": "tspi-session-event/1",
            "session_id": "session-a",
            "sequence": 1,
            "kind": "event",
            "snapshot": {},
            "event": {"type": "run_start"},
        }
    )


def test_session_control_contract_rejects_missing_idempotency_and_operation_fields() -> None:
    request = Draft202012Validator(_schema("session-control-request.schema.json"))
    errors = list(
        request.iter_errors(
            {
                "schema_version": "tspi-session-control/1",
                "request_id": "",
                "session_id": "session-a",
                "action": "prompt",
            }
        )
    )
    assert errors
    errors = list(
        request.iter_errors(
            {
                "schema_version": "tspi-session-control/1",
                "request_id": "phone-2",
                "session_id": "session-a",
                "action": "abort",
            }
        )
    )
    assert errors
