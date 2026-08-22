from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.v4_helpers import accept_research_claim, bootstrap_v4_workspace, build_review_bundle, start_research_act


ROOT = Path(__file__).resolve().parents[1]
TS_LOADER = ROOT / "tests" / "typescript_loader.mjs"
OUTPUT_SCHEMA = ROOT / "src" / "agents" / "review" / "output-schema.cjs"
RESULT_TOOL = ROOT / "src" / "agents" / "review" / "result-tool.ts"
RUNTIME = ROOT / "src" / "agents" / "review" / "runtime.ts"
TASK_PACKET = ROOT / "src" / "agents" / "review" / "task-packet.cjs"
COMPUTE_OUTPUT_SCHEMA = ROOT / "src" / "agents" / "compute" / "output-schema.cjs"
COMPUTE_RESULT_TOOL = ROOT / "src" / "agents" / "compute" / "result-tool.ts"
COMPUTE_RUNTIME = ROOT / "src" / "agents" / "compute" / "runtime.ts"
COMPUTE_TASK_PACKET = ROOT / "src" / "agents" / "compute" / "task-packet.cjs"


def test_review_task_v2_is_graph_scoped_bounded_and_advisory(tmp_path: Path) -> None:
    workspace = bootstrap_v4_workspace(tmp_path / "workspace")
    refs = start_research_act(workspace, claim_statement="The pathway is concerted.")
    bundle = build_review_bundle(workspace, refs, "sub_contract-001")
    task = bundle["task"]
    snapshot = bundle["documents"]["review_snapshot"]
    provider = bundle["documents"]["provider_input"]

    assert task["schema_version"] == "ts-agent-task/2"
    assert task["role"] == "review"
    assert task["authority"] == "advisory"
    assert task["capabilities"] == ["ts_review_result"]
    assert task["scope"]["act_refs"] == [refs["act_id"]]
    assert task["scope"]["claim_refs"] == [refs["claim_id"]]
    assert set(task["inputs"]) == {"review_snapshot", "provider_input"}
    assert snapshot["schema_version"] == "ts-review-task-snapshot/2"
    assert provider["schema_version"] == "ts-review-provider-input/4"
    assert snapshot["artifact_manifest"] == []
    assert provider["artifact_manifest"] == []
    assert provider["research_acts"][0]["related_claim_refs"] == [refs["claim_id"]]
    assert len(json.dumps(provider).encode()) < 48 * 1024
    serialized = json.dumps(provider)
    for retired in ('"node_id"', '"evidence"', '"gate_results"', '"required_gates"'):
        assert retired not in serialized


def test_review_request_accepts_only_claim_and_logical_artifact_ids() -> None:
    script = (
        f"const helper=require({json.dumps(str(TASK_PACKET))});"
        "const values=["
        "{targetClaimRef:'claim_1',question:'Review this.',artifactIds:['art_'+ 'b'.repeat(24)]},"
        "{targetClaimRef:'claim_1',question:'Review this.',artifactIds:['../output.log']},"
        "{targetClaimRef:'clm_'+ 'a'.repeat(24),question:'Review this.',artifactIds:[]}];"
        "const out=values.map(v=>{try{return {ok:true,value:helper.validateSubagentRequest(v)}}"
        "catch(error){return {ok:false,error:error.message}}});process.stdout.write(JSON.stringify(out));"
    )
    rows = json.loads(_node(script).stdout)
    assert rows[0]["ok"] is True
    assert rows[1]["ok"] is False and "artifactIds" in rows[1]["error"]
    assert rows[2]["ok"] is False and "targetClaimRef" in rows[2]["error"]


def test_review_packet_carries_compact_current_acceptance_state(tmp_path: Path) -> None:
    workspace = bootstrap_v4_workspace(tmp_path / "workspace")
    refs = accept_research_claim(workspace)
    bundle = build_review_bundle(
        workspace,
        {"claim_id": refs["claim"], "act_id": refs["act"]},
        "sub_acceptance-001",
    )

    acceptance = bundle["documents"]["provider_input"]["acceptances"][0]
    assert acceptance["acceptance_id"] == refs["acceptance"]
    assert acceptance["current"] is True
    assert acceptance["stale_reasons"] == []
    assert "claim_snapshot" not in acceptance


def test_review_result_requires_array_risks_and_bound_basis_refs(tmp_path: Path) -> None:
    workspace = bootstrap_v4_workspace(tmp_path / "workspace")
    refs = start_research_act(workspace)
    bundle = build_review_bundle(workspace, refs, "sub_result-001")
    task = bundle["task"]
    snapshot = bundle["documents"]["review_snapshot"]
    basis = snapshot["basis_allowlist"][0]
    valid = _result(task, basis)

    accepted = _validate_result(tmp_path, task, snapshot, valid)
    assert accepted.returncode == 0, accepted.stderr
    assert json.loads(accepted.stdout)["facts"][0]["basis_refs"] == [basis]

    risks_string = json.loads(json.dumps(valid))
    risks_string["payload"]["options"][0]["risks"] = "one risk"
    rejected = _validate_result(tmp_path, task, snapshot, risks_string)
    assert rejected.returncode == 2
    assert "risks must be an array" in rejected.stderr

    outside = json.loads(json.dumps(valid))
    outside["facts"][0]["basis_refs"] = ["obs_outside"]
    rejected = _validate_result(tmp_path, task, snapshot, outside)
    assert rejected.returncode == 2
    assert "outside task packet" in rejected.stderr


