#!/usr/bin/env python3
"""Normalize v2 TS-search workspace artifacts into a stable explorer view."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from transition_state_workflow.config.state_contract import (
    EVIDENCE_STATE_PRESENTATION,
    EXPLORER_GRAPH_SCHEMA,
    NODE_STATE_PRESENTATION,
    WORKSPACE_STATE_PRESENTATION,
    TREE_NODE_FORBIDDEN_RUNTIME_FIELDS,
    build_node_state,
    check_node_contract_violations,
    check_workspace_contract_violations,
    derive_claim_level,
)
from transition_state_workflow.base.pathway_model import read_pathway_model_optional, summarize_pathway_model
from transition_state_workflow.util.json_io import read_json_object_required
from transition_state_workflow.util.cli import configure_cli_logging, emit_json, log
from transition_state_workflow.util.path_utils import clean_string, first_nonempty_string, list_or_empty


def main() -> int:
    """Run the strict workspace normalizer command-line interface."""

    parser = argparse.ArgumentParser(
        description="Emit strict ts-explorer-graph-v2 JSON for a v2 TS-search workspace.",
    )
    parser.add_argument("--source", required=True, type=Path, help="tssearch workspace root.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    parser.add_argument("--verbose", action="store_true", help="Write diagnostic logs to stderr.")
    parser.add_argument("--quiet", action="store_true", help="Only write errors to stderr.")
    args = parser.parse_args()
    configure_cli_logging(verbose=args.verbose, quiet=args.quiet)
    try:
        payload = normalize_ts_workspace_to_explorer_graph(args.source)
    except Exception as exc:
        log(f"ERROR ts_normalize_view: {exc}")
        return 1
    emit_json(payload, pretty=args.pretty)
    return 0


def normalize_ts_workspace_to_explorer_graph(workspace_directory: Path) -> dict[str, Any]:
    """Build the strict v2 explorer graph payload for one TS-search workspace."""

    workspace_directory = workspace_directory.expanduser().resolve()
    manifest_payload = read_json_object_required(workspace_directory / "manifest.json")
    tree_payload = read_json_object_required(workspace_directory / "tree.json")
    evidence_registry_payload = read_json_object_required(workspace_directory / "evidence_registry.json")
    pathway_summary = summarize_pathway_model(read_pathway_model_optional(workspace_directory))
    ensure_workspace_uses_v2_contract(manifest_payload, tree_payload, evidence_registry_payload)
    tree_node_index = tree_payload.get("nodes") if isinstance(tree_payload.get("nodes"), dict) else {}

    frontier_node_ids = sorted(clean_string(item) for item in list_or_empty(tree_payload.get("active_frontier")) if clean_string(item))
    closed_node_ids = sorted(clean_string(item) for item in list_or_empty(tree_payload.get("closed_nodes")) if clean_string(item))
    accepted_node_ids = sorted(clean_string(item) for item in list_or_empty(tree_payload.get("accepted_nodes")) if clean_string(item))
    accepted_ts_node_id = first_nonempty_string(manifest_payload.get("current_accepted_ts"))

    evidence_records = normalize_evidence_registry_records(evidence_registry_payload)
    evidence_counts_by_node_id = count_evidence_records_by_node_id(evidence_records)
    timeline_events = normalize_timeline_events(workspace_directory, tree_payload)
    backtrack_events = normalize_backtrack_events(tree_payload)
    node_ids = collect_workspace_node_ids(workspace_directory, tree_payload)

    backtrack_event_ids_by_node_id: dict[str, list[str]] = {}
    generated_from_backtrack_event_ids_by_node_id: dict[str, list[str]] = {}
    for event_payload in backtrack_events:
        event_id = clean_string(event_payload.get("id"))
        from_node = clean_string(event_payload.get("from_node"))
        new_branch_node = clean_string(event_payload.get("new_branch_node"))
        if from_node and event_id:
            backtrack_event_ids_by_node_id.setdefault(from_node, []).append(event_id)
        if new_branch_node and event_id:
            generated_from_backtrack_event_ids_by_node_id.setdefault(new_branch_node, []).append(event_id)

    node_views: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for node_id in node_ids:
        node_json_path = workspace_directory / "nodes" / node_id / "node.json"
        node_payload = read_json_object_required(node_json_path)
        tree_node_payload = normalize_tree_node_index_entry(tree_node_index.get(node_id))
        view = normalize_node_for_explorer_graph(
            node_id=node_id,
            node_payload=node_payload,
            tree_node_payload=tree_node_payload,
            frontier_node_ids=set(frontier_node_ids),
            closed_node_ids=set(closed_node_ids),
            accepted_node_ids=set(accepted_node_ids),
            evidence_count=evidence_counts_by_node_id.get(node_id, 0),
            backtrack_event_ids=backtrack_event_ids_by_node_id.get(node_id, []),
            generated_from_backtrack_event_ids=generated_from_backtrack_event_ids_by_node_id.get(node_id, []),
        )
        node_views.append(view)
        if view["parent_id"]:
            edges.append(
                {
                    "id": f"{view['parent_id']}->{node_id}",
                    "source": view["parent_id"],
                    "target": node_id,
                    "kind": "branch",
                }
            )
        for dependency_id in view["input_refs"]:
            if dependency_id and dependency_id != node_id:
                edges.append(
                    {
                        "id": f"{dependency_id}=>{node_id}",
                        "source": dependency_id,
                        "target": node_id,
                        "kind": "dependency",
                    }
                )

    for backtrack_event_payload in backtrack_events:
        if clean_string(backtrack_event_payload.get("event_state")) != "active":
            continue
        source_id = clean_string(backtrack_event_payload.get("from_node"))
        target_id = clean_string(backtrack_event_payload.get("to_node"))
        if source_id and target_id:
            edges.append(
                {
                    "id": clean_string(backtrack_event_payload.get("id")) or f"{source_id}~>{target_id}",
                    "source": source_id,
                    "target": target_id,
                    "kind": "backtrack",
                    "reason": clean_string(backtrack_event_payload.get("reason")),
                    "reason_code": clean_string(backtrack_event_payload.get("reason_code")),
                }
            )

    if not accepted_ts_node_id and len(accepted_node_ids) == 1:
        accepted_ts_node_id = accepted_node_ids[0]
    validate_accepted_ts_index(
        accepted_ts_node_id=accepted_ts_node_id,
        accepted_node_ids=accepted_node_ids,
        node_views=node_views,
    )

    return {
        "schema": EXPLORER_GRAPH_SCHEMA,
        "source": str(workspace_directory),
        "workspace_id": workspace_directory.name,
        "revision": compute_workspace_revision_timestamp(workspace_directory),
        # Single source of truth for state rendering; the UI must not keep its
        # own copies of these vocabularies.
        "presentation": {
            "node_state": NODE_STATE_PRESENTATION,
            "evidence_state": EVIDENCE_STATE_PRESENTATION,
            "workspace_state": WORKSPACE_STATE_PRESENTATION,
        },
        "nodes": node_views,
        "edges": dedupe_edges(edges),
        "events": timeline_events,
        "backtrack_events": backtrack_events,
        "pathway": pathway_summary,
        "evidence": {"records": evidence_records},
        "evidence_summary": summarize_evidence_records(evidence_records),
        "active_frontier": frontier_node_ids,
        "frontier_nodes": frontier_node_ids,
        "closed_nodes": closed_node_ids,
        "accepted_ts": accepted_ts_node_id,
        "accepted_nodes": accepted_node_ids,
    }


def ensure_workspace_uses_v2_contract(
    manifest_payload: dict[str, Any],
    tree_payload: dict[str, Any],
    evidence_registry_payload: dict[str, Any],
) -> None:
    """Reject a workspace unless its root files declare the v2 contract."""

    violations = check_workspace_contract_violations(
        manifest=manifest_payload,
        tree=tree_payload,
        evidence_registry=evidence_registry_payload,
    )
    if violations:
        raise ValueError(violations[0][1])


def validate_accepted_ts_index(
    *,
    accepted_ts_node_id: str,
    accepted_node_ids: list[str],
    node_views: list[dict[str, Any]],
) -> None:
    """Reject explorer payloads with contradictory accepted-TS indexes."""

    if not accepted_ts_node_id:
        return
    node_by_id = {clean_string(node.get("id")): node for node in node_views}
    accepted_view = node_by_id.get(accepted_ts_node_id)
    if not accepted_view:
        raise ValueError(f"manifest current_accepted_ts references missing node: {accepted_ts_node_id}")
    if clean_string(accepted_view.get("claim_status")) != "accepted_ts":
        raise ValueError(f"manifest current_accepted_ts node is not claim_status=accepted_ts: {accepted_ts_node_id}")
    if accepted_ts_node_id not in accepted_node_ids:
        raise ValueError(f"manifest current_accepted_ts is missing from tree.accepted_nodes: {accepted_ts_node_id}")


def normalize_node_for_explorer_graph(
    *,
    node_id: str,
    node_payload: dict[str, Any],
    tree_node_payload: dict[str, Any],
    frontier_node_ids: set[str],
    closed_node_ids: set[str],
    accepted_node_ids: set[str],
    evidence_count: int,
    backtrack_event_ids: list[str],
    generated_from_backtrack_event_ids: list[str],
) -> dict[str, Any]:
    """Normalize one v2 node.json payload into an explorer node view."""

    ensure_node_uses_v2_contract(node_id, node_payload)
    parent_id = first_nonempty_string(node_payload.get("parent_id"), tree_node_payload.get("parent_id"))
    stage = first_nonempty_string(node_payload.get("stage"), tree_node_payload.get("stage"))
    operation = clean_string(node_payload.get("operation"))
    display = node_payload.get("display") if isinstance(node_payload.get("display"), dict) else {}
    title = first_nonempty_string(display.get("title"), node_payload.get("label"), tree_node_payload.get("label"), node_id)
    summary = first_nonempty_string(display.get("summary"), node_payload.get("summary"), tree_node_payload.get("summary"), "")
    claim_status = clean_string(node_payload.get("claim_status"))
    outcome = clean_string(node_payload.get("outcome"))
    run_state = clean_string(node_payload.get("run_state"))
    outcome_code = node_payload.get("outcome_code")
    node_state = build_node_state(
        claim_status=claim_status,
        outcome=outcome,
        outcome_code=clean_string(outcome_code) or None,
        run_state=run_state,
        stage=stage,
    )
    input_refs = normalize_input_refs(node_payload, tree_node_payload)

    return {
        "id": node_id,
        "label": node_id,
        "title": title,
        "stage": stage,
        "stage_label": make_stage_display_label(stage),
        "operation": operation,
        "lifecycle_state": clean_string(node_payload.get("lifecycle_state")),
        "run_state": run_state,
        "claim_status": claim_status,
        "outcome": outcome,
        "outcome_code": outcome_code,
        "claim_level": derive_claim_level(claim_status),
        "node_state": node_state["key"],
        "state_label": node_state["label"],
        "state_line": node_state["line"],
        "severity": node_state["severity"],
        "color": node_state["color"],
        "parent_id": parent_id,
        "input_refs": input_refs,
        "pathway_id": clean_string(node_payload.get("pathway_id")) or clean_string(tree_node_payload.get("pathway_id")),
        "elementary_step_id": clean_string(node_payload.get("elementary_step_id")) or clean_string(tree_node_payload.get("elementary_step_id")),
        "intended_reaction_boundary": normalize_reaction_boundary(node_payload.get("intended_reaction_boundary")),
        "frontier": node_id in frontier_node_ids,
        "active": node_id in frontier_node_ids,
        "closed": node_id in closed_node_ids,
        "accepted": node_id in accepted_node_ids or claim_status == "accepted_ts",
        "hypothesis": first_nonempty_string(node_payload.get("hypothesis"), tree_node_payload.get("hypothesis")),
        "decision": first_nonempty_string(node_payload.get("decision"), tree_node_payload.get("decision")),
        "backtrack_event_ids": [event_id for event_id in backtrack_event_ids if event_id],
        "generated_from_backtrack_event_ids": [event_id for event_id in generated_from_backtrack_event_ids if event_id],
        "evidence_count": evidence_count,
        "display": {
            **display,
            "title": title,
            "summary": summary,
            "metrics": display.get("metrics") if isinstance(display.get("metrics"), dict) else {},
        },
    }


def normalize_input_refs(node_payload: dict[str, Any], tree_node_payload: dict[str, Any]) -> list[str]:
    """Return normalized dependency/input node references for multi-input routes."""

    refs: list[str] = []
    for source in (tree_node_payload, node_payload):
        for value in list_or_empty(source.get("input_refs")):
            ref = clean_string(value)
            if ref and ref not in refs:
                refs.append(ref)
    return refs


def normalize_reaction_boundary(value: Any) -> dict[str, str] | None:
    """Return a compact intended pathway-step boundary when present."""

    if not isinstance(value, dict):
        return None
    start = clean_string(value.get("from"))
    end = clean_string(value.get("to"))
    if not start and not end:
        return None
    return {"from": start, "to": end}


def ensure_node_uses_v2_contract(node_id: str, node_payload: dict[str, Any]) -> None:
    """Reject node payloads that are missing v2 fields or contain old aliases."""

    violations = check_node_contract_violations(node_id, node_payload)
    if violations:
        raise ValueError(f"{node_id}: {violations[0][1]}")


def normalize_evidence_registry_records(evidence_registry_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize evidence records while preserving the original evidence payload."""

    records: list[dict[str, Any]] = []
    for index, item in enumerate(list_or_empty(evidence_registry_payload.get("records"))):
        if not isinstance(item, dict):
            raise ValueError(f"evidence_registry.json records[{index}] is not an object")
        if "status" in item or "state" in item:
            raise ValueError(
                f"evidence_registry.json records[{index}] uses legacy status/state; use evidence_state"
            )
        if not clean_string(item.get("evidence_id")):
            raise ValueError(f"evidence_registry.json records[{index}] missing evidence_id")
        evidence_state = clean_string(item.get("evidence_state"))
        if not evidence_state:
            raise ValueError(f"evidence_registry.json records[{index}] missing evidence_state")
        presentation = EVIDENCE_STATE_PRESENTATION.get(evidence_state, {})
        records.append(
            {
                **item,
                "evidence_label": presentation.get("label", evidence_state),
                "evidence_severity": presentation.get("severity", "neutral"),
                "evidence_color": presentation.get("color", "grey"),
            }
        )
    return records


