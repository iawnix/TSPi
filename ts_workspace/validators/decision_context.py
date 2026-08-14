"""Workspace-aware validation for mutation decisions."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..artifact_policy import node_owner_from_artifact_path, role_matches_node
from ..evidence_lifecycle import evidence_lifecycle_view
from ..evidence_gates import gate_artifact_metadata_diagnostic
from ..io import read_json
from ..operational import agent_run_index, review_disposition_obligations
from ..revision import report_id_for_revision, workspace_revision
from ..state import HYPOTHESES_FILE, RESEARCH_STATE_FILE
from .decision import (
    ContractError,
    validate_decision,
)
from .workspace import REQUIRED_FILES

_PROTOCOL_VARIANT_RE = re.compile(r"^(irc_.*|integrator|step_size|corrector)", re.IGNORECASE)
_PROGRAM_FAILURE_RE = re.compile(r"(convergence_failed|scheduler_failure|parser_failure)", re.IGNORECASE)
_STRATEGY_TOKEN_RE = re.compile(r"(candidate|geometry|search|seed|method|route)", re.IGNORECASE)


def validate_decision_for_workspace(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    """Validate a v2 decision against its JSON shape and current workspace state."""

    validate_decision(decision)
    return _validate_decision_for_workspace_v2(Path(root), decision)


def _validate_decision_for_workspace_v2(root: Path, decision: dict[str, Any]) -> dict[str, Any]:
    action = decision.get("action")
    if action in {"start_node", "end_node", "update_workspace"}:
        pending_reviews = review_disposition_obligations(agent_run_index(root))
        if pending_reviews:
            refs = ", ".join(
                f"{row.get('task_id')} ({row.get('run_ref')})" for row in pending_reviews[:8]
            )
            raise ContractError(
                "workspace mutation requires a Root disposition for completed Review runs: "
                f"{refs}; call ts_review_disposition first"
            )
        expected_revision = workspace_revision(root)
        if decision.get("base_revision") != expected_revision:
            raise ContractError(
                "stale workspace decision: base_revision does not match current workspace revision"
            )
        report_ref = decision.get("report_ref") if isinstance(decision.get("report_ref"), dict) else {}
        report_root = Path(str(report_ref.get("workspace_root") or "")).expanduser().resolve()
        if report_root != root.expanduser().resolve():
            raise ContractError("report_ref.workspace_root does not match the active workspace")
        if report_ref.get("report_id") != report_id_for_revision(expected_revision):
            raise ContractError("report_ref.report_id does not match the current workspace revision")
    if action == "start_node":
        _validate_start_node_context_v2(root, decision)
    elif action == "end_node":
        _validate_end_node_context_v2(root, decision)
    elif action == "update_workspace":
        _validate_update_workspace_context(root, decision)
    return decision


def _validate_start_node_context_v2(root: Path, decision: dict[str, Any]) -> None:
    _require_initialized(root)
    tree = read_json(root / RESEARCH_STATE_FILE)
    payload = decision["payload"]
    node_id = payload.get("node_id") or _next_node_id(tree)
    if (root / "nodes" / node_id / "node.json").exists():
        raise ContractError(f"node already exists: {node_id}")

    ordered_node_ids = _ordered_node_ids(tree)
    node_ids = set(ordered_node_ids)
    if not ordered_node_ids:
        if node_id != "n000" or payload.get("node_type") != "intake":
            raise ContractError("first node must be explicit n000 with node_type=intake")
        if payload.get("parent_node") is not None or payload.get("branch_context") is not None:
            raise ContractError("n000 intake cannot have a parent or branch_context")
        return

    if payload.get("node_type") == "intake":
        raise ContractError("node_type=intake is reserved for n000")
    _validate_parent_ref(payload.get("parent_node"), node_ids)
    _validate_branch_context_v2(root, payload, node_ids)
    _validate_solution_branch_v2(root, payload)
    _validate_pathway_branch_v2(root, payload)
    _require_known_evidence_refs(root, decision.get("evidence_refs", []), "decision.evidence_refs")

    recalculation = payload.get("recalculation_ref")
    if isinstance(recalculation, dict):
        source_node = recalculation.get("source_node")
        if source_node not in node_ids:
            raise ContractError(f"recalculation_ref.source_node does not exist: {source_node}")
        context = payload.get("branch_context", {})
        if context.get("from_node") != source_node:
            raise ContractError("recalculation_of requires branch_context.from_node to match recalculation_ref.source_node")

    node_type = payload.get("node_type")
    mechanism_action = payload.get("mechanism_action")
    relation = payload.get("branch_context", {}).get("relation")
    if relation == "new_hypothesis_branch" and not (
        node_type == "mechanism" and mechanism_action == "propose"
    ):
        raise ContractError("new_hypothesis_branch requires a mechanism proposal node")
    if node_type == "mechanism" and mechanism_action == "propose":
        _validate_v2_hypothesis_proposal_context(root, payload, decision.get("evidence_refs", []))
        return

    hypothesis_ref = payload.get("hypothesis_ref")
    hypothesis = _v2_hypothesis(root, hypothesis_ref)
    if not isinstance(hypothesis, dict):
        hypothesis_id = hypothesis_ref.get("hypothesis_id") if isinstance(hypothesis_ref, dict) else None
        raise ContractError(f"unknown hypothesis_ref.hypothesis_id: {hypothesis_id}")
    if hypothesis.get("status") in {"unsupported", "refuted", "superseded"} and node_type in {"candidate_search", "validation"}:
        raise ContractError("candidate or validation work cannot target an unsupported hypothesis")
    if node_type == "validation":
        prediction_ids = hypothesis_ref.get("prediction_ids", [])
        if not prediction_ids:
            raise ContractError("validation node requires at least one hypothesis_ref.prediction_id")
        predictions = {
            item.get("prediction_id"): item
            for item in hypothesis.get("testable_predictions", [])
            if isinstance(item, dict) and item.get("prediction_id")
        }
        missing = sorted(set(prediction_ids) - set(predictions))
        if missing:
            raise ContractError(f"unknown validation prediction_ids: {', '.join(missing)}")
        mismatched = sorted(
            prediction_id
            for prediction_id in prediction_ids
            if predictions[prediction_id].get("validation_scope") != payload.get("validation_scope")
        )
        if mismatched:
            raise ContractError(
                "validation_scope does not match referenced predictions: " + ", ".join(mismatched)
            )


def _validate_end_node_context_v2(root: Path, decision: dict[str, Any]) -> None:
    _require_initialized(root)
    node = _read_node(root, decision["payload"]["node_id"])
    if node.get("schema_version") != "ts-node/2":
        raise ContractError("ts-decision/2 can close only a ts-node/2 node")
    if node.get("lifecycle") != "running":
        raise ContractError(f"node is not running: {node.get('node_id')}")

    closure = decision["payload"]["closure"]
    node_type = node.get("node_type")
    hypothesis_section = closure.get("hypothesis")
    audit_section = closure.get("audit")
    intake_section = closure.get("intake")
    if node_type == "intake":
        if not isinstance(intake_section, dict):
            raise ContractError("intake closure requires closure.intake")
        if hypothesis_section is not None or audit_section is not None:
            raise ContractError("intake closure cannot set hypothesis or audit status")
    elif node_type == "mechanism":
        if not isinstance(hypothesis_section, dict):
            raise ContractError("mechanism closure requires closure.hypothesis")
        if audit_section is not None or intake_section is not None:
            raise ContractError("mechanism closure cannot set intake or audit status")
        target_id = _mechanism_target_hypothesis_id(node)
        closure_ref = hypothesis_section.get("hypothesis_ref")
        closure_id = closure_ref.get("hypothesis_id") if isinstance(closure_ref, dict) else None
        if closure_id != target_id:
            raise ContractError("closure.hypothesis.hypothesis_ref must match the mechanism node target")
    elif node_type in {"candidate_search", "validation"}:
        if hypothesis_section is not None or audit_section is not None or intake_section is not None:
            raise ContractError(f"{node_type} closure may record program facts only; use a mechanism node for hypothesis status")
        if closure["program"]["outcome"] == "not_run":
            raise ContractError(f"{node_type} closure requires a program success or failure outcome")
    elif node_type == "audit":
        if not isinstance(audit_section, dict):
            raise ContractError("audit closure requires closure.audit")
        if intake_section is not None or hypothesis_section is not None:
            raise ContractError("audit closure cannot set intake or hypothesis status")

    refs = set(decision.get("evidence_refs", []))
    refs.update(closure.get("program", {}).get("evidence_refs", []))
    if isinstance(hypothesis_section, dict):
        refs.update(hypothesis_section.get("evidence_refs", []))
    if isinstance(audit_section, dict):
        refs.update(audit_section.get("evidence_refs", []))
    _require_known_evidence_refs(root, sorted(refs), "closure evidence_refs")


def _validate_branch_context_v2(root: Path, payload: dict[str, Any], node_ids: set[str]) -> None:
    context = payload.get("branch_context")
    if not isinstance(context, dict):
        raise ContractError("payload.branch_context is required after n000")
    from_node = context.get("from_node")
    anchor_node = context.get("anchor_node")
    if from_node not in node_ids or anchor_node not in node_ids:
        raise ContractError("branch_context from_node and anchor_node must exist")
    relation = context.get("relation")
    if relation in {"continue_parent", "recalculation_of"}:
        _require_parent_matches(payload, from_node, "from_node", relation)
    else:
        _require_parent_matches(payload, anchor_node, "anchor_node", relation)
        if not _is_ancestor(root, anchor_node, from_node):
            raise ContractError(f"{relation} anchor_node must be an ancestor of branch_context.from_node")
    _require_known_evidence_refs(root, context.get("evidence_refs", []), "branch_context.evidence_refs")


def _validate_solution_branch_v2(root: Path, payload: dict[str, Any]) -> None:
    context = payload.get("branch_context") if isinstance(payload.get("branch_context"), dict) else {}
    if context.get("relation") != "new_solution_branch":
        return
    solution_ref = payload.get("solution_ref")
    if not isinstance(solution_ref, dict) or not str(solution_ref.get("solution_id") or "").strip():
        raise ContractError("new_solution_branch requires payload.solution_ref.solution_id")
    from_node = _read_node(root, str(context["from_node"]))
    from_hypothesis = _referenced_hypothesis_id(from_node)
    target_hypothesis = _referenced_hypothesis_id(payload)
    if from_hypothesis and target_hypothesis and from_hypothesis != target_hypothesis:
        raise ContractError("new_solution_branch must keep the same hypothesis_id")
    known_solution_ids = _solution_ids_for_hypothesis(root, target_hypothesis)
    if solution_ref["solution_id"] in known_solution_ids:
        raise ContractError("new_solution_branch requires a new payload.solution_ref.solution_id unique within the workspace")
    _validate_solution_parent(from_node, solution_ref)


def _validate_pathway_branch_v2(root: Path, payload: dict[str, Any]) -> None:
    context = payload.get("branch_context") if isinstance(payload.get("branch_context"), dict) else {}
    if context.get("relation") != "new_pathway_branch":
        return
    pathway_ref = payload.get("pathway_ref")
    if not isinstance(pathway_ref, dict) or not str(pathway_ref.get("pathway_id") or "").strip():
        raise ContractError("new_pathway_branch requires payload.pathway_ref.pathway_id")
    known_pathway_ids = _workspace_pathway_ids(root)
    if pathway_ref["pathway_id"] in known_pathway_ids:
        raise ContractError("new_pathway_branch requires a workspace-new payload.pathway_ref.pathway_id")
    from_node = _read_node(root, str(context["from_node"]))
    from_hypothesis = _referenced_hypothesis_id(from_node)
    target_hypothesis = _referenced_hypothesis_id(payload)
    if from_hypothesis and target_hypothesis and from_hypothesis != target_hypothesis:
        raise ContractError("new_pathway_branch must keep the same hypothesis_id")


def _workspace_pathway_ids(root: Path) -> set[str]:
    model = read_json(root / HYPOTHESES_FILE)
    pathway_ids = {
        str(item.get("pathway_id"))
        for item in model.get("pathways", [])
        if isinstance(item, dict) and item.get("pathway_id")
    }
    state = read_json(root / RESEARCH_STATE_FILE)
    for entry in state.get("nodes", []):
        if not isinstance(entry, dict):
            continue
        pathway_ref = entry.get("pathway_ref") if isinstance(entry.get("pathway_ref"), dict) else {}
        if pathway_ref.get("pathway_id"):
            pathway_ids.add(str(pathway_ref["pathway_id"]))
    return pathway_ids


def _solution_ids_for_hypothesis(root: Path, hypothesis_id: str | None, *, exclude_node: str | None = None) -> set[str]:
    state = read_json(root / RESEARCH_STATE_FILE)
    solution_ids: set[str] = set()
    for entry in state.get("nodes", []):
        if not isinstance(entry, dict) or entry.get("node_id") == exclude_node:
            continue
        node_id = entry.get("node_id")
        node_path = root / "nodes" / str(node_id) / "node.json"
        node = read_json(node_path) if node_path.exists() else entry
        if _referenced_hypothesis_id(node) != hypothesis_id:
            continue
        solution_ref = node.get("solution_ref") if isinstance(node.get("solution_ref"), dict) else {}
        if solution_ref.get("solution_id"):
            solution_ids.add(str(solution_ref["solution_id"]))
    return solution_ids


def _validate_solution_parent(from_node: dict[str, Any], solution_ref: dict[str, Any]) -> None:
    from_solution = from_node.get("solution_ref") if isinstance(from_node.get("solution_ref"), dict) else {}
    source_solution_id = from_solution.get("solution_id")
    parent_solution_id = solution_ref.get("parent_solution_id")
    if source_solution_id and parent_solution_id != source_solution_id:
        raise ContractError("solution_ref.parent_solution_id must match the source node solution_id")
    if not source_solution_id and parent_solution_id is not None:
        raise ContractError("solution_ref.parent_solution_id requires an identified source solution")


def _referenced_hypothesis_id(value: dict[str, Any]) -> str | None:
    ref = value.get("hypothesis_ref") if isinstance(value.get("hypothesis_ref"), dict) else {}
    hypothesis_id = ref.get("hypothesis_id")
    if not hypothesis_id and value.get("mechanism_action") == "propose":
        proposed = value.get("proposed_hypothesis") if isinstance(value.get("proposed_hypothesis"), dict) else {}
        hypothesis_id = proposed.get("hypothesis_id")
    return str(hypothesis_id) if hypothesis_id else None


def _validate_v2_hypothesis_proposal_context(root: Path, payload: dict[str, Any], evidence_refs: list[Any]) -> None:
    proposed = payload["proposed_hypothesis"]
    hypothesis_id = proposed["hypothesis_id"]
    model = read_json(root / HYPOTHESES_FILE)
    known = {
        item.get("hypothesis_id"): item
        for item in model.get("hypotheses", [])
        if isinstance(item, dict) and item.get("hypothesis_id")
    }
    if hypothesis_id in known:
        raise ContractError(f"hypothesis_id already exists: {hypothesis_id}")
    _require_known_evidence_refs(root, evidence_refs, "mechanism proposal evidence_refs")
    parent_hypothesis_id = proposed.get("parent_hypothesis_id")
    if not known:
        if parent_hypothesis_id is not None:
            raise ContractError("initial mechanism proposal cannot have parent_hypothesis_id")
        if payload.get("parent_node") != "n000":
            raise ContractError("initial mechanism proposal must be parented to n000")
        return
    if not isinstance(parent_hypothesis_id, str) or parent_hypothesis_id not in known:
        raise ContractError("alternative mechanism proposal requires a known parent_hypothesis_id")
    parent_ref = payload.get("hypothesis_ref")
    if not isinstance(parent_ref, dict) or parent_ref.get("hypothesis_id") != parent_hypothesis_id:
        raise ContractError("alternative mechanism proposal hypothesis_ref must identify its parent hypothesis")
    if payload.get("branch_context", {}).get("relation") != "new_hypothesis_branch":
        raise ContractError("alternative mechanism proposal requires relation=new_hypothesis_branch")


def _v2_hypothesis(root: Path, ref: Any) -> dict[str, Any] | None:
    hypothesis_id = ref.get("hypothesis_id") if isinstance(ref, dict) else None
    if not isinstance(hypothesis_id, str) or not hypothesis_id:
        return None
    model = read_json(root / HYPOTHESES_FILE)
    return next(
        (
            item
            for item in model.get("hypotheses", [])
            if isinstance(item, dict) and item.get("hypothesis_id") == hypothesis_id
        ),
        None,
    )


def _mechanism_target_hypothesis_id(node: dict[str, Any]) -> Any:
    if node.get("mechanism_action") == "propose":
        proposed = node.get("proposed_hypothesis")
        return proposed.get("hypothesis_id") if isinstance(proposed, dict) else None
    ref = node.get("hypothesis_ref")
    return ref.get("hypothesis_id") if isinstance(ref, dict) else None


def _require_known_evidence_refs(root: Path, refs: Any, label: str) -> None:
    if not refs:
        return
    registry = read_json(root / "evidence_registry.json")
    view = evidence_lifecycle_view(registry.get("evidence", []))
    missing = sorted(
        str(item)
        for item in refs
        if item and view.resolve_ref(str(item)) is None
    )
    if missing:
        raise ContractError(f"{label} references unknown evidence: {', '.join(missing)}")


def detect_decision_warnings(root: str | Path, decision: dict[str, Any]) -> list[dict[str, str]]:
    """Return non-blocking hints for suspicious decision patterns.

    Warnings never reject a decision; they surface likely-misclassification
    signals so the agent can reconsider. Empty list means no signals fired.
    """
    if decision.get("action") != "start_node":
        return []
    payload = decision.get("payload") or {}
    context = payload.get("branch_context") if isinstance(payload.get("branch_context"), dict) else {}
    relation = context.get("relation")
    if relation != "new_solution_branch":
        return []

    warnings: list[dict[str, str]] = []
    node_type = payload.get("node_type")
    validation_scope = payload.get("validation_scope")
    changed_variable = str(context.get("changed_variable") or "")
    reason_code = str(context.get("reason_code") or "")

    if (
        node_type == "validation"
        and validation_scope == "connectivity"
        and changed_variable
        and _PROTOCOL_VARIANT_RE.match(changed_variable)
    ):
        warnings.append(
            {
                "code": "suspicious_new_solution_branch_for_protocol_variant",
                "message": (
                    "new_solution_branch used with an IRC-protocol changed_variable "
                    f"({changed_variable!r}) on a connectivity validation node; "
                    "same-claim IRC parameter changes are usually continue_parent."
                ),
            }
        )
    if reason_code and _PROGRAM_FAILURE_RE.search(reason_code):
        warnings.append(
            {
                "code": "program_failure_used_as_new_solution_branch",
                "message": (
                    "new_solution_branch driven by a program-level failure "
                    f"({reason_code!r}); program failure is not automatically a new branch."
                ),
            }
        )

    hypothesis_ref = payload.get("hypothesis_ref") if isinstance(payload.get("hypothesis_ref"), dict) else {}
    hypothesis_id = hypothesis_ref.get("hypothesis_id")
    if hypothesis_id and _hypothesis_had_recent_tsfreq_support(Path(root), hypothesis_id) and (
        not changed_variable or not _STRATEGY_TOKEN_RE.search(changed_variable)
    ):
        warnings.append(
            {
                "code": "same_claim_reused_as_new_solution_branch",
                "message": (
                    "new_solution_branch under a hypothesis that already has a "
                    "TS/Freq-supported node in the last 24h with no candidate/geometry/search-level "
                    "changed_variable; reconsider continue_parent."
                ),
            }
        )

    return warnings


def _hypothesis_had_recent_tsfreq_support(root: Path, hypothesis_id: str) -> bool:
    tree_path = root / RESEARCH_STATE_FILE
    if not tree_path.exists():
        return False
    try:
        tree = read_json(tree_path)
    except Exception:  # noqa: BLE001
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    for entry in tree.get("nodes", []):
        if entry.get("node_type") != "validation" or entry.get("validation_scope") != "tsfreq":
            continue
        if entry.get("program_outcome") != "success":
            continue
        node_path = root / "nodes" / str(entry.get("node_id")) / "node.json"
        if not node_path.exists():
            continue
        try:
            node = read_json(node_path)
        except Exception:  # noqa: BLE001
            continue
        node_hyp = node.get("hypothesis_ref") if isinstance(node.get("hypothesis_ref"), dict) else {}
        if node_hyp.get("hypothesis_id") != hypothesis_id:
            continue
        closed_at = node.get("closure", {}).get("closed_at") if isinstance(node.get("closure"), dict) else None
        if not closed_at:
            continue
        try:
            closed_ts = datetime.fromisoformat(closed_at)
        except ValueError:
            continue
        if closed_ts.tzinfo is None:
            closed_ts = closed_ts.replace(tzinfo=timezone.utc)
        if closed_ts >= cutoff:
            return True
    return False


def _validate_update_workspace_context(root: Path, decision: dict[str, Any]) -> None:
    _require_initialized(root)
    payload = decision["payload"]
    repair = payload.get("repair_branch_anchor")
    if repair is not None:
        entries = repair if isinstance(repair, list) else [repair]
        for entry in entries:
            _validate_branch_anchor_repair(root, entry)

    solution_repair = payload.get("repair_solution_ref")
    if solution_repair is not None:
        entries = solution_repair if isinstance(solution_repair, list) else [solution_repair]
        for entry in entries:
            _validate_solution_ref_repair(root, entry)

    evidence = payload.get("append_evidence")
    if evidence is None:
        return
    entries = evidence if isinstance(evidence, list) else [evidence]
    registry = read_json(root / "evidence_registry.json")
    evidence_lifecycle_view([*registry.get("evidence", []), *entries])
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        node_id = entry.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            continue
        node = _read_node(root, node_id)
        path = entry.get("path")
        if (
            entry.get("kind") != "evidence_lifecycle"
            and isinstance(path, str)
            and path.strip()
            and not role_matches_node(entry.get("role"), node)
        ):
            raise ContractError(
                "append_evidence.role does not match the node type/scope for a path-bearing artifact: "
                f"role={entry.get('role')!r}, node={node_id}, "
                f"type={node.get('node_type')!r}, "
                f"scope={node.get('validation_scope') or node.get('audit_scope') or node.get('candidate_kind')!r}"
            )
        owner = node_owner_from_artifact_path(path)
        if owner is not None and owner != node_id:
            raise ContractError(
                "append_evidence.path points to a different node artifact directory: "
                f"path owner={owner}, evidence.node_id={node_id}. "
                "Write the validation artifact under the current node and record upstream files "
                "in nodes/<node>/outputs/artifact_manifest.json consumed_artifacts."
            )
        gate_diagnostic = gate_artifact_metadata_diagnostic(entry)
        if gate_diagnostic:
            raise ContractError(gate_diagnostic)


def _validate_branch_anchor_repair(root: Path, repair: Any) -> None:
    if not isinstance(repair, dict):
        raise ContractError("repair_branch_anchor entries must be objects")
    node_id = repair.get("node_id")
    new_anchor = repair.get("new_anchor_node")
    if not isinstance(node_id, str) or not node_id:
        raise ContractError("repair_branch_anchor.node_id is required")
    if not isinstance(new_anchor, str) or not new_anchor:
        raise ContractError("repair_branch_anchor.new_anchor_node is required")
    if not (root / "nodes" / new_anchor / "node.json").exists():
        raise ContractError(f"repair_branch_anchor.new_anchor_node does not exist: {new_anchor}")
    node = _read_node(root, node_id)
    if node.get("lifecycle") == "running":
        raise ContractError(f"repair_branch_anchor refuses to reparent running node: {node_id}")
    context = node.get("branch_context") if isinstance(node.get("branch_context"), dict) else {}
    if context.get("relation") != "new_solution_branch":
        raise ContractError(f"repair_branch_anchor only applies to new_solution_branch nodes: {node_id}")
    from_node = context.get("from_node")
    if not _is_ancestor(root, new_anchor, from_node):
        raise ContractError(
            "repair_branch_anchor.new_anchor_node must be an ancestor of branch_context.from_node: "
            f"node_id={node_id}, from_node={from_node}, new_anchor_node={new_anchor}"
        )


def _validate_solution_ref_repair(root: Path, repair: Any) -> None:
    if not isinstance(repair, dict):
        raise ContractError("repair_solution_ref entries must be objects")
    node_id = repair.get("node_id")
    if not isinstance(node_id, str) or not node_id:
        raise ContractError("repair_solution_ref.node_id is required")
    node = _read_node(root, node_id)
    if node.get("lifecycle") == "running":
        raise ContractError(f"repair_solution_ref refuses to modify running node: {node_id}")
    context = node.get("branch_context") if isinstance(node.get("branch_context"), dict) else {}
    if context.get("relation") != "new_solution_branch":
        raise ContractError(f"repair_solution_ref only applies to new_solution_branch nodes: {node_id}")
    if isinstance(node.get("solution_ref"), dict) and node["solution_ref"].get("solution_id"):
        raise ContractError(f"repair_solution_ref refuses to overwrite an existing solution_ref: {node_id}")
    solution_ref = repair.get("solution_ref")
    if not isinstance(solution_ref, dict) or not str(solution_ref.get("solution_id") or "").strip():
        raise ContractError("repair_solution_ref.solution_ref.solution_id is required")
    hypothesis_id = _referenced_hypothesis_id(node)
    if solution_ref["solution_id"] in _solution_ids_for_hypothesis(root, hypothesis_id, exclude_node=node_id):
        raise ContractError("repair_solution_ref requires a workspace-new solution_ref.solution_id")
    from_node = _read_node(root, str(context.get("from_node") or ""))
    _validate_solution_parent(from_node, solution_ref)


def _require_initialized(root: Path) -> None:
    missing = [filename for filename in REQUIRED_FILES if not (root / filename).exists()]
    if missing:
        raise ContractError(f"workspace is not initialized; missing {', '.join(sorted(missing))}")


def _ordered_node_ids(tree: dict[str, Any]) -> list[str]:
    nodes = tree.get("nodes", [])
    if not isinstance(nodes, list):
        raise ContractError("research_state.nodes must be a list")
    ordered: list[str] = []
    for entry in nodes:
        if not isinstance(entry, dict):
            raise ContractError("research state node entry must be an object")
        node_id = entry.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            raise ContractError("research state node missing node_id")
        ordered.append(node_id)
    return ordered


def _validate_parent_ref(parent_node: Any, node_ids: set[str]) -> None:
    if parent_node is None:
        return
    if parent_node not in node_ids:
        raise ContractError(f"payload.parent_node does not exist: {parent_node}")


def _require_parent_matches(payload: dict[str, Any], expected_node: Any, expected_field: str, relation: Any) -> None:
    parent_node = payload.get("parent_node")
    if parent_node != expected_node:
        raise ContractError(f"{relation} branch_context requires parent_node to match {expected_field}")


def _read_node(root: Path, node_id: str) -> dict[str, Any]:
    node_path = root / "nodes" / node_id / "node.json"
    if not node_path.exists():
        raise ContractError(f"missing node.json for {node_id}")
    node = read_json(node_path)
    if not isinstance(node, dict):
        raise ContractError(f"node.json for {node_id} must be an object")
    return node


def _is_ancestor(root: Path, ancestor_id: Any, node_id: Any) -> bool:
    if not isinstance(ancestor_id, str) or not isinstance(node_id, str):
        return False
    current: str | None = node_id
    visited: set[str] = set()
    while current and current not in visited:
        if current == ancestor_id:
            return True
        visited.add(current)
        node = _read_node(root, current)
        parent = node.get("parent_node")
        current = parent if isinstance(parent, str) and parent else None
    return False


def _next_node_id(tree: dict[str, Any]) -> str:
    numbers = []
    for entry in tree.get("nodes", []):
        if not isinstance(entry, dict):
            continue
        node_id = entry.get("node_id", "")
        if node_id.startswith("n") and node_id[1:].isdigit():
            numbers.append(int(node_id[1:]))
    return f"n{(max(numbers) + 1) if numbers else 1:03d}"