def test_review_tool_uses_local_schema_without_provider_strict_mode(tmp_path: Path) -> None:
    workspace = bootstrap_v4_workspace(tmp_path / "workspace")
    refs = start_research_act(workspace)
    bundle = build_review_bundle(workspace, refs, "sub_tool-001")
    input_path = tmp_path / "bundle.json"
    input_path.write_text(json.dumps(bundle), encoding="utf-8")
    script = f"""
import {{ readFileSync }} from "node:fs";
import {{ Compile }} from "typebox/compile";
import {{ createReviewResultCapture, createReviewResultTool }} from {json.dumps(RESULT_TOOL.as_uri())};
const bundle=JSON.parse(readFileSync(process.argv[1],"utf8"));
const capture=createReviewResultCapture();
const tool=createReviewResultTool(bundle.task,bundle.documents.review_snapshot,capture);
const validator=Compile(tool.parameters);
const base={{outcome:"partial",summary:"Bounded result",facts:[],missing_evidence:[],conflicts:[],options:[],limitations:[]}};
process.stdout.write(JSON.stringify({{
  constrainedSampling:Object.hasOwn(tool,"constrainedSampling"),
  valid:validator.Check(base),
  stringRisks:validator.Check({{...base,options:[{{action:"x",discriminator:"y",risks:"bad"}}]}}),
}}));
"""
    result = json.loads(_node_ts(script, str(input_path)).stdout)
    assert result == {"constrainedSampling": False, "valid": True, "stringRisks": False}


def test_review_runtime_can_force_named_tool_without_adding_function_strict() -> None:
    script = f"""
import {{ forceReviewResultToolChoice }} from {json.dumps(RUNTIME.as_uri())};
const payload=forceReviewResultToolChoice({{model:"probe",tools:[{{type:"function",function:{{name:"ts_review_result",parameters:{{type:"object"}}}}}}]}});
process.stdout.write(JSON.stringify(payload));
"""
    payload = json.loads(_node_ts(script).stdout)
    assert payload["tool_choice"] == {"type": "function", "function": {"name": "ts_review_result"}}
    assert "strict" not in payload["tools"][0]["function"]
    source = RUNTIME.read_text(encoding="utf-8")
    assert "assertProviderTurnSucceeded" in source
    assert "repairMissingToolCall" in source
    assert source.index("assertProviderTurnSucceeded") < source.index("repairMissingToolCall")


def test_compute_and_review_are_the_only_model_child_runtimes() -> None:
    agent_root = ROOT / "src" / "agents"
    packaged_namespaces = {
        path.relative_to(agent_root).parts[0]
        for path in agent_root.rglob("*")
        if path.is_file()
    }
    assert packaged_namespaces == {"compute", "review"}


def test_compute_task_and_result_are_bound_to_typed_actions(tmp_path: Path) -> None:
    script = f"""
const taskHelper=require({json.dumps(str(COMPUTE_TASK_PACKET))});
const resultHelper=require({json.dumps(str(COMPUTE_OUTPUT_SCHEMA))});
const task=taskHelper.buildComputeTask({{
  runId:"sub_compute-001",workspaceRoot:process.argv[1],operation:"launch",backend:"gaussian",actId:"act_1",
  binding:{{intentId:"calc_probe",intentDigest:"sha256:"+"a".repeat(64),executionKind:"remote"}},
}});
const canonical=(state,control={{effect_outcome:"succeeded",reconciliation_required:false}})=>({{
  schema_version:"ts-calculation-result/2",intent_id:"calc_probe",act_id:"act_1",state,
  program_status:"not_run",error_class:null,exit_status:null,artifact_refs:[],control,
  provenance:{{intent_digest:"sha256:"+"a".repeat(64)}},
}});
const successActions=[
  {{tool:"ts_workspace_compute_prepare",result:{{action_status:"completed",result:canonical("prepared")}}}},
  {{tool:"ts_workspace_compute_submit",result:{{action_status:"completed",result:canonical("submitted")}}}},
];
const ambiguousResult=canonical("unknown",{{effect_outcome:"unknown",reconciliation_required:true}});
ambiguousResult.error_class="submission_ambiguous";
const ambiguousActions=[
  successActions[0],
  {{tool:"ts_workspace_compute_submit",result:{{action_status:"unknown",result:ambiguousResult}}}},
];
const success=resultHelper.buildComputeResult({{summary:"Launch completed.",limitations:[]}},task,successActions);
const ambiguous=resultHelper.buildComputeResult({{summary:"Submission requires reconciliation.",limitations:["Scheduler result is unknown."]}},task,ambiguousActions);
let invented="";
try{{resultHelper.buildComputeResult({{summary:"x",limitations:[],outcome:"success"}},task,successActions)}}catch(error){{invented=error.message}}
process.stdout.write(JSON.stringify({{task,success,ambiguous,invented}}));
"""
    completed = _node(script, str(tmp_path))
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["task"]["role"] == "compute"
    assert result["task"]["authority"] == "operational"
    assert result["task"]["inputs"]["required_actions"] == ["prepare", "submit"]
    assert result["success"]["outcome"] == "success"
    assert result["success"]["payload"]["action_outcome"] == "succeeded"
    assert result["ambiguous"]["outcome"] == "partial"
    assert result["ambiguous"]["payload"]["action_outcome"] == "unknown"
    assert result["ambiguous"]["payload"]["reconciliation_required"] is True
    assert "unknown fields" in result["invented"]


