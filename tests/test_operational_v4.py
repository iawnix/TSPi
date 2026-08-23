from __future__ import annotations

import json
from pathlib import Path

from ts_workspace.operational import act_completion_blockers, operational_snapshot


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_v4_operational_snapshot_separates_activities_reviews_and_controls(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_acts.json", {"schema_version": "ts-research-act-registry/3", "acts": [{"act_id": "act_1"}]})
    activity = root / "acts" / "act_1" / "activities" / "op_1"
    _write(
        activity / "request.json",
        {
            "schema_version": "ts-deterministic-activity-request/1",
            "activity_id": "op_1",
            "kind": "report",
            "operation": "build",
            "act_refs": ["act_1"],
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
            "act_refs": ["act_1"],
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
            "scope": {"act_refs": ["act_1"], "claim_refs": ["claim_1"]},
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

    attempt = root / "acts" / "act_1" / "attempts" / "calc_1"
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

    assert report["deterministic_activities"][0]["act_refs"] == ["act_1"]
    assert report["deterministic_activities"][0]["summary"] == "Submission completed."
    assert report["agent_runs"][0]["claim_refs"] == ["claim_1"]
    assert report["pending_review_dispositions"][0]["act_refs"] == ["act_1"]
    assert report["unresolved_controls"][0]["act_id"] == "act_1"
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


def test_operational_snapshot_ignores_legacy_node_paths(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "nodes" / "n001" / "attempts" / "calc_old" / "submit_guard.json", {})
    _write(root / "nodes" / "n001" / "agent-runs" / "sub_old" / "task.json", {"role": "review"})
    _write(root / "acts" / "act_1" / "agent-runs" / "sub_1" / "task.json", {"role": "review"})
    _write(root / "operations" / "agent-runs" / "sub_2" / "task.json", {"role": "review"})
    _write(root / "acts" / "act_1" / "attempts" / "calc_old" / "submit_guard.json", {})
    _write(
        root / "reviews" / "claim_1" / "runs" / "sub_028def15-cbb5-42b4-bbfc-cfbd256c4a0b" / "task.json",
        {"task_id": "sub_028def15-cbb5-42b4-bbfc-cfbd256c4a0b", "role": "review", "authority": "advisory"},
    )
    _write(
        root / "acts" / "act_1" / "attempts" / "calc_old" / "runs" / "sub_3" / "task.json",
        {
            "task_id": "sub_3",
            "role": "compute",
            "authority": "operational",
            "scope": {"act_refs": ["act_1"], "claim_refs": []},
            "inputs": {"intent_id": "calc_old"},
        },
    )

    report = operational_snapshot(root)

    assert report["deterministic_activities"] == []
    assert report["agent_runs"] == []
    assert report["pending_controls"] == []
    assert report["operational_summary"]["tracked_file_count"] == 0


def test_pending_compute_run_blocks_act_completion_without_duplicate_activity(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_acts.json", {
        "schema_version": "ts-research-act-registry/3",
        "acts": [{"act_id": "act_1"}],
    })
    run = root / "acts" / "act_1" / "attempts" / "calc_1" / "runs" / "sub_1"
    _write(run / "task.json", {
        "task_id": "sub_1",
        "role": "compute",
        "authority": "operational",
        "operation": "launch",
        "scope": {"act_refs": ["act_1"], "claim_refs": []},
        "inputs": {"intent_id": "calc_1", "backend": "gaussian"},
    })

    pending = operational_snapshot(root)
    assert pending["deterministic_activities"] == []
    assert act_completion_blockers(pending, act_id="act_1", outcome="completed") == [{
        "code": "compute_run_not_terminal",
        "ref": "acts/act_1/attempts/calc_1/runs/sub_1",
        "message": "Compute run is still pending: acts/act_1/attempts/calc_1/runs/sub_1",
    }]

    _write(run / "run.json", {
        "task_id": "sub_1",
        "status": "failed",
        "error": {"code": "provider_failed", "message": "Provider failed."},
    })
    terminal = operational_snapshot(root)
    assert act_completion_blockers(terminal, act_id="act_1", outcome="inconclusive") == []
