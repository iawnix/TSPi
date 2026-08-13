"""LLM-facing workspace report builder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..evidence_lifecycle import EvidenceLifecycleError, evidence_lifecycle_view
from ..identity import IDENTITY_REF, WorkspaceIdentityError, read_workspace_identity
from ..io import read_json, write_json
from ..operational import agent_run_index, operational_snapshot
from ..revision import report_id_for_revision, workspace_revision_from_documents
from ..state import EVIDENCE_FILE, HYPOTHESES_FILE, RESEARCH_STATE_FILE
from ..validators.workspace import validate_workspace

def report_workspace(root: str | Path) -> dict[str, Any]:
    """Build a read-only report context. This function does NOT write to disk.

    Use `snapshot_report(root)` when a persisted audit snapshot is needed.
    """
    root_path = Path(root).resolve()
    validation = validate_workspace(root_path)

    research_state = _read_or_empty(root_path / RESEARCH_STATE_FILE)
    hypotheses = _read_or_empty(root_path / HYPOTHESES_FILE)
    evidence = _read_or_empty(root_path / EVIDENCE_FILE)
    evidence_records = evidence.get("evidence", []) if isinstance(evidence, dict) else []
    try:
        lifecycle_view = evidence_lifecycle_view(evidence_records)
        active_evidence_records = lifecycle_view.active_records
        lifecycle_counts: dict[str, int] = {}
        for status in lifecycle_view.status_by_id.values():
            lifecycle_counts[status] = lifecycle_counts.get(status, 0) + 1
    except EvidenceLifecycleError:
        active_evidence_records = [item for item in evidence_records if isinstance(item, dict)]
        lifecycle_counts = {"unresolved": len(active_evidence_records)}
    active_evidence = {"schema_version": "ts-evidence-registry", "evidence": active_evidence_records}
    tree = research_state
    manifest = research_state
    pathway = hypotheses
    mechanism = hypotheses

    nodes = tree.get("nodes", []) if isinstance(tree, dict) else []
    branch_events = tree.get("branch_events", []) if isinstance(tree, dict) else []
    open_nodes = [item for item in nodes if item.get("lifecycle") == "running"]
    closed_nodes = [item for item in nodes if item.get("lifecycle") in {"closed", "stopped"}]
    hypothesis_context = _build_hypothesis_context(mechanism, active_evidence, manifest)
    workspace_revision = workspace_revision_from_documents(research_state, hypotheses, evidence)
    report_id = report_id_for_revision(workspace_revision)
    operations = operational_snapshot(root_path)
    try:
        identity = read_workspace_identity(root_path)
    except WorkspaceIdentityError:
        identity = {}

    report = {
        "report_id": report_id,
        "workspace_id": identity.get("workspace_id"),
        "workspace_revision": workspace_revision,
        "operational_revision": operations["operational_revision"],
        "workspace_root": str(root_path),
        "valid": validation["valid"],
        "validation_findings": validation["findings"],
        "focus": {
            "current_node": tree.get("current_node"),
            "focus_pathway_id": pathway.get("focus_pathway_id"),
            "focus_hypothesis_id": mechanism.get("focus_hypothesis_id"),
            "accepted_ts_refs": manifest.get("accepted_ts_refs", []),
        },
        "hypothesis_context": hypothesis_context,
        "node_index": nodes,
        "solution_lineage": _build_solution_lineage(nodes, branch_events),
        "branch_frontiers": _build_branch_frontiers(nodes, branch_events),
        "readiness": _build_readiness(validation, manifest, hypothesis_context),
        "open_nodes": open_nodes,
        "closed_node_count": len(closed_nodes),
        "evidence_count": len(active_evidence_records),
        "evidence_history_count": len(evidence_records),
        "evidence_lifecycle": lifecycle_counts,
        "branch_events": branch_events,
        "agent_runs": operations["agent_runs"],
        "pending_controls": operations["pending_controls"],
        "unresolved_controls": operations["unresolved_controls"],
        "ambiguous_submissions": operations["ambiguous_submissions"],
        "ambiguous_cancellations": operations["ambiguous_cancellations"],
        "retryable_controls": operations["retryable_controls"],
        "operational_summary": operations["operational_summary"],
        "workspace_state_refs": {
            "workspace_identity": IDENTITY_REF,
            "research_state": RESEARCH_STATE_FILE,
            "hypotheses": HYPOTHESES_FILE,
            "evidence_registry": EVIDENCE_FILE,
        },
        "allowed_decision_actions": [
            "start_node",
            "end_node",
            "update_workspace",
            "ask_user",
            "stop",
        ],
        "decision_contract": {
            "schema_version": "ts-decision/2",
            "requires_report_ref": ["start_node", "end_node", "update_workspace"],
            "mutation_channel": "ts_workspace",
        },
    }
    return report


def report_node(root: str | Path, node_id: str) -> dict[str, Any]:
    """Return a compact, read-only context capsule for one historical node."""

    root_path = Path(root)
    research_state = read_json(root_path / RESEARCH_STATE_FILE)
    hypotheses = read_json(root_path / HYPOTHESES_FILE)
    registry = read_json(root_path / EVIDENCE_FILE)
    evidence_records = registry.get("evidence", [])
    lifecycle_view = evidence_lifecycle_view(evidence_records)
    node_path = root_path / "nodes" / node_id / "node.json"
    if not node_path.exists():
        raise ValueError(f"unknown node: {node_id}")
    node = read_json(node_path)
    if not isinstance(node, dict):
        raise ValueError(f"node record must be an object: {node_id}")

    evidence_refs = _node_evidence_refs(node)
    resolved_evidence_refs = set(lifecycle_view.resolve_refs(sorted(evidence_refs)))
    evidence = [
        _evidence_capsule(entry)
        for entry in lifecycle_view.active_records
        if isinstance(entry, dict)
        and (entry.get("node_id") == node_id or entry.get("evidence_id") in resolved_evidence_refs)
    ]
    events = [
        _branch_event_capsule(event)
        for event in research_state.get("branch_events", [])
        if isinstance(event, dict) and node_id in {event.get("from_node"), event.get("anchor_node"), event.get("new_node")}
    ]
    hypothesis_id = _node_hypothesis_id(node)
    pathway_ref = node.get("pathway_ref") if isinstance(node.get("pathway_ref"), dict) else {}
    agent_runs = [row for row in agent_run_index(root_path) if node_id in row.get("node_ids", [])]

    return {
        "context_type": "node",
        "workspace_root": str(root_path),
        "node": _node_capsule(node),
        "lineage": _lineage_to_root(research_state, node_id),
        "evidence": evidence,
        "evidence_lifecycle": {
            evidence_id: lifecycle_view.status_by_id.get(evidence_id)
            for evidence_id in sorted(evidence_refs)
            if evidence_id in lifecycle_view.status_by_id
        },
        "branch_events": events,
        "hypothesis": _hypothesis_capsule(
            _find_by_id(hypotheses.get("hypotheses", []), "hypothesis_id", hypothesis_id)
        ),
        "pathway": _pathway_capsule(
            _find_by_id(hypotheses.get("pathways", []), "pathway_id", pathway_ref.get("pathway_id"))
        ),
        "decisions": _node_decision_capsules(root_path, node),
        "artifact_refs": _artifact_refs(node, evidence),
        "agent_runs": agent_runs,
    }


def report_branch_context(root: str | Path, from_node: str, anchor_node: str) -> dict[str, Any]:
    """Return the trigger, selected checkpoint, and intervening attempt summaries."""

    root_path = Path(root)
    research_state = read_json(root_path / RESEARCH_STATE_FILE)
    path = _path_from_ancestor(research_state, anchor_node, from_node)
    if path is None:
        raise ValueError(f"anchor_node must be an ancestor of from_node: {anchor_node} -> {from_node}")
    return {
        "context_type": "branch",
        "workspace_root": str(root_path),
        "from_node": report_node(root_path, from_node),
        "anchor_node": report_node(root_path, anchor_node),
        "path_delta": [
            _node_capsule(read_json(root_path / "nodes" / node_id / "node.json"))
            for node_id in path[1:]
        ],
    }


def snapshot_report(root: str | Path) -> dict[str, Any]:
    """Build a report and persist it under `reports/<report_id>.json`."""
    root_path = Path(root)
    report = report_workspace(root_path)
    write_json(root_path / "reports" / f"{report['report_id']}.json", report)
    return report


def _read_or_empty(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return read_json(path)
    except Exception:  # noqa: BLE001
        return {}


def _node_capsule(node: dict[str, Any]) -> dict[str, Any]:
    closure = node.get("closure") if isinstance(node.get("closure"), dict) else {}
    program = closure.get("program") if isinstance(closure.get("program"), dict) else {}
    hypothesis = closure.get("hypothesis") if isinstance(closure.get("hypothesis"), dict) else {}
    audit = closure.get("audit") if isinstance(closure.get("audit"), dict) else {}
    return {
        "node_id": node.get("node_id"),
        "parent_node": node.get("parent_node"),
        "node_type": node.get("node_type"),
        "objective": node.get("objective"),
        "mechanism_action": node.get("mechanism_action"),
        "candidate_kind": node.get("candidate_kind"),
        "validation_scope": node.get("validation_scope"),
        "audit_scope": node.get("audit_scope"),
        "attempt_kind": node.get("attempt_kind"),
        "recalculation_ref": node.get("recalculation_ref"),
        "lifecycle": node.get("lifecycle"),
        "hypothesis_ref": node.get("hypothesis_ref"),
        "solution_ref": node.get("solution_ref"),
        "pathway_ref": node.get("pathway_ref"),
        "branch_context": node.get("branch_context"),
        "program_outcome": program.get("outcome"),
        "hypothesis_status": hypothesis.get("status"),
        "audit_status": audit.get("status"),
        "study_complete": audit.get("study_complete"),
        "program_summary": program.get("summary"),
        "program_facts": program.get("facts", []),
        "open_questions": closure.get("open_questions", []),
        "evidence_refs": sorted(_node_evidence_refs(node)),
        "created_by_decision": node.get("created_by_decision"),
        "ended_by_decision": node.get("ended_by_decision"),
    }


def _node_evidence_refs(node: dict[str, Any]) -> set[str]:
    refs = {str(item) for item in node.get("evidence_refs", []) if item}
    context = node.get("branch_context") if isinstance(node.get("branch_context"), dict) else {}
    refs.update(str(item) for item in context.get("evidence_refs", []) if item)
    closure = node.get("closure") if isinstance(node.get("closure"), dict) else {}
    for section_name in ("program", "hypothesis", "audit"):
        section = closure.get(section_name) if isinstance(closure.get(section_name), dict) else {}
        refs.update(str(item) for item in section.get("evidence_refs", []) if item)
    return refs


def _node_hypothesis_id(node: dict[str, Any]) -> str | None:
    ref = node.get("hypothesis_ref") if isinstance(node.get("hypothesis_ref"), dict) else {}
    hypothesis_id = ref.get("hypothesis_id")
    if not hypothesis_id:
        proposed = node.get("proposed_hypothesis")
        hypothesis_id = proposed.get("hypothesis_id") if isinstance(proposed, dict) else None
    return str(hypothesis_id) if hypothesis_id else None


def _evidence_capsule(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_id": entry.get("evidence_id"),
        "node_id": entry.get("node_id"),
        "kind": entry.get("kind"),
        "role": entry.get("role"),
        "evidence_tier": entry.get("evidence_tier"),
        "summary": entry.get("summary"),
        "quality": entry.get("quality", {}),
        "diagnostics": entry.get("diagnostics", []),
        "path": entry.get("path"),
        "source_files": entry.get("source_files", []),
        "normal_termination": entry.get("normal_termination"),
        "supersedes_evidence_id": entry.get("supersedes_evidence_id"),
        "lifecycle_status": "active",
    }


def _branch_event_capsule(event: dict[str, Any]) -> dict[str, Any]:
    return {
        key: event.get(key)
        for key in (
            "event_id",
            "relation",
            "from_node",
            "anchor_node",
            "new_node",
            "parent_node",
            "is_rebased",
            "changed_variable",
            "reason_code",
            "rationale",
            "evidence_refs",
        )
        if key in event
    }


def _lineage_to_root(research_state: dict[str, Any], node_id: str) -> list[str]:
    parents = {
        str(item.get("node_id")): item.get("parent_node")
        for item in research_state.get("nodes", [])
        if isinstance(item, dict) and item.get("node_id")
    }
    lineage: list[str] = []
    current: str | None = node_id
    visited: set[str] = set()
    while current and current not in visited:
        visited.add(current)
        lineage.append(current)
        parent = parents.get(current)
        current = parent if isinstance(parent, str) and parent else None
    lineage.reverse()
    return lineage


def _path_from_ancestor(research_state: dict[str, Any], anchor_node: str, from_node: str) -> list[str] | None:
    lineage = _lineage_to_root(research_state, from_node)
    if anchor_node not in lineage:
        return None
    return lineage[lineage.index(anchor_node):]


def _find_by_id(values: Any, key: str, expected: Any) -> dict[str, Any]:
    if expected is None or not isinstance(values, list):
        return {}
    return next(
        (item for item in values if isinstance(item, dict) and item.get(key) == expected),
        {},
    )


def _hypothesis_capsule(hypothesis: dict[str, Any]) -> dict[str, Any]:
    if not hypothesis:
        return {}
    return {
        key: hypothesis.get(key)
        for key in (
            "hypothesis_id",
            "status",
            "summary",
            "parent_hypothesis_id",
            "source_node",
            "branch_anchor_node",
            "structured_claim",
            "testable_predictions",
            "prediction_status",
            "required_evidence",
            "uncertainties",
            "evidence_refs",
        )
        if key in hypothesis
    }


def _pathway_capsule(pathway: dict[str, Any]) -> dict[str, Any]:
    if not pathway:
        return {}
    return {
        key: pathway.get(key)
        for key in ("pathway_id", "label", "pattern", "status", "steps", "audit_nodes")
        if key in pathway
    }


def _node_decision_capsules(root: Path, node: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for field in ("created_by_decision", "ended_by_decision"):
        decision_id = node.get(field)
        if not isinstance(decision_id, str) or not decision_id or decision_id in seen:
            continue
        seen.add(decision_id)
        path = root / "decisions" / f"{decision_id}.json"
        if not path.exists():
            continue
        decision = read_json(path)
        if not isinstance(decision, dict):
            continue
        out.append(
            {
                "decision_id": decision_id,
                "action": decision.get("action"),
                "rationale": decision.get("rationale"),
                "evidence_refs": decision.get("evidence_refs", []),
            }
        )
    return out


def _artifact_refs(node: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "node_artifacts": node.get("artifacts", {}),
        "evidence_paths": sorted({str(item["path"]) for item in evidence if item.get("path")}),
        "source_files": sorted(
            {
                str(source)
                for item in evidence
                for source in item.get("source_files", [])
                if source
            }
        ),
    }


def _build_solution_lineage(nodes: list[Any], branch_events: list[Any]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    node_by_id = {str(node.get("node_id")): node for node in nodes if isinstance(node, dict) and node.get("node_id")}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        hypothesis_ref = node.get("hypothesis_ref") if isinstance(node.get("hypothesis_ref"), dict) else {}
        solution_ref = node.get("solution_ref") if isinstance(node.get("solution_ref"), dict) else {}
        if not solution_ref:
            continue
        hypothesis_id = str(hypothesis_ref.get("hypothesis_id") or "unassigned")
        group = groups.setdefault(hypothesis_id, {"hypothesis_id": hypothesis_id, "solutions": {}, "branch_events": []})
        solution_id = str(solution_ref.get("solution_id") or "unassigned")
        solution = group["solutions"].setdefault(
            solution_id,
            {
                "solution_id": solution_id,
                "solution_ref": solution_ref,
                "nodes": [],
                "latest_lifecycle": None,
                "latest_program_outcome": None,
                "latest_hypothesis_status": None,
                "latest_audit_status": None,
            },
        )
        solution["nodes"].append(node.get("node_id"))
        solution["latest_lifecycle"] = node.get("lifecycle")
        solution["latest_program_outcome"] = node.get("program_outcome")
        solution["latest_hypothesis_status"] = node.get("hypothesis_status")
        solution["latest_audit_status"] = node.get("audit_status")

    for event in branch_events:
        if not isinstance(event, dict):
            continue
        target_ref = event.get("target_hypothesis_ref") if isinstance(event.get("target_hypothesis_ref"), dict) else {}
        if not target_ref:
            target_node = node_by_id.get(str(event.get("new_node")))
            target_ref = target_node.get("hypothesis_ref") if isinstance(target_node, dict) and isinstance(target_node.get("hypothesis_ref"), dict) else {}
        hypothesis_id = str(target_ref.get("hypothesis_id") or "unassigned")
        if hypothesis_id not in groups:
            groups[hypothesis_id] = {"hypothesis_id": hypothesis_id, "solutions": {}, "branch_events": []}
        groups[hypothesis_id]["branch_events"].append(
            {
                "event_id": event.get("event_id"),
                "relation": event.get("relation"),
                "from_node": event.get("from_node"),
                "anchor_node": event.get("anchor_node"),
                "new_node": event.get("new_node"),
                "reason_code": event.get("reason_code"),
                "changed_variable": event.get("changed_variable"),
                "target_solution_ref": event.get("target_solution_ref"),
            }
        )

    out: list[dict[str, Any]] = []
    for hypothesis_id in sorted(groups):
        group = groups[hypothesis_id]
        out.append(
            {
                "hypothesis_id": hypothesis_id,
                "solutions": [
                    group["solutions"][solution_id]
                    for solution_id in sorted(group["solutions"])
                ],
                "branch_events": group["branch_events"],
            }
        )
    return out


def _build_branch_frontiers(nodes: list[Any], branch_events: list[Any]) -> list[dict[str, Any]]:
    outgoing = {
        str(event.get("from_node"))
        for event in branch_events
        if isinstance(event, dict) and event.get("from_node")
    }
    frontiers: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict) or node.get("lifecycle") not in {"closed", "stopped"}:
            continue
        node_id = str(node.get("node_id") or "")
        if not node_id:
            continue
        frontiers.append(
            {
                "node_id": node_id,
                "lifecycle": node.get("lifecycle"),
                "node_type": node.get("node_type"),
                "scope": node.get("validation_scope") or node.get("audit_scope") or node.get("candidate_kind") or node.get("mechanism_action"),
                "hypothesis_status": node.get("hypothesis_status"),
                "program_outcome": node.get("program_outcome"),
                "audit_status": node.get("audit_status"),
                "has_outgoing_branch": node_id in outgoing,
            }
        )
    return frontiers


def _build_readiness(
    validation: dict[str, Any],
    manifest: dict[str, Any],
    hypothesis_context: dict[str, Any],
) -> dict[str, Any]:
    required_next = [str(item) for item in hypothesis_context.get("required_next_evidence", []) if item]
    pathway_audits = hypothesis_context.get("pathway_audits", [])
    accepted_pathway_audit = any(
        isinstance(item, dict) and str(item.get("audit_outcome") or "").lower() == "accepted"
        for item in pathway_audits
    )
    accepted_ts_ready = bool(manifest.get("accepted_ts_refs"))
    strict_ready = accepted_ts_ready and accepted_pathway_audit
    return {
        "structural_valid": bool(validation.get("valid")),
        "highest_validated_layer": _highest_validated_layer(hypothesis_context, accepted_ts_ready, accepted_pathway_audit),
        "strict_r_to_p_ready": strict_ready,
        "blocking_evidence": [] if strict_ready else required_next,
        "warnings": [
            item for item in validation.get("findings", [])
            if isinstance(item, dict) and item.get("severity") == "warning"
        ],
    }


def _highest_validated_layer(
    hypothesis_context: dict[str, Any],
    accepted_ts_ready: bool,
    accepted_pathway_audit: bool,
) -> str:
    if accepted_pathway_audit:
        return "pathway"
    if accepted_ts_ready:
        return "accepted_ts"
    if not hypothesis_context.get("active_hypothesis"):
        return "endpoint"
    required_next = set(str(item) for item in hypothesis_context.get("required_next_evidence", []) if item)
    if "connectivity_gate" not in required_next:
        return "connectivity"
    if "tsfreq_gate" not in required_next:
        return "tsfreq"
    if "candidate_geometry" not in required_next:
        return "candidate"
    return "hypothesis"


def _build_hypothesis_context(mechanism: dict[str, Any], evidence: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    focus_id = mechanism.get("focus_hypothesis_id")
    hypotheses = [item for item in mechanism.get("hypotheses", []) if isinstance(item, dict)]
    active = next((item for item in hypotheses if item.get("hypothesis_id") == focus_id), None)
    prediction_status = active.get("prediction_status", []) if isinstance(active, dict) else []
    pathway_audits = _pathway_audit_summaries(mechanism.get("audit_records", []), evidence)
    claim_prediction_status = _claim_prediction_rows(prediction_status)
    supported = _prediction_ids_by_verdict(claim_prediction_status, "supported")
    refuted = _prediction_ids_by_verdict(claim_prediction_status, "refuted")
    all_predictions = active.get("testable_predictions", []) if isinstance(active, dict) else []
    known_prediction_ids = (
        supported
        | refuted
        | _prediction_ids_by_verdict(claim_prediction_status, "inconclusive")
        | _audited_prediction_ids(pathway_audits)
    )
    open_predictions = [
        item for item in all_predictions
        if isinstance(item, dict) and item.get("prediction_id") not in known_prediction_ids
    ]
    evidence_roles = {
        item.get("role")
        for item in evidence.get("evidence", [])
        if isinstance(item, dict) and _evidence_satisfies_active_hypothesis(item, active, focus_id)
    }
    evidence_roles.update(_satisfied_audit_roles(prediction_status, manifest))
    evidence_roles.update(_satisfied_pathway_audit_roles(pathway_audits))
    required_next = [
        role for role in (active.get("required_evidence", []) if isinstance(active, dict) else [])
        if role not in evidence_roles
    ]
    return {
        "focus_hypothesis_id": focus_id,
        "active_hypothesis": active or {},
        "open_predictions": open_predictions,
        "supported_predictions": sorted(supported),
        "refuted_predictions": sorted(refuted),
        "required_next_evidence": required_next,
        "pathway_audits": pathway_audits,
    }


def _claim_prediction_rows(rows: list[Any]) -> list[dict[str, Any]]:
    """Rows whose verdict directly evaluates the referenced prediction."""
    return [row for row in rows if isinstance(row, dict)]


def _satisfied_audit_roles(rows: list[Any], manifest: dict[str, Any]) -> set[str]:
    roles: set[str] = set()
    if manifest.get("accepted_ts_refs"):
        roles.add("accepted_audit")

    return roles


def _satisfied_pathway_audit_roles(pathway_audits: list[dict[str, Any]]) -> set[str]:
    for audit in pathway_audits:
        if audit.get("audit_outcome"):
            return {"pathway_audit_summary"}
    return set()


def _audited_prediction_ids(pathway_audits: list[dict[str, Any]]) -> set[str]:
    audited: set[str] = set()
    for audit in pathway_audits:
        if not audit.get("audit_outcome"):
            continue
        audited.update(str(item) for item in audit.get("prediction_ids", []) if item)
    return audited


def _pathway_audit_summaries(rows: list[Any], evidence: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_records = evidence.get("evidence", []) if isinstance(evidence, dict) else []
    summaries: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("audit_scope") != "pathway":
            continue
        outcome = _pathway_audit_outcome(row, evidence_records)
        hypothesis_ref = row.get("hypothesis_ref") if isinstance(row.get("hypothesis_ref"), dict) else {}
        item = {
            "node_id": row.get("node_id"),
            "audit_status": row.get("status"),
            "prediction_ids": [str(item) for item in hypothesis_ref.get("prediction_ids", []) if item],
            "evidence_refs": [str(item) for item in row.get("evidence_refs", []) if item],
            "audit_outcome": outcome,
        }
        if outcome in {"pathway_not_accepted", "not_accepted"}:
            item["branch_state"] = "current_branch_not_accepted"
        summaries.append(item)
    return summaries


def _pathway_audit_outcome(row: dict[str, Any], evidence_records: list[Any]) -> str | None:
    status = row.get("status")
    if status == "accepted":
        return "accepted"
    if status == "not_accepted":
        return "pathway_not_accepted"
    lifecycle_view = evidence_lifecycle_view(evidence_records)
    evidence_refs = set(
        lifecycle_view.resolve_refs([str(item) for item in row.get("evidence_refs", []) if item])
    )
    for record in lifecycle_view.active_records:
        if not isinstance(record, dict) or str(record.get("evidence_id")) not in evidence_refs:
            continue
        quality = record.get("quality") if isinstance(record.get("quality"), dict) else {}
        facts = record.get("facts") if isinstance(record.get("facts"), dict) else {}
        decision = str(quality.get("strict_pathway_decision") or quality.get("audit_outcome") or "").lower()
        if not decision:
            decision = str(facts.get("strict_pathway_decision") or facts.get("audit_outcome") or facts.get("verdict") or "").lower()
        if decision == "not_accepted":
            return "pathway_not_accepted"
        if decision:
            return decision
        if quality.get("strict_pathway_supported") is False or facts.get("whole_R_to_P_pathway_accepted") is False:
            return "pathway_not_accepted"
    return None


def _prediction_ids_by_verdict(rows: list[Any], verdict: str) -> set[str]:
    out: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or _prediction_row_verdict(row) != verdict:
            continue
        out.update(str(item) for item in row.get("prediction_ids", []) if item)
    return out


def _prediction_row_verdict(row: dict[str, Any]) -> str | None:
    return {
        "supported": "supported",
        "unsupported": "refuted",
        "ambiguous": "inconclusive",
    }.get(row.get("hypothesis_status"))


def _evidence_satisfies_active_hypothesis(record: dict[str, Any], active: dict[str, Any] | None, hypothesis_id: Any) -> bool:
    if _evidence_matches_hypothesis(record, hypothesis_id):
        return True
    if not isinstance(active, dict):
        return False
    evidence_id = record.get("evidence_id")
    if evidence_id and evidence_id in set(str(item) for item in active.get("evidence_refs", []) if item):
        return True
    source_node = active.get("source_node")
    if source_node and record.get("node_id") == source_node and record.get("role") in set(active.get("required_evidence", [])):
        return True
    return False


def _evidence_matches_hypothesis(record: dict[str, Any], hypothesis_id: Any) -> bool:
    quality = record.get("quality") if isinstance(record.get("quality"), dict) else {}
    return bool(hypothesis_id and quality.get("hypothesis_id") == hypothesis_id)