def test_compute_result_tool_is_local_and_inspect_retains_optional_tail(tmp_path: Path) -> None:
    script = f"""
import {{ Compile }} from "typebox/compile";
import {{ createComputeResultCapture,createComputeResultTool }} from {json.dumps(COMPUTE_RESULT_TOOL.as_uri())};
import {{ shouldForceComputeResult }} from {json.dumps(COMPUTE_RUNTIME.as_uri())};
import {{ createRequire }} from "node:module";
const require=createRequire(import.meta.url);
const taskHelper=require({json.dumps(str(COMPUTE_TASK_PACKET))});
const task=taskHelper.buildComputeTask({{
  runId:"sub_compute-002",workspaceRoot:process.argv[1],operation:"inspect",backend:"gaussian",actId:"act_1",
  binding:{{intentId:"calc_probe",intentDigest:"sha256:"+"b".repeat(64),executionKind:"remote"}},tailLines:80,
}});
const result={{schema_version:"ts-calculation-result/2",intent_id:"calc_probe",act_id:"act_1",state:"running",program_status:"running",error_class:null,exit_status:null,artifact_refs:[],provenance:{{intent_digest:"sha256:"+"b".repeat(64)}}}};
const status={{tool:"ts_workspace_compute_status",result:{{action_status:"completed",result}}}};
const tail={{tool:"ts_workspace_compute_tail",result:{{action_status:"completed",result:{{...result,schema_version:"ts-calculation-tail/1"}}}}}};
const actions=[];
const tool=createComputeResultTool(task,actions,createComputeResultCapture());
const check=Compile(tool.parameters);
process.stdout.write(JSON.stringify({{
  constrainedSampling:Object.hasOwn(tool,"constrainedSampling"),
  keys:Object.keys(tool.parameters.properties).sort(),
  valid:check.Check({{summary:"Status checked.",limitations:[]}}),
  before:shouldForceComputeResult(task,[]),
  afterStatus:shouldForceComputeResult(task,[status]),
  afterTail:shouldForceComputeResult(task,[status,tail]),
  repair:shouldForceComputeResult(task,[status],true),
}}));
"""
    result = json.loads(_node_ts(script, str(tmp_path)).stdout)
    assert result == {
        "constrainedSampling": False,
        "keys": ["limitations", "summary"],
        "valid": True,
        "before": False,
        "afterStatus": False,
        "afterTail": True,
        "repair": True,
    }


def _result(task: dict, basis_ref: str) -> dict:
    return {
        "schema_version": "ts-agent-result/1",
        "task_id": task["task_id"],
        "role": "review",
        "authority": "advisory",
        "operation": task["operation"],
        "outcome": "partial",
        "summary": "The current graph supports only a bounded advisory conclusion.",
        "scope": task["scope"],
        "facts": [{"kind": "review", "statement": "One graph fact is relevant.", "status": "supported", "basis_refs": [basis_ref]}],
        "artifact_refs": [],
        "program": None,
        "payload": {
            "missing_evidence": ["One discriminating observation is missing."],
            "conflicts": [],
            "options": [{"action": "Collect the observation.", "discriminator": "It separates the Claims.", "risks": ["The result may remain inconclusive."]}],
        },
        "limitations": ["Advisory only."],
        "provenance": {"source": "bounded_task_packet"},
    }


def _validate_result(tmp_path: Path, task: dict, snapshot: dict, result: dict) -> subprocess.CompletedProcess[str]:
    input_path = tmp_path / "review-result.json"
    input_path.write_text(json.dumps({"task": task, "snapshot": snapshot, "result": result}), encoding="utf-8")
    script = (
        f"const fs=require('node:fs');const helper=require({json.dumps(str(OUTPUT_SCHEMA))});"
        "const value=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));"
        "try{process.stdout.write(JSON.stringify(helper.validateReviewResult(value.result,value.task,value.snapshot)));}"
        "catch(error){process.stderr.write(error.message);process.exitCode=2;}"
    )
    return _node(script, str(input_path))


def _node(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "-e", script, *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _node_ts(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["node", "--experimental-loader", str(TS_LOADER), "--input-type=module", "--eval", script, *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed
