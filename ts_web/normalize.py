"""Read-only workspace normalization for the web explorer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ts_workspace.io import read_json
from ts_workspace.validators.workspace import validate_workspace


def normalize_workspace(source_root: str | Path, *, label: str | None = None) -> dict[str, Any]:
    root = Path(source_root).resolve()
    validation = validate_workspace(root)
    tree = _read_json(root / "tree.json")
    manifest = _read_json(root / "manifest.json")
    evidence_registry = _read_json(root / "evidence_registry.json")
    pathway_model = _read_json(root / "pathway_model.json")
    mechanism_model = _read_json(root / "mechanism_model.json")

    evidence_records = _list(evidence_registry.get("evidence"))
    nodes = [_normalize_node(root, row, evidence_records) for row in _list(tree.get("nodes"))]
    branch_events = _list(tree.get("branch_events"))
    decision_events = _normalize_decision_events(root / "decision_log.jsonl")
    return {
        "label": label or root.name,
        "source_root": str(root),
        "valid": validation["valid"],
        "validation_findings": validation["findings"],
        "focus": {
            "current_node": tree.get("current_node"),
            "focus_pathway_id": pathway_model.get("focus_pathway_id"),
            "focus_hypothesis_id": mechanism_model.get("focus_hypothesis_id"),
            "accepted_ts_refs": manifest.get("accepted_ts_refs", []),
        },
        "nodes": nodes,
        "edges": _list(tree.get("edges")),
        "branch_edges": [_normalize_branch_event(event) for event in branch_events],
        "decision_events": decision_events,
        "pathways": _list(pathway_model.get("pathways")),
        "evidence": evidence_records,
        "mechanism": {
            "focus_hypothesis_id": mechanism_model.get("focus_hypothesis_id"),
            "hypotheses": _list(mechanism_model.get("hypotheses")),
            "accepted_facts": _list(mechanism_model.get("accepted_facts")),
            "refuted_hypotheses": _list(mechanism_model.get("refuted_hypotheses")),
            "open_questions": _list(mechanism_model.get("open_questions")),
        },
    }


def explorer_job_payload(
    source_root: str | Path,
    *,
    label: str | None = None,
    workspace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the full read-only payload consumed by the explorer UI."""

    root = Path(source_root).resolve()
    manifest = _read_json(root / "manifest.json")
    mechanism_model = _read_json(root / "mechanism_model.json")
    pathway_model = _read_json(root / "pathway_model.json")
    view = normalize_workspace(root, label=label)
    graph = explorer_graph_payload_from_view(view)
    return {
        "app": "TS Hypothesis Explorer",
        "source": str(root),
        "manifest": manifest,
        "mechanism": _explorer_mechanism(mechanism_model, view=view),
        "evidence_summary": graph["evidence_summary"],
        "graph": graph,
        "workspace": explorer_workspace_summary(
            workspace or {}, view=view, manifest=manifest, pathway_model=pathway_model
        ),
        "read_only": True,
    }


