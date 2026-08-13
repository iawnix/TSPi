"""Workspace contract validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..artifact_policy import consumed_paths_from_manifest, node_owner_from_artifact_path, role_matches_node
from ..evidence_gates import (
    STRICT_PATHWAY_ACCEPTED,
    STEREOCHEMICAL_GATE_ROLE,
    accepted_gate_evidence,
    gate_artifact_metadata_diagnostic,
    hypothesis_requires_stereochemical_gate,
    mechanism_reflection_gate_evidence,
    mechanism_reflection_required_roles,
    stereochemical_gate_diagnostic,
    strict_connectivity_diagnostic,
    strict_pathway_decision,
    validate_mechanism_reflection_gate,
)
from ..evidence_lifecycle import EvidenceLifecycleError, evidence_lifecycle_view
from ..identity import IDENTITY_REF, WorkspaceIdentityError, read_workspace_identity
from ..io import read_json
from ..ontology import (
    AUDIT_SCOPES,
    AUDIT_STATUSES,
    CANDIDATE_KINDS,
    HYPOTHESIS_STATUSES,
    INTAKE_STATUSES,
    MECHANISM_ACTIONS,
    NODE_SCHEMA,
    NODE_TYPES,
    PROGRAM_OUTCOMES,
    VALIDATION_SCOPES,
)
from ..schema_validation import schema_findings
from ..state import EVIDENCE_FILE, HYPOTHESES_FILE, RESEARCH_STATE_FILE
from .decision import (
    ANCHORED_BRANCH_RELATIONS,
    FORBIDDEN_PUBLIC_FIELDS,
    VALID_BRANCH_RELATIONS,
)

REQUIRED_FILES = {
    RESEARCH_STATE_FILE,
    HYPOTHESES_FILE,
    EVIDENCE_FILE,
}

REQUIRED_DIRS = {"inputs", "nodes", "reports", "accepted", "rejected"}
# Auto-created on first mutation; missing is a warning, not an error.
SOFT_DIRS = {"decisions"}
VALID_LIFECYCLES = {"running", "closed", "stopped"}
UNRESOLVED_TERMINAL_STATUSES = {"unsupported", "ambiguous", "not_accepted", "failure", "needs_input"}
SCHEMA_BY_FILE = {
    RESEARCH_STATE_FILE: "research_state.schema.json",
    HYPOTHESES_FILE: "hypotheses.schema.json",
    EVIDENCE_FILE: "evidence_registry.schema.json",
}


def validate_workspace(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    findings: list[dict[str, str]] = []

    for filename in sorted(REQUIRED_FILES):
        path = root_path / filename
        if not path.exists():
            _finding(findings, "error", "missing_file", f"missing {filename}", filename)

    for dirname in sorted(REQUIRED_DIRS):
        path = root_path / dirname
        if not path.is_dir():
            _finding(findings, "error", "missing_dir", f"missing {dirname}/", dirname)
    for dirname in sorted(SOFT_DIRS):
        path = root_path / dirname
        if not path.is_dir():
            _finding(
                findings,
                "warning",
                "missing_soft_dir",
                f"missing {dirname}/ (auto-created on next mutation)",
                dirname,
            )

    identity_path = root_path / IDENTITY_REF
    if not identity_path.exists() and not identity_path.is_symlink():
        _finding(
            findings,
            "warning",
            "missing_workspace_identity",
            "missing workspace identity (auto-created before the next remote preparation)",
            IDENTITY_REF,
        )
    else:
        try:
            read_workspace_identity(root_path)
        except WorkspaceIdentityError as exc:
            _finding(findings, "error", "invalid_workspace_identity", str(exc), IDENTITY_REF)

    loaded: dict[str, Any] = {}
    for filename in sorted(REQUIRED_FILES):
        path = root_path / filename
        if path.exists():
            try:
                loaded[filename] = read_json(path)
            except Exception as exc:  # noqa: BLE001
                _finding(findings, "error", "invalid_json", str(exc), filename)
                continue
            schema_name = SCHEMA_BY_FILE.get(filename)
            if schema_name:
                findings.extend(schema_findings(schema_name, loaded[filename], filename))

    mechanism_model = loaded.get(HYPOTHESES_FILE, {})
    hypothesis_ids = _validate_mechanism_model(mechanism_model, findings)
    tree = loaded.get(RESEARCH_STATE_FILE, {})
    node_entries = tree.get("nodes", []) if isinstance(tree, dict) else []
    node_ids = set()
    node_details: dict[str, dict[str, Any]] = {}
    ordered_node_ids: list[str] = []
    if not isinstance(node_entries, list):
        _finding(findings, "error", "invalid_tree", "research_state.nodes must be a list", RESEARCH_STATE_FILE)
        node_entries = []

    for entry in node_entries:
        if not isinstance(entry, dict):
            _finding(findings, "error", "invalid_tree_node", "research state node entry must be an object", RESEARCH_STATE_FILE)
            continue
        node_id = entry.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            _finding(findings, "error", "invalid_node_id", "research state node missing node_id", RESEARCH_STATE_FILE)
            continue
        node_ids.add(node_id)
        ordered_node_ids.append(node_id)
        node_path = root_path / "nodes" / node_id / "node.json"
        if not node_path.exists():
            _finding(findings, "error", "missing_node_json", f"missing node.json for {node_id}", str(node_path))
            continue
        try:
            node = read_json(node_path)
        except Exception as exc:  # noqa: BLE001
            _finding(findings, "error", "invalid_node_json", str(exc), str(node_path))
            continue
        findings.extend(schema_findings("node_v2.schema.json", node, str(node_path)))
        if not isinstance(node, dict):
            _finding(findings, "error", "invalid_node_json", "node.json must contain an object", str(node_path))
            continue
        node_details[node_id] = node
        _validate_node(node, node_id, hypothesis_ids, findings, str(node_path))
        _validate_tree_node_lineage(entry, node, findings, f"{RESEARCH_STATE_FILE}.nodes[{len(ordered_node_ids) - 1}]")

    current_node = tree.get("current_node") if isinstance(tree, dict) else None
    if current_node is not None and current_node not in node_ids:
        _finding(findings, "error", "invalid_current_node", "research_state.current_node does not exist", RESEARCH_STATE_FILE)
    if isinstance(tree, dict):
        _validate_initial_node_sequence(ordered_node_ids, node_details, hypothesis_ids, findings)
        _validate_hypothesis_provenance(mechanism_model, node_details, findings)
        _validate_branch_contexts(node_details, findings)
        _validate_branch_events(tree, node_ids, findings)
        _validate_branch_lineage(tree, node_details, findings)
        _validate_branch_identity_uniqueness(tree, node_details, findings)
        _validate_unresolved_terminal_state(
            tree,
            _as_dict(loaded.get(RESEARCH_STATE_FILE)),
            _as_dict(loaded.get(HYPOTHESES_FILE)),
            ordered_node_ids,
            node_details,
            findings,
        )

    for filename, data in loaded.items():
        _reject_forbidden(data, findings, filename)

    evidence = _as_dict(loaded.get(EVIDENCE_FILE)).get("evidence", [])
    if isinstance(evidence, list):
        try:
            lifecycle_view = evidence_lifecycle_view(evidence)
            active_evidence = lifecycle_view.active_records
            active_evidence_ids = {
                str(item.get("evidence_id")) for item in active_evidence if item.get("evidence_id")
            }
        except EvidenceLifecycleError as exc:
            _finding(
                findings,
                "error",
                "invalid_evidence_lifecycle",
                str(exc),
                "evidence_registry.json",
            )
            active_evidence = [item for item in evidence if isinstance(item, dict)]
            active_evidence_ids = {
                str(item.get("evidence_id")) for item in active_evidence if item.get("evidence_id")
            }
        ids: set[str] = set()
        for item in evidence:
            if not isinstance(item, dict):
                _finding(findings, "error", "invalid_evidence", "evidence entry must be an object", "evidence_registry.json")
                continue
            evidence_id = item.get("evidence_id")
            if not isinstance(evidence_id, str) or not evidence_id:
                _finding(findings, "error", "invalid_evidence_id", "evidence entry missing evidence_id", "evidence_registry.json")
            elif evidence_id in ids:
                _finding(findings, "error", "duplicate_evidence_id", f"duplicate evidence {evidence_id}", "evidence_registry.json")
            else:
                ids.add(evidence_id)
            if evidence_id not in active_evidence_ids:
                continue
            quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
            hypothesis_id = quality.get("hypothesis_id")
            if hypothesis_id is not None and hypothesis_id not in hypothesis_ids:
                _finding(
                    findings,
                    "error",
                    "unknown_evidence_hypothesis",
                    f"evidence references unknown hypothesis_id: {hypothesis_id}",
                    "evidence_registry.json",
                )
            gate_diagnostic = gate_artifact_metadata_diagnostic(item)
            if gate_diagnostic:
                _finding(findings, "error", "missing_gate_artifact_metadata", gate_diagnostic, "evidence_registry.json")
        _validate_evidence_artifact_boundaries(root_path, active_evidence, node_details, findings)

    _validate_accepted_ts_refs(
        root_path,
        _as_dict(loaded.get(RESEARCH_STATE_FILE)),
        _as_dict(loaded.get(HYPOTHESES_FILE)),
        evidence,
        findings,
    )
    _validate_v2_accepted_audit_refs(
        _as_dict(loaded.get(RESEARCH_STATE_FILE)),
        node_details,
        findings,
    )
    _validate_pathway_audit_mechanism_gates(
        _as_dict(loaded.get(HYPOTHESES_FILE)),
        node_details,
        evidence,
        findings,
    )
    _validate_pending_transactions(root_path, findings)

    return {"valid": not any(item["severity"] == "error" for item in findings), "findings": findings}


def _validate_pending_transactions(root: Path, findings: list[dict[str, str]]) -> None:
    """Detect prepare rows without a matching committed row in transaction_log.jsonl."""
    tx_path = root / "transaction_log.jsonl"
    if not tx_path.exists():
        return
    prepared: dict[str, dict[str, Any]] = {}
    for line in tx_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            import json as _json

            row = _json.loads(line)
        except Exception:  # noqa: BLE001
            _finding(findings, "error", "transaction_log_unreadable", "malformed transaction_log row", "transaction_log.jsonl")
            continue
        decision_id = row.get("decision_id")
        stage = row.get("stage")
        if not decision_id or stage not in {"prepare", "committed", "aborted"}:
            continue
        if stage == "prepare":
            prepared[decision_id] = row
        elif stage in {"committed", "aborted"}:
            prepared.pop(decision_id, None)
    for decision_id, row in prepared.items():
        _finding(
            findings,
            "error",
            "pending_transaction",
            f"decision {decision_id} recorded prepare without committed",
            "transaction_log.jsonl",
        )


def _validate_node(
    node: dict[str, Any],
    expected_id: str,
    hypothesis_ids: set[str],
    findings: list[dict[str, str]],
    source: str,
) -> None:
    if node.get("schema_version") != NODE_SCHEMA:
        _finding(findings, "error", "invalid_node_schema", "node schema_version must be ts-node/2", source)
    if node.get("node_id") != expected_id:
        _finding(findings, "error", "node_id_mismatch", "node_id does not match tree entry", source)
    node_type = node.get("node_type")
    if node_type not in NODE_TYPES:
        _finding(findings, "error", "invalid_node_type", "node_type is invalid", source)
    if expected_id == "n000" and node_type != "intake":
        _finding(findings, "error", "invalid_n000_type", "n000 must use node_type=intake", source)
    if expected_id != "n000" and node_type == "intake":
        _finding(findings, "error", "intake_after_n000", "node_type=intake is reserved for n000", source)
    if not isinstance(node.get("objective"), str) or not node["objective"].strip():
        _finding(findings, "error", "missing_objective", "v2 node objective is required", source)
    if node.get("lifecycle") not in VALID_LIFECYCLES:
        _finding(findings, "error", "invalid_lifecycle", "node lifecycle is invalid", source)
    if node_type == "mechanism" and node.get("mechanism_action") not in MECHANISM_ACTIONS:
        _finding(findings, "error", "invalid_mechanism_action", "mechanism_action is invalid", source)
    if node_type == "candidate_search" and node.get("candidate_kind") not in CANDIDATE_KINDS:
        _finding(findings, "error", "invalid_candidate_kind", "candidate_kind is invalid", source)
    if node_type == "validation" and node.get("validation_scope") not in VALIDATION_SCOPES:
        _finding(findings, "error", "invalid_validation_scope", "validation_scope is invalid", source)
    if node_type == "audit" and node.get("audit_scope") not in AUDIT_SCOPES:
        _finding(findings, "error", "invalid_audit_scope", "audit_scope is invalid", source)

    if node_type in {"candidate_search", "validation", "audit"} or (
        node_type == "mechanism" and node.get("mechanism_action") != "propose"
    ):
        _validate_hypothesis_ref(node.get("hypothesis_ref"), hypothesis_ids, findings, source, "node.hypothesis_ref")
    if node_type == "mechanism" and node.get("mechanism_action") == "propose":
        proposed = node.get("proposed_hypothesis")
        if not isinstance(proposed, dict) or not isinstance(proposed.get("hypothesis_id"), str):
            _finding(findings, "error", "missing_proposed_hypothesis", "mechanism proposal requires proposed_hypothesis", source)

    closure = node.get("closure")
    lifecycle = node.get("lifecycle")
    if lifecycle == "running" and closure is not None:
        _finding(findings, "error", "running_node_has_closure", "running node cannot have closure", source)
    if lifecycle in {"closed", "stopped"}:
        if not isinstance(closure, dict):
            _finding(findings, "error", "missing_closure", "closed or stopped node requires closure", source)
            return
        program = closure.get("program") if isinstance(closure.get("program"), dict) else {}
        if program.get("outcome") not in PROGRAM_OUTCOMES:
            _finding(findings, "error", "invalid_program_outcome", "closure.program.outcome is invalid", source)
        if node_type == "intake":
            intake = closure.get("intake") if isinstance(closure.get("intake"), dict) else {}
            if intake.get("status") not in INTAKE_STATUSES:
                _finding(findings, "error", "invalid_intake_status", "intake closure status is invalid", source)
        if node_type == "mechanism":
            hypothesis = closure.get("hypothesis") if isinstance(closure.get("hypothesis"), dict) else {}
            if hypothesis.get("status") not in HYPOTHESIS_STATUSES:
                _finding(findings, "error", "invalid_hypothesis_status", "mechanism closure hypothesis status is invalid", source)
        if node_type == "audit":
            audit = closure.get("audit") if isinstance(closure.get("audit"), dict) else {}
            if audit.get("status") not in AUDIT_STATUSES:
                _finding(findings, "error", "invalid_audit_status", "audit closure status is invalid", source)


def _validate_mechanism_model(model: Any, findings: list[dict[str, str]]) -> set[str]:
    source = HYPOTHESES_FILE
    hypothesis_ids: set[str] = set()
    if not isinstance(model, dict):
        _finding(findings, "error", "invalid_mechanism_model", "hypotheses state must be an object", source)
        return hypothesis_ids
    if model.get("schema_version") != "ts-hypotheses":
        _finding(findings, "error", "invalid_mechanism_schema", "hypotheses schema_version must be ts-hypotheses", source)
    if "focus_hypothesis_id" not in model:
        _finding(findings, "error", "missing_focus_hypothesis_id", "hypotheses.focus_hypothesis_id is required", source)
    hypotheses = model.get("hypotheses")
    if not isinstance(hypotheses, list):
        _finding(findings, "error", "invalid_hypotheses", "hypotheses.hypotheses must be a list", source)
        return hypothesis_ids
    for index, hypothesis in enumerate(hypotheses):
        path = f"{source}.hypotheses[{index}]"
        if not isinstance(hypothesis, dict):
            _finding(findings, "error", "invalid_hypothesis", "hypothesis must be an object", path)
            continue
        hypothesis_id = hypothesis.get("hypothesis_id")
        if not isinstance(hypothesis_id, str) or not hypothesis_id:
            _finding(findings, "error", "missing_hypothesis_id", "hypothesis_id is required", path)
            continue
        if hypothesis_id in hypothesis_ids:
            _finding(findings, "error", "duplicate_hypothesis_id", f"duplicate hypothesis_id: {hypothesis_id}", path)
        hypothesis_ids.add(hypothesis_id)
        for field in ("summary", "status", "source_node"):
            if not isinstance(hypothesis.get(field), str) or not hypothesis[field].strip():
                _finding(findings, "error", "invalid_hypothesis", f"{field} is required", path)
        if not isinstance(hypothesis.get("structured_claim"), dict):
            _finding(findings, "error", "invalid_hypothesis", "structured_claim must be an object", path)
        if not isinstance(hypothesis.get("testable_predictions"), list):
            _finding(findings, "error", "invalid_hypothesis", "testable_predictions must be a list", path)
        if not isinstance(hypothesis.get("required_evidence"), list):
            _finding(findings, "error", "invalid_hypothesis", "required_evidence must be a list", path)
    focus = model.get("focus_hypothesis_id")
    if focus is not None and focus not in hypothesis_ids:
        _finding(findings, "error", "invalid_focus_hypothesis_id", "focus_hypothesis_id does not exist", source)
    return hypothesis_ids


def _validate_hypothesis_provenance(
    model: Any,
    node_details: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
) -> None:
    if not isinstance(model, dict):
        return
    for index, hypothesis in enumerate(model.get("hypotheses", [])):
        if not isinstance(hypothesis, dict):
            continue
        hypothesis_id = hypothesis.get("hypothesis_id")
        source = f"{HYPOTHESES_FILE}.hypotheses[{index}]"
        source_node_id = hypothesis.get("source_node")
        source_node = node_details.get(str(source_node_id))
        if not isinstance(source_node, dict):
            _finding(
                findings,
                "error",
                "hypothesis_source_node_missing",
                f"source_node does not reference an existing node for {hypothesis_id}: {source_node_id}",
                source,
            )
            continue
        proposed = source_node.get("proposed_hypothesis")
        if (
            source_node.get("node_type") != "mechanism"
            or source_node.get("mechanism_action") != "propose"
            or not isinstance(proposed, dict)
            or proposed.get("hypothesis_id") != hypothesis_id
        ):
            _finding(
                findings,
                "error",
                "hypothesis_source_node_mismatch",
                f"source_node is not the mechanism proposal node for {hypothesis_id}",
                source,
            )
        if hypothesis.get("proposed_by_decision") != source_node.get("created_by_decision"):
            _finding(
                findings,
                "error",
                "hypothesis_proposal_decision_missing",
                f"proposed_by_decision must match the source node decision for {hypothesis_id}",
                source,
            )
        context = source_node.get("branch_context") if isinstance(source_node.get("branch_context"), dict) else {}
        expected_anchor = context.get("anchor_node") or source_node.get("parent_node") or source_node_id
        if hypothesis.get("branch_anchor_node") != expected_anchor:
            _finding(
                findings,
                "error",
                "hypothesis_proposal_anchor_mismatch",
                f"branch_anchor_node does not match the mechanism proposal node for {hypothesis_id}",
                source,
            )


def _validate_hypothesis_ref(
    value: Any,
    hypothesis_ids: set[str],
    findings: list[dict[str, str]],
    source: str,
    label: str,
) -> None:
    if not isinstance(value, dict):
        _finding(findings, "error", "missing_hypothesis_ref", f"{label} is required", source)
        return
    hypothesis_id = value.get("hypothesis_id")
    if not isinstance(hypothesis_id, str) or not hypothesis_id:
        _finding(findings, "error", "invalid_hypothesis_ref", f"{label}.hypothesis_id is required", source)
    elif hypothesis_id not in hypothesis_ids:
        _finding(findings, "error", "unknown_hypothesis_ref", f"{label} references unknown hypothesis_id: {hypothesis_id}", source)
    prediction_ids = value.get("prediction_ids", [])
    if not isinstance(prediction_ids, list):
        _finding(findings, "error", "invalid_hypothesis_ref", f"{label}.prediction_ids must be a list", source)


def _validate_tree_node_lineage(
    entry: dict[str, Any],
    node: dict[str, Any],
    findings: list[dict[str, str]],
    source: str,
) -> None:
    if entry.get("solution_ref") != node.get("solution_ref"):
        _finding(findings, "error", "solution_ref_mismatch", "tree node solution_ref must match node solution_ref", source)
    if entry.get("branch_context") != node.get("branch_context"):
        _finding(findings, "error", "branch_context_mismatch", "tree node branch_context must match node branch_context", source)


def _validate_branch_contexts(
    node_details: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
) -> None:
    for node_id, node in node_details.items():
        source = f"nodes/{node_id}/node.json"
        if node_id == "n000":
            if node.get("branch_context") is not None:
                _finding(findings, "error", "invalid_n000_branch_context", "n000 must not have branch_context", source)
            continue
        context = node.get("branch_context")
        if not isinstance(context, dict):
            _finding(findings, "error", "missing_branch_context", "post-n000 node requires branch_context", source)
            continue
        relation = context.get("relation")
        if relation not in VALID_BRANCH_RELATIONS:
            _finding(findings, "error", "invalid_branch_context", "branch_context.relation is invalid", source)
        from_node_id = context.get("from_node")
        anchor_node_id = context.get("anchor_node")
        for field, ref in (("from_node", from_node_id), ("anchor_node", anchor_node_id)):
            if not isinstance(ref, str) or not ref:
                _finding(findings, "error", "invalid_branch_context", f"branch_context.{field} is required", source)
            elif ref not in node_details:
                _finding(findings, "error", "invalid_branch_context_node", f"branch_context.{field} does not exist: {ref}", source)
        from_node = node_details.get(str(from_node_id))
        if relation in {"continue_parent", "recalculation_of"}:
            if node.get("parent_node") != from_node_id:
                _finding(findings, "error", "invalid_branch_context", f"{relation} requires parent_node to match from_node", source)
        elif relation in ANCHORED_BRANCH_RELATIONS and node.get("parent_node") != anchor_node_id:
            _finding(
                findings,
                "error",
                "branch_parent_anchor_mismatch",
                f"{relation} requires parent_node to match branch_context.anchor_node",
                source,
            )
        if relation in ANCHORED_BRANCH_RELATIONS and not _is_ancestor(node_details, anchor_node_id, from_node_id):
            _finding(
                findings,
                "error",
                "branch_anchor_not_ancestor",
                f"{relation} anchor_node must be an ancestor of branch_context.from_node",
                source,
            )
        if relation == "recalculation_of":
            recalculation = node.get("recalculation_ref") if isinstance(node.get("recalculation_ref"), dict) else {}
            if node.get("attempt_kind") != "recalculation":
                _finding(findings, "error", "invalid_recalculation", "recalculation_of requires attempt_kind=recalculation", source)
            if recalculation.get("source_node") != from_node_id:
                _finding(findings, "error", "invalid_recalculation", "recalculation_ref.source_node must match branch_context.from_node", source)
        elif node.get("attempt_kind") == "recalculation":
            _finding(findings, "error", "invalid_recalculation", "attempt_kind=recalculation requires relation=recalculation_of", source)
        if relation == "new_solution_branch":
            _validate_solution_branch_context(node, from_node, findings, source)
        elif relation == "new_hypothesis_branch":
            if node.get("mechanism_action") == "propose":
                proposed = node.get("proposed_hypothesis") if isinstance(node.get("proposed_hypothesis"), dict) else {}
                from_hypothesis_id = _node_hypothesis_id(from_node or {})
                if proposed.get("parent_hypothesis_id") != from_hypothesis_id:
                    _finding(findings, "error", "hypothesis_branch_parent_mismatch", "proposed parent_hypothesis_id must match from_node hypothesis", source)
            else:
                _validate_hypothesis_branch_context(node, from_node, findings, source)
        elif relation == "new_pathway_branch":
            if not isinstance(node.get("pathway_ref"), dict):
                _finding(findings, "error", "invalid_branch_context", "new_pathway_branch requires node.pathway_ref", source)


def _validate_solution_branch_context(
    node: dict[str, Any],
    from_node: dict[str, Any] | None,
    findings: list[dict[str, str]],
    source: str,
) -> None:
    solution_ref = node.get("solution_ref")
    if not isinstance(solution_ref, dict) or not str(solution_ref.get("solution_id") or "").strip():
        _finding(findings, "error", "invalid_branch_context", "new_solution_branch requires node.solution_ref.solution_id", source)
    if from_node is None:
        return
    from_ref = from_node.get("hypothesis_ref") if isinstance(from_node.get("hypothesis_ref"), dict) else {}
    new_ref = node.get("hypothesis_ref") if isinstance(node.get("hypothesis_ref"), dict) else {}
    if from_ref and new_ref and from_ref.get("hypothesis_id") != new_ref.get("hypothesis_id"):
        _finding(findings, "error", "solution_branch_hypothesis_mismatch", "new_solution_branch must keep the same hypothesis_id", source)
    from_solution = from_node.get("solution_ref") if isinstance(from_node.get("solution_ref"), dict) else {}
    if isinstance(solution_ref, dict) and from_solution and from_solution.get("solution_id") == solution_ref.get("solution_id"):
        _finding(findings, "error", "solution_branch_duplicate_solution", "new_solution_branch requires a new solution_ref.solution_id", source)


def _validate_hypothesis_branch_context(
    node: dict[str, Any],
    from_node: dict[str, Any] | None,
    findings: list[dict[str, str]],
    source: str,
) -> None:
    if from_node is None:
        return
    from_hypothesis_id = _node_hypothesis_id(from_node)
    new_hypothesis_id = _node_hypothesis_id(node)
    if from_hypothesis_id and from_hypothesis_id == new_hypothesis_id:
        _finding(findings, "error", "hypothesis_branch_same_hypothesis", "new_hypothesis_branch requires a different hypothesis_id", source)
    initial = node.get("initial_mechanism_hypothesis")
    parent_hypothesis_id = initial.get("parent_hypothesis_id") if isinstance(initial, dict) else None
    if parent_hypothesis_id and from_hypothesis_id and parent_hypothesis_id != from_hypothesis_id:
        _finding(
            findings,
            "error",
            "hypothesis_branch_parent_mismatch",
            "new hypothesis parent_hypothesis_id must match the from_node hypothesis",
            source,
        )


def _is_ancestor(node_details: dict[str, dict[str, Any]], ancestor_id: Any, node_id: Any) -> bool:
    if not isinstance(ancestor_id, str) or not isinstance(node_id, str):
        return False
    current: str | None = node_id
    visited: set[str] = set()
    while current and current not in visited:
        if current == ancestor_id:
            return True
        visited.add(current)
        node = node_details.get(current)
        if node is None:
            return False
        parent = node.get("parent_node")
        current = parent if isinstance(parent, str) and parent else None
    return False


def _validate_branch_events(tree: dict[str, Any], node_ids: set[str], findings: list[dict[str, str]]) -> None:
    events = tree.get("branch_events", [])
    if not isinstance(events, list):
        _finding(findings, "error", "invalid_branch_events", "research_state.branch_events must be a list", RESEARCH_STATE_FILE)
        return
    for index, event in enumerate(events):
        path = f"{RESEARCH_STATE_FILE}.branch_events[{index}]"
        if not isinstance(event, dict):
            _finding(findings, "error", "invalid_branch_event", "branch event must be an object", path)
            continue
        relation = event.get("relation")
        if relation not in VALID_BRANCH_RELATIONS:
            _finding(findings, "error", "invalid_branch_event", "relation is invalid", path)
        for field in ("from_node", "anchor_node", "new_node", "parent_node"):
            node_id = event.get(field)
            if not isinstance(node_id, str) or not node_id:
                _finding(findings, "error", "invalid_branch_event", f"{field} is required", path)
            elif node_id not in node_ids:
                _finding(findings, "error", "invalid_branch_event_node", f"{field} does not exist: {node_id}", path)
        if not isinstance(event.get("is_rebased"), bool):
            _finding(findings, "error", "invalid_branch_event", "is_rebased is required", path)


def _validate_branch_lineage(
    tree: dict[str, Any],
    node_details: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
) -> None:
    for index, event in enumerate(_branch_events(tree)):
        path = f"{RESEARCH_STATE_FILE}.branch_events[{index}]"
        new_node = node_details.get(str(event.get("new_node")))
        from_node = node_details.get(str(event.get("from_node")))
        if new_node is None:
            continue
        parent_node = new_node.get("parent_node")
        if event.get("parent_node") != parent_node:
            _finding(
                findings,
                "error",
                "branch_event_parent_mismatch",
                "branch event parent_node must match the new node parent_node",
                path,
            )
        expected_rebased = parent_node == event.get("anchor_node") and event.get("from_node") != event.get("anchor_node")
        if event.get("is_rebased") != expected_rebased:
            _finding(
                findings,
                "error",
                "branch_event_rebased_mismatch",
                "branch event is_rebased must match parent/from/anchor topology",
                path,
            )
        context = new_node.get("branch_context") if isinstance(new_node.get("branch_context"), dict) else {}
        for field in ("relation", "from_node", "anchor_node", "reason_code", "changed_variable"):
            if field in event or field in context:
                if event.get(field) != context.get(field):
                    _finding(
                        findings,
                        "error",
                        "branch_event_context_mismatch",
                        f"branch event {field} must match new node branch_context",
                        path,
                    )
        expected_hypothesis_ref = _branch_target_hypothesis_ref(new_node)
        if "target_hypothesis_ref" in event and event.get("target_hypothesis_ref") != expected_hypothesis_ref:
            _finding(
                findings,
                "error",
                "branch_target_hypothesis_mismatch",
                "branch target_hypothesis_ref must match the new node hypothesis",
                path,
            )
        if event.get("relation") == "new_solution_branch" and "target_solution_ref" not in event:
            _finding(
                findings,
                "error",
                "branch_target_solution_missing",
                "new_solution_branch requires target_solution_ref in its branch event",
                path,
            )
        elif "target_solution_ref" in event and event.get("target_solution_ref") != new_node.get("solution_ref"):
            _finding(
                findings,
                "error",
                "branch_target_solution_mismatch",
                "branch target_solution_ref must match the new node solution_ref",
                path,
            )
        if event.get("relation") == "new_pathway_branch" and "target_pathway_ref" not in event:
            _finding(
                findings,
                "error",
                "branch_target_pathway_missing",
                "new_pathway_branch requires target_pathway_ref in its branch event",
                path,
            )
        elif "target_pathway_ref" in event and event.get("target_pathway_ref") != new_node.get("pathway_ref"):
            _finding(
                findings,
                "error",
                "branch_target_pathway_mismatch",
                "branch target_pathway_ref must match the new node pathway_ref",
                path,
            )
        if event.get("relation") != "new_solution_branch":
            continue
        if not isinstance(new_node.get("solution_ref"), dict):
            _finding(
                findings,
                "error",
                "solution_branch_missing_solution_ref",
                "new_solution_branch requires the new node solution_ref",
                path,
            )
        if from_node is None:
            continue
        from_ref = from_node.get("hypothesis_ref") if isinstance(from_node.get("hypothesis_ref"), dict) else {}
        new_ref = new_node.get("hypothesis_ref") if isinstance(new_node.get("hypothesis_ref"), dict) else {}
        if from_ref and new_ref and from_ref.get("hypothesis_id") != new_ref.get("hypothesis_id"):
            _finding(
                findings,
                "error",
                "solution_branch_hypothesis_mismatch",
                "new_solution_branch must keep the same hypothesis_id",
                path,
            )


def _validate_branch_identity_uniqueness(
    tree: dict[str, Any],
    node_details: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
) -> None:
    introduced_solutions: dict[tuple[str | None, str], str] = {}
    introduced_pathways: dict[str, str] = {}
    for index, event in enumerate(_branch_events(tree)):
        source = f"{RESEARCH_STATE_FILE}.branch_events[{index}]"
        new_node = node_details.get(str(event.get("new_node")))
        from_node = node_details.get(str(event.get("from_node")))
        if new_node is None:
            continue
        relation = event.get("relation")
        if relation == "new_solution_branch":
            solution_ref = new_node.get("solution_ref") if isinstance(new_node.get("solution_ref"), dict) else {}
            solution_id = solution_ref.get("solution_id")
            if not isinstance(solution_id, str) or not solution_id:
                continue
            key = (_node_hypothesis_id(new_node), solution_id)
            previous = introduced_solutions.get(key)
            if previous is not None:
                _finding(
                    findings,
                    "error",
                    "duplicate_solution_branch_identity",
                    f"solution_id {solution_id} was already introduced by {previous}",
                    source,
                )
            else:
                introduced_solutions[key] = str(event.get("new_node"))
            from_solution = from_node.get("solution_ref") if isinstance(from_node, dict) and isinstance(from_node.get("solution_ref"), dict) else {}
            source_solution_id = from_solution.get("solution_id")
            parent_solution_id = solution_ref.get("parent_solution_id")
            if source_solution_id and parent_solution_id != source_solution_id:
                _finding(
                    findings,
                    "error",
                    "solution_parent_identity_mismatch",
                    "solution_ref.parent_solution_id must match the source node solution_id",
                    source,
                )
            elif not source_solution_id and parent_solution_id is not None:
                _finding(
                    findings,
                    "error",
                    "solution_parent_identity_mismatch",
                    "solution_ref.parent_solution_id requires an identified source solution",
                    source,
                )
        elif relation == "new_pathway_branch":
            pathway_ref = new_node.get("pathway_ref") if isinstance(new_node.get("pathway_ref"), dict) else {}
            pathway_id = pathway_ref.get("pathway_id")
            if not isinstance(pathway_id, str) or not pathway_id:
                continue
            previous = introduced_pathways.get(pathway_id)
            if previous is not None:
                _finding(
                    findings,
                    "error",
                    "duplicate_pathway_branch_identity",
                    f"pathway_id {pathway_id} was already introduced by {previous}",
                    source,
                )
            else:
                introduced_pathways[pathway_id] = str(event.get("new_node"))
            from_pathway = from_node.get("pathway_ref") if isinstance(from_node, dict) and isinstance(from_node.get("pathway_ref"), dict) else {}
            if from_pathway.get("pathway_id") == pathway_id:
                _finding(
                    findings,
                    "error",
                    "pathway_branch_reused_source_identity",
                    "new_pathway_branch must not reuse the source node pathway_id",
                    source,
                )


def _validate_initial_node_sequence(
    ordered_node_ids: list[str],
    node_details: dict[str, dict[str, Any]],
    hypothesis_ids: set[str],
    findings: list[dict[str, str]],
) -> None:
    if not ordered_node_ids:
        return
    first_id = ordered_node_ids[0]
    first = node_details.get(first_id, {})
    if first_id != "n000":
        _finding(findings, "error", "missing_n000", "first node must be n000", f"{RESEARCH_STATE_FILE}.nodes[0]")
    if first.get("node_type") != "intake":
        _finding(findings, "error", "invalid_n000_type", "n000 must be intake", "nodes/n000/node.json")


def _validate_unresolved_terminal_state(
    tree: dict[str, Any],
    manifest: dict[str, Any],
    pathway_model: dict[str, Any],
    ordered_node_ids: list[str],
    node_details: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
) -> None:
    if tree.get("current_node") or any(node.get("lifecycle") == "running" for node in node_details.values()):
        return
    if _has_accepted_claim(manifest, pathway_model):
        return
    if not ordered_node_ids:
        return
    terminal_id = ordered_node_ids[-1]
    terminal = node_details.get(terminal_id, {})
    if not _is_unresolved_closed(terminal):
        return
    status = _terminal_status(terminal)
    _finding(
        findings,
        "warning",
        "terminal_unresolved_no_running_node",
        (
            f"terminal node {terminal_id} is {status} and the workspace has no "
            "running node or accepted TS/pathway; agent decision is still required"
        ),
        f"{RESEARCH_STATE_FILE}.current_node",
    )


def _branch_events(tree: dict[str, Any]) -> list[dict[str, Any]]:
    return [event for event in tree.get("branch_events", []) if isinstance(event, dict)]


def _is_unresolved_closed(node: dict[str, Any]) -> bool:
    return node.get("lifecycle") in {"closed", "stopped"} and _terminal_status(node) in UNRESOLVED_TERMINAL_STATUSES


def _terminal_status(node: dict[str, Any]) -> str | None:
    closure = node.get("closure")
    if isinstance(closure, dict):
        for section_name in ("hypothesis", "audit", "intake"):
            section = closure.get(section_name)
            if isinstance(section, dict) and isinstance(section.get("status"), str):
                return section["status"]
        program = closure.get("program")
        if isinstance(program, dict):
            return program.get("outcome")
    return None


def _has_accepted_claim(manifest: dict[str, Any], pathway_model: dict[str, Any]) -> bool:
    if _as_list(manifest.get("accepted_ts_refs")):
        return True
    for pathway in _as_list(pathway_model.get("pathways")):
        if isinstance(pathway, dict) and pathway.get("status") == "accepted":
            return True
    return False


def _validate_accepted_ts_refs(
    root: Path,
    manifest: dict[str, Any],
    mechanism_model: dict[str, Any],
    evidence_records: list[Any],
    findings: list[dict[str, str]],
) -> None:
    for ref in _as_list(manifest.get("accepted_ts_refs")):
        if not isinstance(ref, str) or not ref:
            _finding(findings, "error", "invalid_accepted_ts_ref", "accepted_ts_ref must be a non-empty string", RESEARCH_STATE_FILE)
            continue
        path = root / ref
        if not path.exists():
            _finding(findings, "error", "missing_accepted_ts_artifact", f"missing accepted artifact: {ref}", ref)
            continue
        try:
            artifact = read_json(path)
        except Exception as exc:  # noqa: BLE001
            _finding(findings, "error", "invalid_accepted_ts_artifact", str(exc), ref)
            continue
        findings.extend(schema_findings("accepted_ts.schema.json", artifact, ref))
        if not isinstance(artifact, dict):
            _finding(findings, "error", "invalid_accepted_ts_artifact", "accepted artifact must be an object", ref)
            continue
        evidence_refs = [str(item) for item in _as_list(artifact.get("evidence_refs")) if item]
        hypothesis_id = _artifact_hypothesis_id(artifact)
        hypothesis = _mechanism_hypothesis_by_id(mechanism_model, hypothesis_id)
        require_stereo = hypothesis_requires_stereochemical_gate(hypothesis)
        try:
            gate_evidence = accepted_gate_evidence(
                evidence_records,
                evidence_refs,
                require_stereochemical_gate=require_stereo,
            )
        except ValueError as exc:
            _finding(findings, "error", "invalid_accepted_ts_gates", str(exc), ref)
            continue
        if hypothesis_id and gate_evidence.get("__hypothesis_id") != hypothesis_id:
            _finding(
                findings,
                "error",
                "invalid_accepted_ts_hypothesis",
                "accepted artifact gate evidence must match artifact.hypothesis_ref",
                ref,
            )
        diagnostic = strict_connectivity_diagnostic(gate_evidence["connectivity_gate"])
        if diagnostic:
            _finding(findings, "error", "non_strict_accepted_ts_connectivity", diagnostic, ref)
        if require_stereo:
            stereo_diagnostic = stereochemical_gate_diagnostic(gate_evidence[STEREOCHEMICAL_GATE_ROLE])
            if stereo_diagnostic:
                _finding(findings, "error", "invalid_accepted_ts_stereochemistry", stereo_diagnostic, ref)
        mechanism_roles = mechanism_reflection_required_roles(hypothesis, include_shared_basin=False)
        try:
            mechanism_gate_evidence = mechanism_reflection_gate_evidence(
                evidence_records,
                evidence_refs,
                mechanism_roles,
            )
        except ValueError as exc:
            _finding(findings, "error", "invalid_accepted_ts_mechanism_reflection_gates", str(exc), ref)
            continue
        if mechanism_roles and hypothesis_id and mechanism_gate_evidence.get("__hypothesis_id") != hypothesis_id:
            _finding(
                findings,
                "error",
                "invalid_accepted_ts_mechanism_reflection_hypothesis",
                "accepted artifact mechanism reflection evidence must match artifact.hypothesis_ref",
                ref,
            )
        for role in sorted(mechanism_roles):
            try:
                validate_mechanism_reflection_gate(mechanism_gate_evidence[role], role)
            except ValueError as exc:
                _finding(findings, "error", "invalid_accepted_ts_mechanism_reflection_gate", str(exc), ref)


def _validate_v2_accepted_audit_refs(
    research_state: dict[str, Any],
    node_details: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
) -> None:
    accepted_refs = set(str(item) for item in _as_list(research_state.get("accepted_ts_refs")) if item)
    for node_id, node in node_details.items():
        if node.get("node_type") != "audit":
            continue
        if node.get("audit_scope") not in {"transition_state", "elementary_step"}:
            continue
        closure = node.get("closure") if isinstance(node.get("closure"), dict) else {}
        audit = closure.get("audit") if isinstance(closure.get("audit"), dict) else {}
        if node.get("lifecycle") not in {"closed", "stopped"} or audit.get("status") != "accepted":
            continue
        expected_ref = f"accepted/accepted_ts_{node_id}.json"
        if expected_ref not in accepted_refs:
            _finding(
                findings,
                "error",
                "missing_v2_accepted_ts_ref",
                f"accepted v2 audit is missing accepted artifact ref: {expected_ref}",
                f"nodes/{node_id}/node.json",
            )


def _artifact_hypothesis_id(artifact: dict[str, Any]) -> str | None:
    hypothesis_ref = artifact.get("hypothesis_ref")
    if not isinstance(hypothesis_ref, dict):
        return None
    hypothesis_id = hypothesis_ref.get("hypothesis_id")
    return str(hypothesis_id) if hypothesis_id else None


def _mechanism_hypothesis_by_id(model: dict[str, Any], hypothesis_id: str | None) -> dict[str, Any] | None:
    if not hypothesis_id:
        return None
    for item in model.get("hypotheses", []):
        if isinstance(item, dict) and item.get("hypothesis_id") == hypothesis_id:
            return item
    return None


def _validate_pathway_audit_mechanism_gates(
    mechanism_model: dict[str, Any],
    node_details: dict[str, dict[str, Any]],
    evidence_records: list[Any],
    findings: list[dict[str, str]],
) -> None:
    for node_id, node in node_details.items():
        if node.get("node_type") != "audit" or node.get("audit_scope") != "pathway":
            continue
        closure = node.get("closure") if isinstance(node.get("closure"), dict) else {}
        if node.get("lifecycle") not in {"closed", "stopped"}:
            continue
        audit = closure.get("audit") if isinstance(closure.get("audit"), dict) else {}
        evidence_refs = sorted(
            set(
                _as_list(node.get("evidence_refs"))
                + _as_list(closure.get("program", {}).get("evidence_refs") if isinstance(closure.get("program"), dict) else [])
                + _as_list(audit.get("evidence_refs"))
            )
        )
        source = f"nodes/{node_id}/node.json"
        try:
            strict_decision = strict_pathway_decision(evidence_records, evidence_refs)
        except ValueError as exc:
            _finding(findings, "error", "invalid_pathway_audit_strict_decision", str(exc), source)
            continue
        if strict_decision is None:
            _finding(
                findings,
                "error",
                "missing_pathway_audit_strict_decision",
                "pathway_audit requires pathway_audit_summary evidence with quality.strict_pathway_decision",
                source,
            )
            continue
        expected_status = "accepted" if strict_decision == STRICT_PATHWAY_ACCEPTED else "not_accepted"
        if audit.get("status") != expected_status:
            _finding(
                findings,
                "error",
                "pathway_audit_status_mismatch",
                "closure.audit.status must match pathway_audit_summary quality.strict_pathway_decision",
                source,
            )
            continue
        if strict_decision != STRICT_PATHWAY_ACCEPTED:
            continue
        hypothesis_id = _node_hypothesis_id(node)
        hypothesis = _mechanism_hypothesis_by_id(mechanism_model, hypothesis_id)
        roles = mechanism_reflection_required_roles(hypothesis, include_shared_basin=True)
        try:
            gate_evidence = mechanism_reflection_gate_evidence(evidence_records, evidence_refs, roles)
        except ValueError as exc:
            _finding(findings, "error", "invalid_pathway_audit_mechanism_reflection_gates", str(exc), source)
            continue
        if roles and hypothesis_id and gate_evidence.get("__hypothesis_id") != hypothesis_id:
            _finding(
                findings,
                "error",
                "invalid_pathway_audit_mechanism_reflection_hypothesis",
                "pathway audit mechanism reflection evidence must match node.hypothesis_ref",
                source,
            )
        for role in sorted(roles):
            try:
                validate_mechanism_reflection_gate(gate_evidence[role], role)
            except ValueError as exc:
                _finding(findings, "error", "invalid_pathway_audit_mechanism_reflection_gate", str(exc), source)


def _node_hypothesis_id(node: dict[str, Any]) -> str | None:
    ref = node.get("hypothesis_ref")
    hypothesis_id = ref.get("hypothesis_id") if isinstance(ref, dict) else None
    if not hypothesis_id and node.get("mechanism_action") == "propose":
        proposed = node.get("proposed_hypothesis")
        hypothesis_id = proposed.get("hypothesis_id") if isinstance(proposed, dict) else None
    return str(hypothesis_id) if hypothesis_id else None


def _branch_target_hypothesis_ref(node: dict[str, Any]) -> Any:
    ref = node.get("hypothesis_ref")
    if isinstance(ref, dict):
        return ref
    context = node.get("branch_context") if isinstance(node.get("branch_context"), dict) else {}
    if node.get("mechanism_action") != "propose" or context.get("relation") != "new_hypothesis_branch":
        return ref
    hypothesis_id = _node_hypothesis_id(node)
    if not hypothesis_id:
        return None
    return {"hypothesis_id": hypothesis_id, "prediction_ids": []}


def _validate_evidence_artifact_boundaries(
    root: Path,
    evidence: list[Any],
    node_details: dict[str, dict[str, Any]],
    findings: list[dict[str, str]],
) -> None:
    manifest_cache: dict[str, dict[str, Any] | None] = {}
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            continue
        source = f"evidence_registry.json.evidence[{index}]"
        evidence_id = str(item.get("evidence_id") or f"#{index}")
        node_id = item.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            continue
        node = node_details.get(node_id)
        if node is None:
            _finding(findings, "error", "unknown_evidence_node", f"evidence {evidence_id} references unknown node {node_id}", source)
            continue
        if not role_matches_node(item.get("role"), node):
            _finding(
                findings,
                "warning",
                "evidence_role_node_mismatch",
                f"evidence {evidence_id} role {item.get('role')!r} is not owned by "
                f"node type/scope {node.get('node_type')!r}/"
                f"{(node.get('validation_scope') or node.get('audit_scope') or node.get('candidate_kind'))!r}",
                source,
            )
        path = item.get("path")
        owner = node_owner_from_artifact_path(path)
        if owner is None or owner == node_id:
            continue
        _finding(
            findings,
            "warning",
            "cross_node_evidence_path",
            f"evidence {evidence_id} belongs to {node_id} but path points into node {owner}",
            source,
        )
        manifest = _artifact_manifest(root, node_id, manifest_cache, findings)
        consumed = consumed_paths_from_manifest(manifest)
        if isinstance(path, str) and path not in consumed:
            _finding(
                findings,
                "warning",
                "missing_artifact_manifest_consumed_path",
                f"node {node_id} should declare consumed artifact {path!r} in outputs/artifact_manifest.json",
                f"nodes/{node_id}/outputs/artifact_manifest.json",
            )


def _artifact_manifest(
    root: Path,
    node_id: str,
    cache: dict[str, dict[str, Any] | None],
    findings: list[dict[str, str]],
) -> dict[str, Any] | None:
    if node_id in cache:
        return cache[node_id]
    path = root / "nodes" / node_id / "outputs" / "artifact_manifest.json"
    if not path.exists():
        cache[node_id] = None
        return None
    try:
        manifest = read_json(path)
    except Exception as exc:  # noqa: BLE001
        _finding(findings, "error", "invalid_artifact_manifest", str(exc), str(path))
        cache[node_id] = None
        return None
    findings.extend(schema_findings("artifact_manifest.schema.json", manifest, str(path)))
    node = read_json(root / "nodes" / node_id / "node.json")
    if isinstance(manifest, dict):
        if manifest.get("node_id") != node_id:
            _finding(findings, "error", "artifact_manifest_node_mismatch", "artifact manifest node_id must match node", str(path))
        if manifest.get("node_type") != node.get("node_type"):
            _finding(findings, "error", "artifact_manifest_node_type_mismatch", "artifact manifest node_type must match node", str(path))
    cache[node_id] = manifest if isinstance(manifest, dict) else None
    return cache[node_id]


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _reject_forbidden(value: Any, findings: list[dict[str, str]], path: str) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in FORBIDDEN_PUBLIC_FIELDS:
                _finding(findings, "error", "forbidden_public_field", f"forbidden field {key}", path)
            _reject_forbidden(nested, findings, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_forbidden(nested, findings, f"{path}[{index}]")


def _finding(findings: list[dict[str, str]], severity: str, code: str, message: str, path: str) -> None:
    findings.append({"severity": severity, "code": code, "message": message, "path": path})
