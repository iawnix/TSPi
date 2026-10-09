"""Large research maps remain readable without silently satisfying obligations."""
import copy
import json

import pytest

from research_memory import decision_context
from research_state.agent_workspace import read_context
from tests.unit.test_job_recovery import workspace


def encoded_size(value):
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def large_map(root, monkeypatch, *, count=200, explicit_focus=False):
    workspace(root)
    state = read_context(root)
    prototype = copy.deepcopy(state["nodes"][0])
    claim = copy.deepcopy(state["claims"][0])
    state.update(nodes=[], claims=[], gates=[], strategy_plans=[], attempts=[])
    text = "需要验证成键方向与反应路径。" * 600
    for index in range(count):
        node_id, claim_id, attempt_id = f"node_{index}", f"claim_{index}", f"attempt_{index}"
        state["claims"].append({**claim, "id": claim_id, "statement": text, "node_ids": [node_id]})
        state["nodes"].append({**prototype, "id": node_id, "objective": text, "claim_ids": [claim_id],
                               "dependencies": [], "gate_ids": [f"gate_{index}"]})
        state["gates"].append({"id": f"gate_{index}", "scope": "node", "target_id": node_id, "version": 1,
                               "criteria": [{"id": "scientific_check", "source_type": "agent_assessment", "description": text}], "evaluations": []})
        state["strategy_plans"].append({"id": f"strategy_{index}", "node_id": node_id, "claim_id": claim_id,
                                        "status": "active", "objective": text, "steps": [text]})
        state["attempts"].append({"id": attempt_id, "node_id": node_id, "state": "running", "metadata": {"job_id": f"job_{index}"}})
    state["focus"] = {"claim_ids": [c["id"] for c in state["claims"]] if explicit_focus else [],
                       "node_ids": [n["id"] for n in state["nodes"]] if explicit_focus else []}
    live = {"lifecycle": "blocked", "disposition": "blocked", "checkpoint_id": "checkpoint_blocked",
            "execution_ready": False, "running_attempt_ids": [a["id"] for a in state["attempts"]]}
    monkeypatch.setattr(decision_context, "read_context", lambda _root: state)
    monkeypatch.setattr(decision_context, "read_liveness", lambda _root: live)
    return state


@pytest.mark.parametrize("max_bytes", [2048, 4096, 16000, 32000])
@pytest.mark.parametrize("explicit_focus", [False, True])
def test_large_map_never_blocks_and_accounts_for_every_omitted_row(tmp_path, monkeypatch, max_bytes, explicit_focus):
    state = large_map(tmp_path, monkeypatch, explicit_focus=explicit_focus)
    view = decision_context.build_decision_context(tmp_path, max_bytes=max_bytes)
    assert encoded_size(view) == view["bounds"]["used_bytes"] <= max_bytes
    assert view["bounds"]["degraded"] is True
    assert view["lifecycle"]["recovery_required"] is True
    assert view["lifecycle"]["execution_ready"] is False
    assert view["lifecycle"]["checkpoint_id"] == "checkpoint_blocked"
    assert view["scope"]["omitted_nodes"] == 200 - len(view["nodes"]) - len(view["related_nodes"])
    for name, source in (("goals", "claims"), ("nodes", "nodes"), ("gates", "gates"), ("strategies", "strategy_plans"), ("attempts", "attempts")):
        assert len(view[name]) + view["bounds"]["omitted"].get(name, 0) == len(state[source])
        assert {row["id"] for row in view[name]} <= {row["id"] for row in state[source]}
    assert "required_action" in view
    assert view["read"]


def event(root, index, *, long_ids=False):
    suffix = str(index) + ("x" * 220 if long_ids else "")
    record = {"schema_version": "ts-job-monitor-event/1", "event_id": "event_" + suffix,
              "monitor_id": "monitor_test", "job_id": "job_" + suffix,
              "attempt_id": "attempt_" + suffix, "node_id": "node_0", "state": "failed", "observed_at": str(index)}
    path = root / "operations/monitors/monitor_test/events" / (record["event_id"] + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))
    return record["event_id"]


def test_requested_wakes_are_explicit_when_even_their_identities_do_not_fit(tmp_path, monkeypatch):
    large_map(tmp_path, monkeypatch, count=2)
    ids = [event(tmp_path, i, long_ids=True) for i in range(8)]
    view = decision_context.build_decision_context(tmp_path, max_bytes=2048, event_ids=ids)
    assert view["bounds"]["used_bytes"] <= 2048
    shown = {row["event_id"] for row in view["events"]}
    assert shown <= set(ids)
    assert view["wake_events"] == {"requested": 8, "included": len(shown), "omitted": 8 - len(shown)}
    assert view["wake_events"]["omitted"] > 0
    assert view["bounds"]["omitted"]["events"] == 8 - len(shown)
    assert view["read"]["event"]["mode"] == "context"
    assert set(view["read"]["pending_events"]["event_ids"]) <= set(ids) - shown


def test_default_wake_page_counts_all_pending_events(tmp_path, monkeypatch):
    large_map(tmp_path, monkeypatch, count=1)
    for i in range(20):
        event(tmp_path, i)
    view = decision_context.build_decision_context(tmp_path)
    assert len(view["events"]) + view["bounds"]["omitted"]["events"] == 20
    hint = view["read"]["pending_events"]
    assert hint["mode"] == "context"
    assert not set(hint["event_ids"]) & {row["event_id"] for row in view["events"]}
    next_page = decision_context.build_decision_context(tmp_path, event_ids=hint["event_ids"])
    assert {row["event_id"] for row in next_page["events"]} == set(hint["event_ids"])
    assert view["bounds"]["degraded"] is True


def test_field_reduction_is_marked_even_when_no_records_are_dropped(tmp_path, monkeypatch):
    large_map(tmp_path, monkeypatch, count=1)
    view = decision_context.build_decision_context(tmp_path)
    assert view["bounds"]["degraded"] is True
    assert view["bounds"]["omitted"] == {}
    assert view["bounds"]["compacted"]
    assert view["goals"][0]["assessment_state"] == "not_assessed"
    assert view["goals"][0]["details_omitted"] is True
    assert view["read"]["gate"]["kind"] == "gate"
    assert view["bounds"]["used_bytes"] <= 16000


def test_small_snapshot_keeps_complete_scientific_fields(tmp_path):
    workspace(tmp_path)
    view = decision_context.build_decision_context(tmp_path)
    assert view["bounds"]["degraded"] is False
    assert view["nodes"][0]["objective"]
    assert "dependencies" in view["nodes"][0]
    assert view["goals"][0]["assessment_state"] == "not_assessed"
    assert "steps" in view["strategies"][0]
    assert "details_omitted" not in view["nodes"][0]
    assert encoded_size(view) == view["bounds"]["used_bytes"]
