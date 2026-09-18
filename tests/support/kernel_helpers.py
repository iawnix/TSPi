"""Test-only adapters for inspecting the private kernel transaction stages.

Production callers use ``ts_change``/``change_workspace``.  A few kernel tests
need to forge a compiled transaction in order to exercise stale revisions,
rollback, and schema guards; those tests use this module rather than reviving
the removed public draft/validate/apply API.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ts_agent.workspace.decision import _compile_change
from ts_agent.workspace.engine import _apply_decision, _validate_decision_dry_run


def complete_request(value: dict[str, Any]) -> dict[str, Any]:
    request = deepcopy(value)
    request.setdefault("schema_version", "ts-change-request/1")
    for operation in request.get("operations", []):
        if not isinstance(operation, dict) or operation.get("op") != "create_claim":
            continue
        statement = str(operation.get("statement") or "A bounded scientific claim requires evaluation.")
        operation.setdefault("question", "What evidence would test this bounded Claim?")
        operation.setdefault("scope", "The explicitly referenced test fixture and its declared assumptions.")
        operation.setdefault("uncertainty", "The Claim remains uncertain until its declared observations are evaluated.")
        operation.setdefault("predictions", [f"Observable evidence is consistent with: {statement}"])
        operation.setdefault("falsifiers", [f"Observable evidence contradicts: {statement}"])
    return request


def compile_change(root: str | Path, request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return _compile_change(root, complete_request(request), **kwargs)


def validate_compiled_change(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    return _validate_decision_dry_run(root, decision)


def apply_compiled_change(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    return _apply_decision(root, decision)
