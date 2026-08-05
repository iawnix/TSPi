"""Decision JSON validation for all workspace mutations."""

from __future__ import annotations

from typing import Any

from ..ontology import (
    ATTEMPT_KINDS,
    AUDIT_SCOPES,
    AUDIT_STATUSES,
    CANDIDATE_KINDS,
    DECISION_SCHEMA as DECISION_SCHEMA_V2,
    HYPOTHESIS_STATUSES,
    INTAKE_STATUSES,
    MECHANISM_ACTIONS,
    NODE_TYPES,
    PROGRAM_OUTCOMES,
    VALIDATION_SCOPES,
)
from ..schema_validation import SchemaValidationError, validate_contract


class ContractError(ValueError):
    """Raised when a decision or workspace contract is invalid."""


SCHEMA_VERSION = "ts-decision"

VALID_ACTIONS = {
    "init_workspace",
    "start_node",
    "propose_hypothesis",
    "end_node",
    "update_workspace",
    "ask_user",
    "stop",
}

MUTATION_ACTIONS = {"init_workspace", "start_node", "propose_hypothesis", "end_node", "update_workspace"}

VALID_PHASES = {
    "endpoint",
    "candidate_generation",
    "tsfreq_validation",
    "connectivity_validation",
    "accepted_audit",
    "pathway_audit",
}
LEGACY_PHASES = {"preflight", "rp_conformer_generation", "hypothesis_generation"}
WORKSPACE_PHASES = VALID_PHASES | LEGACY_PHASES
WORKSPACE_HYPOTHESIS_CREATION_PHASES = {"preflight", "hypothesis_generation"}
HYPOTHESIS_REF_PHASES = WORKSPACE_PHASES - WORKSPACE_HYPOTHESIS_CREATION_PHASES - {"endpoint"}

VALID_LIFECYCLES = {"running", "closed", "stopped"}
VALID_PROGRAM_STATUSES = {"completed", "failed", "stopped", "not_run"}
VALID_CLAIM_VERDICTS = {"supported", "refuted", "inconclusive", "not_evaluated"}
VALID_PATHWAY_STATUSES = {"proposed", "active", "supported", "refuted", "superseded", "accepted"}
VALID_BRANCH_EVENT_STATES = {"active", "resolved", "superseded"}
VALID_BRANCH_RELATIONS = {
    "continue_parent",
    "new_solution_branch",
    "new_hypothesis_branch",
    "new_pathway_branch",
    "recalculation_of",
}
LEGACY_BRANCH_RELATIONS = {"administrative_followup"}
WORKSPACE_BRANCH_RELATIONS = VALID_BRANCH_RELATIONS | LEGACY_BRANCH_RELATIONS
ANCHORED_BRANCH_RELATIONS = {
    "new_solution_branch",
    "new_hypothesis_branch",
    "new_pathway_branch",
}
VALID_IMPACT_SCOPES = {"solution_only", "prediction", "pathway_step", "hypothesis"}
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
    "_".join(("out" + "come", "code")),
    "_".join(("lifecycle", "state")),
    "_".join(("run", "state")),
    "_".join(("claim", "level")),
}


def validate_decision(decision: Any) -> dict[str, Any]:
    if isinstance(decision, dict) and decision.get("schema_version") == DECISION_SCHEMA_V2:
        return _validate_decision_v2(decision)
    try:
        validate_contract("decision.schema.json", decision)
    except SchemaValidationError as exc:
        raise ContractError(str(exc)) from exc

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

    if action in {"start_node", "propose_hypothesis", "end_node", "update_workspace"}:
        report_ref = decision.get("report_ref")
        _require(isinstance(report_ref, dict), "mutation decision requires report_ref")
        _require(_clean(report_ref.get("report_id")), "report_ref.report_id is required")
        _require(_clean(report_ref.get("workspace_root")), "report_ref.workspace_root is required")

    if action == "start_node":
        _validate_start_payload(payload)
    elif action == "propose_hypothesis":
        _validate_propose_hypothesis_payload(payload, evidence_refs)
    elif action == "end_node":
        _validate_end_payload(payload)
    elif action == "update_workspace":
        _validate_update_payload(payload)
    elif action == "ask_user":
        _require(_clean(payload.get("question")), "ask_user payload.question is required")
    elif action == "stop":
        _require(_clean(payload.get("reason")), "stop payload.reason is required")

    return decision


