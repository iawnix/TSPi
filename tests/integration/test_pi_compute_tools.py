from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ts_agent.calculation_contracts import validate_calculation_contract


ROOT = Path(__file__).resolve().parents[2]
TS_LOADER = ROOT / "tests" / "support" / "typescript_loader.mjs"
COMPUTE = ROOT / "extensions" / "pi" / "compute" / "index.ts"
COMPUTE_TOOLS = ROOT / "extensions" / "pi" / "compute" / "tools.ts"
ACTION_LOG = ROOT / "packages" / "ts-agent-runtime" / "agents" / "compute" / "action-log.cjs"


def test_compute_extension_registers_bounded_subagent_and_read_only_remote_tools() -> None:
    script = f"""
import install from {json.dumps(COMPUTE.as_uri())};
const tools=[];const commands=[];const pi={{registerTool:(tool)=>tools.push(tool),registerCommand:(name)=>commands.push(name),registerEntryRenderer:()=>{{}},appendEntry:()=>{{}},getThinkingLevel:()=>"off",events:{{emit:()=>{{}}}}}};
install(pi);
process.stdout.write(JSON.stringify({{tools:tools.map((tool)=>tool.name),commands}}));
"""
    result = _node_json(script)
    assert result == {"tools": ["ts_environment", "ts_dispatch", "ts_calc"], "commands": ["compute"]}


def test_compact_compute_schema_uses_logical_artifacts_and_host_enforces_operation_fields() -> None:
    script = f"""
import install from {json.dumps(COMPUTE.as_uri())};
import {{ Compile }} from "typebox/compile";
let compute;const pi={{registerTool:(tool)=>{{if(tool.name==="ts_calc")compute=tool}},registerCommand:()=>{{}},registerEntryRenderer:()=>{{}},appendEntry:()=>{{}},getThinkingLevel:()=>"off",events:{{emit:()=>{{}}}}}};
install(pi);const check=Compile(compute.parameters);
const base={{nodeId:"node_1"}};
const launch={{...base,operation:"launch",purpose:"Single point",capability:"gaussian.sp",capabilityVersion:"1",attemptKind:"primary",inputArtifacts:[{{inputRole:"gjf",artifactId:"art_"+"b".repeat(24)}}],executionTarget:{{kind:"remote",environment:"cluster_1w",resources:{{queue:"batch",nodes:1,ncpus:8,memory:"16gb",walltime:"01:00:00",ngpus:0}}}}}};
const localLaunch={{...launch,executionTarget:{{kind:"local"}}}};
const invalidInspect={{...base,operation:"inspect",intentId:"calc_1",purpose:"bad"}};
let hostError="";
try {{ await compute.execute("call-1",invalidInspect,undefined,()=>{{}},{{cwd:"/tmp"}}); }} catch(error) {{ hostError=error.message; }}
process.stdout.write(JSON.stringify({{
  launch:check.Check(launch),
  localLaunch:check.Check(localLaunch),
  physicalPath:check.Check({{...launch,inputArtifacts:[{{inputRole:"gjf",artifactId:"inputs/test.gjf"}}]}}),
  oldNode:check.Check({{...launch,nodeId:undefined,nodeId:"n001"}}),
  inspect:check.Check({{...base,operation:"inspect",intentId:"calc_1"}}),
  noncanonicalIntent:check.Check({{...base,operation:"inspect",intentId:"calc_probe"}}),
  compactSchemaAcceptsCrossOperationField:check.Check(invalidInspect),
  hostError,
}}));
"""
    result = _node_json(script)
    assert result == {
        "launch": True,
        "localLaunch": True,
        "physicalPath": False,
        "oldNode": False,
        "inspect": True,
        "noncanonicalIntent": False,
        "compactSchemaAcceptsCrossOperationField": True,
        "hostError": "inspect does not accept: purpose",
    }


def test_compute_extension_delegates_fixed_plan_with_one_run_journal_owner() -> None:
    source = COMPUTE_TOOLS.read_text(encoding="utf-8")
    assert "createAgentSession" not in source
    assert "runComputeOperator" in source
    assert "buildComputeTask" in source
    assert "beginAgentRun" in source
    assert "beginActivity" not in source
    assert "createScopedComputeTools" in source
    assert "settleFailedAgentRun" in source
    assert '"compute_result_journal_failed"' in source
    assert '"compute_activity_journal_failed"' not in source
    assert '"compute_result_delivery_failed"' in source
    assert 'onStage?.("intent_creation")' in source
    assert 'onStage?.("preflight")' in source
    assert "ts_change" not in source
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


def test_action_log_fails_a_program_that_completed_without_completing_its_task() -> None:
    script = (
        f"const helper=require({json.dumps(str(ACTION_LOG))});"
        "const result={state:'completed',program_status:'completed',"
        "task_validation:{status:'incomplete',failures:['optimization_not_converged']}};"
        "process.stdout.write(JSON.stringify({status:helper.actionStatusForResult(result)}));"
    )
    assert json.loads(_node(script).stdout) == {"status": "failed"}


def test_untyped_control_exception_requires_reconciliation_and_stays_schema_valid() -> None:
    script = (
        f"const helper=require({json.dumps(str(ACTION_LOG))});"
        "const actions=[];const action=helper.reserveAction(actions,'ts_workspace_compute_submit');"
        "const result=helper.failAction(action,new Error('connection lost'),{"
        "intentId:'calc_1',nodeId:'node_1',backend:'gaussian',"
        "capability:'gaussian.opt_freq',capabilityVersion:'1',"
        "capabilityDescriptorDigest:'sha256:'+'b'.repeat(64),"
        "outputRoles:['program_output','optimized_geometry','frequencies'],"
        "intentDigest:'sha256:'+'a'.repeat(64)});"
        "process.stdout.write(JSON.stringify({action,result}));"
    )
    payload = json.loads(_node(script).stdout)
    result = payload["result"]
    validate_calculation_contract("calculation_result.schema.json", result)
    assert payload["action"]["result"]["action_status"] == "unknown"
    assert result["state"] == "unknown"
    assert result["error_class"] == "submission_ambiguous"
    assert result["control"] == {
        "schema_version": "ts-control-outcome/1",
        "operation": "submit",
        "phase": "client_result_unknown",
        "effect_outcome": "unknown",
        "effect_attempted": True,
        "retry_disposition": "reconcile_only",
        "reconciliation_required": True,
        "submission_id": None,
        "job_id": None,
    }
    assert result["provenance"]["diagnostic"]["message"] == "connection lost"


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
