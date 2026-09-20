from __future__ import annotations

from pathlib import Path

from tests.support.workspace_helpers import bootstrap_workspace_fixture
from ts_agent.workspace.monitor import (
    claim_delivery,
    complete_delivery,
    list_pending_deliveries,
    register_monitor,
    read_event,
    tick_monitors,
)
from ts_agent.workspace.operational import runtime_status


def test_monitor_ticks_state_changes_once_and_persists_delivery(tmp_path: Path, monkeypatch) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    digest = "sha256:" + "a" * 64
    registered = register_monitor(
        root,
        node_id="node_1",
        intent_id="calc_1",
        intent_digest=digest,
        session_id="session-1",
    )

    observed = {"state": "running", "program_status": "not_run", "job_id": "job-1"}
    monkeypatch.setattr("ts_agent.compute.control.calculation_status", lambda *args: dict(observed))

    first = tick_monitors(root, observed_at="2026-09-20T00:00:00+00:00")
    row = first["monitors"][0]
    assert row["changed"] is True
    assert row["state"] == "running"
    event_id = row["event_id"]
    assert event_id
    assert len(list_pending_deliveries(root)) == 1

    second = tick_monitors(root, observed_at="2026-09-20T00:00:05+00:00")
    assert second["monitors"][0]["changed"] is False
    assert second["monitors"][0]["event_id"] == event_id
    assert len(list_pending_deliveries(root)) == 1

    claimed = claim_delivery(root, event_id)
    assert claimed["status"] == "delivering"
    assert claimed["request_id"] == f"monitor:{event_id}"
    assert claim_delivery(root, event_id)["status"] == "delivering"
    completed = complete_delivery(root, event_id, delivered=True)
    assert completed["status"] == "delivered"
    assert list_pending_deliveries(root) == []
    assert read_event(root, event_id)["state"] == "running"

    observed.update(state="completed", program_status="completed")
    third = tick_monitors(root, observed_at="2026-09-20T00:00:10+00:00")
    assert third["monitors"][0]["previous_state"] == "running"
    assert third["monitors"][0]["state"] == "completed"
    assert third["monitors"][0]["changed"] is True

    same = register_monitor(
        root,
        node_id="node_1",
        intent_id="calc_1",
        intent_digest=digest,
        session_id="session-1",
    )
    assert same["monitor_id"] == registered["monitor_id"]
    assert same["registration"]["created_at"] == registered["registration"]["created_at"]


def test_monitor_keeps_unknown_and_distinguishes_parsed(tmp_path: Path, monkeypatch) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    register_monitor(
        root,
        node_id="node_1",
        intent_id="calc_1",
        intent_digest="sha256:" + "b" * 64,
    )
    monkeypatch.setattr(
        "ts_agent.compute.control.calculation_status",
        lambda *args: {"state": "unknown", "program_status": "not_run", "error_class": "local_process_unknown"},
    )
    unknown = tick_monitors(root)
    assert unknown["monitors"][0]["state"] == "unknown"
    assert read_event(root, unknown["monitors"][0]["event_id"])["state"] == "unknown"

    monkeypatch.setattr(
        "ts_agent.compute.control.calculation_status",
        lambda *args: {"state": "completed", "program_status": "completed"},
    )
    monkeypatch.setattr(
        "ts_agent.workspace.monitor._attempt_rows",
        lambda *args: [{"intent_id": "calc_1", "state": "parsed"}],
    )
    parsed = tick_monitors(root)
    assert parsed["monitors"][0]["state"] == "parsed"
    assert read_event(root, parsed["monitors"][0]["event_id"])["state"] == "parsed"
    assert runtime_status(root)["runtime_summary"]["tracked_file_count"] == 6
