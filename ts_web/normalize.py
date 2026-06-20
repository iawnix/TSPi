"""Read-only workspace normalization for the web explorer."""

from __future__ import annotations

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

    nodes = [_normalize_node(root, row) for row in _list(tree.get("nodes"))]
    backtrack_events = _list(tree.get("backtrack_events"))
    return {
        "label": label or root.name,
        "source_root": str(root),
        "valid": validation["valid"],
        "validation_findings": validation["findings"],
        "focus": {
            "current_node": tree.get("current_node"),
            "focus_pathway_id": pathway_model.get("focus_pathway_id"),
            "accepted_ts_refs": manifest.get("accepted_ts_refs", []),
        },
        "nodes": nodes,
        "edges": _list(tree.get("edges")),
        "backtrack_edges": [_normalize_backtrack_event(event) for event in backtrack_events],
        "pathways": _list(pathway_model.get("pathways")),
        "evidence": _list(evidence_registry.get("evidence")),
        "mechanism": {
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
        "mechanism": _explorer_mechanism(mechanism_model),
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

    nodes = [_explorer_node(row, _list(view.get("backtrack_edges"))) for row in _list(view.get("nodes"))]
    edges = _explorer_edges(nodes, _list(view.get("edges")), _list(view.get("backtrack_edges")))
    evidence = _explorer_evidence(_list(view.get("evidence")))
    events = _explorer_events(_list(view.get("backtrack_edges")))
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


def _normalize_node(root: Path, row: dict[str, Any]) -> dict[str, Any]:
    node_id = row.get("node_id")
    detail = _read_json(root / "nodes" / str(node_id) / "node.json") if node_id else {}
    lifecycle = detail.get("lifecycle") or row.get("lifecycle")
    closure = detail.get("closure") or {}
    # closure is the authoritative source per SKILL.md; tree row is only a fallback
    # when node.json is missing or hasn't been closed yet.
    claim_verdict = closure.get("claim_verdict") or row.get("claim_verdict")
    program_status = closure.get("program_status") or row.get("program_status")
    return {
        "node_id": node_id,
        "parent_node": detail.get("parent_node", row.get("parent_node")),
        "phase": detail.get("phase", row.get("phase")),
        "lifecycle": lifecycle,
        "hypothesis": detail.get("hypothesis", row.get("hypothesis")),
        "pathway_ref": detail.get("pathway_ref"),
        "evidence_refs": detail.get("evidence_refs", []),
        "closure": closure or None,
        "display": {
            "label": _display_label(lifecycle, claim_verdict),
            "tone": _display_tone(lifecycle, claim_verdict, program_status),
            "program_status": program_status,
            "claim_verdict": claim_verdict,
        },
    }


def _explorer_node(row: dict[str, Any], backtrack_events: list[Any]) -> dict[str, Any]:
    node_id = str(row.get("node_id") or "")
    lifecycle = row.get("lifecycle")
    display = row.get("display") if isinstance(row.get("display"), dict) else {}
    closure = row.get("closure") if isinstance(row.get("closure"), dict) else {}
    program = closure.get("program") if isinstance(closure.get("program"), dict) else {}
    program_status = display.get("program_status") or closure.get("program_status")
    claim_verdict = display.get("claim_verdict") or closure.get("claim_verdict")
    tone = display.get("tone") or _display_tone(lifecycle, claim_verdict, program_status)
    state_key = _node_state_key(lifecycle, claim_verdict, program_status)
    backtrack_ids = [
        str(event.get("event_id"))
        for event in backtrack_events
        if isinstance(event, dict)
        and event.get("event_id")
        and (event.get("from_node") == node_id or event.get("to_node") == node_id)
    ]
    generated_ids = [
        str(event.get("event_id"))
        for event in backtrack_events
        if isinstance(event, dict) and event.get("event_id") and event.get("new_branch_node") == node_id
    ]
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
        "backtrack_event_ids": backtrack_ids,
        "generated_from_backtrack_event_ids": generated_ids,
    }


def _explorer_edges(nodes: list[dict[str, Any]], tree_edges: list[Any], backtrack_events: list[Any]) -> list[dict[str, Any]]:
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
        edges.append({"source": source, "target": target, "kind": kind, **extra})

    for node in nodes:
        add(node.get("parent_id"), node.get("id"), "branch")
    for edge in tree_edges:
        if not isinstance(edge, dict):
            continue
        add(edge.get("source") or edge.get("parent"), edge.get("target") or edge.get("child"), edge.get("kind") or "branch")
    for event in backtrack_events:
        if not isinstance(event, dict):
            continue
        extra = {
            "event_id": event.get("event_id"),
            "event_state": event.get("event_state"),
            "reason": event.get("reason_code"),
        }
        if event.get("from_node") != event.get("to_node"):
            add(event.get("from_node"), event.get("to_node"), "backtrack", **extra)
        add(event.get("from_node"), event.get("new_branch_node"), "backtrack_replacement", **extra)
    return edges


def _explorer_events(backtrack_events: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for event in backtrack_events:
        if not isinstance(event, dict):
            continue
        event_id = event.get("event_id")
        for node_id in (event.get("from_node"), event.get("to_node"), event.get("new_branch_node")):
            if not node_id:
                continue
            out.append(
                {
                    "event_id": event_id,
                    "node_id": node_id,
                    "event_type": "backtrack",
                    "decision": event.get("reason_code") or "backtrack",
                    "reason": event.get("rationale") or event.get("changed_variable"),
                    "evidence_refs": _list(event.get("evidence_refs")),
                }
            )
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


def _explorer_mechanism(mechanism_model: dict[str, Any]) -> dict[str, Any]:
    return {
        **mechanism_model,
        "validated_facts": _mechanism_lines(_list(mechanism_model.get("accepted_facts"))),
        "refuted_hypotheses": _mechanism_lines(_list(mechanism_model.get("refuted_hypotheses"))),
        "open_questions": _mechanism_lines(_list(mechanism_model.get("open_questions"))),
    }


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
            "pathway_rejected": {"label": "pathway rejected", "color": "red"},
        },
        "node_state": {
            "running": {"label": "running", "color": "accent"},
            "supported": {"label": "supported", "color": "green"},
            "refuted": {"label": "refuted", "color": "red"},
            "inconclusive": {"label": "inconclusive", "color": "amber"},
            "not_evaluated": {"label": "not evaluated", "color": "grey"},
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
    }


def _normalize_backtrack_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event.get("event_id"),
        "event_state": event.get("event_state"),
        "from_node": event.get("from_node"),
        "to_node": event.get("to_node"),
        "new_branch_node": event.get("new_branch_node"),
        "changed_variable": event.get("changed_variable"),
        "reason_code": event.get("reason_code"),
        "evidence_refs": event.get("evidence_refs", []),
    }


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


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
