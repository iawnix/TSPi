from __future__ import annotations

import json
from pathlib import Path

from tests.support.workspace_helpers import (
    calculation_intent_fixture,
    calculation_prepared_fixture,
    calculation_result_fixture,
    start_research_node,
)
from ts_agent.workspace.operational import node_completion_blockers, operational_snapshot
from ts_agent.workspace.engine import init_workspace


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_operational_snapshot_separates_activities_reviews_and_controls(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    start_research_node(root)
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
        "paused_node_count": 0,
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
        "calculation_attempt_count": 0,
        "calculation_attempt_blocking_count": 0,
        "calculation_attempt_integrity_error_count": 0,
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
        "schema_version": "ts-research-node-registry/2",
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
        "schema_version": "ts-research-node-registry/2",
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
        "schema_version": "ts-research-node-registry/2",
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


def test_nonterminal_calculation_attempt_blocks_node_completion(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/2",
        "nodes": [{"node_id": "node_1"}],
    })
    attempt = root / "nodes" / "node_1" / "attempts" / "calc_1"
    intent = calculation_intent_fixture("node_1", "calc_1")
    _write(attempt / "intent.json", intent)
    _write(attempt / "prepared.json", calculation_prepared_fixture(intent))
    _write(
        attempt / "status.json",
        calculation_result_fixture(
            intent,
            state="queued",
            program_status="not_run",
            job_id="208319.cluster.hpc",
        ),
    )

    snapshot = operational_snapshot(root)

    assert snapshot["calculation_attempts"] == [{
        "node_id": "node_1",
        "intent_id": "calc_1",
        "path": "nodes/node_1/attempts/calc_1",
        "state": "queued",
        "program_status": "not_run",
        "job_id": "208319.cluster.hpc",
        "terminal": False,
        "blocks_completion": True,
        "integrity_error": None,
    }]
    assert node_completion_blockers(snapshot, node_id="node_1", outcome="inconclusive") == [{
        "code": "calculation_attempt_not_terminal",
        "ref": "nodes/node_1/attempts/calc_1",
        "message": "calculation Attempt is still queued: nodes/node_1/attempts/calc_1",
    }]


def test_parsed_calculation_attempt_releases_node_completion_guard(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/2",
        "nodes": [{"node_id": "node_1"}],
    })
    attempt = root / "nodes" / "node_1" / "attempts" / "calc_1"
    intent = calculation_intent_fixture("node_1", "calc_1")
    _write(attempt / "intent.json", intent)
    _write(attempt / "prepared.json", calculation_prepared_fixture(intent))
    _write(
        attempt / "outputs" / "calculation_result.json",
        calculation_result_fixture(
            intent,
            state="parsed",
            program_status="completed",
            job_id="208319.cluster.hpc",
        ),
    )

    snapshot = operational_snapshot(root)

    assert snapshot["calculation_attempts"][0]["terminal"] is True
    assert snapshot["calculation_attempts"][0]["blocks_completion"] is False
    assert node_completion_blockers(snapshot, node_id="node_1", outcome="completed") == []


def test_executed_calculation_attempt_without_prepared_binding_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/2",
        "nodes": [{"node_id": "node_1"}],
    })
    attempt = root / "nodes" / "node_1" / "attempts" / "calc_1"
    intent = calculation_intent_fixture("node_1", "calc_1")
    _write(attempt / "intent.json", intent)
    _write(
        attempt / "outputs" / "calculation_result.json",
        calculation_result_fixture(
            intent,
            state="parsed",
            program_status="completed",
            job_id="208319.cluster.hpc",
        ),
    )

    snapshot = operational_snapshot(root)

    row = snapshot["calculation_attempts"][0]
    assert row["terminal"] is False
    assert row["blocks_completion"] is True
    assert row["integrity_error"] == "prepared.json is missing for an executed Attempt"
    assert node_completion_blockers(snapshot, node_id="node_1", outcome="completed")[0] == {
        "code": "calculation_attempt_invalid",
        "ref": "nodes/node_1/attempts/calc_1",
        "message": "calculation Attempt status is invalid: nodes/node_1/attempts/calc_1",
    }


