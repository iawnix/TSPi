from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess

import pytest

from ts_agent.io import read_json, write_json

from tests.support.workspace_helpers import bootstrap_workspace_fixture
from ts_agent.workspace.monitor import (
    claim_delivery,
    complete_delivery,
    list_pending_deliveries,
    register_monitor,
    read_event,
    tick_monitors,
    monitor_status,
    stage_registration,
    reconcile_registrations,
    set_monitor_enabled,
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
    assert claim_delivery(root, event_id)["claimed"] is False
    completed = complete_delivery(root, event_id, delivered=True, claim_token=claimed["claim_token"])
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


def _registered(root: Path, **options):
    return register_monitor(root, node_id="node_1", intent_id="calc_1", intent_digest="sha256:" + "c" * 64,
                            session_id="session-1", **options)


def test_repeated_state_is_a_new_event_after_recovery(tmp_path, monkeypatch):
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    _registered(root)
    observed = {"state": "running"}
    monkeypatch.setattr("ts_agent.compute.control.calculation_status", lambda *args: dict(observed))
    ids = []
    for state in ("running", "unknown", "running"):
        observed["state"] = state
        ids.append(tick_monitors(root)["monitors"][0]["event_id"])
    assert len(set(ids)) == 3
    assert [read_event(root, event_id)["sequence"] for event_id in ids] == [1, 2, 3]
    assert tick_monitors(root)["monitors"][0]["changed"] is False


def test_event_commit_recovers_missing_delivery_and_state(tmp_path, monkeypatch):
    import ts_agent.workspace.monitor as monitor
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    _registered(root)
    monkeypatch.setattr("ts_agent.compute.control.calculation_status", lambda *args: {"state": "queued"})
    original = monitor._ensure_event_delivery
    monkeypatch.setattr(monitor, "_ensure_event_delivery", lambda *args: (_ for _ in ()).throw(OSError("simulated crash")))
    with pytest.raises(OSError, match="simulated crash"):
        tick_monitors(root)
    monkeypatch.setattr(monitor, "_ensure_event_delivery", original)
    recovered = tick_monitors(root)
    assert recovered["monitors"][0]["changed"] is False
    assert len(list_pending_deliveries(root)) == 1
    assert monitor_status(root)["monitors"][0]["state"]["last_sequence"] == 1


def test_wake_and_notification_ack_retry_independently(tmp_path, monkeypatch):
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    _registered(root, notify_policy="user")
    monkeypatch.setattr("ts_agent.compute.control.calculation_status", lambda *args: {"state": "running"})
    event_id = tick_monitors(root)["monitors"][0]["event_id"]
    at = "2026-09-21T00:00:00+00:00"
    wake = claim_delivery(root, event_id, channel="wake", at=at)
    complete_delivery(root, event_id, channel="wake", claim_token=wake["claim_token"], delivered=True, at=at)
    notify = claim_delivery(root, event_id, channel="notify", at=at)
    failed = complete_delivery(root, event_id, channel="notify", claim_token=notify["claim_token"], delivered=False,
                               error="mail offline", at=at)
    assert failed["channels"]["wake"]["status"] == "delivered"
    assert failed["channels"]["notify"]["next_attempt_at"] == "2026-09-21T00:00:05+00:00"
    assert list_pending_deliveries(root, at=at) == []
    assert claim_delivery(root, event_id, channel="wake", at="2026-09-21T01:00:00+00:00")["claimed"] is False
    retry = claim_delivery(root, event_id, channel="notify", at="2026-09-21T00:00:05+00:00")
    assert retry["claimed"] is True
    done = complete_delivery(root, event_id, channel="notify", claim_token=retry["claim_token"], delivered=True)
    assert done["status"] == "delivered"


def test_claims_are_exclusive_and_stale_completion_cannot_overwrite(tmp_path, monkeypatch):
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    _registered(root)
    monkeypatch.setattr("ts_agent.compute.control.calculation_status", lambda *args: {"state": "running"})
    event_id = tick_monitors(root)["monitors"][0]["event_id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: claim_delivery(root, event_id, at="2026-09-21T00:00:00+00:00"), range(4)))
    assert sum(row["claimed"] for row in claims) == 1
    old = next(row for row in claims if row["claimed"])
    new = claim_delivery(root, event_id, at="2026-09-21T00:03:01+00:00")
    assert new["claimed"] is True
    with pytest.raises(ValueError, match="stale"):
        complete_delivery(root, event_id, delivered=True, claim_token=old["claim_token"])
    assert complete_delivery(root, event_id, delivered=True, claim_token=new["claim_token"])["status"] == "delivered"


def test_disable_stops_poll_and_delivery_and_unchanged_tick_updates_health(tmp_path, monkeypatch):
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    registered = _registered(root)
    calls = []
    monkeypatch.setattr("ts_agent.compute.control.calculation_status", lambda *args: calls.append(1) or {"state": "submitted"})
    tick_monitors(root, observed_at="2026-09-21T00:00:00+00:00")
    tick_monitors(root, observed_at="2026-09-21T00:01:00+00:00")
    state = monitor_status(root)["monitors"][0]["state"]
    assert state["last_observed_at"] == "2026-09-21T00:01:00+00:00"
    assert state["last_changed_at"] == "2026-09-21T00:00:00+00:00"
    set_monitor_enabled(root, registered["monitor_id"], False)
    assert _registered(root)["registration"]["enabled"] is False
    tick_monitors(root)
    assert len(calls) == 2
    assert list_pending_deliveries(root) == []
    set_monitor_enabled(root, registered["monitor_id"], True)
    assert len(list_pending_deliveries(root)) == 1


def test_staged_binding_is_recovered_after_submission_without_resubmit(tmp_path, monkeypatch):
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    binding = dict(node_id="node_1", intent_id="calc_1", intent_digest="sha256:" + "d" * 64, session_id="session-1")
    staged = stage_registration(root, **binding)
    monkeypatch.setattr("ts_agent.compute.control._load_prepared", lambda *args: (root, binding, {}))
    monkeypatch.setattr("ts_agent.compute.control._read_control_result", lambda *args: None)
    monkeypatch.setattr("ts_agent.compute.control._read_control_guard", lambda *args: None)
    assert reconcile_registrations(root)["registrations"] == []
    assert monitor_status(root)["monitors"] == []
    # A guard without a receipt represents an interrupted submission, never a
    # reason to submit again. Monitoring reconciles its unknown outcome.
    monkeypatch.setattr("ts_agent.compute.control._read_control_guard", lambda *args: {"attempt": 1})
    assert reconcile_registrations(root, force=True)["registrations"][0]["status"] == "registered"
    assert monitor_status(root)["monitors"][0]["monitor_id"] == staged["monitor_id"]
    assert monitor_status(root)["pending_registrations"] == []


def test_staged_registration_error_remains_visible_and_retries(tmp_path, monkeypatch):
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    binding = dict(node_id="node_1", intent_id="calc_1", intent_digest="sha256:" + "e" * 64, session_id="session-1")
    stage_registration(root, **binding)
    monkeypatch.setattr("ts_agent.compute.control._load_prepared", lambda *args: (_ for _ in ()).throw(OSError("receipt unavailable")))
    reconcile_registrations(root)
    assert monitor_status(root)["pending_registrations"][0]["last_error"] == "receipt unavailable"
    monkeypatch.setattr("ts_agent.compute.control._load_prepared", lambda *args: (root, binding, {}))
    monkeypatch.setattr("ts_agent.compute.control._read_control_result", lambda *args: {"state": "submitted"})
    monkeypatch.setattr("ts_agent.compute.control._read_control_guard", lambda *args: {"attempt": 1})
    assert reconcile_registrations(root, force=True)["registrations"][0]["status"] == "registered"


def test_monitor_records_match_contracts_and_old_completed_delivery_stays_completed(tmp_path, monkeypatch):
    from jsonschema import Draft202012Validator
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    registered = _registered(root, notify_policy="user")
    monkeypatch.setattr("ts_agent.compute.control.calculation_status", lambda *args: {"state": "queued"})
    event_id = tick_monitors(root)["monitors"][0]["event_id"]
    delivery = list_pending_deliveries(root)[0]
    schema_dir = Path(__file__).resolve().parents[2] / "contracts" / "tspi-monitor" / "1"
    for name, record in (("monitor", registered["registration"]), ("event", read_event(root, event_id)), ("delivery", delivery)):
        Draft202012Validator(read_json(schema_dir / f"{name}.schema.json")).validate(record)
    # Existing single-ack records upgrade on read without waking a completed
    # event again. Unacknowledged legacy deliveries remain retryable.
    del delivery["channels"]
    delivery["status"] = "delivered"
    delivery["delivered_at"] = "2026-09-21T00:00:00+00:00"
    path = root / "operations" / "monitors" / registered["monitor_id"] / "deliveries" / f"{event_id}.json"
    write_json(path, delivery)
    assert claim_delivery(root, event_id, channel="wake")["claimed"] is False
    assert claim_delivery(root, event_id, channel="notify")["claimed"] is False


def test_bootstrapped_monitor_uses_host_directory_route_without_changing_canonical_identity(tmp_path, monkeypatch):
    root = bootstrap_workspace_fixture(tmp_path / "ts_001")
    canonical_id = read_json(root / "workspace.json")["workspace_id"]
    assert canonical_id.startswith("ws_") and canonical_id != root.name
    _registered(root)
    monkeypatch.setattr("ts_agent.compute.control.calculation_status", lambda *args: {"state": "running"})
    event_id = tick_monitors(root)["monitors"][0]["event_id"]
    event = read_event(root, event_id)
    delivery = list_pending_deliveries(root)[0]
    worker = Path(__file__).resolve().parents[2] / "apps" / "app-server" / "pi-monitor-worker.mjs"
    script = (
        f"import {{ deliverMonitorEvent }} from {json.dumps(worker.as_uri())};\n"
        f"const workspace = {json.dumps(str(root))};\n"
        f"const event = {json.dumps(event)};\n"
        f"const delivery = {json.dumps(delivery)};\n"
        """
async function attempt(value) {
  const wakes = [];
  const errors = await deliverMonitorEvent({ workspace, delivery,
    async runJson(command, root, args) {
      if (command === 'event') return value;
      if (command === 'complete') return {};
      return {...delivery, claimed: args[args.indexOf('--channel') + 1] === 'wake', claim_token: 'regression-claim'};
    },
    async sendWake(params) { wakes.push(params); return { accepted: true }; },
    async sendNotification() { throw new Error('notification is disabled'); },
  });
  return { wakes, errors };
}
const valid = await attempt(event);
const foreign = await attempt({...event, workspace_id: 'ws_' + '0'.repeat(24)});
process.stdout.write(JSON.stringify({valid, foreign, canonical: event.workspace_id}));
"""
    )
    completed = subprocess.run(["node", "--input-type=module", "-e", script], check=True, capture_output=True, text=True)
    result = json.loads(completed.stdout)
    assert result["valid"]["errors"] == []
    assert result["valid"]["wakes"][0]["workspace_id"] == "ts_001"
    assert result["valid"]["wakes"][0]["session_id"] == "session-1"
    assert result["foreign"]["wakes"] == []
    assert result["foreign"]["errors"] == ["wake: monitor event belongs to another workspace"]
    assert result["canonical"] == canonical_id
    assert read_event(root, event_id)["workspace_id"] == canonical_id
    assert monitor_status(root)["workspace_id"] == canonical_id
