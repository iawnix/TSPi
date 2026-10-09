"""Disposable bounded decision view; the State snapshot remains authoritative."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research_state.agent_workspace import read_context, read_liveness
from research_state.assessments import claim_review_state
from research_state.requirements import requirements_evaluation
from research_state.invariants import validate_context
from research_state.transactions import TransactionCoordinator


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _finish_view(view, max_bytes, requested_events, event_order):
    """Bound a disposable view without weakening the authoritative State.

    Identities are never truncated. Whole records or fields may be omitted, but
    their counts and read routes remain visible. Even focus and running-ID
    lists are projections; neither may prevent an operator/Agent from reading.
    """
    collections = ("goals", "requirements", "sources", "nodes", "related_nodes", "issues", "events", "attempts", "gates", "strategies", "interpretations")
    totals = {name: len(view[name]) + view["bounds"]["omitted"].get(name, 0) for name in collections}
    focus = view["focus"]
    running = view["lifecycle"].get("running_attempt_ids") or []

    def account():
        omitted = {name: totals[name] - len(view[name]) for name in collections if totals[name] > len(view[name])}
        for kind in ("claim_ids", "node_ids"):
            if len(focus[kind]) > len(view["focus"][kind]):
                omitted["focus_" + kind] = len(focus[kind]) - len(view["focus"][kind])
        if len(running) > len(view["lifecycle"].get("running_attempt_ids", [])):
            omitted["running_attempt_ids"] = len(running) - len(view["lifecycle"].get("running_attempt_ids", []))
        view["bounds"]["omitted"] = omitted
        compacted = {name: sum(row.get("details_omitted", False) is True for row in view[name])
                     for name in collections if any(row.get("details_omitted") for row in view[name])}
        if compacted:
            view["bounds"]["compacted"] = compacted
        else:
            view["bounds"].pop("compacted", None)
        view["bounds"]["degraded"] = bool(omitted or compacted)
        view["scope"]["omitted_nodes"] = view["scope"]["total_nodes"] - len(view["nodes"]) - len(view["related_nodes"])
        shown = {row["event_id"] for row in view["events"]}
        next_event = next((event_id for event_id in event_order if event_id not in shown), None)
        if next_event is not None:
            view["read"]["pending_events"] = {"mode": "context", "event_ids": [next_event], "max_bytes": 16000}
        else:
            view["read"].pop("pending_events", None)
        if requested_events:
            view["wake_events"] = {"requested": len(requested_events), "included": len(set(requested_events) & shown),
                                   "omitted": len(set(requested_events) - shown)}

    def fits():
        account()
        # context_id and final byte accounting are added only after selection.
        return len(_encode(view).encode()) <= max_bytes - 128

    if not fits():
        view["read"]["claim"] = {"mode": "detail", "kind": "claim", "id": "<claim_id>"}
        view["read"]["gate"] = {"mode": "detail", "kind": "gate", "id": "<gate_id>"}
        view["read"]["nodes"] = {"mode": "locate", "query": "node_", "offset": 0, "limit": 20}
        view["read"]["claims"] = {"mode": "locate", "query": "claim_", "offset": 0, "limit": 20}
        view["read"]["decisions"]["offset"] = 0
        view["read"]["evidence"]["offset"] = 0
        view["read"]["event"] = {"mode": "context", "event_ids": ["<event_id from triggering message>"], "max_bytes": 16000}
        view["required_action"] = "Read relevant omitted details before deciding completion or handling a wake; narrow focus with research_change set_focus. Omission is not satisfaction."
        # Strip explanatory text before dropping identities. The complete
        # record remains available through detail; no partial text is a fact.
        keys = {
            "goals": ("id", "status", "assessment_state"),
            "requirements": ("id", "state", "satisfied", "settled", "covered"),
            "sources": ("source_ref", "reviewed"),
            "nodes": ("id", "state", "outcome"),
            "related_nodes": ("id", "state", "outcome"),
            "gates": ("id", "scope", "target_id", "version"),
            "strategies": ("id", "claim_id", "node_id", "status"),
            "interpretations": ("id", "attempt_ref", "outcome", "review_state"),
            "attempts": ("id", "node_id", "state", "job_id", "collection_state", "required_action"),
            "events": ("event_id", "job_id", "attempt_id", "node_id", "state"),
        }
        for name, fields in keys.items():
            if fits():
                break
            view[name] = [{**{key: row[key] for key in fields if key in row}, "details_omitted": True}
                          for row in view[name]]
        # Focus/liveness lists are redundant references and can themselves be
        # enormous. The scope counts make their incompleteness explicit.
        if not fits():
            view["focus"] = {"claim_ids": [], "node_ids": []}
            view["lifecycle"]["running_attempt_ids"] = []
            view["lifecycle"]["running_attempt_count"] = len(running)
        # Keep current/wake Attempts and events until other optional sections
        # have been exhausted. Requested events are counted even if all of
        # their exact identities cannot fit the smallest supported budget.
        for name in ("interpretations", "strategies", "issues", "related_nodes", "gates", "goals", "nodes", "requirements", "sources", "attempts", "events"):
            if fits():
                break
            rows = view[name]
            view[name] = []
            if not fits():
                continue
            # Find the largest fitting prefix without serializing the full
            # remaining history once for every discarded record.
            lower, upper = 0, len(rows)
            while lower < upper:
                middle = (lower + upper + 1) // 2
                view[name] = rows[:middle]
                if fits():
                    lower = middle
                else:
                    upper = middle - 1
            view[name] = rows[:lower]
        if not fits():
            # A fixed-size recovery envelope, including the authoritative
            # lifecycle, must fit even when all detail routes do not.
            view["read"] = {"nodes": {"mode": "locate", "query": "node_", "offset": 0, "limit": 20},
                            "event": {"mode": "context", "event_ids": ["<event_id from triggering message>"], "max_bytes": 16000}}
            view["required_action"] = "Projection incomplete; read details before acting."
        account()
    view["context_id"] = "ctx_" + hashlib.sha256(_encode(view).encode()).hexdigest()
    view["bounds"]["used_bytes"] = 0
    while view["bounds"]["used_bytes"] != len(_encode(view).encode()):
        view["bounds"]["used_bytes"] = len(_encode(view).encode())
    if view["bounds"]["used_bytes"] > max_bytes:
        raise ValueError("context_budget_invalid: minimal lifecycle envelope exceeds byte budget")
    return view


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
        "requirements": requirements_evaluation(state)["requirements"],
        "sources": [{"source_ref": row["source_ref"], "reviewed": bool(row.get("review"))}
                    for row in state.get("requirement_sources", [])],
        "goals": [{**{k: c.get(k) for k in ("id", "statement", "status", "predictions", "falsifiers", "source_refs", "constraints")},
                   "assessment_state": claim_review_state(state, c)}
                  for c in state.get("claims", []) if c["id"] in focus.get("claim_ids", [])],
        "nodes": [{k: n.get(k) for k in ("id", "objective", "state", "outcome", "gate_ids", "dependencies", "consumes")}
                  for n in state.get("nodes", []) if n["id"] in focus_nodes],
        "related_nodes": [],
        "issues": validate_context(state)["issues"],
        "events": [], "attempts": [], "gates": [], "strategies": [], "interpretations": [],
        "read": {"node": {"mode": "detail", "kind": "node", "id": "<node_id>"},
                 "requirements": {"mode": "requirements"}, "sources": {"mode": "sources", "limit": 4},
                 "evidence": {"mode": "evidence", "limit": 20},
                 "decisions": {"mode": "decisions", "limit": 10}},
        "bounds": {"max_bytes": max_bytes, "estimated_tokens": True, "omitted": {}},
    }

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
                view["related_nodes"].append({k: node.get(k) for k in ("id", "state", "outcome", "dependencies")})
                included.add(node_id)
            pending.extend(row["node_id"] for row in node.get("dependencies", []))

    include_nodes(sorted(focus_nodes))
    def add(name, values):
        for value in values:
            if value.get("node_id"):
                include_nodes([value["node_id"]])
            view[name].append(value)

    add("gates", [{**{k: g.get(k) for k in ("id", "scope", "target_id", "version", "criteria")},
                   "evaluations": g.get("evaluations", [])[-1:]}
                  for g in state.get("gates", []) if g.get("target_id") in focus_nodes | set(focus.get("claim_ids", []))])
    add("events", [{k: e.get(k) for k in ("event_id", "job_id", "attempt_id", "node_id", "state", "observed_at")}
                   for e in latest[:8]])
    if len(latest) > len(view["events"]):
        view["bounds"]["omitted"]["events"] = len(latest) - len(view["events"])
    add("strategies", [{k: s.get(k) for k in ("id", "claim_id", "node_id", "objective", "steps", "status", "stop_conditions")}
                       for s in reversed(state.get("strategy_plans", []))
                       if s.get("status") in {"proposed", "active"} and (s.get("claim_id") in focus_claims or s.get("node_id") in focus_nodes)])
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
    add("interpretations", [{k: i.get(k) for k in ("id", "attempt_ref", "outcome", "summary", "supersedes_id", "superseded_by", "review_state")}
                           for i in reversed(state.get("attempt_interpretations", []))][:8])
    if len(state.get("attempt_interpretations", [])) > len(view["interpretations"]):
        view["bounds"]["omitted"]["interpretations"] = len(state["attempt_interpretations"]) - len(view["interpretations"])
    return _finish_view(view, max_bytes, tuple(dict.fromkeys(event_ids)), [event["event_id"] for event in latest])
