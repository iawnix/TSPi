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
COMPUTE_TASK = ROOT / "src" / "agents" / "compute" / "task-packet.cjs"
COMPUTE_OUTPUT = ROOT / "src" / "agents" / "compute" / "output-schema.cjs"


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
    assert operations["agent_runs"][0]["task_id"] == task["task_id"]
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


def test_completed_compute_is_act_scoped_private_and_never_requires_review_disposition(tmp_path: Path) -> None:
    workspace, refs = _workspace_with_act(tmp_path)
    bundle = _compute_bundle(workspace, refs["act_id"], "sub_compute-journal-001")
    script = (
        "const journal=require(process.argv[1]);"
        "const h=journal.beginAgentRun(process.argv[2],JSON.parse(process.argv[3]));"
        "const ref=journal.completeAgentRun(h,{actions:JSON.parse(process.argv[4]),"
        "result:JSON.parse(process.argv[5]),metadata:{schema_valid:true}});process.stdout.write(ref);"
    )
    completed = subprocess.run(
        [
            "node", "-e", script, str(JOURNAL), str(workspace),
            json.dumps(bundle["task"]), json.dumps(bundle["actions"]), json.dumps(bundle["result"]),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    run_ref = completed.stdout
    assert run_ref == f"acts/{refs['act_id']}/agent-runs/{bundle['task']['task_id']}"

    run_dir = workspace / run_ref
    assert stat.S_IMODE(run_dir.stat().st_mode) == 0o700
    assert {path.name for path in run_dir.iterdir()} == {
        "actions.json", "result.json", "run.json", "task.json",
    }
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in run_dir.iterdir())

    snapshot = operational_snapshot(workspace)
    row = snapshot["agent_runs"][0]
    assert row["role"] == "compute"
    assert row["authority"] == "operational"
    assert row["backend"] == "gaussian"
    assert row["intent_id"] == "calc_journal"
    assert snapshot["pending_review_dispositions"] == []

    disposition = _write_disposition(
        workspace,
        bundle["task"]["task_id"],
        run_ref,
        "accepted",
        check=False,
    )
    assert isinstance(disposition, subprocess.CompletedProcess)
    assert disposition.returncode == 2
    assert "not an advisory Review" in disposition.stderr


def test_compute_journal_enforces_task_result_and_action_size_limits(tmp_path: Path) -> None:
    workspace, refs = _workspace_with_act(tmp_path)
    script = """
const journal=require(process.argv[1]);
const taskHelper=require(process.argv[2]);
const resultHelper=require(process.argv[3]);
const workspace=process.argv[4];
const actId=process.argv[5];
const digest="sha256:"+"d".repeat(64);
const task=taskHelper.buildComputeTask({
  runId:"sub_compute-limits-001",workspaceRoot:workspace,operation:"cancel",backend:"gaussian",actId,
  binding:{intentId:"calc_limits",intentDigest:digest,executionKind:"remote"},
});
const canonical={
  schema_version:"ts-calculation-result/2",intent_id:"calc_limits",act_id:actId,state:"cancelled",
  program_status:"not_run",error_class:null,exit_status:null,artifact_refs:[],
  control:{effect_outcome:"succeeded",reconciliation_required:false},
  provenance:{intent_digest:digest},
};
const actions=[{tool:"ts_workspace_compute_cancel",result:{action_status:"completed",result:canonical}}];
const result=resultHelper.buildComputeResult({summary:"Cancellation completed.",limitations:[]},task,actions);

const oversizedTask=JSON.parse(JSON.stringify(task));
oversizedTask.objective="o".repeat(4000);
oversizedTask.workspace.root="/"+"w".repeat(4095);
oversizedTask.operation="finalize";
oversizedTask.inputs.required_actions=["collect","parse"];
oversizedTask.inputs.optional_actions=[];
oversizedTask.inputs.collect_artifacts=Array.from({length:32},(_,index)=>String(index).padStart(3,"0")+"a".repeat(252));
oversizedTask.inputs.parse_artifact_ref="p".repeat(4096);
oversizedTask.capabilities=["ts_workspace_compute_collect","ts_workspace_compute_parse","ts_compute_result"];
let taskError="";
try{taskHelper.validateComputeTask(oversizedTask)}catch(error){taskError=error.message}

const oversizedCanonical={...canonical,artifact_refs:Array.from({length:64},(_,index)=>String(index).padStart(3,"0")+"r".repeat(997))};
const oversizedResultActions=[{tool:"ts_workspace_compute_cancel",result:{action_status:"completed",result:oversizedCanonical}}];
let resultError="";
try{resultHelper.buildComputeResult({summary:"Large result.",limitations:[]},task,oversizedResultActions)}catch(error){resultError=error.message}

const handle=journal.beginAgentRun(workspace,task);
const oversizedActions=[{...actions[0],diagnostic:"x".repeat(1024*1024)}];
let actionError="";
try{journal.completeAgentRun(handle,{actions:oversizedActions,result,metadata:{}})}catch(error){actionError=error.message}
process.stdout.write(JSON.stringify({taskError,resultError,actionError,runRef:handle.runRef}));
"""
    completed = subprocess.run(
        [
            "node", "-e", script, str(JOURNAL), str(COMPUTE_TASK), str(COMPUTE_OUTPUT),
            str(workspace), refs["act_id"],
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["taskError"] == "Compute task exceeds 16384 bytes"
    assert result["resultError"] == "Compute result exceeds 32768 bytes"
    assert result["actionError"] == "agent-run actions exceed 1048576 bytes"
    run_dir = workspace / result["runRef"]
    assert {path.name for path in run_dir.iterdir()} == {"task.json"}
    assert stat.S_IMODE((run_dir / "task.json").stat().st_mode) == 0o600


def test_failed_run_settlement_preserves_partial_journal_as_pending(tmp_path: Path) -> None:
    workspace, refs = _workspace_with_act(tmp_path)
    bundle = _compute_bundle(workspace, refs["act_id"], "sub_compute-partial-journal-001")
    script = """
const fs=require("node:fs");
const path=require("node:path");
const journal=require(process.argv[1]);
const workspace=process.argv[2];
const task=JSON.parse(process.argv[3]);
const actions=JSON.parse(process.argv[4]);
const handle=journal.beginAgentRun(workspace,task);
fs.writeFileSync(path.join(handle.runDir,"actions.json"),"{}\\n",{flag:"wx",mode:0o600});
const settled=journal.settleFailedAgentRun(handle,{
  actions,
  error:new Error("primary provider failure"),
  metadata:{failure_class:"model_provider_failed"},
});
process.stdout.write(JSON.stringify({settled,files:fs.readdirSync(handle.runDir).sort()}));
"""
    completed = subprocess.run(
        [
            "node", "-e", script, str(JOURNAL), str(workspace),
            json.dumps(bundle["task"]), json.dumps(bundle["actions"]),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["settled"]["run_ref"].endswith("/sub_compute-partial-journal-001")
    assert result["settled"]["journal_error"]["code"] == "EEXIST"
    assert "actions.json" in result["settled"]["journal_error"]["message"]
    assert result["files"] == ["actions.json", "task.json"]

    row = operational_snapshot(workspace)["agent_runs"][0]
    assert row["status"] == "pending"
    assert row["role"] == "compute"


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


def _compute_bundle(workspace: Path, act_id: str, task_id: str) -> dict[str, object]:
    script = """
const taskHelper=require(process.argv[1]);
const resultHelper=require(process.argv[2]);
const workspace=process.argv[3];
const actId=process.argv[4];
const taskId=process.argv[5];
const digest="sha256:"+"c".repeat(64);
const task=taskHelper.buildComputeTask({
  runId:taskId,workspaceRoot:workspace,operation:"cancel",backend:"gaussian",actId,
  binding:{intentId:"calc_journal",intentDigest:digest,executionKind:"remote"},
});
const canonical={
  schema_version:"ts-calculation-result/2",intent_id:"calc_journal",act_id:actId,state:"cancelled",
  program_status:"not_run",error_class:null,exit_status:null,artifact_refs:[],
  control:{effect_outcome:"succeeded",reconciliation_required:false},
  provenance:{intent_digest:digest},
};
const actions=[{tool:"ts_workspace_compute_cancel",result:{action_status:"completed",result:canonical}}];
const result=resultHelper.buildComputeResult({summary:"Cancellation completed.",limitations:[]},task,actions);
process.stdout.write(JSON.stringify({task,actions,result}));
"""
    completed = subprocess.run(
        [
            "node", "-e", script, str(COMPUTE_TASK), str(COMPUTE_OUTPUT),
            str(workspace), act_id, task_id,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


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