def _validate_decision_v2(decision: dict[str, Any]) -> dict[str, Any]:
    try:
        validate_contract("decision_v2.schema.json", decision)
    except SchemaValidationError as exc:
        raise ContractError(str(exc)) from exc

    action = decision.get("action")
    _require(action in VALID_ACTIONS - {"propose_hypothesis"}, f"unsupported v2 action: {action!r}")
    _require(_clean(decision.get("rationale")), "rationale is required")
    evidence_refs = decision.get("evidence_refs", [])
    _require(isinstance(evidence_refs, list), "evidence_refs must be a list")
    _require(all(_clean(item) for item in evidence_refs), "evidence_refs cannot contain empty values")
    payload = decision.get("payload")
    _require(isinstance(payload, dict), "payload must be an object")

    if action in {"start_node", "end_node", "update_workspace"}:
        report_ref = decision.get("report_ref")
        _require(isinstance(report_ref, dict), "mutation decision requires report_ref")
        _require(_clean(report_ref.get("report_id")), "report_ref.report_id is required")
        _require(_clean(report_ref.get("workspace_root")), "report_ref.workspace_root is required")

    if action == "start_node":
        _validate_start_payload_v2(payload)
    elif action == "end_node":
        _validate_end_payload_v2(payload)
    elif action == "update_workspace":
        _validate_update_payload(payload)
    elif action == "ask_user":
        _require(_clean(payload.get("question")), "ask_user payload.question is required")
    elif action == "stop":
        _require(_clean(payload.get("reason")), "stop payload.reason is required")
    return decision


def _validate_start_payload_v2(payload: dict[str, Any]) -> None:
    node_type = payload.get("node_type")
    _require(node_type in NODE_TYPES, "payload.node_type is invalid")
    _require(_clean(payload.get("objective")), "payload.objective is required")
    expected = payload.get("expected_evidence", [])
    _require(isinstance(expected, list), "payload.expected_evidence must be a list")
    _require(all(_clean(item) for item in expected), "payload.expected_evidence cannot contain empty values")

    branch_context = payload.get("branch_context")
    if branch_context is not None:
        _validate_branch_context_v2(branch_context)
    pathway_ref = payload.get("pathway_ref")
    if pathway_ref is not None:
        _validate_pathway_ref_v2(pathway_ref)

    attempt_kind = payload.get("attempt_kind", "primary")
    _require(attempt_kind in ATTEMPT_KINDS, "payload.attempt_kind is invalid")
    if attempt_kind == "recalculation":
        _validate_recalculation_ref(payload.get("recalculation_ref"))
        _require(
            isinstance(branch_context, dict) and branch_context.get("relation") == "recalculation_of",
            "recalculation node requires branch_context.relation=recalculation_of",
        )
    else:
        _require(payload.get("recalculation_ref") is None, "primary attempt cannot include recalculation_ref")

    if node_type == "intake":
        _require(payload.get("hypothesis_ref") is None, "intake cannot reference a hypothesis")
        _require(payload.get("proposed_hypothesis") is None, "intake cannot propose a hypothesis")
    elif node_type == "mechanism":
        action = payload.get("mechanism_action")
        _require(action in MECHANISM_ACTIONS, "mechanism node requires a valid mechanism_action")
        if action == "propose":
            _validate_mechanism_hypothesis_v2(payload.get("proposed_hypothesis"))
        else:
            _validate_hypothesis_ref(payload.get("hypothesis_ref"), "payload.hypothesis_ref")
            _require(payload.get("proposed_hypothesis") is None, "non-proposal mechanism node cannot include proposed_hypothesis")
    elif node_type == "candidate_search":
        _require(payload.get("candidate_kind") in CANDIDATE_KINDS, "candidate_search requires a valid candidate_kind")
        _validate_hypothesis_ref(payload.get("hypothesis_ref"), "payload.hypothesis_ref")
    elif node_type == "validation":
        _require(payload.get("validation_scope") in VALIDATION_SCOPES, "validation requires a valid validation_scope")
        _validate_hypothesis_ref(payload.get("hypothesis_ref"), "payload.hypothesis_ref")
    elif node_type == "audit":
        scope = payload.get("audit_scope")
        _require(scope in AUDIT_SCOPES, "audit requires a valid audit_scope")
        _validate_hypothesis_ref(payload.get("hypothesis_ref"), "payload.hypothesis_ref")
        if scope in {"elementary_step", "pathway"}:
            _require(isinstance(pathway_ref, dict), f"audit_scope={scope} requires pathway_ref")
        if scope == "elementary_step":
            _require(_clean(pathway_ref.get("step_id")), "audit_scope=elementary_step requires pathway_ref.step_id")