def count_evidence_records_by_node_id(evidence_records: list[dict[str, Any]]) -> dict[str, int]:
    """Count non-superseded evidence records for each node id."""

    counts: dict[str, int] = {}
    for item in evidence_records:
        if clean_string(item.get("evidence_state")) == "superseded":
            continue
        node_id = clean_string(item.get("node_id"))
        if node_id:
            counts[node_id] = counts.get(node_id, 0) + 1
    return counts


def normalize_timeline_events(workspace_directory: Path, tree_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize tree and JSONL timeline events for explorer rendering."""

    events: list[dict[str, Any]] = []
    events_path = workspace_directory / "events.jsonl"
    if events_path.exists():
        for index, line in enumerate(events_path.read_text(encoding="utf-8", errors="replace").splitlines()):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"events.jsonl line {index + 1} is invalid JSON: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"events.jsonl line {index + 1} is not an object")
            events.append(normalize_event(payload, f"evt_jsonl_{index + 1:04d}"))
    for index, item in enumerate(list_or_empty(tree_payload.get("events"))):
        if not isinstance(item, dict):
            raise ValueError(f"tree.json events[{index}] is not an object")
        events.append(normalize_event(item, f"evt_tree_{index + 1:04d}"))
    # Historical workspaces mixed append and prepend ordering, so array position
    # is not a reliable timeline; ISO-8601 timestamps are the canonical order.
    events.sort(key=lambda item: clean_string(item.get("time")))
    return events


def normalize_event(item: dict[str, Any], fallback_id: str) -> dict[str, Any]:
    """Normalize one canonical v2 timeline event."""

    if "evidence" in item and "evidence_refs" not in item:
        raise ValueError(f"event {clean_string(item.get('event_id')) or fallback_id} uses legacy evidence; use evidence_refs")
    evidence_refs = [clean_string(value) for value in list_or_empty(item.get("evidence_refs")) if clean_string(value)]
    return {
        **item,
        "event_id": clean_string(item.get("event_id")) or fallback_id,
        "time": clean_string(item.get("time")),
        "node_id": clean_string(item.get("node_id")),
        "event_type": clean_string(item.get("event_type")) or "manual_note",
        "decision": clean_string(item.get("decision")),
        "reason": clean_string(item.get("reason")),
        "evidence_refs": evidence_refs,
    }


def normalize_backtrack_events(tree_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize canonical backtrack events used for dashed graph edges."""

    events: list[dict[str, Any]] = []
    for index, item in enumerate(list_or_empty(tree_payload.get("backtrack_events"))):
        if not isinstance(item, dict):
            raise ValueError(f"tree.json backtrack_events[{index}] is not an object")
        events.append(normalize_backtrack_event(item, f"bt_{index + 1:04d}"))
    return events


def normalize_backtrack_event(item: dict[str, Any], fallback_id: str) -> dict[str, Any]:
    """Normalize one v2 backtrack event and reject old edge aliases."""

    if "evidence" in item and "evidence_refs" not in item:
        raise ValueError(f"backtrack event {clean_string(item.get('id')) or fallback_id} uses legacy evidence; use evidence_refs")
    legacy_fields = [field for field in ("from", "source", "to", "target", "time") if field in item]
    if legacy_fields:
        raise ValueError(
            f"backtrack event {clean_string(item.get('id')) or fallback_id} contains legacy fields: {', '.join(legacy_fields)}"
        )
    evidence_refs = [clean_string(value) for value in list_or_empty(item.get("evidence_refs")) if clean_string(value)]
    return {
        **item,
        "id": clean_string(item.get("id")) or fallback_id,
        "from_node": clean_string(item.get("from_node")),
        "to_node": clean_string(item.get("to_node")),
        "new_branch_node": clean_string(item.get("new_branch_node")),
        "reason_code": clean_string(item.get("reason_code")),
        "reason": clean_string(item.get("reason")),
        "evidence_refs": evidence_refs,
        "event_state": clean_string(item.get("event_state")) or "active",
        "created_at": clean_string(item.get("created_at")),
    }


def collect_workspace_node_ids(workspace_directory: Path, tree_payload: dict[str, Any]) -> list[str]:
    """Collect node ids from tree.json and the nodes directory."""

    ids: set[str] = set()
    tree_nodes = tree_payload.get("nodes")
    if isinstance(tree_nodes, dict):
        ids.update(str(key) for key in tree_nodes if clean_string(key))
    nodes_dir = workspace_directory / "nodes"
    if nodes_dir.exists():
        ids.update(child.name for child in nodes_dir.iterdir() if child.is_dir())
    return sorted(ids)


def normalize_tree_node_index_entry(value: Any) -> dict[str, Any]:
    """Return a tree node index entry after rejecting duplicated runtime state."""

    payload = dict(value) if isinstance(value, dict) else {}
    forbidden_fields = [field_name for field_name in TREE_NODE_FORBIDDEN_RUNTIME_FIELDS if field_name in payload]
    if forbidden_fields:
        raise ValueError(f"tree.json nodes entry contains non-v2 runtime fields: {', '.join(forbidden_fields)}")
    return payload


def compute_workspace_revision_timestamp(workspace_directory: Path) -> int:
    """Return the newest mtime among files that define the explorer graph."""

    paths = [
        workspace_directory / name
        for name in ("manifest.json", "tree.json", "evidence_registry.json", "events.jsonl", "pathway_model.json")
    ]
    nodes_dir = workspace_directory / "nodes"
    if nodes_dir.exists():
        paths.extend(nodes_dir.glob("*/node.json"))
    mtimes = [int(path.stat().st_mtime) for path in paths if path.exists()]
    return max(mtimes) if mtimes else 0


def summarize_evidence_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize evidence counts by kind and state."""

    by_kind: dict[str, int] = {}
    by_state: dict[str, int] = {}
    for item in records:
        kind = clean_string(item.get("kind")) or "unknown"
        state = clean_string(item.get("evidence_state")) or "unknown"
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_state[state] = by_state.get(state, 0) + 1
    return {"count": len(records), "by_kind": by_kind, "by_state": by_state}


def make_stage_display_label(stage: str) -> str:
    """Return a compact human-readable label for a workflow stage."""

    text = stage.replace("_", " ").replace("-", " ").strip()
    if not text:
        return ""
    lower = text.lower()
    if "tsfreq" in lower or ("ts" in lower and "freq" in lower):
        return "Gaussian TS/Freq"
    if "irc" in lower:
        return "IRC"
    if "connect" in lower:
        return "Connectivity"
    if "neb" in lower:
        return "NEB"
    return text.title()


def dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate graph edges while preserving reason metadata when possible."""

    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    out: list[dict[str, Any]] = []
    for edge in edges:
        key = (clean_string(edge.get("source")), clean_string(edge.get("target")), clean_string(edge.get("kind")))
        if key in seen:
            existing = seen[key]
            for detail_key in ("reason", "reason_code"):
                if not clean_string(existing.get(detail_key)) and clean_string(edge.get(detail_key)):
                    existing[detail_key] = clean_string(edge.get(detail_key))
            continue
        seen[key] = edge
        out.append(edge)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
