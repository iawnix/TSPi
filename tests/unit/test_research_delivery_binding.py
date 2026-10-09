"""Delivery labels, scope and retries follow authoritative research state."""
import json
import sys
import time

import pytest

from notify_lib import delivery
from research_state.agent_workspace import checkpoint, read_context
from research_state.delivery import delivery_snapshot
from tspi_runtime.execution import dispatch
from tests.unit.test_job_recovery import workspace
from tests.unit.test_reliability_contract import change
from tests.unit.test_research_requirements import assess, requirement
from tspi_runtime.evidence import dispatch as artifact


def delivery_node(root, *, dependencies=None, consumes=None):
    change(root, [{"type": "create_node", "id": "node_delivery", "title": "Notify", "objective": "Report the consumed work",
                   "claim_ids": ["claim_1"], "dependencies": dependencies if dependencies is not None else [{"node_id": "node_1", "condition": "finished"}],
                   **({"consumes": consumes} if consumes is not None else {})}])


def email_request(root, monkeypatch, event, *, notification_id="notification-1"):
    config = delivery.EmailNotificationConfig(source=root / "notifications.toml", enabled=True,
        recipient="reader@example.test", digest="fixture-config", provider="smtp", from_address="sender@example.test")
    monkeypatch.setattr(delivery, "load_notification_config", lambda *args: config)
    value = {"schema_version": "ts-user-notification/2", "notification_id": notification_id,
             "recipient": config.recipient, "node_id": "node_delivery", "event": event,
             "subject": "Research update", "summary": "Report the recorded state", "report_refs": [], "attachments": [],
             "state_binding": delivery_snapshot(read_context(root), "node_delivery", event, root=root)}
    path = root / (notification_id + ".json")
    path.write_text(json.dumps(value))
    return path, value


def failed_calculation(root):
    job = dispatch("start", {"root": str(root), "node_id": "node_1", "request_id": "failed-calculation",
                              "command": [sys.executable, "-c", "raise SystemExit(23)"]})
    try:
        for _ in range(200):
            if dispatch("status", {"root": str(root), "job_id": job["job_id"]})["state"] == "failed":
                break
            time.sleep(.01)
        result = dispatch("collect", {"root": str(root), "job_id": job["job_id"]})
        assert result["status"]["state"] == "failed"
        return result["result_receipt"]
    finally:
        dispatch("cancel", {"root": str(root), "job_id": job["job_id"]})


def test_events_require_matching_consumed_state_and_tracked_study_scope(tmp_path):
    workspace(tmp_path)
    delivery_node(tmp_path)
    for event in ("node_completed", "calculation_failed", "calculation_ambiguous"):
        with pytest.raises(ValueError, match="delivery_event_mismatch"):
            delivery_snapshot(read_context(tmp_path), "node_delivery", event)
    with pytest.raises(ValueError, match="delivery_requirements_untracked"):
        delivery_snapshot(read_context(tmp_path), "node_delivery", "study_completed")
    change(tmp_path, [{"type": "set_node_state", "node_id": "node_1", "state": "closed", "outcome": "inconclusive"}])
    snapshot = delivery_snapshot(read_context(tmp_path), "node_delivery", "progress")
    assert snapshot["snapshot"]["dependencies"][0]["satisfied"] is True
    with pytest.raises(ValueError, match="delivery_event_mismatch"):
        delivery_snapshot(read_context(tmp_path), "node_delivery", "node_completed")


def test_finished_dependency_can_report_actual_failure_and_retry_does_not_send_again(tmp_path, monkeypatch):
    workspace(tmp_path)
    requirement(tmp_path, {"id": "research.material", "version": "1"}, constraints={})
    delivery_node(tmp_path, consumes={"requirement_ids": ["requirement_path"], "condition": "observed"})
    result = failed_calculation(tmp_path)
    change(tmp_path, [{"type": "record_requirement_stop", "id": "stop_failed", "requirement_id": "requirement_path",
                      "category": "execution_failed", "result_receipt_refs": [result["receipt_id"]],
                      "reason": "The attempted work failed; retain its unmet deliverable"},
                     {"type": "set_node_state", "node_id": "node_1", "state": "closed", "outcome": "stopped"}])
    request, prepared = email_request(tmp_path, monkeypatch, "calculation_failed")
    calls = []
    monkeypatch.setattr(delivery, "_run_transport", lambda *args, **kwargs: calls.append(kwargs) or "accepted")
    sent = delivery.notify_user(tmp_path, request)
    assert sent["state"] == "sent"
    basis = json.loads((tmp_path / sent["receipt_ref"]).read_text())["state_binding"]
    assert basis == prepared["state_binding"]
    assert basis["snapshot"]["requirements"][0]["satisfied"] is False
    assert basis["snapshot"]["attempts"][0]["state"] == "failed"
    change(tmp_path, [{"type": "set_node_state", "node_id": "node_delivery", "state": "closed", "outcome": "completed"}])
    checkpoint(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "checkpoint": {"id": "failed_run_final", "disposition": "terminal", "reason": "The failure was reported; the unmet requirement remains recorded"}})
    assert delivery.notify_user(tmp_path, request)["state"] == "already_sent"
    assert len(calls) == 1
    assert len(read_context(tmp_path)["attempts"]) == 1