def _validate_end_payload_v2(payload: dict[str, Any]) -> None:
    _require(_clean(payload.get("node_id")), "payload.node_id is required")
    closure = payload.get("closure")
    _require(isinstance(closure, dict), "payload.closure is required")
    _require(_clean(closure.get("summary")), "closure.summary is required")
    program = closure.get("program")
    _require(isinstance(program, dict), "closure.program is required")
    _require(program.get("outcome") in PROGRAM_OUTCOMES, "closure.program.outcome is invalid")
    _validate_v2_section(program, "closure.program")
    _require(isinstance(closure.get("open_questions"), list), "closure.open_questions must be a list")

    intake = closure.get("intake")
    if intake is not None:
        _require(isinstance(intake, dict), "closure.intake must be an object")
        _require(intake.get("status") in INTAKE_STATUSES, "closure.intake.status is invalid")
    hypothesis = closure.get("hypothesis")
    if hypothesis is not None:
        _validate_v2_section(hypothesis, "closure.hypothesis")
        _require(hypothesis.get("status") in HYPOTHESIS_STATUSES, "closure.hypothesis.status is invalid")
        if hypothesis.get("hypothesis_ref") is not None:
            _validate_hypothesis_ref(hypothesis["hypothesis_ref"], "closure.hypothesis.hypothesis_ref")
    audit = closure.get("audit")
    if audit is not None:
        _validate_v2_section(audit, "closure.audit")
        _require(audit.get("status") in AUDIT_STATUSES, "closure.audit.status is invalid")
        _require(isinstance(audit.get("study_complete"), bool), "closure.audit.study_complete must be boolean")


def _validate_v2_section(value: dict[str, Any], path: str) -> None:
    _require(_clean(value.get("summary")), f"{path}.summary is required")
    refs = value.get("evidence_refs", [])
    _require(isinstance(refs, list), f"{path}.evidence_refs must be a list")
    _require(all(_clean(item) for item in refs), f"{path}.evidence_refs cannot contain empty values")


def _validate_branch_context_v2(value: Any) -> None:
    _require(isinstance(value, dict), "payload.branch_context must be an object")
    _require(
        value.get("relation") in VALID_BRANCH_RELATIONS | {"recalculation_of"},
        "payload.branch_context.relation is invalid",
    )
    for field in ("from_node", "anchor_node"):
        _require(_clean(value.get(field)), f"payload.branch_context.{field} is required")
    refs = value.get("evidence_refs", [])
    _require(isinstance(refs, list), "payload.branch_context.evidence_refs must be a list")
    _require(all(_clean(item) for item in refs), "payload.branch_context.evidence_refs cannot contain empty values")


def _validate_pathway_ref_v2(value: Any) -> None:
    _require(isinstance(value, dict), "payload.pathway_ref must be an object")
    _require(_clean(value.get("pathway_id")), "payload.pathway_ref.pathway_id is required")
    step_id = value.get("step_id")
    _require(step_id is None or _clean(step_id), "payload.pathway_ref.step_id cannot be empty")


def _validate_recalculation_ref(value: Any) -> None:
    _require(isinstance(value, dict), "payload.recalculation_ref is required")
    _require(_clean(value.get("source_node")), "payload.recalculation_ref.source_node is required")
    changed = value.get("changed_settings")
    _require(isinstance(changed, list) and bool(changed), "payload.recalculation_ref.changed_settings is required")
    _require(all(_clean(item) for item in changed), "payload.recalculation_ref.changed_settings cannot contain empty values")
    _require(value.get("purpose") in {"repair", "refinement", "method_robustness"}, "payload.recalculation_ref.purpose is invalid")


