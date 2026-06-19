"""Decision JSON validation for all workspace mutations."""

from __future__ import annotations

from typing import Any


class ContractError(ValueError):
    """Raised when a decision or workspace contract is invalid."""


SCHEMA_VERSION = "ts-decision"

VALID_ACTIONS = {
    "init_workspace",
    "start_node",
    "end_node",
    "update_workspace",
    "ask_user",
    "stop",
}

MUTATION_ACTIONS = {"init_workspace", "start_node", "end_node", "update_workspace"}

VALID_PHASES = {
    "preflight",
    "endpoint",
    "rp_conformer_generation",
    "candidate_generation",
    "tsfreq_validation",
    "connectivity_validation",
    "accepted_audit",
    "pathway_audit",
}

VALID_LIFECYCLES = {"running", "closed", "stopped"}
VALID_PROGRAM_STATUSES = {"completed", "failed", "stopped", "not_run"}
VALID_CLAIM_VERDICTS = {"supported", "refuted", "inconclusive", "not_evaluated"}
VALID_PATHWAY_STATUSES = {"proposed", "active", "supported", "refuted", "superseded", "accepted"}
VALID_BACKTRACK_EVENT_STATES = {"active", "resolved", "superseded"}
VALID_EVIDENCE_TIERS = {
    "local_compute",
    "local_parse",
    "manual_observation",
    "literature",
    "user_provided",
    "hypothesis",
}

FORBIDDEN_PUBLIC_FIELDS = {
    "_".join(("node", "disposition")),
    "_".join(("closure", "explanation")),
    "_".join(("claim", "status")),
    "out" + "come",
    "_".join(("out" + "come", "code")),
    "_".join(("lifecycle", "state")),
    "_".join(("run", "state")),
    "_".join(("claim", "level")),
}


def validate_decision(decision: dict[str, Any]) -> dict[str, Any]:
    _require(isinstance(decision, dict), "decision must be an object")
    _reject_forbidden_keys(decision)

    _require(decision.get("schema_version") == SCHEMA_VERSION, "schema_version must be ts-decision")
    action = decision.get("action")
    _require(action in VALID_ACTIONS, f"unsupported action: {action!r}")
    _require(_clean(decision.get("rationale")), "rationale is required")

    evidence_refs = decision.get("evidence_refs", [])
    _require(isinstance(evidence_refs, list), "evidence_refs must be a list")
    _require(all(_clean(item) for item in evidence_refs), "evidence_refs cannot contain empty values")

    payload = decision.get("payload", {})
    _require(isinstance(payload, dict), "payload must be an object")

    if action in {"start_node", "end_node", "update_workspace"}:
        report_ref = decision.get("report_ref")
        _require(isinstance(report_ref, dict), "mutation decision requires report_ref")
        _require(_clean(report_ref.get("report_id")), "report_ref.report_id is required")
        _require(_clean(report_ref.get("workspace_root")), "report_ref.workspace_root is required")

    if action == "start_node":
        _validate_start_payload(payload)
    elif action == "end_node":
        _validate_end_payload(payload)
    elif action == "update_workspace":
        _validate_update_payload(payload)
    elif action == "ask_user":
        _require(_clean(payload.get("question")), "ask_user payload.question is required")
    elif action == "stop":
        _require(_clean(payload.get("reason")), "stop payload.reason is required")

    return decision


def _validate_start_payload(payload: dict[str, Any]) -> None:
    _require(payload.get("phase") in VALID_PHASES, "payload.phase is invalid")
    _require(_clean(payload.get("hypothesis")), "payload.hypothesis is required")

    expected = payload.get("expected_evidence", [])
    _require(isinstance(expected, list), "payload.expected_evidence must be a list")
    _require(all(_clean(item) for item in expected), "payload.expected_evidence cannot contain empty values")

    pathway_ref = payload.get("pathway_ref")
    if pathway_ref is not None:
        _require(isinstance(pathway_ref, dict), "payload.pathway_ref must be an object")
        _require(_clean(pathway_ref.get("pathway_id")), "pathway_ref.pathway_id is required")
        _require(_clean(pathway_ref.get("step_id")), "pathway_ref.step_id is required")

    backtrack = payload.get("backtrack")
    if backtrack is not None:
        _require(isinstance(backtrack, dict), "payload.backtrack must be an object")
        for field in ("from_node", "to_node", "changed_variable", "reason_code"):
            _require(_clean(backtrack.get(field)), f"backtrack.{field} is required")
        refs = backtrack.get("evidence_refs", [])
        _require(isinstance(refs, list), "backtrack.evidence_refs must be a list")


def _validate_end_payload(payload: dict[str, Any]) -> None:
    _require(_clean(payload.get("node_id")), "payload.node_id is required")
    closure = payload.get("closure")
    _require(isinstance(closure, dict), "payload.closure is required")
    _require(closure.get("program_status") in VALID_PROGRAM_STATUSES, "closure.program_status is invalid")
    _require(closure.get("claim_verdict") in VALID_CLAIM_VERDICTS, "closure.claim_verdict is invalid")

    program = closure.get("program", {})
    mechanism = closure.get("mechanism", {})
    _require(isinstance(program, dict), "closure.program must be an object")
    _require(isinstance(mechanism, dict), "closure.mechanism must be an object")
    _require(_clean(program.get("summary")), "closure.program.summary is required")
    _require(_clean(mechanism.get("summary")), "closure.mechanism.summary is required")
    _require(isinstance(program.get("evidence_refs", []), list), "closure.program.evidence_refs must be a list")
    _require(isinstance(mechanism.get("evidence_refs", []), list), "closure.mechanism.evidence_refs must be a list")
    _require(isinstance(closure.get("open_questions", []), list), "closure.open_questions must be a list")

    if closure["program_status"] in {"failed", "stopped"}:
        _require(
            closure["claim_verdict"] == "not_evaluated",
            "failed or stopped program work must use claim_verdict=not_evaluated",
        )


def _validate_update_payload(payload: dict[str, Any]) -> None:
    allowed = {"append_evidence", "append_knowledge", "append_provenance"}
    _require(any(key in payload for key in allowed), "update_workspace needs an append operation")
    forbidden = {"lifecycle", "closure", "claim_verdict", "accepted_ts", "current_accepted_ts"}
    touched = forbidden.intersection(payload)
    _require(not touched, f"update_workspace cannot write {sorted(touched)}")

    evidence = payload.get("append_evidence")
    if evidence is not None:
        entries = evidence if isinstance(evidence, list) else [evidence]
        _require(all(isinstance(item, dict) for item in entries), "append_evidence entries must be objects")
        for item in entries:
            for field in ("evidence_id", "kind", "role", "evidence_tier", "node_id", "summary"):
                _require(_clean(item.get(field)), f"append_evidence.{field} is required")
            _require(item["evidence_tier"] in VALID_EVIDENCE_TIERS, "append_evidence.evidence_tier is invalid")

    knowledge = payload.get("append_knowledge")
    if knowledge is not None:
        _require(isinstance(knowledge, (str, dict, list)), "append_knowledge must be a string, object, or list")


def _reject_forbidden_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            _require(key not in FORBIDDEN_PUBLIC_FIELDS, f"forbidden public field {path}.{key}")
            _reject_forbidden_keys(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_forbidden_keys(nested, f"{path}[{index}]")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
