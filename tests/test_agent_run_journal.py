from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

from tests.v4_helpers import bootstrap_v4_workspace, build_review_bundle, start_research_act
from ts_workspace import apply_decision, draft_decision, validate_decision_dry_run
from ts_workspace.context import compile_context
from ts_workspace.errors import ContractError
from ts_workspace.operational import operational_snapshot


ROOT = Path(__file__).resolve().parents[1]
JOURNAL = ROOT / "src" / "agent-core" / "run-journal.cjs"


def test_completed_review_is_act_scoped_and_changes_only_operational_state(tmp_path: Path) -> None:
    workspace, refs = _workspace_with_act(tmp_path)
    task, documents = _review_bundle(workspace, refs, "sub_journal-001")
    before = compile_context(workspace, mode="frontier")

    run_ref = _journal(workspace, task, documents, mode="complete")

    assert run_ref == f"acts/{refs['act_id']}/agent-runs/{task['task_id']}"
    run_dir = workspace / run_ref
    assert {path.name for path in run_dir.iterdir()} == {
        "actions.json",
        "provider-input.json",
        "result.json",
        "review-snapshot.json",
        "run.json",
        "task.json",
    }
    assert all(stat.S_IMODE((run_dir / name).stat().st_mode) == 0o600 for name in (
        "task.json", "review-snapshot.json", "provider-input.json", "run.json"
    ))

    after = compile_context(workspace, mode="frontier")
    operations = operational_snapshot(workspace)
    assert after["workspace_revision"] == before["workspace_revision"]
    assert after["operational_revision"] != before["operational_revision"]
    assert operations["review_runs"][0]["task_id"] == task["task_id"]
    assert operations["pending_review_dispositions"][0]["claim_refs"] == [refs["claim_id"]]


@pytest.mark.parametrize("disposition", ["accepted", "partially_accepted", "rejected", "deferred"])
def test_root_review_disposition_is_write_once_and_unblocks_mutation(
    tmp_path: Path,
    disposition: str,
) -> None:
    workspace, refs = _workspace_with_act(tmp_path)
    task, documents = _review_bundle(workspace, refs, f"sub_disposition-{disposition.replace('_', '-')}")
    run_ref = _journal(workspace, task, documents, mode="complete")
    drafted = draft_decision(
        workspace,
        {
            "rationale": "Record a post-review research note.",
            "basis_refs": [],
            "operations": [{"op": "set_focus", "claimRefs": [refs["claim_id"]], "actRefs": [refs["act_id"]]}],
        },
    )
    with pytest.raises(ContractError, match="requires a Root response"):
        validate_decision_dry_run(workspace, drafted["decision"])

    document = _write_disposition(workspace, task["task_id"], run_ref, disposition)
    assert document["schema_version"] == "ts-review-root-disposition/1"
    assert stat.S_IMODE((workspace / run_ref / "root-disposition.json").stat().st_mode) == 0o600
    assert validate_decision_dry_run(workspace, drafted["decision"])["valid"] is True
    apply_decision(workspace, drafted["decision"])
    assert operational_snapshot(workspace)["pending_review_dispositions"] == []

    repeated = _write_disposition(workspace, task["task_id"], run_ref, disposition, check=False)
    assert isinstance(repeated, subprocess.CompletedProcess)
    assert repeated.returncode == 2


def test_invalid_review_output_is_bounded_private_operational_data(tmp_path: Path) -> None:
    workspace, refs = _workspace_with_act(tmp_path)
    task, documents = _review_bundle(workspace, refs, "sub_invalid-001")
    script = (
        "const journal=require(process.argv[1]);"
        "const h=journal.beginAgentRun(process.argv[2],JSON.parse(process.argv[3]),{documents:JSON.parse(process.argv[4])});"
        "journal.writeInvalidReviewOutput(h,[{validation_stage:'tool_schema',reason:'risks must be an array',"
        "source:'tool_arguments',raw:'x'.repeat(40000)}]);"
        "journal.failAgentRun(h,{error:new Error('invalid review result')});"
    )
    subprocess.run(
        ["node", "-e", script, str(JOURNAL), str(workspace), json.dumps(task), json.dumps(documents)],
        cwd=ROOT,
        check=True,
    )
    invalid = workspace / "acts" / refs["act_id"] / "agent-runs" / task["task_id"] / "invalid-review-output.json"
    value = json.loads(invalid.read_text(encoding="utf-8"))
    assert value["invalid"] is True
    assert value["attempts"][0]["truncated"] is True
    assert invalid.stat().st_size <= 16 * 1024
    assert stat.S_IMODE(invalid.stat().st_mode) == 0o600
    assert compile_context(workspace, mode="frontier")["observations"] == []