def _validate_mechanism_hypothesis_v2(value: Any) -> None:
    _require(isinstance(value, dict), "payload.proposed_hypothesis is required")
    for field in ("hypothesis_id", "summary"):
        _require(_clean(value.get(field)), f"proposed_hypothesis.{field} is required")
    for field in ("derived_from", "structured_claim"):
        _require(isinstance(value.get(field), dict), f"proposed_hypothesis.{field} must be an object")
    for field in ("mechanism_claims", "testable_predictions", "required_evidence", "uncertainties", "alternative_hypotheses"):
        _require(isinstance(value.get(field), list), f"proposed_hypothesis.{field} must be a list")
    prediction_ids: set[str] = set()
    for index, prediction in enumerate(value["testable_predictions"]):
        _require(isinstance(prediction, dict), f"testable_predictions[{index}] must be an object")
        prediction_id = _clean(prediction.get("prediction_id"))
        _require(bool(prediction_id), f"testable_predictions[{index}].prediction_id is required")
        _require(prediction_id not in prediction_ids, f"duplicate prediction_id: {prediction_id}")
        prediction_ids.add(prediction_id)
        _require(_clean(prediction.get("expectation")), f"testable_predictions[{index}].expectation is required")
        scope = prediction.get("validation_scope")
        _require(scope in VALIDATION_SCOPES, f"testable_predictions[{index}].validation_scope is invalid")
    for index, claim in enumerate(value["mechanism_claims"]):
        _validate_mechanism_claim(claim, index)


def _validate_start_payload(payload: dict[str, Any]) -> None:
    phase = payload.get("phase")
    _require(phase in VALID_PHASES, "payload.phase is invalid")
    _require(_clean(payload.get("hypothesis")), "payload.hypothesis is required")

    if phase == "endpoint":
        _require(payload.get("initial_mechanism_hypothesis") is None, "endpoint cannot create a mechanism hypothesis")
        _require(payload.get("hypothesis_ref") is None, "endpoint cannot reference a mechanism hypothesis")
    else:
        _require(
            payload.get("initial_mechanism_hypothesis") is None,
            "start_node cannot create a mechanism hypothesis; use propose_hypothesis",
        )
        _validate_hypothesis_ref(payload.get("hypothesis_ref"), "payload.hypothesis_ref")
        if payload.get("solution_ref") is not None:
            _validate_solution_ref(payload.get("solution_ref"), "payload.solution_ref")

    expected = payload.get("expected_evidence", [])
    _require(isinstance(expected, list), "payload.expected_evidence must be a list")
    _require(all(_clean(item) for item in expected), "payload.expected_evidence cannot contain empty values")

    pathway_ref = payload.get("pathway_ref")
    if phase == "pathway_audit":
        _validate_pathway_ref(pathway_ref, "payload.pathway_ref")
    elif pathway_ref is not None:
        _validate_pathway_ref(pathway_ref, "payload.pathway_ref")

    branch_context = payload.get("branch_context")
    if branch_context is not None:
        _validate_branch_context(branch_context)


def _validate_propose_hypothesis_payload(payload: dict[str, Any], evidence_refs: list[Any]) -> None:
    unexpected = sorted(set(payload) - {"proposed_hypothesis", "proposal_context"})
    _require(not unexpected, f"propose_hypothesis payload contains unsupported fields: {', '.join(unexpected)}")
    hypothesis = payload.get("proposed_hypothesis")
    _validate_initial_mechanism_hypothesis(hypothesis)
    _require(_clean(hypothesis.get("hypothesis_id")), "proposed_hypothesis.hypothesis_id is required")
    _require(bool(evidence_refs), "propose_hypothesis requires evidence_refs")
    hypothesis_refs = hypothesis.get("evidence_refs", [])
    _require(
        set(hypothesis_refs).issubset(set(evidence_refs)),
        "proposed_hypothesis.evidence_refs must be cited by decision.evidence_refs",
    )

    context = payload.get("proposal_context")
    _require(isinstance(context, dict), "payload.proposal_context is required")
    kind = context.get("kind")
    _require(kind in {"initial", "alternative"}, "proposal_context.kind is invalid")
    for field in ("from_node", "anchor_node", "changed_variable", "reason_code"):
        _require(_clean(context.get(field)), f"proposal_context.{field} is required")
    refs = context.get("evidence_refs", [])
    _require(isinstance(refs, list), "proposal_context.evidence_refs must be a list")
    _require(all(_clean(item) for item in refs), "proposal_context.evidence_refs cannot contain empty values")
    _require(set(refs).issubset(set(evidence_refs)), "proposal_context.evidence_refs must be cited by decision.evidence_refs")

    parent_hypothesis_id = hypothesis.get("parent_hypothesis_id")
    if kind == "initial":
        _require(parent_hypothesis_id is None, "initial proposal cannot have parent_hypothesis_id")
    else:
        _require(_clean(parent_hypothesis_id), "alternative proposal requires parent_hypothesis_id")


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
    if mechanism.get("hypothesis_ref") is not None:
        _validate_hypothesis_ref(mechanism.get("hypothesis_ref"), "closure.mechanism.hypothesis_ref")
    if mechanism.get("revision") is not None:
        _validate_revision(mechanism.get("revision"))
    impact_scope = mechanism.get("impact_scope")
    _require(
        impact_scope is None or impact_scope in VALID_IMPACT_SCOPES,
        "closure.mechanism.impact_scope is invalid",
    )

    if closure["program_status"] in {"failed", "stopped"}:
        _require(
            closure["claim_verdict"] == "not_evaluated",
            "failed or stopped program work must use claim_verdict=not_evaluated",
        )


