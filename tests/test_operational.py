from __future__ import annotations

import json
from pathlib import Path

from ts_agent.workspace.operational import node_completion_blockers, operational_snapshot


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_operational_snapshot_separates_activities_reviews_and_controls(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {"schema_version": "ts-research-node-registry/1", "nodes": [{"node_id": "node_1"}]})
    activity = root / "nodes" / "node_1" / "activities" / "op_1"
    _write(
        activity / "request.json",
        {
            "schema_version": "ts-deterministic-activity-request/1",
            "activity_id": "op_1",
            "kind": "report",
            "operation": "build",
            "node_refs": ["node_1"],
            "request": {},
            "started_at": "2026-08-16T00:00:00+00:00",
        },
    )
    _write(
        activity / "status.json",
        {
            "schema_version": "ts-deterministic-activity-status/1",
            "activity_id": "op_1",
            "kind": "report",
            "operation": "build",
            "node_refs": ["node_1"],
            "status": "completed",
            "started_at": "2026-08-16T00:00:00+00:00",
            "completed_at": "2026-08-16T00:01:00+00:00",
            "error": None,
        },
    )
    _write(activity / "result.json", {"outcome": "success", "summary": "Submission completed."})

    review = root / "reviews" / "claim_1" / "runs" / "sub_1"
    _write(
        review / "task.json",
        {
            "task_id": "sub_1",
            "role": "review",
            "authority": "advisory",
            "operation": "claim_review",
            "scope": {"node_refs": ["node_1"], "claim_refs": ["claim_1"]},
        },
    )
    _write(
        review / "run.json",
        {
            "task_id": "sub_1",
            "status": "completed",
            "started_at": "2026-08-16T00:02:00+00:00",
            "finished_at": "2026-08-16T00:03:00+00:00",
            "error": None,
        },
    )
    _write(review / "result.json", {"outcome": "success", "summary": "Review completed."})

    attempt = root / "nodes" / "node_1" / "attempts" / "calc_1"
    _write(attempt / "submit_guard.json", {"operation": "submit"})
    _write(
        attempt / "submit_result.json",
        {
            "state": "unknown",
            "error_class": "submission_ambiguous",
            "job_id": None,
            "control": {"effect_outcome": "unknown", "retry_disposition": "reconcile_only"},
        },
    )

    report = operational_snapshot(root)

    assert report["deterministic_activities"][0]["node_refs"] == ["node_1"]
    assert report["deterministic_activities"][0]["summary"] == "Submission completed."
    assert report["agent_runs"][0]["claim_refs"] == ["claim_1"]
    assert report["pending_review_dispositions"][0]["node_refs"] == ["node_1"]
    assert report["unresolved_controls"][0]["node_id"] == "node_1"
    assert report["unresolved_controls"][0]["intent_id"] == "calc_1"
    assert report["pending_controls"] == []
    assert report["operational_summary"] == {
        "tracked_file_count": 8,
        "calculation_file_count": 2,
        "activity_count": 1,
        "activity_failed_count": 0,
        "activity_running_count": 0,
        "activity_pending_count": 0,
        "activity_integrity_error_count": 0,
        "agent_run_count": 1,
        "agent_run_failed_count": 0,
        "agent_run_pending_count": 0,
        "review_disposition_count": 0,
        "review_disposition_pending_count": 1,
        "control_pending_count": 0,
        "control_unresolved_count": 1,
        "ambiguous_submission_count": 1,
        "ambiguous_cancellation_count": 0,
        "control_retryable_count": 0,
    }


def test_operational_snapshot_ignores_unsupported_node_paths(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "nodes" / "n001" / "attempts" / "calc_old" / "submit_guard.json", {})
    _write(root / "nodes" / "n001" / "agent-runs" / "sub_old" / "task.json", {"role": "review"})
    _write(root / "nodes" / "node_1" / "agent-runs" / "sub_1" / "task.json", {"role": "review"})
    _write(root / "operations" / "agent-runs" / "sub_2" / "task.json", {"role": "review"})
    _write(root / "nodes" / "node_1" / "attempts" / "calc_old" / "submit_guard.json", {})
    _write(
        root / "reviews" / "claim_1" / "runs" / "sub_028def15-cbb5-42b4-bbfc-cfbd256c4a0b" / "task.json",
        {"task_id": "sub_028def15-cbb5-42b4-bbfc-cfbd256c4a0b", "role": "review", "authority": "advisory"},
    )
    _write(
        root / "nodes" / "node_1" / "attempts" / "calc_old" / "runs" / "sub_3" / "task.json",
        {
            "task_id": "sub_3",
            "role": "compute",
            "authority": "operational",
            "scope": {"node_refs": ["node_1"], "claim_refs": []},
            "inputs": {"intent_id": "calc_old"},
        },
    )

    report = operational_snapshot(root)

    assert report["deterministic_activities"] == []
    assert report["agent_runs"] == []
    assert report["pending_controls"] == []
    assert report["operational_summary"]["tracked_file_count"] == 0


def test_pending_compute_run_blocks_node_completion_without_duplicate_activity(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/1",
        "nodes": [{"node_id": "node_1"}],
    })
    run = root / "nodes" / "node_1" / "attempts" / "calc_1" / "runs" / "sub_1"
    _write(run / "task.json", {
        "task_id": "sub_1",
        "role": "compute",
        "authority": "operational",
        "operation": "launch",
        "scope": {"node_refs": ["node_1"], "claim_refs": []},
        "inputs": {"intent_id": "calc_1", "backend": "gaussian"},
    })

    pending = operational_snapshot(root)
    assert pending["deterministic_activities"] == []
    assert node_completion_blockers(pending, node_id="node_1", outcome="completed") == [{
        "code": "compute_run_not_terminal",
        "ref": "nodes/node_1/attempts/calc_1/runs/sub_1",
        "message": "Compute run is still pending: nodes/node_1/attempts/calc_1/runs/sub_1",
    }]

    _write(run / "run.json", {
        "task_id": "sub_1",
        "status": "failed",
        "error": {"code": "provider_failed", "message": "Provider failed."},
    })
    terminal = operational_snapshot(root)
    assert node_completion_blockers(terminal, node_id="node_1", outcome="inconclusive") == []


def test_retryable_pre_submit_failure_is_not_an_unresolved_control(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/1",
        "nodes": [{"node_id": "node_1"}, {"node_id": "node_2"}],
    })
    retryable = root / "nodes" / "node_1" / "attempts" / "calc_1"
    _write(retryable / "submit_guard.json", {"operation": "submit"})
    _write(retryable / "submit_result.json", {
        "state": "failed",
        "error_class": "remote_staging_failed",
        "job_id": None,
        "control": {
            "effect_outcome": "failed",
            "effect_attempted": False,
            "retry_disposition": "retry_same_submission",
            "reconciliation_required": False,
        },
    })
    ambiguous = root / "nodes" / "node_2" / "attempts" / "calc_2"
    _write(ambiguous / "submit_guard.json", {"operation": "submit"})
    _write(ambiguous / "submit_result.json", {
        "state": "unknown",
        "error_class": "submission_ambiguous",
        "job_id": None,
        "control": {
            "effect_outcome": "unknown",
            "effect_attempted": True,
            "retry_disposition": "reconcile_only",
            "reconciliation_required": True,
        },
    })

    snapshot = operational_snapshot(root)

    assert [row["intent_id"] for row in snapshot["retryable_controls"]] == ["calc_1"]
    assert snapshot["retryable_controls"][0]["classification"] == "retryable"
    assert [row["intent_id"] for row in snapshot["unresolved_controls"]] == ["calc_2"]
    assert snapshot["unresolved_controls"][0]["classification"] == "unresolved"
    assert snapshot["operational_summary"]["control_retryable_count"] == 1
    assert snapshot["operational_summary"]["control_unresolved_count"] == 1
    assert node_completion_blockers(snapshot, node_id="node_1", outcome="completed") == []
    assert node_completion_blockers(snapshot, node_id="node_2", outcome="completed")[0]["code"] == "unresolved_compute_control"


def test_incomplete_retry_receipt_fails_closed_as_unresolved(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/1",
        "nodes": [{"node_id": "node_1"}],
    })
    attempt = root / "nodes" / "node_1" / "attempts" / "calc_1"
    _write(attempt / "submit_guard.json", {"operation": "submit"})
    _write(attempt / "submit_result.json", {
        "state": "failed",
        "error_class": "remote_staging_failed",
        "job_id": None,
        "control": {
            "effect_outcome": "failed",
            "retry_disposition": "retry_same_submission",
        },
    })

    snapshot = operational_snapshot(root)

    assert snapshot["retryable_controls"] == []
    assert snapshot["unresolved_controls"][0]["intent_id"] == "calc_1"
    assert snapshot["unresolved_controls"][0]["classification"] == "unresolved"