def test_prepared_attempt_without_external_effect_does_not_block_completion(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/2",
        "nodes": [{"node_id": "node_1"}],
    })
    attempt = root / "nodes" / "node_1" / "attempts" / "calc_1"
    _write(attempt / "intent.json", calculation_intent_fixture("node_1", "calc_1"))

    snapshot = operational_snapshot(root)

    assert snapshot["calculation_attempts"][0]["state"] == "prepared"
    assert snapshot["calculation_attempts"][0]["terminal"] is False
    assert snapshot["calculation_attempts"][0]["blocks_completion"] is False
    assert node_completion_blockers(snapshot, node_id="node_1", outcome="inconclusive") == []


def test_empty_calculation_attempt_directory_is_visible_and_blocks_completion(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/2",
        "nodes": [{"node_id": "node_1"}],
    })
    (root / "nodes" / "node_1" / "attempts" / "calc_1").mkdir(parents=True)

    snapshot = operational_snapshot(root)

    assert snapshot["calculation_attempts"] == [{
        "node_id": "node_1",
        "intent_id": "calc_1",
        "path": "nodes/node_1/attempts/calc_1",
        "state": "unknown",
        "program_status": "not_run",
        "job_id": None,
        "terminal": False,
        "blocks_completion": True,
        "integrity_error": "intent.json is missing",
    }]
    assert node_completion_blockers(
        snapshot,
        node_id="node_1",
        outcome="inconclusive",
    )[0]["code"] == "calculation_attempt_invalid"


def test_calculation_attempt_intent_uses_authoritative_compute_contract(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/2",
        "nodes": [{"node_id": "node_1"}],
    })
    attempt = root / "nodes" / "node_1" / "attempts" / "calc_1"
    intent = calculation_intent_fixture("node_1", "calc_1")
    intent["retired_field"] = "must be rejected"
    _write(attempt / "intent.json", intent)

    snapshot = operational_snapshot(root)

    row = snapshot["calculation_attempts"][0]
    assert row["blocks_completion"] is True
    assert "calculation_intent.schema.json validation failed" in row["integrity_error"]


def test_malformed_calculation_attempt_status_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/2",
        "nodes": [{"node_id": "node_1"}],
    })
    attempt = root / "nodes" / "node_1" / "attempts" / "calc_1"
    _write(attempt / "intent.json", calculation_intent_fixture("node_1", "calc_1"))
    (attempt / "status.json").parent.mkdir(parents=True, exist_ok=True)
    (attempt / "status.json").write_text("not-json", encoding="utf-8")

    snapshot = operational_snapshot(root)

    row = snapshot["calculation_attempts"][0]
    assert row["terminal"] is False
    assert row["integrity_error"]
    assert node_completion_blockers(snapshot, node_id="node_1", outcome="inconclusive")[0]["code"] == "calculation_attempt_invalid"


def test_incomplete_terminal_result_cannot_release_completion_guard(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/2",
        "nodes": [{"node_id": "node_1"}],
    })
    attempt = root / "nodes" / "node_1" / "attempts" / "calc_1"
    _write(attempt / "intent.json", calculation_intent_fixture("node_1", "calc_1"))
    _write(attempt / "outputs" / "calculation_result.json", {
        "schema_version": "ts-calculation-result/2",
        "intent_id": "calc_1",
        "node_id": "node_1",
        "state": "parsed",
        "program_status": "completed",
    })

    snapshot = operational_snapshot(root)

    row = snapshot["calculation_attempts"][0]
    assert row["state"] == "parsed"
    assert row["terminal"] is False
    assert row["blocks_completion"] is True
    assert "attempt_result_projection.schema.json validation failed" in row["integrity_error"]