def _validate_update_payload(payload: dict[str, Any]) -> None:
    allowed = {"append_evidence", "append_provenance", "repair_branch_anchor"}
    _require(any(key in payload for key in allowed), "update_workspace needs a supported operation")
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
            is_lifecycle_event = item.get("kind") == "evidence_lifecycle"
            if is_lifecycle_event:
                _require(
                    item.get("role") == "evidence_lifecycle",
                    "evidence lifecycle event must use role=evidence_lifecycle",
                )
                _require(
                    item.get("lifecycle_status") in {"withdrawn", "invalidated"},
                    "evidence lifecycle event requires lifecycle_status withdrawn or invalidated",
                )
                _require(
                    _clean(item.get("supersedes_evidence_id")),
                    "evidence lifecycle event requires supersedes_evidence_id",
                )
            else:
                _require(
                    item.get("lifecycle_status") is None,
                    "lifecycle_status is reserved for evidence lifecycle events",
                )

def _validate_hypothesis_ref(value: Any, path: str) -> None:
    _require(isinstance(value, dict), f"{path} is required")
    _require(_clean(value.get("hypothesis_id")), f"{path}.hypothesis_id is required")
    prediction_ids = value.get("prediction_ids", [])
    _require(isinstance(prediction_ids, list), f"{path}.prediction_ids must be a list")
    _require(all(_clean(item) for item in prediction_ids), f"{path}.prediction_ids cannot contain empty values")


def _validate_solution_ref(value: Any, path: str) -> None:
    _require(isinstance(value, dict), f"{path} must be an object")
    _require(_clean(value.get("solution_id")), f"{path}.solution_id is required")
    for field in ("summary", "strategy", "parent_solution_id"):
        nested = value.get(field)
        _require(nested is None or isinstance(nested, str), f"{path}.{field} must be a string or null")
        if isinstance(nested, str):
            _require(bool(nested.strip()), f"{path}.{field} cannot be empty")


def _validate_pathway_ref(value: Any, path: str) -> None:
    _require(isinstance(value, dict), f"{path} is required")
    _require(_clean(value.get("pathway_id")), f"{path}.pathway_id is required")
    _require(_clean(value.get("step_id")), f"{path}.step_id is required")


def _validate_branch_context(value: Any) -> None:
    _require(isinstance(value, dict), "payload.branch_context must be an object")
    relation = value.get("relation")
    _require(relation in VALID_BRANCH_RELATIONS, "payload.branch_context.relation is invalid")
    for field in ("from_node", "anchor_node"):
        _require(_clean(value.get(field)), f"payload.branch_context.{field} is required")
    for field in ("reason_code", "changed_variable"):
        nested = value.get(field)
        _require(nested is None or _clean(nested), f"payload.branch_context.{field} cannot be empty")
    refs = value.get("evidence_refs", [])
    _require(isinstance(refs, list), "payload.branch_context.evidence_refs must be a list")
    _require(all(_clean(item) for item in refs), "payload.branch_context.evidence_refs cannot contain empty values")


