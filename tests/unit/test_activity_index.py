from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.support.workspace_helpers import start_research_node
from ts_agent.report import build_report_package
from ts_agent.workspace.activities import build_activity_index
from ts_agent.workspace.context import compile_context
from tests.support.kernel_helpers import compile_change
from ts_agent.workspace.engine import init_workspace
from tests.support.kernel_helpers import apply_compiled_change, validate_compiled_change
from ts_agent.workspace.errors import ContractError
from ts_agent.io import read_json, write_json
from ts_agent.workspace.operational import operational_snapshot
from ts_agent.workspace.validator import validate_workspace


ROOT = Path(__file__).resolve().parents[2]
ACTIVITY_JOURNAL = ROOT / "packages" / "ts-agent-runtime" / "agent-core" / "activity-journal.cjs"


def _activity_documents(
    root: Path,
    node_id: str,
    *,
    activity_id: str = "op_1",
    state: str = "completed",
    owner_node: str | None = None,
    kind: str = "render",
) -> Path:
    owner = owner_node or node_id
    operation = "import" if kind == "artifact_import" else "render"
    activity = root / "nodes" / owner / "activities" / activity_id
    started_at = "2026-08-16T00:00:00+00:00"
    write_json(
        activity / "request.json",
        {
            "schema_version": "ts-deterministic-activity-request/1",
            "activity_id": activity_id,
            "kind": kind,
            "operation": operation,
            "node_refs": [node_id],
            "request": {"input_artifact_ids": []},
            "started_at": started_at,
        },
    )
    terminal = state in {"completed", "failed"}
    write_json(
        activity / "status.json",
        {
            "schema_version": "ts-deterministic-activity-status/1",
            "activity_id": activity_id,
            "kind": kind,
            "operation": operation,
            "node_refs": [node_id],
            "status": state,
            "started_at": started_at,
            "completed_at": "2026-08-16T00:01:00+00:00" if terminal else None,
            "error": {"name": "ProgramError", "message": "Program failed."} if state == "failed" else None,
        },
    )
    if state == "completed":
        write_json(activity / "result.json", {"outcome": "success", "summary": "Input prepared."})
    elif state == "failed":
        write_json(activity / "result.json", {"outcome": "failed", "summary": "Program failed."})
    return activity


def _completion(root: Path, node_id: str, outcome: str) -> dict:
    return compile_change(
        root,
        {
            "rationale": "Close the bounded ResearchNode after checking operational state.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "complete_node",
                    "nodeRef": node_id,
                    "outcome": outcome,
                    "summary": "The bounded Node reached a terminal outcome.",
                }
            ],
        },
    )["decision"]