def test_invalid_prepared_binding_blocks_node_completion(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/2",
        "nodes": [{"node_id": "node_1"}],
    })
    attempt = root / "nodes" / "node_1" / "attempts" / "calc_1"
    _write(attempt / "intent.json", calculation_intent_fixture("node_1", "calc_1"))
    _write(attempt / "prepared.json", {
        "schema_version": "ts-compute-prepared/1",
        "intent_id": "calc_1",
        "node_id": "node_1",
        "intent_ref": "nodes/node_1/attempts/calc_1/intent.json",
        "intent_digest": "sha256:" + "0" * 64,
        "prepared_task": {},
        "execution_policy": {"kind": "local"},
    })

    snapshot = operational_snapshot(root)

    assert "intent_digest does not match" in snapshot["calculation_attempts"][0]["integrity_error"]
    assert node_completion_blockers(
        snapshot,
        node_id="node_1",
        outcome="inconclusive",
    )[0]["code"] == "calculation_attempt_invalid"


def test_symlinked_attempt_directory_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/2",
        "nodes": [{"node_id": "node_1"}],
    })
    target = tmp_path / "outside-attempt"
    _write(target / "intent.json", calculation_intent_fixture("node_1", "calc_1"))
    attempt = root / "nodes" / "node_1" / "attempts" / "calc_1"
    attempt.parent.mkdir(parents=True, exist_ok=True)
    attempt.symlink_to(target, target_is_directory=True)

    snapshot = operational_snapshot(root)

    assert snapshot["calculation_attempts"][0]["integrity_error"] == (
        "Attempt path must be a physical directory"
    )
    assert snapshot["operational_summary"]["calculation_attempt_integrity_error_count"] == 1


def test_symlinked_attempt_parent_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/2",
        "nodes": [{"node_id": "node_1"}],
    })
    outside_attempts = tmp_path / "outside-attempts"
    intent = calculation_intent_fixture("node_1", "calc_1")
    _write(outside_attempts / "calc_1" / "intent.json", intent)
    attempts = root / "nodes" / "node_1" / "attempts"
    attempts.parent.mkdir(parents=True, exist_ok=True)
    attempts.symlink_to(outside_attempts, target_is_directory=True)

    snapshot = operational_snapshot(root)

    assert snapshot["calculation_attempts"][0]["integrity_error"] == (
        "Attempt parent path contains a symbolic-link component"
    )
    # The parent diagnostic is not a synthetic calc entity in the public
    # Attempt count, but it remains visible through the dedicated stream.
    assert snapshot["calculation_attempts"][0]["intent_id"] is None
    assert snapshot["operational_summary"]["calculation_attempt_count"] == 0
    assert snapshot["calculation_attempt_integrity_findings"] == [{
        "code": "calculation_attempt_integrity",
        "scope": "attempt_parent",
        "path": "nodes/node_1/attempts",
        "node_refs": ["node_1"],
        "message": "Attempt parent path contains a symbolic-link component",
    }]
    assert node_completion_blockers(
        snapshot,
        node_id="node_1",
        outcome="inconclusive",
    )[0]["code"] == "calculation_attempt_invalid"


def test_symlinked_attempt_output_is_not_read_as_workspace_state(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/2",
        "nodes": [{"node_id": "node_1"}],
    })
    attempt = root / "nodes" / "node_1" / "attempts" / "calc_1"
    intent = calculation_intent_fixture("node_1", "calc_1")
    _write(attempt / "intent.json", intent)
    _write(attempt / "prepared.json", calculation_prepared_fixture(intent))
    outside_outputs = tmp_path / "outside-outputs"
    _write(
        outside_outputs / "calculation_result.json",
        calculation_result_fixture(
            intent,
            state="parsed",
            program_status="completed",
            job_id="outside.job",
        ),
    )
    (attempt / "outputs").symlink_to(outside_outputs, target_is_directory=True)

    snapshot = operational_snapshot(root)

    row = snapshot["calculation_attempts"][0]
    assert row["state"] == "unknown"
    assert row["blocks_completion"] is True
    assert row["integrity_error"] == "symbolic link is not allowed"


