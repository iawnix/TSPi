from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TS_LOADER = ROOT / "tests" / "typescript_loader.mjs"
COMPUTE = ROOT / "extensions" / "ts-workflow-compute" / "index.ts"
ACTION_LOG = ROOT / "extensions" / "ts-workflow-compute" / "action-log.cjs"


def test_compute_extension_registers_direct_compute_and_read_only_remote_tools() -> None:
    script = f"""
import install from {json.dumps(COMPUTE.as_uri())};
const tools=[];const commands=[];const pi={{registerTool:(tool)=>tools.push(tool),registerCommand:(name)=>commands.push(name),registerEntryRenderer:()=>{{}},appendEntry:()=>{{}},getThinkingLevel:()=>"off",events:{{emit:()=>{{}}}}}};
install(pi);
process.stdout.write(JSON.stringify({{tools:tools.map((tool)=>tool.name),commands}}));
"""
    result = _node_json(script)
    assert result == {"tools": ["ts_remote_inspect", "ts_compute"], "commands": ["ts-remote"]}


def test_compute_schema_is_operation_specific_and_uses_logical_artifacts() -> None:
    script = f"""
import install from {json.dumps(COMPUTE.as_uri())};
import {{ Compile }} from "typebox/compile";
let compute;const pi={{registerTool:(tool)=>{{if(tool.name==="ts_compute")compute=tool}},registerCommand:()=>{{}},registerEntryRenderer:()=>{{}},appendEntry:()=>{{}},getThinkingLevel:()=>"off",events:{{emit:()=>{{}}}}}};
install(pi);const check=Compile(compute.parameters);
const base={{backend:"gaussian",actId:"act_"+"a".repeat(24)}};
const prepare={{...base,operation:"prepare",purpose:"Single point",taskType:"sp",inputArtifacts:[{{inputRole:"gjf",artifactId:"art_"+"b".repeat(24)}}],executionTarget:{{kind:"local"}},dryRun:true}};
process.stdout.write(JSON.stringify({{
  prepare:check.Check(prepare),
  physicalPath:check.Check({{...prepare,inputArtifacts:[{{inputRole:"gjf",artifactId:"inputs/test.gjf"}}]}}),
  oldNode:check.Check({{...prepare,actId:undefined,nodeId:"n001"}}),
  submit:check.Check({{...base,operation:"submit",intentId:"calc_probe"}}),
  submitWithIntentRequest:check.Check({{...base,operation:"submit",intentId:"calc_probe",purpose:"bad"}}),
}}));
"""
    result = _node_json(script)
    assert result == {
        "prepare": True,
        "physicalPath": False,
        "oldNode": False,
        "submit": True,
        "submitWithIntentRequest": False,
    }


def test_compute_extension_has_no_model_session_or_scientific_mutation_authority() -> None:
    source = COMPUTE.read_text(encoding="utf-8")
    assert "createAgentSession" not in source
    assert "ts_subagent_compute" not in source
    assert "beginActivity" in source
    assert "createScopedComputeTools" in source
    assert "ts_workspace_decision_apply" not in source
    assert "append_observation" not in source
    assert "accept_claim" not in source


def test_action_log_preserves_ambiguous_control_and_redacts_secrets() -> None:
    script = (
        f"const helper=require({json.dumps(str(ACTION_LOG))});"
        "const ambiguous={state:'unknown',error_class:'submission_ambiguous',control:{effect_outcome:'unknown'}};"
        "const staged={state:'failed',error_class:'remote_staging_failed',control:{effect_outcome:'failed'}};"
        "const diagnostic=helper.sanitizeActionError(new Error('Bearer abc token=secret https://user:pass@example.org'));"
        "process.stdout.write(JSON.stringify({ambiguous:helper.actionStatusForResult(ambiguous),staged:helper.actionStatusForResult(staged),diagnostic}));"
    )
    result = json.loads(_node(script).stdout)
    assert result["ambiguous"] == "unknown"
    assert result["staged"] == "failed"
    assert "abc" not in result["diagnostic"]["message"]
    assert "secret" not in result["diagnostic"]["message"]
    assert "user:pass" not in result["diagnostic"]["message"]


def test_action_log_extracts_only_canonical_compute_results() -> None:
    script = (
        f"const helper=require({json.dumps(str(ACTION_LOG))});"
        "const direct={schema_version:'ts-calculation-result/2',state:'prepared'};"
        "const envelope={result:{schema_version:'ts-calculation-result/2',state:'completed'}};"
        "let error;try{helper.extractComputeToolResult({ok:true},'probe')}catch(e){error=e.message}"
        "process.stdout.write(JSON.stringify({direct:helper.extractComputeToolResult(direct,'probe'),envelope:helper.extractComputeToolResult(envelope,'probe'),error}));"
    )
    result = json.loads(_node(script).stdout)
    assert result["direct"]["state"] == "prepared"
    assert result["envelope"]["state"] == "completed"
    assert "no canonical compute result" in result["error"]


def _node(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _node_json(script: str) -> dict:
    completed = subprocess.run(
        ["node", "--experimental-loader", str(TS_LOADER), "--input-type=module", "--eval", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)