def test_activity_is_derived_for_its_node_without_a_link_decision(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = start_research_node(root)
    activity = _activity_documents(root, refs["node_id"])

    index = build_activity_index(root)
    node = read_json(root / "research_nodes.json")["nodes"][0]

    assert node["schema_version"] == "ts-research-node/2"
    assert "operation_refs" not in node
    assert index["integrity_findings"] == []
    assert index["activities"][0]["activity_ref"] == activity.relative_to(root).as_posix()
    assert index["activity_summaries"][0]["completed_count"] == 1
    assert validate_workspace(root)["valid"] is True


def test_activity_journal_rejects_noncanonical_activity_ids(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = start_research_node(root)
    script = (
        "const journal=require(process.argv[1]);"
        "const input=JSON.parse(process.argv[3]);"
        "try{journal.beginActivity(process.argv[2],input);process.exitCode=0;}"
        "catch(error){process.stderr.write(String(error.message||error));process.exitCode=2;}"
    )

    rejected = subprocess.run(
        [
            "node",
            "-e",
            script,
            str(ACTIVITY_JOURNAL),
            str(root),
            json.dumps({
                "activity_id": "activity_probe",
                "kind": "render",
                "operation": "render",
                "node_refs": [refs["node_id"]],
                "request": {},
            }),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert rejected.returncode == 2
    assert "operational activity ID" in rejected.stderr


def test_activity_index_ignores_unsupported_uuid_journals(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = start_research_node(root)
    unsupported_id = "op_019a338f-acaf-43e6-b498-4e3994971399"
    activity = _activity_documents(root, refs["node_id"], activity_id=unsupported_id)
    for name in ("request.json", "status.json"):
        document = read_json(activity / name)
        document["kind"] = "compute"
        write_json(activity / name, document)

    index = build_activity_index(root)

    assert index["activities"] == []
    assert index["integrity_findings"] == []


def test_activity_index_sorts_operational_ordinals_numerically(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = start_research_node(root)
    _activity_documents(root, refs["node_id"], activity_id="op_10")
    _activity_documents(root, refs["node_id"], activity_id="op_2")

    index = build_activity_index(root)

    assert index["integrity_findings"] == []
    assert [row["activity_id"] for row in index["activities"]] == ["op_2", "op_10"]


def test_artifact_import_is_a_valid_node_owned_activity(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = start_research_node(root)
    activity = _activity_documents(root, refs["node_id"])
    for name in ("request.json", "status.json"):
        document = read_json(activity / name)
        document["kind"] = "artifact_import"
        document["operation"] = "import"
        write_json(activity / name, document)

    index = build_activity_index(root)
    assert index["integrity_findings"] == []
    assert index["activities"][0]["kind"] == "artifact_import"


def test_structure_seed_is_a_valid_node_owned_activity(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = start_research_node(root)
    activity = _activity_documents(root, refs["node_id"])
    for name in ("request.json", "status.json"):
        document = read_json(activity / name)
        document["kind"] = "structure_seed"
        document["operation"] = "generate"
        write_json(activity / name, document)

    index = build_activity_index(root)
    assert index["integrity_findings"] == []
    assert index["activities"][0]["kind"] == "structure_seed"


def test_structure_compare_is_a_valid_node_owned_activity(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = start_research_node(root)
    activity = _activity_documents(root, refs["node_id"])
    for name in ("request.json", "status.json"):
        document = read_json(activity / name)
        document["kind"] = "structure_compare"
        document["operation"] = "compare"
        write_json(activity / name, document)

    index = build_activity_index(root)
    assert index["integrity_findings"] == []
    assert index["activities"][0]["kind"] == "structure_compare"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("directory_id", "activity_id_path_mismatch"),
        ("status_id", "activity_request_status_mismatch"),
        ("node_refs", "activity_path_owner_mismatch"),
    ],
)
def test_activity_integrity_rejects_path_id_and_owner_mismatches(
    tmp_path: Path,
    mutation: str,
    code: str,
) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = start_research_node(root)
    activity = _activity_documents(root, refs["node_id"])
    if mutation == "directory_id":
        activity.rename(activity.with_name("op_2"))
    elif mutation == "status_id":
        status = read_json(activity / "status.json")
        status["activity_id"] = "op_2"
        write_json(activity / "status.json", status)
    else:
        status = read_json(activity / "status.json")
        status["node_refs"] = []
        write_json(activity / "status.json", status)

    validation = validate_workspace(root)

    assert validation["valid"] is False
    assert code in {finding["code"] for finding in validation["findings"]}


def test_activity_integrity_detects_missing_documents_and_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = start_research_node(root)
    activity = _activity_documents(root, refs["node_id"])
    (activity / "status.json").unlink()
    (activity / "status.json").symlink_to("request.json")

    codes = {finding["code"] for finding in build_activity_index(root)["integrity_findings"]}

    assert "activity_document_symlink" in codes
    assert "invalid_activity_status_schema" in codes
    with pytest.raises(ContractError, match="activity_integrity_error"):
        validate_compiled_change(root, _completion(root, refs["node_id"], "blocked"))


def test_running_activity_blocks_dry_run_and_apply(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = start_research_node(root)
    _activity_documents(root, refs["node_id"], state="running")
    decision = _completion(root, refs["node_id"], "completed")

    with pytest.raises(ContractError, match="activity_not_terminal"):
        validate_compiled_change(root, decision)
    with pytest.raises(ContractError, match="activity_not_terminal"):
        apply_compiled_change(root, decision)
    assert read_json(root / "research_nodes.json")["nodes"][0]["status"] == "open"


@pytest.mark.parametrize(
    ("records", "expected"),
    [
        ("pending", "pending_compute_control"),
        ("ambiguous", "unresolved_compute_control"),
    ],
)
def test_pending_and_ambiguous_compute_controls_block_completion(
    tmp_path: Path,
    records: str,
    expected: str,
) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = start_research_node(root)
    attempt = root / "nodes" / refs["node_id"] / "attempts" / "calc_1"
    write_json(attempt / "submit_guard.json", {"operation": "submit"})
    if records == "ambiguous":
        write_json(
            attempt / "submit_result.json",
            {
                "state": "unknown",
                "error_class": "submission_ambiguous",
                "job_id": None,
                "control": {"effect_outcome": "unknown", "retry_disposition": "reconcile_only"},
            },
        )

    with pytest.raises(ContractError, match=expected):
        validate_compiled_change(root, _completion(root, refs["node_id"], "blocked"))


def test_analytical_and_terminal_activity_completion_policy(tmp_path: Path) -> None:
    analytical = tmp_path / "analytical"
    init_workspace(analytical)
    analytical_refs = start_research_node(analytical)
    analytical_decision = _completion(analytical, analytical_refs["node_id"], "completed")
    validate_compiled_change(analytical, analytical_decision)
    apply_compiled_change(analytical, analytical_decision)

    successful = tmp_path / "successful"
    init_workspace(successful)
    successful_refs = start_research_node(successful)
    _activity_documents(successful, successful_refs["node_id"], state="completed")
    successful_decision = _completion(successful, successful_refs["node_id"], "completed")
    validate_compiled_change(successful, successful_decision)
    apply_compiled_change(successful, successful_decision)

    failed_render = tmp_path / "failed-render"
    init_workspace(failed_render)
    failed_render_refs = start_research_node(failed_render)
    _activity_documents(failed_render, failed_render_refs["node_id"], state="failed")
    completed = _completion(failed_render, failed_render_refs["node_id"], "completed")
    validate_compiled_change(failed_render, completed)
    apply_compiled_change(failed_render, completed)

    failed = tmp_path / "failed-input"
    init_workspace(failed)
    failed_refs = start_research_node(failed)
    _activity_documents(failed, failed_refs["node_id"], state="failed", kind="artifact_import")
    with pytest.raises(ContractError, match="failed_activity_requires_non_success_outcome"):
        validate_compiled_change(failed, _completion(failed, failed_refs["node_id"], "completed"))
    inconclusive = _completion(failed, failed_refs["node_id"], "inconclusive")
    validate_compiled_change(failed, inconclusive)
    apply_compiled_change(failed, inconclusive)


def test_failed_activity_is_superseded_by_a_later_retry_of_same_intent(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = start_research_node(root)
    _activity_documents(root, refs["node_id"], activity_id="op_1", state="failed", kind="artifact_import")
    retry = _activity_documents(root, refs["node_id"], activity_id="op_2", state="completed", kind="artifact_import")
    request = read_json(retry / "request.json")
    request["started_at"] = "2026-08-16T00:02:00+00:00"
    write_json(retry / "request.json", request)
    status = read_json(retry / "status.json")
    status["started_at"] = "2026-08-16T00:02:00+00:00"
    status["completed_at"] = "2026-08-16T00:03:00+00:00"
    write_json(retry / "status.json", status)

    decision = _completion(root, refs["node_id"], "completed")
    validate_compiled_change(root, decision)


def test_failed_activity_with_different_intent_still_blocks_completion(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = start_research_node(root)
    _activity_documents(root, refs["node_id"], activity_id="op_1", state="failed", kind="artifact_import")
    retry = _activity_documents(root, refs["node_id"], activity_id="op_2", state="completed", kind="artifact_import")
    request = read_json(retry / "request.json")
    request["request"]["input_artifact_ids"] = ["art_other"]
    write_json(retry / "request.json", request)

    with pytest.raises(ContractError, match="failed_activity_requires_non_success_outcome"):
        validate_compiled_change(root, _completion(root, refs["node_id"], "completed"))


def test_report_and_frontier_use_compact_derived_activity_projection(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = start_research_node(root)
    _activity_documents(root, refs["node_id"], state="completed")
    report_activity = root / "operations" / "activities" / "op_2"
    started_at = "2026-08-16T01:00:00+00:00"
    write_json(
        report_activity / "request.json",
        {
            "schema_version": "ts-deterministic-activity-request/1",
            "activity_id": "op_2",
            "kind": "report",
            "operation": "build",
            "node_refs": [],
            "request": {"package_name": "study"},
            "started_at": started_at,
        },
    )
    write_json(
        report_activity / "status.json",
        {
            "schema_version": "ts-deterministic-activity-status/1",
            "activity_id": "op_2",
            "kind": "report",
            "operation": "build",
            "node_refs": [],
            "status": "running",
            "started_at": started_at,
            "completed_at": None,
            "error": None,
        },
    )

    frontier = compile_context(root, mode="frontier")
    built = build_report_package(
        root,
        root / "reports" / "study",
        exclude_activity_refs=["operations/activities/op_2"],
    )
    activities = read_json(root / "reports" / "study" / "activities.json")
    manifest = read_json(Path(built["manifest"]))

    assert frontier["activity_summaries"][0]["completed_count"] == 1
    assert "deterministic_activities" not in frontier
    assert [row["activity_id"] for row in activities["activities"]] == ["op_1"]
    assert activities["excluded_activity_refs"] == ["operations/activities/op_2"]
    assert manifest["workspace_revision"] == built["workspace_revision"]
    assert manifest["operational_revision"] == built["operational_revision"]
    assert operational_snapshot(root)["operational_revision"] != built["operational_revision"]