def test_agent_run_index_does_not_read_run_through_symlinked_attempt_parent(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/2",
        "nodes": [{"node_id": "node_1"}],
    })
    outside = tmp_path / "outside-attempts" / "calc_1" / "runs" / "sub_1"
    _write(
        outside / "task.json",
        {
            "task_id": "sub_1",
            "role": "compute",
            "authority": "operational",
            "scope": {"node_refs": ["node_1"], "claim_refs": []},
            "inputs": {"intent_id": "calc_1"},
        },
    )
    attempts = root / "nodes" / "node_1" / "attempts"
    attempts.parent.mkdir(parents=True, exist_ok=True)
    attempts.symlink_to(tmp_path / "outside-attempts", target_is_directory=True)

    snapshot = operational_snapshot(root)

    assert snapshot["agent_runs"] == []
    assert snapshot["calculation_attempts"][0]["intent_id"] is None
    assert snapshot["calculation_attempt_integrity_findings"][0]["scope"] == "attempt_parent"


def test_agent_run_index_reports_symlinked_review_runs_parent(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/2",
        "nodes": [{"node_id": "node_1"}],
    })
    outside = tmp_path / "outside-review-runs"
    _write(
        outside / "sub_1" / "task.json",
        {
            "task_id": "sub_1",
            "role": "review",
            "authority": "advisory",
            "scope": {"node_refs": ["node_1"], "claim_refs": ["claim_1"]},
        },
    )
    runs = root / "reviews" / "claim_1" / "runs"
    runs.parent.mkdir(parents=True, exist_ok=True)
    runs.symlink_to(outside, target_is_directory=True)

    snapshot = operational_snapshot(root)

    assert snapshot["agent_runs"] == []
    assert {
        finding["path"] for finding in snapshot["operational_integrity_findings"]
    } >= {"reviews/claim_1/runs"}


def test_unresolved_control_suppresses_duplicate_attempt_state_blocker(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/2",
        "nodes": [{"node_id": "node_1"}],
    })
    attempt = root / "nodes" / "node_1" / "attempts" / "calc_1"
    intent = calculation_intent_fixture("node_1", "calc_1")
    _write(attempt / "intent.json", intent)
    _write(attempt / "prepared.json", calculation_prepared_fixture(intent))
    _write(
        attempt / "status.json",
        calculation_result_fixture(
            intent,
            state="unknown",
            program_status="not_run",
        ),
    )
    _write(attempt / "submit_guard.json", {"operation": "submit"})
    _write(attempt / "submit_result.json", {
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

    blockers = node_completion_blockers(
        operational_snapshot(root),
        node_id="node_1",
        outcome="blocked",
    )

    assert [item["code"] for item in blockers] == ["unresolved_compute_control"]


def test_symlinked_control_result_is_visible_and_blocks_node_completion(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/2",
        "nodes": [{"node_id": "node_1"}],
    })
    attempt = root / "nodes" / "node_1" / "attempts" / "calc_1"
    intent = calculation_intent_fixture("node_1", "calc_1")
    _write(attempt / "intent.json", intent)
    _write(attempt / "prepared.json", calculation_prepared_fixture(intent))
    outside = tmp_path / "outside-result.json"
    outside.write_text(json.dumps({"state": "submitted"}), encoding="utf-8")
    (attempt / "submit_result.json").symlink_to(outside)

    snapshot = operational_snapshot(root)

    assert snapshot["unresolved_controls"] == []
    assert snapshot["operational_integrity_findings"] == [{
        "code": "operational_path_integrity",
        "path": "nodes/node_1/attempts/calc_1/submit_result.json",
        "node_refs": ["node_1"],
        "message": "operational path contains a symbolic-link component",
    }]
    assert node_completion_blockers(
        snapshot,
        node_id="node_1",
        outcome="completed",
    )[0]["code"] == "operational_integrity_error"


def test_malformed_control_result_is_not_treated_as_absent(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write(root / "research_nodes.json", {
        "schema_version": "ts-research-node-registry/2",
        "nodes": [{"node_id": "node_1"}],
    })
    result = root / "nodes" / "node_1" / "attempts" / "calc_1" / "submit_result.json"
    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_text("not-json", encoding="utf-8")

    snapshot = operational_snapshot(root)

    assert snapshot["unresolved_controls"] == []
    assert snapshot["operational_integrity_findings"][0]["path"] == (
        "nodes/node_1/attempts/calc_1/submit_result.json"
    )
    assert node_completion_blockers(
        snapshot,
        node_id="node_1",
        outcome="inconclusive",
    )[0]["code"] == "operational_integrity_error"