def test_review_journal_rejects_duplicate_task_and_detects_bound_document_tampering(tmp_path: Path) -> None:
    workspace, refs = _workspace_with_act(tmp_path)
    task, documents = _review_bundle(workspace, refs, "sub_tamper-001")
    _journal(workspace, task, documents, mode="complete")
    duplicate = _journal(workspace, task, documents, mode="complete", check=False)
    assert isinstance(duplicate, subprocess.CompletedProcess)
    assert duplicate.returncode == 2
    assert "already exists" in duplicate.stderr

    task2, documents2 = _review_bundle(workspace, refs, "sub_tamper-002")
    script = (
        "const fs=require('node:fs');const journal=require(process.argv[1]);"
        "const h=journal.beginAgentRun(process.argv[2],JSON.parse(process.argv[3]),{documents:JSON.parse(process.argv[4])});"
        "fs.appendFileSync(h.runDir+'/provider-input.json',' ');"
        "try{journal.readAgentRunInputs(h);}catch(error){process.stderr.write(error.message);process.exitCode=2;}"
    )
    completed = subprocess.run(
        ["node", "-e", script, str(JOURNAL), str(workspace), json.dumps(task2), json.dumps(documents2)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 2
    assert "does not match task binding" in completed.stderr


def _workspace_with_act(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    workspace = bootstrap_v4_workspace(tmp_path / "workspace")
    refs = start_research_act(workspace, claim_statement="The proposed pathway is concerted.")
    return workspace, refs


def _review_bundle(
    workspace: Path,
    refs: dict[str, str],
    task_id: str,
) -> tuple[dict[str, object], dict[str, object]]:
    value = build_review_bundle(workspace, refs, task_id)
    return value["task"], value["documents"]


def _review_result(task: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "ts-agent-result/1",
        "task_id": task["task_id"],
        "role": "review",
        "authority": "advisory",
        "operation": task["operation"],
        "outcome": "success",
        "summary": "The bounded advisory Review completed.",
        "scope": task["scope"],
        "facts": [],
        "artifact_refs": [],
        "program": None,
        "payload": {"missing_evidence": [], "conflicts": [], "options": []},
        "limitations": [],
        "provenance": {"source": "test"},
    }


def _journal(
    workspace: Path,
    task: dict[str, object],
    documents: dict[str, object],
    *,
    mode: str,
    check: bool = True,
) -> str | subprocess.CompletedProcess[str]:
    result = _review_result(task)
    script = (
        "const journal=require(process.argv[1]);"
        "try{const h=journal.beginAgentRun(process.argv[2],JSON.parse(process.argv[3]),{documents:JSON.parse(process.argv[4])});"
        "const ref=journal.completeAgentRun(h,{actions:[],result:JSON.parse(process.argv[5]),metadata:{schema_valid:true}});"
        "process.stdout.write(ref);}catch(error){process.stderr.write(error.message);process.exitCode=2;}"
    )
    completed = subprocess.run(
        ["node", "-e", script, str(JOURNAL), str(workspace), json.dumps(task), json.dumps(documents), json.dumps(result)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if check:
        assert completed.returncode == 0, completed.stderr
        return completed.stdout
    return completed


def _write_disposition(
    workspace: Path,
    task_id: object,
    run_ref: str,
    disposition: str,
    *,
    check: bool = True,
) -> dict[str, object] | subprocess.CompletedProcess[str]:
    value = {
        "task_id": task_id,
        "review_run_ref": run_ref,
        "disposition": disposition,
        "response": "Root assessed the advice against the frozen graph and primary artifacts.",
        "next_steps": [],
    }
    script = (
        "const journal=require(process.argv[1]);"
        "try{process.stdout.write(JSON.stringify(journal.writeReviewRootDisposition(process.argv[2],JSON.parse(process.argv[3]))));}"
        "catch(error){process.stderr.write(error.code||error.message);process.exitCode=2;}"
    )
    completed = subprocess.run(
        ["node", "-e", script, str(JOURNAL), str(workspace), json.dumps(value)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if check:
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)
    return completed
