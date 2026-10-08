"""Disposable bounded decision view; the State snapshot remains authoritative."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research_state.agent_workspace import read_context, read_liveness
from research_state.invariants import validate_context
from research_state.transactions import TransactionCoordinator


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_decision_context(root, *, max_bytes=16000, event_ids=()):
    if type(max_bytes) is not int or not 2048 <= max_bytes <= 32000:
        raise ValueError("context_budget_invalid: max_bytes must be between 2048 and 32000")
    if not isinstance(event_ids, (list, tuple)) or len(event_ids) > 8 or any(not isinstance(e, str) for e in event_ids):
        raise ValueError("context_event_ids_invalid: provide at most eight event IDs")
    root = Path(root)
    with TransactionCoordinator(root).locked():
        state, live = read_context(root), read_liveness(root)
        events = []
        for path in sorted((root / "operations/monitors").glob("*/events/*.json")):
            event = json.loads(path.read_text())
            from research_state.monitor_wake import validate_event
            validate_event(event)
            delivery_path = path.parent.parent / "deliveries" / path.name
            delivery = json.loads(delivery_path.read_text()) if delivery_path.exists() else {}
            if not event_ids and delivery.get("delivered"):
                continue
            if event_ids and event["event_id"] not in event_ids:
                continue
            events.append(event)
        receipts = {}
        for path in sorted((root / "operations/results").glob("*.json")):
            receipt = json.loads(path.read_text())
            receipts[receipt["receipt_id"]] = receipt
    focus = state.get("focus", {})
    if not focus.get("claim_ids") and not focus.get("node_ids"):
        focus = {"claim_ids": [c["id"] for c in state.get("claims", [])], "node_ids": [n["id"] for n in state.get("nodes", []) if n.get("state") != "closed"]}
    latest = sorted(events, key=lambda e: (e.get("observed_at", ""), e["event_id"]), reverse=True)
    if set(event_ids) - {e["event_id"] for e in latest}:
        raise ValueError("context_event_not_found: requested wake event is missing")
    event_attempts = {e.get("attempt_id") for e in latest[:8]}
    focus_nodes = set(focus.get("node_ids", [])) | {e['node_id'] for e in latest[:8] if e.get('node_id')}
    focus_claims = set(focus.get("claim_ids", []))
    for node in state.get("nodes", []):
        if node["id"] in focus_nodes:
            focus_claims.update(node.get("claim_ids", []))
    focus = {"claim_ids": sorted(focus_claims), "node_ids": sorted(focus_nodes)}
    nodes_by_id = {node["id"]: node for node in state.get("nodes", [])}
    attempts = sorted(state.get("attempts", []), key=lambda a: (
        a["id"] in event_attempts, a.get("state") in {"started", "running", "unknown"},
        a.get("node_id") in focus_nodes, a.get("updated_at", a.get("created_at", ""))), reverse=True)
    view = {
        "schema_version": "research-decision-context/2",
        "workspace_id": state["workspace_id"], "revision": state["revision"],
        "authority": "research_state", "focus": focus,
        "lifecycle": {
            **{k: live.get(k) for k in ("lifecycle", "disposition", "checkpoint_id", "running_attempt_ids", "execution_ready")},
            "recovery_required": live.get("lifecycle") in {"blocked", "user_input_required", "deferred", "terminal"},
        },
        "scope": {"kind": "focused", "unlisted_objects": "not_necessarily_missing", "total_nodes": len(nodes_by_id)},
        "goals": [{k: c.get(k) for k in ("id", "statement", "status", "predictions", "falsifiers", "source_refs", "constraints")}
                  for c in state.get("claims", []) if c["id"] in focus.get("claim_ids", [])],
        "nodes": [{k: n.get(k) for k in ("id", "objective", "state", "outcome", "gate_ids", "completion_exemption", "dependency_ids")}
                  for n in state.get("nodes", []) if n["id"] in focus_nodes],
        "related_nodes": [],
        "issues": validate_context(state)["issues"],
        "events": [], "attempts": [], "gates": [], "strategies": [], "interpretations": [],
        "read": {"node": {"mode": "detail", "kind": "node", "id": "<node_id>"},
                 "evidence": {"mode": "evidence", "limit": 20},
                 "decisions": {"mode": "decisions", "limit": 10}},
        "bounds": {"max_bytes": max_bytes, "estimated_tokens": True, "omitted": {}},
    }

    def fits():
        # Reserve space for digest, accounting and query cursors.
        return len(_encode(view).encode()) <= max_bytes - 768

    def include_nodes(ids):
        """Keep references resolvable without changing focus or copying full nodes."""
        included = focus_nodes | {n["id"] for n in view["related_nodes"]}
        pending = list(ids)
        visited = set()
        while pending:
            node_id = pending.pop()
            if node_id in visited or node_id not in nodes_by_id:
                continue
            visited.add(node_id)
            node = nodes_by_id[node_id]
            if node_id not in included:
                view["related_nodes"].append({k: node.get(k) for k in ("id", "state", "outcome", "dependency_ids")})
                included.add(node_id)
            pending.extend(node.get("dependency_ids", []))

    include_nodes(sorted(focus_nodes))
    if not fits():
        raise ValueError("context_budget_exceeded: narrow focus; required goals and constraints cannot be omitted")

    def add(name, values):
        for index, value in enumerate(values):
            related_count = len(view["related_nodes"])
            if value.get("node_id"):
                include_nodes([value["node_id"]])
            view[name].append(value)
            if not fits():
                view[name].pop()
                del view["related_nodes"][related_count:]
                view["bounds"]["omitted"][name] = len(values) - index
                return

    add("gates", [{**{k: g.get(k) for k in ("id", "scope", "target_id", "version", "criteria")},
                   "evaluations": g.get("evaluations", [])[-1:]}
                  for g in state.get("gates", []) if g.get("target_id") in focus_nodes | set(focus.get("claim_ids", []))])
    if view["bounds"]["omitted"].get("gates"):
        raise ValueError("context_budget_exceeded: completion conditions cannot be omitted; narrow focus")
    add("events", [{k: e.get(k) for k in ("event_id", "job_id", "attempt_id", "node_id", "state", "observed_at")}
                   for e in latest[:8]])
    if latest and not view["events"]:
        raise ValueError("context_budget_exceeded: current event cannot be omitted")
    if event_ids and len(view["events"]) != len(latest):
        raise ValueError("context_budget_exceeded: requested wake events cannot be omitted")
    if len(latest) > len(view["events"]):
        view["bounds"]["omitted"]["events"] = len(latest) - len(view["events"])
        view["read"]["pending_events"] = {"command": "monitor.pending", "next_event_ids": [e["event_id"] for e in latest[len(view["events"]):][:8]]}
    add("strategies", [{k: s.get(k) for k in ("id", "claim_id", "node_id", "objective", "steps", "status", "stop_conditions")}
                       for s in reversed(state.get("strategy_plans", []))
                       if s.get("status") in {"proposed", "active"} and (s.get("claim_id") in focus_claims or s.get("node_id") in focus_nodes)])
    if view["bounds"]["omitted"].get("strategies"):
        raise ValueError("context_budget_exceeded: current strategies cannot be omitted; narrow focus")
    rows = []
    for a in attempts:
        row = {k: a.get(k) for k in ("id", "node_id", "state", "exit_code", "finished_at")}
        row["job_id"] = a.get("metadata", {}).get("job_id")
        row["observation"] = a.get("metadata", {}).get("execution_observation")
        receipt = receipts.get(a.get("metadata", {}).get("latest_result_receipt_ref"))
        row["result_receipt_ref"] = receipt.get("receipt_id") if receipt else None
        row["collection_state"] = receipt.get("collection_state") if receipt else "not_collected"
        row["read"] = {"mode": "evidence", "attempt_id": a["id"], "limit": 20}
        if row["job_id"] and (a.get("state") == "unknown" or a.get("metadata", {}).get("execution_conflict")):
            row["required_action"] = {"tool": "job_reconcile", "attempt_id": a["id"],
                                      "reason": "Execution is not confirmed; scientific completion remains blocked."}
        rows.append(row)
    add("attempts", rows)
    if attempts and not view["attempts"]:
        raise ValueError("context_budget_exceeded: current Attempt cannot be omitted")
    if event_attempts - {a["id"] for a in view["attempts"]}:
        raise ValueError("context_budget_exceeded: wake event Attempts cannot be omitted; request a smaller event batch")
    add("interpretations", [{k: i.get(k) for k in ("id", "attempt_ref", "outcome", "summary", "supersedes_id", "superseded_by", "review_state")}
                           for i in reversed(state.get("attempt_interpretations", []))][:8])
    view["scope"]["omitted_nodes"] = len(nodes_by_id) - len(view["nodes"]) - len(view["related_nodes"])
    view["context_id"] = "ctx_" + hashlib.sha256(_encode(view).encode()).hexdigest()
    view["bounds"]["used_bytes"] = 0
    while view["bounds"]["used_bytes"] != len(_encode(view).encode()):
        view["bounds"]["used_bytes"] = len(_encode(view).encode())
    if view["bounds"]["used_bytes"] > max_bytes:
        raise ValueError("context_budget_exceeded: required projection exceeds byte budget")
    return view