def _validate_initial_mechanism_hypothesis(value: Any) -> None:
    _require(isinstance(value, dict), "payload.initial_mechanism_hypothesis is required")
    _require(_clean(value.get("summary")), "initial_mechanism_hypothesis.summary is required")
    for field in ("derived_from", "structured_claim"):
        _require(isinstance(value.get(field), dict), f"initial_mechanism_hypothesis.{field} must be an object")
    for field in ("mechanism_claims", "testable_predictions", "required_evidence", "uncertainties", "alternative_hypotheses"):
        _require(isinstance(value.get(field), list), f"initial_mechanism_hypothesis.{field} must be a list")

    structured = value["structured_claim"]
    reaction_center = structured.get("reaction_center")
    _require(isinstance(reaction_center, dict), "initial_mechanism_hypothesis.structured_claim.reaction_center is required")
    forming = reaction_center.get("forming_bonds", [])
    breaking = reaction_center.get("breaking_bonds", [])
    _require(isinstance(forming, list), "reaction_center.forming_bonds must be a list")
    _require(isinstance(breaking, list), "reaction_center.breaking_bonds must be a list")
    _require(bool(forming or breaking), "reaction_center requires forming_bonds or breaking_bonds")
    _require(isinstance(structured.get("reaction_class"), list), "structured_claim.reaction_class must be a list")
    _require(_clean(structured.get("elementary_step_model")), "structured_claim.elementary_step_model is required")
    _require(isinstance(structured.get("electronic_model"), dict), "structured_claim.electronic_model must be an object")

    for index, prediction in enumerate(value["testable_predictions"]):
        _require(isinstance(prediction, dict), f"testable_predictions[{index}] must be an object")
        _require(_clean(prediction.get("prediction_id")), f"testable_predictions[{index}].prediction_id is required")
        _require(prediction.get("phase") in VALID_PHASES, f"testable_predictions[{index}].phase is invalid")
        _require(_clean(prediction.get("expectation")), f"testable_predictions[{index}].expectation is required")
    for index, claim in enumerate(value["mechanism_claims"]):
        _validate_mechanism_claim(claim, index)


def _validate_mechanism_claim(claim: Any, index: int) -> None:
    _require(isinstance(claim, dict), f"mechanism_claims[{index}] must be an object")
    _require(_clean(claim.get("claim_id")), f"mechanism_claims[{index}].claim_id is required")
    _require(_clean(claim.get("claim_type")), f"mechanism_claims[{index}].claim_type is required")
    _require(_clean(claim.get("summary")), f"mechanism_claims[{index}].summary is required")
    _require(
        isinstance(claim.get("geometry_reflection_plan"), dict),
        f"mechanism_claims[{index}].geometry_reflection_plan must be an object",
    )
    _require(
        isinstance(claim.get("electronic_structure_reflection_plan"), dict),
        f"mechanism_claims[{index}].electronic_structure_reflection_plan must be an object",
    )
    state_plan = claim.get("state_character_reflection_plan")
    _require(
        state_plan is None or isinstance(state_plan, dict),
        f"mechanism_claims[{index}].state_character_reflection_plan must be an object when present",
    )
    roles = claim.get("required_evidence_roles", [])
    _require(isinstance(roles, list), f"mechanism_claims[{index}].required_evidence_roles must be a list")
    _require(all(_clean(item) for item in roles), f"mechanism_claims[{index}].required_evidence_roles cannot contain empty values")


def _validate_revision(value: Any) -> None:
    _require(isinstance(value, dict), "closure.mechanism.revision must be an object")
    action = value.get("action")
    _require(
        action in {"refute_prediction", "refute_hypothesis", "revise_hypothesis", "supersede_hypothesis"},
        "closure.mechanism.revision.action is invalid",
    )
    if value.get("prediction_ids") is not None:
        prediction_ids = value["prediction_ids"]
        _require(isinstance(prediction_ids, list), "closure.mechanism.revision.prediction_ids must be a list")
        _require(all(_clean(item) for item in prediction_ids), "closure.mechanism.revision.prediction_ids cannot be empty")
    if action in {"refute_prediction", "refute_hypothesis", "revise_hypothesis", "supersede_hypothesis"}:
        _require(_clean(value.get("changed_variable")), "closure.mechanism.revision.changed_variable is required")


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