def explorer_workspace_summary(
    row: dict[str, Any],
    *,
    view: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    pathway_model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one workspace row in the shape used by the explorer UI."""

    source_root = row.get("source_root") or row.get("source") or ""
    label = row.get("label") or row.get("name") or (Path(source_root).name if source_root else "")
    workspace_id = row.get("workspace_id") or row.get("id") or ""
    if view is None and source_root:
        try:
            view = normalize_workspace(source_root, label=label)
        except Exception:  # noqa: BLE001
            view = None
    if manifest is None:
        manifest = _read_json(Path(source_root) / "manifest.json") if source_root else {}
    if pathway_model is None:
        pathway_model = _read_json(Path(source_root) / "pathway_model.json") if source_root else {}
    accepted_refs = _list(manifest.get("accepted_ts_refs"))
    focus = view.get("focus", {}) if isinstance(view, dict) else {}
    summary = {
        **row,
        "id": workspace_id,
        "workspace_id": workspace_id,
        "name": label or workspace_id,
        "label": label or workspace_id,
        "source": source_root,
        "source_root": source_root,
        "system": manifest.get("system") or manifest.get("system_slug") or Path(source_root).name,
        "claim_state": _claim_state(accepted_refs, pathway_model, view=view),
    }
    _put_if_present(summary, "charge", manifest.get("charge"))
    _put_if_present(summary, "multiplicity", manifest.get("multiplicity"))
    _put_if_present(summary, "accepted_ts", ", ".join(str(item) for item in accepted_refs))
    _put_if_present(summary, "focus_node", focus.get("current_node"))
    return summary


def _claim_state(accepted_refs: list[Any], pathway_model: dict[str, Any], *, view: dict[str, Any] | None = None) -> str:
    """Authoritative workspace claim state. UI must NOT re-derive."""

    focus_id = pathway_model.get("focus_pathway_id") if isinstance(pathway_model, dict) else None
    pathways = _list(pathway_model.get("pathways") if isinstance(pathway_model, dict) else None)
    focus = next(
        (p for p in pathways if isinstance(p, dict) and p.get("pathway_id") == focus_id),
        None,
    )
    statuses = {p.get("status") for p in pathways if isinstance(p, dict)}
    focus_status = focus.get("status") if isinstance(focus, dict) else None
    audit_outcome = _latest_pathway_audit_outcome(view)
    if audit_outcome in {"accepted", "pathway_accepted"}:
        return "pathway_complete"
    if audit_outcome == "pathway_not_accepted":
        return "pathway_not_accepted"
    if focus_status in {"accepted", "complete"}:
        return "pathway_complete"
    if focus_status == "supported":
        if _is_complete_pathway(focus):
            return "pathway_complete"
        if accepted_refs:
            return "accepted_ts"
        return "pathway_partial"
    if focus_status in {"active", "proposed"}:
        return "pathway_hypothesis"
    if focus_status in {"refuted", "superseded"}:
        # If only refuted/superseded exist, treat as rejected; else still searching.
        if statuses and statuses.issubset({"refuted", "superseded"}):
            return "pathway_rejected"
    if accepted_refs:
        return "accepted_ts"
    if _view_needs_followup(view):
        return "needs_followup"
    return "searching"


def _is_complete_pathway(pathway: Any) -> bool:
    if not isinstance(pathway, dict):
        return False
    steps = [step for step in _list(pathway.get("steps")) if isinstance(step, dict)]
    if not steps:
        return False
    supported = [step for step in steps if step.get("status") in {"supported", "accepted", "complete"}]
    if len(supported) != len(steps):
        return False
    if len(steps) > 1:
        return True
    step_id = str(steps[0].get("step_id") or "")
    return "pathway" in step_id


def explorer_graph_payload(source_root: str | Path, *, label: str | None = None) -> dict[str, Any]:
    """Return only the explorer graph payload for a workspace."""

    return explorer_graph_payload_from_view(normalize_workspace(source_root, label=label))


def explorer_graph_payload_from_view(view: dict[str, Any]) -> dict[str, Any]:
    """Transform the canonical normalized view into the explorer graph shape."""

    nodes = [_explorer_node(row, _list(view.get("branch_edges"))) for row in _list(view.get("nodes"))]
    edges = _explorer_edges(nodes, _list(view.get("edges")), _list(view.get("branch_edges")))
    evidence = _explorer_evidence(_list(view.get("evidence")))
    events = _explorer_events(_list(view.get("branch_edges")), _list(view.get("decision_events")))
    return {
        "schema": "ts-explorer-graph",
        "nodes": nodes,
        "edges": edges,
        "events": events,
        "frontier_nodes": [node["id"] for node in nodes if node.get("frontier")],
        "accepted_nodes": list(view.get("focus", {}).get("accepted_ts_refs", [])),
        "accepted_ts": ", ".join(str(item) for item in view.get("focus", {}).get("accepted_ts_refs", [])),
        "pathway": {"focus_pathway_id": view.get("focus", {}).get("focus_pathway_id")},
        "validation": {
            "valid": bool(view.get("valid")),
            "findings": _list(view.get("validation_findings")),
        },
        "evidence_summary": evidence["summary"],
        "evidence": {"records": evidence["records"]},
        "presentation": _explorer_presentation(),
    }


def explorer_node_payload(source_root: str | Path, node_id: str, *, label: str | None = None) -> dict[str, Any]:
    """Return read-only node detail for the explorer UI."""

    root = Path(source_root).resolve()
    view = normalize_workspace(root, label=label)
    graph = explorer_graph_payload_from_view(view)
    node = next((item for item in graph["nodes"] if item.get("id") == node_id), None)
    if node is None:
        raise ValueError(f"unknown node id: {node_id}")
    detail = _read_json(root / "nodes" / node_id / "node.json")
    merged = {**detail, **node, "node_id": node_id}
    evidence_records = [
        record
        for record in graph["evidence"]["records"]
        if isinstance(record, dict) and record.get("node_id") == node_id
    ]
    node_dir = root / "nodes" / node_id
    markdown = {
        "hypothesis": _read_text(node_dir / "hypothesis.md") or str(merged.get("hypothesis") or ""),
        "decision_card": _read_text(node_dir / "decision_card.md") or _read_text(node_dir / "decision.md"),
        "reflection": _read_text(node_dir / "reflection.md") or _render_closure_reflection(merged),
        "report": _read_text(node_dir / "report.md"),
    }
    return {
        "node_id": node_id,
        "node": merged,
        "rationale_lint": {},
        "markdown": markdown,
        "evidence": evidence_records,
        "files": list_node_files(source_root, node_id),
        "file_notes": [],
    }


def list_node_files(source_root: str | Path, node_id: str) -> dict[str, Any]:
    """List files below one node directory without modifying the workspace."""

    root = Path(source_root).resolve()
    node_dir = root / "nodes" / node_id
    if not node_dir.exists():
        return {"node_id": node_id, "files": []}
    files: list[dict[str, Any]] = []
    for path in sorted(node_dir.rglob("*")):
        if not path.is_file():
            continue
        stat = path.stat()
        files.append(
            {
                "path": path.resolve().relative_to(root).as_posix(),
                "name": path.name,
                "size": stat.st_size,
                "modified": int(stat.st_mtime),
            }
        )
    return {"node_id": node_id, "files": files}


def _normalize_node(root: Path, row: dict[str, Any], evidence_records: list[Any]) -> dict[str, Any]:
    node_id = row.get("node_id")
    detail = _read_json(root / "nodes" / str(node_id) / "node.json") if node_id else {}
    lifecycle = detail.get("lifecycle") or row.get("lifecycle")
    closure = detail.get("closure") or {}
    # closure is the authoritative source per SKILL.md; tree row is only a fallback
    # when node.json is missing or hasn't been closed yet.
    claim_verdict = closure.get("claim_verdict") or row.get("claim_verdict")
    program_status = closure.get("program_status") or row.get("program_status")
    phase = detail.get("phase", row.get("phase"))
    audit_display = _pathway_audit_display(str(node_id), phase, closure, evidence_records)
    return {
        "node_id": node_id,
        "parent_node": detail.get("parent_node", row.get("parent_node")),
        "phase": phase,
        "lifecycle": lifecycle,
        "hypothesis": detail.get("hypothesis", row.get("hypothesis")),
        "pathway_ref": detail.get("pathway_ref"),
        "evidence_refs": detail.get("evidence_refs", []),
        "closure": closure or None,
        "display": {
            "label": audit_display.get("label") or _display_label(lifecycle, claim_verdict),
            "tone": audit_display.get("tone") or _display_tone(lifecycle, claim_verdict, program_status),
            "state": audit_display.get("state"),
            "audit_outcome": audit_display.get("audit_outcome"),
            "program_status": program_status,
            "claim_verdict": claim_verdict,
        },
    }


def _explorer_node(row: dict[str, Any], branch_events: list[Any]) -> dict[str, Any]:
    node_id = str(row.get("node_id") or "")
    lifecycle = row.get("lifecycle")
    display = row.get("display") if isinstance(row.get("display"), dict) else {}
    closure = row.get("closure") if isinstance(row.get("closure"), dict) else {}
    program = closure.get("program") if isinstance(closure.get("program"), dict) else {}
    program_status = display.get("program_status") or closure.get("program_status")
    claim_verdict = display.get("claim_verdict") or closure.get("claim_verdict")
    tone = display.get("tone") or _display_tone(lifecycle, claim_verdict, program_status)
    state_key = display.get("state") or _node_state_key(lifecycle, claim_verdict, program_status)
    branch_from_ids: list[str] = []
    branch_anchor_ids: list[str] = []
    generated_ids: list[str] = []
    for event in branch_events:
        if not isinstance(event, dict) or not event.get("event_id"):
            continue
        event_id = str(event["event_id"])
        if event.get("from_node") == node_id:
            branch_from_ids.append(event_id)
        if event.get("anchor_node") == node_id and event.get("anchor_node") != event.get("new_node"):
            branch_anchor_ids.append(event_id)
        if event.get("new_node") == node_id:
            generated_ids.append(event_id)
    branch_ids = _dedupe(branch_from_ids + branch_anchor_ids + generated_ids)
    state_line = _closure_line(closure, program_status, claim_verdict)
    return {
        "id": node_id,
        "node_id": node_id,
        "parent_id": row.get("parent_node"),
        "stage": row.get("phase"),
        "stage_label": _phase_label(row.get("phase")),
        "card_phase": row.get("phase"),
        "card_label": display.get("label") or state_key,
        "card_line": display.get("label") or state_key,
        "card_color": _tone_color(tone),
        "color": _tone_color(tone),
        "node_state": state_key,
        "state_label": display.get("label") or state_key,
        "state_line": state_line,
        "hypothesis": row.get("hypothesis"),
        "pathway_ref": row.get("pathway_ref"),
        "lifecycle": lifecycle,
        "program_status": program_status,
        "claim_verdict": claim_verdict,
        "reason_code": closure.get("reason_code") or program.get("reason_code"),
        "closure": closure or None,
        "evidence_count": len(_list(row.get("evidence_refs"))),
        "evidence_refs": _list(row.get("evidence_refs")),
        "input_refs": _list(row.get("evidence_refs")),
        "active": lifecycle == "running",
        "frontier": lifecycle == "running",
        "branch_event_ids": branch_ids,
        "branch_from_event_ids": _dedupe(branch_from_ids),
        "branch_anchor_event_ids": _dedupe(branch_anchor_ids),
        "generated_from_branch_event_ids": _dedupe(generated_ids),
        "branch_badge": _branch_badge(branch_from_ids, branch_anchor_ids, generated_ids),
    }


def _explorer_edges(nodes: list[dict[str, Any]], tree_edges: list[Any], branch_events: list[Any]) -> list[dict[str, Any]]:
    node_ids = {node.get("id") for node in nodes}
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(source: Any, target: Any, kind: str, **extra: Any) -> None:
        if not source or not target or source not in node_ids or target not in node_ids:
            return
        key = (str(source), str(target), kind)
        if key in seen:
            return
        seen.add(key)
        edges.append({"source": source, "target": target, "kind": kind, **_edge_display(kind), **extra})

    for node in nodes:
        add(node.get("parent_id"), node.get("id"), "branch")
    for edge in tree_edges:
        if not isinstance(edge, dict):
            continue
        add(edge.get("source") or edge.get("parent"), edge.get("target") or edge.get("child"), edge.get("kind") or "branch")
    for event in branch_events:
        if not isinstance(event, dict):
            continue
        extra = {
            "event_id": event.get("event_id"),
            "event_state": event.get("event_state"),
            "reason": event.get("reason_code"),
        }
        if event.get("from_node") != event.get("anchor_node") and event.get("anchor_node") != event.get("new_node"):
            add(event.get("from_node"), event.get("anchor_node"), "branch_anchor", **extra)
        add(event.get("from_node"), event.get("new_node"), "branch_generated", **extra)
    return edges


def _explorer_events(branch_events: list[Any], decision_events: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(event: dict[str, Any]) -> None:
        event_id = event.get("event_id")
        node_id = event.get("node_id")
        role = event.get("event_role") or event.get("event_type") or "event"
        if not event_id or not node_id:
            return
        key = (str(event_id), str(node_id), str(role))
        if key in seen:
            return
        seen.add(key)
        out.append(event)

    for event in branch_events:
        if not isinstance(event, dict):
            continue
        event_id = event.get("event_id")
        role_nodes = [
            ("branch_source", event.get("from_node")),
            ("generated_from_branch", event.get("new_node")),
        ]
        if event.get("anchor_node") != event.get("new_node"):
            role_nodes.insert(1, ("branch_anchor", event.get("anchor_node")))
        for role, node_id in role_nodes:
            display = _event_role_display(role)
            add(
                {
                    "event_id": event_id,
                    "node_id": node_id,
                    "event_type": "branch",
                    "event_role": role,
                    "event_label": display["label"],
                    "event_color": display["color"],
                    "decision": event.get("reason_code") or "branch",
                    "reason": event.get("rationale") or event.get("changed_variable"),
                    "evidence_refs": _list(event.get("evidence_refs")),
                }
            )
    for event in decision_events:
        if isinstance(event, dict):
            add(event)
    return out


def _explorer_evidence(records: list[Any]) -> dict[str, Any]:
    # Single source of truth for evidence vocabulary: the presentation table.
    # Anything not in the table falls back to "grey" so unknown states still render.
    vocab = _explorer_presentation()["evidence_state"]
    normalized: list[dict[str, Any]] = []
    by_kind: dict[str, int] = {}
    by_state: dict[str, int] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        kind = str(record.get("kind") or "unknown")
        state = str(record.get("evidence_tier") or record.get("role") or "recorded")
        entry = vocab.get(state) or {}
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_state[state] = by_state.get(state, 0) + 1
        normalized.append(
            {
                **record,
                "evidence_state": state,
                "evidence_label": entry.get("label") or state.replace("_", " "),
                "evidence_color": entry.get("color") or "grey",
                "claim": record.get("summary") or record.get("claim") or "",
                "source": record.get("path") or record.get("source") or "",
            }
        )
    return {"records": normalized, "summary": {"count": len(normalized), "by_kind": by_kind, "by_state": by_state}}


def _explorer_mechanism(mechanism_model: dict[str, Any], *, view: dict[str, Any] | None = None) -> dict[str, Any]:
    accepted_facts = _list(mechanism_model.get("accepted_facts"))
    refuted_hypotheses = _list(mechanism_model.get("refuted_hypotheses"))
    open_questions = _list(mechanism_model.get("open_questions"))
    hypotheses = _list(mechanism_model.get("hypotheses"))
    hypothesis_predictions = _hypothesis_prediction_records(hypotheses)
    latest_records = _latest_mechanism_records(
        {
            "accepted_facts": accepted_facts,
            "refuted_hypotheses": refuted_hypotheses,
            "open_questions": open_questions,
            "hypothesis_predictions": hypothesis_predictions,
            "hypotheses": hypotheses,
        },
        view=view,
    )
    return {
        **mechanism_model,
        "validated_facts": _mechanism_lines(accepted_facts),
        "refuted_hypotheses": _mechanism_lines(refuted_hypotheses),
        "open_questions": _mechanism_lines(open_questions),
        "latest_analysis": _latest_mechanism_analysis_lines(latest_records, view=view),
    }


def _hypothesis_prediction_records(hypotheses: list[Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for hypothesis in hypotheses:
        if not isinstance(hypothesis, dict):
            continue
        for row in _list(hypothesis.get("prediction_status")):
            if not isinstance(row, dict):
                continue
            records.append(
                {
                    **row,
                    "hypothesis_id": hypothesis.get("hypothesis_id"),
                    "hypothesis": hypothesis.get("summary"),
                    "mechanism_summary": f"Prediction status for {hypothesis.get('hypothesis_id')}.",
                }
            )
    return records


def _latest_mechanism_records(
    groups: dict[str, list[Any]],
    *,
    view: dict[str, Any] | None = None,
) -> list[Any]:
    records: list[Any] = []
    for key in ("accepted_facts", "refuted_hypotheses", "open_questions", "hypothesis_predictions", "hypotheses"):
        records.extend(groups.get(key, []))
    if not records:
        return []

    node_order = _node_order(view)
    if node_order:
        by_order = [
            (node_order[record.get("node_id")], record)
            for record in records
            if isinstance(record, dict) and record.get("node_id") in node_order
        ]
        if by_order:
            latest_order = max(order for order, _record in by_order)
            return [record for order, record in by_order if order == latest_order]
    return [records[-1]]


def _node_order(view: dict[str, Any] | None) -> dict[str, int]:
    if not isinstance(view, dict):
        return {}
    order: dict[str, int] = {}
    for index, node in enumerate(_list(view.get("nodes"))):
        if isinstance(node, dict) and node.get("node_id"):
            order[str(node["node_id"])] = index
    return order


def _mechanism_lines(records: list[Any]) -> list[str]:
    lines: list[str] = []
    for record in records:
        if isinstance(record, str):
            lines.append(record)
            continue
        if not isinstance(record, dict):
            lines.append(str(record))
            continue
        summary = (
            record.get("summary")
            or record.get("mechanism_summary")
            or record.get("hypothesis")
            or record.get("claim")
            or ""
        )
        prefix = " / ".join(
            str(item)
            for item in (record.get("node_id"), record.get("phase"), record.get("claim_verdict"))
            if item
        )
        lines.append(f"{prefix}: {summary}" if prefix and summary else prefix or str(record))
    return lines


def _latest_mechanism_analysis_lines(records: list[Any], *, view: dict[str, Any] | None = None) -> list[str]:
    lines = _mechanism_lines(records)
    if not isinstance(view, dict):
        return lines
    node_ids = {
        str(record.get("node_id"))
        for record in records
        if isinstance(record, dict) and record.get("node_id")
    }
    evidence_refs = _evidence_refs_for_records(records)
    for node in _list(view.get("nodes")):
        if not isinstance(node, dict) or str(node.get("node_id")) not in node_ids:
            continue
        lines.extend(_closure_fact_lines(node))
        evidence_refs.extend(_evidence_refs_for_closure(node.get("closure")))
    lines.extend(_evidence_analysis_lines(view, evidence_refs))
    return _dedupe_strings(lines)


def _closure_fact_lines(node: dict[str, Any]) -> list[str]:
    closure = node.get("closure") if isinstance(node.get("closure"), dict) else {}
    if not closure:
        return []
    node_id = node.get("node_id")
    out: list[str] = []
    mechanism = closure.get("mechanism") if isinstance(closure.get("mechanism"), dict) else {}
    program = closure.get("program") if isinstance(closure.get("program"), dict) else {}
    for fact in _list(mechanism.get("facts")):
        out.append(f"{node_id} / mechanism fact: {fact}")
    for fact in _list(program.get("facts")):
        out.append(f"{node_id} / program fact: {fact}")
    return out


def _evidence_refs_for_records(records: list[Any]) -> list[str]:
    refs: list[str] = []
    for record in records:
        if isinstance(record, dict):
            refs.extend(str(ref) for ref in _list(record.get("evidence_refs")) if ref)
    return refs


def _evidence_refs_for_closure(closure: Any) -> list[str]:
    if not isinstance(closure, dict):
        return []
    refs: list[str] = []
    for key in ("program", "mechanism"):
        section = closure.get(key)
        if isinstance(section, dict):
            refs.extend(str(ref) for ref in _list(section.get("evidence_refs")) if ref)
    return refs


def _evidence_analysis_lines(view: dict[str, Any], evidence_refs: list[str]) -> list[str]:
    wanted = set(evidence_refs)
    if not wanted:
        return []
    records = [
        record
        for record in _list(view.get("evidence"))
        if isinstance(record, dict) and record.get("evidence_id") in wanted
    ]
    by_id = {str(record.get("evidence_id")): record for record in records}
    lines: list[str] = []
    for evidence_id in _dedupe([str(ref) for ref in evidence_refs if ref]):
        record = by_id.get(evidence_id)
        if not record:
            continue
        role = record.get("role") or record.get("kind") or "evidence"
        summary = record.get("summary") or ""
        quality = _quality_summary(record.get("quality"))
        line = f"evidence {evidence_id} / {role}: {summary}"
        if quality:
            line = f"{line} | {quality}"
        lines.append(line)
    return lines


def _quality_summary(quality: Any) -> str:
    if not isinstance(quality, dict):
        return ""
    preferred = [
        "imaginary_frequencies_cm-1",
        "imaginary_frequency_count",
        "mode_verdict",
        "final_reaction_center_distances_A",
        "forward_assignment",
        "reverse_assignment",
        "forward_irc_end_assignment",
        "reverse_irc_end_assignment",
        "forward_same_level_key_distance_error_to_reactant_A_sum",
        "reverse_same_level_key_distance_error_to_product_A_sum",
        "forward_key_distance_error_to_product_A_sum",
        "reverse_key_distance_error_to_reactant_A_sum",
        "strict_pathway_decision",
    ]
    parts: list[str] = []
    for key in preferred:
        if key in quality:
            parts.append(f"{key}={_compact_quality_value(quality[key])}")
    return "; ".join(parts[:6])


def _compact_quality_value(value: Any) -> str:
    if isinstance(value, dict):
        items = list(value.items())[:4]
        return "{" + ", ".join(f"{key}:{val}" for key, val in items) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(str(item) for item in value[:4]) + "]"
    return str(value)


def _explorer_presentation() -> dict[str, Any]:
    return {
        "card_status": {
            "success": {"label": "supported", "color": "green"},
            "error": {"label": "refuted", "color": "red"},
            "running": {"label": "running", "color": "accent"},
            "ready": {"label": "inconclusive", "color": "amber"},
            "stopped": {"label": "stopped", "color": "grey"},
            "unknown": {"label": "unknown", "color": "grey"},
        },
        "workspace_state": {
            "searching": {"label": "searching", "color": "accent"},
            "needs_followup": {"label": "needs follow-up", "color": "amber"},
            "accepted_ts": {"label": "accepted TS", "color": "green"},
            "pathway_complete": {"label": "pathway complete", "color": "green"},
            "pathway_partial": {"label": "pathway partial", "color": "amber"},
            "pathway_hypothesis": {"label": "pathway hypothesis", "color": "purple"},
            "pathway_not_accepted": {"label": "pathway not accepted", "color": "amber"},
            "pathway_rejected": {"label": "pathway rejected", "color": "red"},
        },
        "node_state": {
            "running": {"label": "running", "color": "accent"},
            "supported": {"label": "supported", "color": "green"},
            "refuted": {"label": "refuted", "color": "red"},
            "inconclusive": {"label": "inconclusive", "color": "amber"},
            "not_evaluated": {"label": "not evaluated", "color": "grey"},
            "pathway_not_accepted": {"label": "pathway not accepted", "color": "amber"},
            "failed": {"label": "failed", "color": "red"},
            "stopped": {"label": "stopped", "color": "grey"},
            "unknown": {"label": "unknown", "color": "grey"},
        },
        "evidence_state": {
            "local_parse": {"label": "local parse", "color": "green"},
            "recorded": {"label": "recorded", "color": "grey"},
            "tsfreq_gate": {"label": "TS/Freq gate", "color": "cyan"},
            "connectivity_gate": {"label": "connectivity gate", "color": "purple"},
        },
        "edge_kind": {
            "branch": {"label": "branch", "color": "accent"},
            "dependency": {"label": "dependency", "color": "cyan"},
            "branch_anchor": {"label": "branch anchor", "color": "purple"},
            "branch_generated": {"label": "generated branch", "color": "blue"},
        },
        "event_role": {
            "branch_source": {"label": "branched from", "color": "purple"},
            "branch_anchor": {"label": "branch anchor", "color": "purple"},
            "generated_from_branch": {"label": "generated by branch", "color": "blue"},
            "branch": {"label": "branch", "color": "purple"},
            "start_node": {"label": "node started", "color": "accent"},
            "end_node": {"label": "node closed", "color": "green"},
            "update_workspace": {"label": "workspace updated", "color": "cyan"},
        },
    }


def _edge_display(kind: str) -> dict[str, str]:
    entry = _explorer_presentation()["edge_kind"].get(kind, {})
    return {
        "edge_label": str(entry.get("label") or kind.replace("_", " ")),
        "edge_color": str(entry.get("color") or "grey"),
    }


def _event_role_display(role: str) -> dict[str, str]:
    entry = _explorer_presentation()["event_role"].get(role, {})
    return {
        "label": str(entry.get("label") or role.replace("_", " ")),
        "color": str(entry.get("color") or "grey"),
    }


def _branch_badge(source_ids: list[str], anchor_ids: list[str], generated_ids: list[str]) -> dict[str, Any] | None:
    if source_ids:
        display = _event_role_display("branch_source")
        return {"role": "branch_source", "label": display["label"], "color": display["color"], "event_ids": _dedupe(source_ids)}
    if generated_ids:
        display = _event_role_display("generated_from_branch")
        return {
            "role": "generated_from_branch",
            "label": display["label"],
            "color": display["color"],
            "event_ids": _dedupe(generated_ids),
        }
    if anchor_ids:
        display = _event_role_display("branch_anchor")
        return {"role": "branch_anchor", "label": display["label"], "color": display["color"], "event_ids": _dedupe(anchor_ids)}
    return None


def _normalize_branch_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event.get("event_id"),
        "event_state": event.get("event_state"),
        "relation": event.get("relation"),
        "from_node": event.get("from_node"),
        "anchor_node": event.get("anchor_node"),
        "new_node": event.get("new_node"),
        "changed_variable": event.get("changed_variable"),
        "reason_code": event.get("reason_code"),
        "evidence_refs": event.get("evidence_refs", []),
    }


def _normalize_decision_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in _read_jsonl(path):
        decision_id = row.get("decision_id")
        action = row.get("action")
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        node_id = result.get("node_id")
        if not decision_id or not action or not node_id:
            continue
        display = _event_role_display(str(action))
        lifecycle = result.get("lifecycle")
        appended = result.get("appended")
        detail = ""
        if lifecycle:
            detail = f"lifecycle={lifecycle}"
        elif isinstance(appended, dict):
            detail = ", ".join(f"{key}={value}" for key, value in appended.items())
        created = row.get("created_at")
        reason = " / ".join(str(part) for part in (created, detail) if part)
        events.append(
            {
                "event_id": decision_id,
                "node_id": node_id,
                "event_type": "decision",
                "event_role": action,
                "event_label": display["label"],
                "event_color": display["color"],
                "decision": action,
                "reason": reason,
                "evidence_refs": _list(row.get("evidence_refs")),
            }
        )
    return events


def _view_needs_followup(view: dict[str, Any] | None) -> bool:
    if not isinstance(view, dict):
        return False
    findings = _list(view.get("validation_findings"))
    if any(isinstance(item, dict) and item.get("code") == "workspace_needs_followup" for item in findings):
        return True
    nodes = [node for node in _list(view.get("nodes")) if isinstance(node, dict)]
    if not nodes:
        return False
    if view.get("focus", {}).get("current_node"):
        return False
    if any(node.get("lifecycle") == "running" for node in nodes):
        return False
    last = nodes[-1]
    display = last.get("display") if isinstance(last.get("display"), dict) else {}
    return display.get("claim_verdict") in {"refuted", "inconclusive", "not_evaluated"}


def _latest_pathway_audit_outcome(view: dict[str, Any] | None) -> str | None:
    if not isinstance(view, dict):
        return None
    nodes = [node for node in _list(view.get("nodes")) if isinstance(node, dict)]
    for node in reversed(nodes):
        display = node.get("display") if isinstance(node.get("display"), dict) else {}
        outcome = display.get("audit_outcome")
        if outcome:
            return str(outcome)
    return None


def _pathway_audit_display(
    node_id: str,
    phase: Any,
    closure: dict[str, Any],
    evidence_records: list[Any],
) -> dict[str, str]:
    if phase != "pathway_audit" or not closure:
        return {}
    outcome = _pathway_audit_outcome(node_id, closure, evidence_records)
    if outcome == "pathway_not_accepted":
        return {
            "label": "pathway not accepted",
            "tone": "audit_negative",
            "state": "pathway_not_accepted",
            "audit_outcome": outcome,
        }
    if outcome in {"accepted", "pathway_accepted"}:
        return {
            "label": "pathway accepted",
            "tone": "success",
            "state": "supported",
            "audit_outcome": "accepted",
        }
    return {}


def _pathway_audit_outcome(node_id: str, closure: dict[str, Any], evidence_records: list[Any]) -> str | None:
    for record in evidence_records:
        if not isinstance(record, dict) or str(record.get("node_id") or "") != node_id:
            continue
        if _record_says_pathway_not_accepted(record):
            return "pathway_not_accepted"
        decision = _record_pathway_audit_decision(record)
        if decision in {"accepted", "pathway_accepted"}:
            return "accepted"
    text_parts = [
        closure.get("reason_code"),
        closure.get("implication"),
        closure.get("mechanism", {}).get("summary") if isinstance(closure.get("mechanism"), dict) else "",
        closure.get("program", {}).get("summary") if isinstance(closure.get("program"), dict) else "",
    ]
    text = " ".join(str(part or "").lower() for part in text_parts)
    if any(marker in text for marker in ("not_accepted", "not accepted", "missing connectivity", "no accepted ts")):
        return "pathway_not_accepted"
    if any(marker in text for marker in ("pathway_accepted", "pathway accepted", "strict_r_to_p_pathway_accepted")):
        return "accepted"
    return None


def _record_says_pathway_not_accepted(record: dict[str, Any]) -> bool:
    quality = record.get("quality") if isinstance(record.get("quality"), dict) else {}
    diagnostics = " ".join(str(item).lower() for item in _list(record.get("diagnostics")))
    summary = str(record.get("summary") or "").lower()
    decision = _record_pathway_audit_decision(record)
    if quality.get("strict_pathway_supported") is False:
        return True
    if quality.get("accepted_ts_available") is False and "accepted" in summary:
        return True
    if decision in {"not_accepted", "pathway_not_accepted", "not accepted"}:
        return True
    return any(marker in f"{diagnostics} {summary}" for marker in ("no_accepted_ts", "missing connectivity", "not accepted"))


def _record_pathway_audit_decision(record: dict[str, Any]) -> str:
    quality = record.get("quality") if isinstance(record.get("quality"), dict) else {}
    facts = record.get("facts") if isinstance(record.get("facts"), dict) else {}
    return str(
        quality.get("strict_pathway_decision")
        or quality.get("audit_outcome")
        or facts.get("strict_pathway_decision")
        or facts.get("audit_outcome")
        or facts.get("verdict")
        or ""
    ).lower()


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _dedupe_strings(items: list[str]) -> list[str]:
    return _dedupe([item for item in items if item])


def _put_if_present(target: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str) and not value.strip():
        return
    target[key] = value


def _display_label(lifecycle: str | None, claim_verdict: str | None) -> str:
    if lifecycle == "running":
        return "running"
    if lifecycle == "stopped":
        return "stopped"
    return claim_verdict or lifecycle or "unknown"


def _display_tone(lifecycle: str | None, claim_verdict: str | None, program_status: str | None) -> str:
    if lifecycle == "running":
        return "active"
    if program_status in {"failed", "stopped"}:
        return "blocked"
    if claim_verdict == "supported":
        return "supported"
    if claim_verdict == "refuted":
        return "refuted"
    if claim_verdict == "inconclusive":
        return "inconclusive"
    return "neutral"


def _node_state_key(lifecycle: str | None, claim_verdict: str | None, program_status: str | None) -> str:
    if lifecycle == "running":
        return "running"
    if lifecycle == "stopped":
        return "stopped"
    if program_status == "failed":
        return "failed"
    return claim_verdict or lifecycle or "unknown"


def _tone_color(tone: str | None) -> str:
    return {
        "active": "accent",
        "supported": "green",
        "audit_negative": "amber",
        "refuted": "red",
        "blocked": "red",
        "inconclusive": "amber",
        "neutral": "grey",
    }.get(str(tone or ""), "grey")


def _phase_label(phase: Any) -> str:
    return str(phase or "").replace("_", " ").strip().title() if phase else ""


def _closure_line(closure: dict[str, Any], program_status: Any, claim_verdict: Any) -> str:
    for value in (
        closure.get("implication"),
        closure.get("mechanism", {}).get("summary") if isinstance(closure.get("mechanism"), dict) else "",
        closure.get("program", {}).get("summary") if isinstance(closure.get("program"), dict) else "",
    ):
        if value:
            return str(value)
    return " / ".join(str(item) for item in (program_status, claim_verdict) if item)


def _render_closure_reflection(node: dict[str, Any]) -> str:
    closure = node.get("closure") if isinstance(node.get("closure"), dict) else {}
    if not closure:
        return ""
    lines = ["# Closure Reflection", ""]
    status = [
        ("phase", node.get("phase") or node.get("stage")),
        ("lifecycle", node.get("lifecycle")),
        ("program_status", closure.get("program_status")),
        ("claim_verdict", closure.get("claim_verdict")),
        ("closed_at", closure.get("closed_at") or node.get("ended_at")),
        ("reason_code", closure.get("reason_code") or node.get("reason_code")),
    ]
    for key, value in status:
        if value:
            lines.append(f"- {key}: {value}")
    _append_closure_section(lines, "Program", closure.get("program"))
    _append_closure_section(lines, "Mechanism", closure.get("mechanism"))
    if closure.get("implication"):
        lines.extend(["", "## Implication", "", str(closure["implication"])])
    open_questions = _list(closure.get("open_questions"))
    if open_questions:
        lines.extend(["", "## Open Questions", ""])
        lines.extend(f"- {item}" for item in open_questions)
    return "\n".join(lines).strip() + "\n"


def _append_closure_section(lines: list[str], title: str, section: Any) -> None:
    if not isinstance(section, dict):
        return
    summary = section.get("summary")
    facts = _list(section.get("facts"))
    evidence_refs = _list(section.get("evidence_refs"))
    if not summary and not facts and not evidence_refs:
        return
    lines.extend(["", f"## {title}", ""])
    if summary:
        lines.append(str(summary))
    if facts:
        lines.extend(["", "Facts:"])
        lines.extend(f"- {item}" for item in facts)
    if evidence_refs:
        lines.extend(["", "Evidence refs:"])
        lines.extend(f"- {item}" for item in evidence_refs)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = read_json(path)
    return data if isinstance(data, dict) else {}


def _read_text(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