def test_unrelated_failed_attempt_cannot_authorize_a_failure_label(tmp_path):
    workspace(tmp_path)
    change(tmp_path, [{"type": "create_node", "id": "node_other", "title": "Other scope", "objective": "Independent work",
                       "claim_ids": ["claim_1"], },
                      {"type": "set_node_state", "node_id": "node_other", "state": "closed", "outcome": "inconclusive"}])
    delivery_node(tmp_path, dependencies=[{"node_id": "node_other", "condition": "finished"}])
    failed_calculation(tmp_path)
    with pytest.raises(ValueError, match="delivery_event_mismatch.*no consumed calculation"):
        delivery_snapshot(read_context(tmp_path), "node_delivery", "calculation_failed")


def test_finished_dependency_never_bypasses_global_blocked_state(tmp_path, monkeypatch):
    workspace(tmp_path)
    delivery_node(tmp_path)
    change(tmp_path, [{"type": "set_node_state", "node_id": "node_1", "state": "closed", "outcome": "inconclusive"}])
    request, _ = email_request(tmp_path, monkeypatch, "progress")
    calls = []
    monkeypatch.setattr(delivery, "_run_transport", lambda *args, **kwargs: calls.append(1) or "accepted")
    checkpoint(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "checkpoint": {"id": "blocked_run", "disposition": "blocked", "reason": "Wait for explicit recovery"}})
    with pytest.raises(ValueError, match="research_lifecycle_blocked"):
        delivery.notify_user(tmp_path, request)
    assert calls == []


def test_study_success_preparation_expires_when_requirement_scope_changes(tmp_path, monkeypatch):
    workspace(tmp_path)
    requirement(tmp_path, {"id": "research.material", "version": "1"}, constraints={})
    material = artifact("create", {"root": str(tmp_path), "content": "Supplied literature"})
    assert assess(tmp_path, evidence_refs=[material["artifact_id"]])["satisfied"]
    delivery_node(tmp_path, consumes={"requirement_ids": ["requirement_path"]})
    change(tmp_path, [{"type": "set_node_state", "node_id": "node_1", "state": "closed", "outcome": "completed"}])
    request, prepared = email_request(tmp_path, monkeypatch, "study_completed")
    assert prepared["state_binding"]["snapshot"]["study_requirements"]["satisfied"]
    additional = artifact("create", {"root": str(tmp_path), "content": "New material expands the required scope"})
    change(tmp_path, [{"type": "bind_requirement", "requirement_id": "requirement_path",
                      "input_artifact_ids": [additional["artifact_id"]], "reason": "Include newly supplied material"}])
    calls = []
    monkeypatch.setattr(delivery, "_run_transport", lambda *args, **kwargs: calls.append(1) or "accepted")
    with pytest.raises(ValueError, match="delivery_requirements_unmet"):
        delivery.notify_user(tmp_path, request)
    assert calls == []


def test_observed_requirement_pins_source_node_state_without_dependency_edge(tmp_path, monkeypatch):
    workspace(tmp_path)
    requirement(tmp_path, {"id": "research.material", "version": "1"}, constraints={})
    delivery_node(tmp_path, dependencies=[], consumes={"requirement_ids": ["requirement_path"], "condition": "observed"})
    request, prepared = email_request(tmp_path, monkeypatch, "progress")
    assert prepared["state_binding"]["snapshot"]["source_nodes"][0]["state"] == "planned"
    change(tmp_path, [{"type": "set_node_state", "node_id": "node_1", "state": "closed", "outcome": "inconclusive"}])
    calls = []
    monkeypatch.setattr(delivery, "_run_transport", lambda *args, **kwargs: calls.append(1) or "accepted")
    with pytest.raises(ValueError, match="delivery_state_changed"):
        delivery.notify_user(tmp_path, request)
    assert calls == []


def test_consumed_artifact_uses_its_producer_and_current_collected_version(tmp_path):
    workspace(tmp_path)
    job = dispatch("start", {"root": str(tmp_path), "node_id": "node_1", "request_id": "successful-artifact",
                              "command": [sys.executable, "-c", "from pathlib import Path;Path('result.txt').write_text('version 1')"],
                              "outputs": [{"path": "result.txt", "required": True}]})
    try:
        for _ in range(200):
            if dispatch("status", {"root": str(tmp_path), "job_id": job["job_id"]})["state"] == "succeeded":
                break
            time.sleep(.01)
        result = dispatch("collect", {"root": str(tmp_path), "job_id": job["job_id"]})
        from pathlib import Path
        output_ref = next(row["artifact_id"] for row in result["artifacts"]
                          if row["provenance"]["source_path"].endswith("/result.txt"))
        delivery_node(tmp_path, dependencies=[], consumes={"artifact_refs": [output_ref], "condition": "observed"})
        failed_calculation(tmp_path)
        # Another Attempt failed in the same Node, but the explicit material
        # selection names only the successful producer.
        with pytest.raises(ValueError, match="delivery_event_mismatch.*no consumed calculation"):
            delivery_snapshot(read_context(tmp_path), "node_delivery", "calculation_failed", root=tmp_path)
        original = delivery_snapshot(read_context(tmp_path), "node_delivery", "progress", root=tmp_path)
        assert [row["id"] for row in original["snapshot"]["attempts"]] == [job["attempt_id"]]
        (Path(job["cwd"]) / "result.txt").write_text("version 2")
        dispatch("collect", {"root": str(tmp_path), "job_id": job["job_id"]})
        # Re-preparing the old Artifact must not bless it using the producer's
        # latest receipt; the caller must select current collected material.
        with pytest.raises(ValueError, match="assessment_result_stale"):
            delivery_snapshot(read_context(tmp_path), "node_delivery", "progress", root=tmp_path)
    finally:
        dispatch("cancel", {"root": str(tmp_path), "job_id": job["job_id"]})
