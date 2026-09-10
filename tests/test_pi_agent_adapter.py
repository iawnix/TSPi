from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.workspace_helpers import bootstrap_workspace_fixture, start_research_node
from scripts.check_package import SKILL_ENTRIES, validate_version_surfaces


ROOT = Path(__file__).resolve().parents[1]
TS_LOADER = ROOT / "tests" / "typescript_loader.mjs"
EXPECTED_TOOLS = {
    "ts_state",
    "ts_change",
    "ts_remote",
    "ts_review",
    "ts_reply",
    "ts_calc",
    "ts_seed",
    "ts_compare",
    "ts_import",
    "ts_render",
    "ts_report",
    "ts_notify",
}
EXPECTED_COMMANDS = {"ts", "ts-check", "ts-remote", "ts-runs"}


def test_package_manifest_and_profile_expose_skill_family_five_extensions_one_theme() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    validate_version_surfaces()
    assert package["pi"]["skills"] == SKILL_ENTRIES
    assert len(package["pi"]["extensions"]) == 5
    assert package["pi"]["themes"] == ["./themes/ts-theme.json"]
    assert any("packages/ts-agent-runtime/agents/compute" in item for item in package["files"])
    assert all("packages/ts-agent-runtime/agents/artifacts" not in item for item in package["files"])


def test_loaded_extension_inventory_has_two_bounded_child_agents_and_direct_host_tools() -> None:
    script = f"""
import control from {json.dumps((ROOT / 'extensions/ts-workflow-control/index.ts').as_uri())};
import ui from {json.dumps((ROOT / 'extensions/ts-workflow-ui/index.ts').as_uri())};
import review from {json.dumps((ROOT / 'extensions/ts-workflow-review/index.ts').as_uri())};
import compute from {json.dumps((ROOT / 'extensions/ts-workflow-compute/index.ts').as_uri())};
import artifacts from {json.dumps((ROOT / 'extensions/ts-workflow-artifacts/index.ts').as_uri())};
import {{ TS_PUBLIC_TOOL_EXECUTION }} from {json.dumps((ROOT / 'extensions/shared/tool-catalog.ts').as_uri())};
const tools=[];const commands=[];const handlers={{}};
const pi={{
  registerTool:(tool)=>tools.push(tool),registerCommand:(name)=>commands.push(name),
  registerEntryRenderer:()=>{{}},on:(name,handler)=>{{handlers[name]=handler}},
  appendEntry:()=>{{}},sendMessage:()=>{{}},getThinkingLevel:()=>"high",
  events:{{on:()=>()=>{{}}}},exec:async()=>({{code:0,stdout:"{{}}",stderr:""}}),
}};
for (const install of [control,ui,review,compute,artifacts]) install(pi);
process.stdout.write(JSON.stringify({{
  tools:tools.map((tool)=>({{name:tool.name,properties:Object.keys(tool.parameters?.properties||{{}})}})),
  commands,execution:TS_PUBLIC_TOOL_EXECUTION,
}}));
"""
    result = _node_json(script)
    assert {item["name"] for item in result["tools"]} == EXPECTED_TOOLS
    assert set(result["commands"]) == EXPECTED_COMMANDS
    assert {name for name, mode in result["execution"].items() if mode == "child_agent"} == {
        "ts_review", "ts_calc"
    }
    assert result["execution"]["ts_seed"] == "deterministic_artifact"
    assert result["execution"]["ts_compare"] == "deterministic_artifact"
    assert result["execution"]["ts_import"] == "deterministic_artifact"
    assert result["execution"]["ts_render"] == "deterministic_artifact"
    assert result["execution"]["ts_report"] == "deterministic_artifact"
    context = next(item for item in result["tools"] if item["name"] == "ts_state")
    assert "query" in context["properties"]
    assert "operation" in context["properties"]
    assert not any(name.startswith("ts_workspace_") or name.startswith("ts_subagent_") for name in EXPECTED_TOOLS)


def test_public_parameters_use_research_node_and_logical_artifact_vocabulary() -> None:
    script = f"""
import review from {json.dumps((ROOT / 'extensions/ts-workflow-review/index.ts').as_uri())};
import compute from {json.dumps((ROOT / 'extensions/ts-workflow-compute/index.ts').as_uri())};
import artifacts from {json.dumps((ROOT / 'extensions/ts-workflow-artifacts/index.ts').as_uri())};
const tools={{}};const pi={{registerTool:(tool)=>tools[tool.name]=tool,registerCommand:()=>{{}},registerEntryRenderer:()=>{{}},on:()=>{{}},appendEntry:()=>{{}},getThinkingLevel:()=>"off",events:{{on:()=>()=>{{}}}}}};
for (const install of [review,compute,artifacts]) install(pi);
function propertyKeys(schema, found=new Set()) {{
  for (const key of Object.keys(schema?.properties||{{}})) found.add(key);
  for (const branch of [...(schema?.anyOf||[]),...(schema?.oneOf||[]),...(schema?.allOf||[])]) propertyKeys(branch,found);
  return [...found];
}}
process.stdout.write(JSON.stringify(Object.fromEntries(Object.entries(tools).map(([name,tool])=>[name,propertyKeys(tool.parameters)]))));
"""
    schemas = _node_json(script)
    assert "nodeId" in schemas["ts_calc"]
    assert "smiles" in schemas["ts_seed"]
    assert "optimization" in schemas["ts_seed"]
    assert "referenceArtifactId" in schemas["ts_compare"]
    assert "targetArtifactId" in schemas["ts_compare"]
    assert "nodeId" in schemas["ts_import"]
    assert "content" in schemas["ts_import"]
    assert "nodeId" in schemas["ts_render"]
    assert "inputArtifactIds" in schemas["ts_render"]
    assert "packageName" in schemas["ts_report"]
    assert "targetClaimRef" in schemas["ts_review"]
    public_fields = {field for fields in schemas.values() for field in fields}
    assert "actId" not in public_fields
    assert "inputRefs" not in public_fields
    assert "outputRef" not in public_fields


def test_root_skill_and_public_tool_contracts_stay_within_context_budget() -> None:
    skill_bytes = len((ROOT / "skills/tspi-orchestration/SKILL.md").read_bytes())
    script = f"""
import control from {json.dumps((ROOT / 'extensions/ts-workflow-control/index.ts').as_uri())};
import review from {json.dumps((ROOT / 'extensions/ts-workflow-review/index.ts').as_uri())};
import compute from {json.dumps((ROOT / 'extensions/ts-workflow-compute/index.ts').as_uri())};
import artifacts from {json.dumps((ROOT / 'extensions/ts-workflow-artifacts/index.ts').as_uri())};
import {{ packageSourceSystemPrompt }} from {json.dumps((ROOT / 'extensions/shared/package-source-policy.ts').as_uri())};
const tools=[];const pi={{registerTool:(tool)=>tools.push(tool),registerCommand:()=>{{}},registerEntryRenderer:()=>{{}},on:()=>{{}},events:{{on:()=>()=>{{}}}}}};
for (const install of [control,review,compute,artifacts]) install(pi);
const rows=tools.map((tool)=>{{
  const schema=Buffer.byteLength(JSON.stringify(tool.parameters));
  const prose=Buffer.byteLength(String(tool.description||""))+Buffer.byteLength(String(tool.promptSnippet||""))+Buffer.byteLength(JSON.stringify(tool.promptGuidelines||[]));
  return {{name:tool.name,schema,prose,total:schema+prose}};
}});
process.stdout.write(JSON.stringify({{rows,total:rows.reduce((sum,row)=>sum+row.total,0),systemPromptBytes:Buffer.byteLength(packageSourceSystemPrompt())}}));
"""
    measured = _node_json(script)
    by_name = {row["name"]: row for row in measured["rows"]}

    assert skill_bytes <= 7_000
    assert by_name["ts_calc"]["schema"] <= 4_500
    assert measured["total"] <= 13_000
    assert skill_bytes + measured["total"] + measured["systemPromptBytes"] <= 19_800


def test_workspace_cli_compiles_frontier_and_focused_node(tmp_path: Path) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    refs = start_research_node(workspace)
    frontier = _workspace_cli("context", "--root", str(workspace), "--mode", "frontier")
    node = _workspace_cli("context", "--root", str(workspace), "--mode", "node", "--node-ref", refs["node_id"])
    assert frontier["schema_version"] == "ts-context-projection/3"
    assert frontier["focus"]["node_refs"] == [refs["node_id"]]
    assert frontier["workspace_brief"]["nodes"][0]["decision_rationale"]
    assert frontier["workspace_brief"]["nodes"][0]["objective"]
    assert frontier["workspace_brief"]["nodes"][0]["deliverable"]
    assert frontier["workspace_brief"]["nodes"][0]["contract_digest"].startswith("sha256:")
    assert "research_trajectory" not in frontier
    assert node["research_nodes"][0]["node_id"] == refs["node_id"]
    assert "node_index" not in frontier
    assert "gate_results" not in frontier


def test_context_summary_uses_unified_agent_run_counts() -> None:
    script = f"""
import summary from {json.dumps((ROOT / 'extensions/ts-workflow-control/summary.cjs').as_uri())};
const {{buildContextDetails,buildContextSummary}}=summary;
const context={{valid:true,mode:"frontier",projection_id:"ctx_0123456789abcdef01234567",workspace_id:"ws_0123456789abcdef01234567",workspace_revision:"sha256:"+"a".repeat(64),operational_revision:"sha256:"+"b".repeat(64),operational_summary:{{
  agent_run_count:3,agent_run_failed_count:1,agent_run_pending_count:1,
  review_disposition_pending_count:1,calculation_attempt_count:1,
  calculation_attempt_blocking_count:1,
}},calculation_attempts:[{{node_id:"node_1",intent_id:"calc_1",state:"queued",program_status:"not_run",blocks_completion:true}}],workspace_brief:{{phases:[],claims:[],open_findings:[],incomplete_validation:[],nodes:[{{node_id:"node_1",phase_ref:"phase_1",status:"open",title:"Locate saddle",objective:"Locate one first-order saddle.",deliverable:"One verified TS candidate.",attempts:[{{intent_id:"calc_1",state:"queued",program_status:"not_run",blocks_completion:true}}]}}]}}}};
process.stdout.write(JSON.stringify({{details:buildContextDetails(context),summary:buildContextSummary(context)}}));
"""
    result = _node_json(script)
    operational = result["details"]["operationalSummary"]
    assert operational["agentRunCount"] == 3
    assert operational["agentRunFailedCount"] == 1
    assert operational["agentRunPendingCount"] == 1
    assert "agent_runs=3" in result["summary"]
    assert "agent_failures=1" in result["summary"]
    assert "attempts=1" in result["summary"]
    assert "calc_1/queued!" in result["summary"]
    assert "trajectory:" in result["summary"]
    assert "reviews=" not in result["summary"]
    assert "context: mode=frontier; valid=true" in result["summary"]
    assert "delta_tokens:" in result["summary"]
    assert "question=Locate one first-order saddle." in result["summary"]
    assert "deliverable=One verified TS candidate." in result["summary"]
    assert "ctx_0123456789abcdef01234567" not in result["summary"]
    assert "ws_0123456789abcdef01234567" not in result["summary"]


def test_control_prompt_injection_states_authority_without_prescribing_sequence(tmp_path: Path) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    script = f"""
import install from {json.dumps((ROOT / 'extensions/ts-workflow-control/index.ts').as_uri())};
const handlers={{}};const pi={{registerTool:()=>{{}},registerCommand:()=>{{}},registerEntryRenderer:()=>{{}},on:(name,handler)=>handlers[name]=handler}};
install(pi);
const result=await handlers.before_agent_start({{systemPrompt:"BASE"}},{{cwd:{json.dumps(str(workspace))}}});
process.stdout.write(JSON.stringify(result));
"""
    result = _node_json(script)
    prompt = result["systemPrompt"]
    assert "TS workspace active" in prompt
    assert "ts_state" in prompt
    assert "ts_change" in prompt
    assert "Give each changed question" in prompt
    assert "include set_focus with exact claimRefs/nodeRefs" in prompt
    assert "workflow phase" not in prompt.lower()


def test_host_turn_refreshes_bounded_science_without_appending_history(tmp_path: Path) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    script = f"""
import install from {json.dumps((ROOT / 'extensions/ts-workflow-control/index.ts').as_uri())};
const handlers={{}}; let reads=0; let unavailable=false;
const pi={{registerTool:()=>{{}},registerCommand:()=>{{}},registerEntryRenderer:()=>{{}},
  on:(name,handler)=>handlers[name]=handler,
  exec:async (command,args)=>{{
    if (args[0].endsWith("ts_runtime.py")) return {{stdout:JSON.stringify({{configured:true,python_executable:{json.dumps(sys.executable)}}})}};
    if (args[0].endsWith("ts_workspace.py") && args[1] === "context") {{
      if (unavailable) throw new Error("private diagnostic");
      reads++;
      return {{stdout:JSON.stringify({{mode:"frontier",valid:true,workspace_revision:"revision-"+reads,
        workspace_brief:{{nodes:[{{node_id:"node_"+reads,title:"Current research",status:"open"}}]}}}})}};
    }}
    throw new Error("unexpected command");
  }},
}};
install(pi);
process.env.TS_PHONE_WORKER="1";
const first=await handlers.before_agent_start({{systemPrompt:"BASE"}},{{cwd:{json.dumps(str(workspace))}}});
const second=await handlers.before_agent_start({{systemPrompt:"BASE"}},{{cwd:{json.dumps(str(workspace))}}});
unavailable=true;
const failed=await handlers.before_agent_start({{systemPrompt:"BASE"}},{{cwd:{json.dumps(str(workspace))}}});
delete process.env.TS_PHONE_WORKER;
const standalone=await handlers.before_agent_start({{systemPrompt:"BASE"}},{{cwd:{json.dumps(str(workspace))}}});
process.stdout.write(JSON.stringify({{first,second,failed,standalone,reads}}));
"""
    result = _node_json(script)
    assert result["reads"] == 2
    assert "revision-1" in result["first"]["systemPrompt"]
    assert "revision-2" in result["second"]["systemPrompt"]
    assert "revision-1" not in result["second"]["systemPrompt"]
    assert "node_2" in result["second"]["systemPrompt"]
    assert "Current workspace snapshot is unavailable" in result["failed"]["systemPrompt"]
    assert "private diagnostic" not in result["failed"]["systemPrompt"]
    assert "workspace snapshot" not in result["standalone"]["systemPrompt"]
    assert all(set(result[key]) == {"systemPrompt"} for key in ["first", "second", "failed", "standalone"])


def test_state_change_contract_routes_to_the_kernel_without_leaking_other_selectors(tmp_path: Path) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    script = f"""
import control from {json.dumps((ROOT / 'extensions/ts-workflow-control/index.ts').as_uri())};
const calls=[];
const pi={{
  registerTool:(tool)=>{{ if (tool.name === "ts_state") globalThis.stateTool=tool; }},
  registerCommand:()=>{{}}, registerEntryRenderer:()=>{{}}, on:()=>{{}}, appendEntry:()=>{{}},
  exec:async (command,args)=>{{
    calls.push([command,args]);
    if (args[0].endsWith("ts_runtime.py")) return {{stdout:JSON.stringify({{configured:true,python_executable:{json.dumps(sys.executable)}}})}};
    if (args[0].endsWith("ts_workspace.py") && args[1] === "change_contract") return {{stdout:JSON.stringify({{schema_version:"ts-change-operation-catalog/1",selected_operation:"set_focus",operations:[]}})}};
    throw new Error("unexpected command");
  }},
}};
control(pi);
const result=await globalThis.stateTool.execute("tool-1", {{mode:"change_contract",operation:"set_focus",root:{json.dumps(str(workspace))}}}, undefined, undefined, {{cwd:{json.dumps(str(workspace))}}});
let rejected=false;
try {{ await globalThis.stateTool.execute("tool-2", {{mode:"change_contract",operation:"set_focus",root:{json.dumps(str(workspace))},capabilityKind:"compute"}}, undefined, undefined, {{cwd:{json.dumps(str(workspace))}}}); }}
catch (error) {{ rejected=String(error.message).includes("does not accept capability selectors"); }}
process.stdout.write(JSON.stringify({{result,calls,rejected}}));
"""
    result = _node_json(script)
    assert result["result"]["details"]["contract"]["selected_operation"] == "set_focus"
    workspace_calls = [args for command, args in result["calls"] if args and args[0].endswith("ts_workspace.py")]
    assert workspace_calls and workspace_calls[-1][1:4] == ["change_contract", "--root", str(workspace)]
    assert "--operation" in workspace_calls[-1]
    assert workspace_calls[-1][workspace_calls[-1].index("--operation") + 1] == "set_focus"
    assert result["rejected"] is True


def test_ts_change_forwards_unknown_operation_to_kernel_for_explicit_registry_error(tmp_path: Path) -> None:
    """The public envelope stays open; the Python registry owns support errors."""

    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    script = f"""
import {{ readFileSync }} from "node:fs";
import {{ spawnSync }} from "node:child_process";
import control from {json.dumps((ROOT / 'extensions/ts-workflow-control/index.ts').as_uri())};
process.env.TS_AGENT_PYTHON = {json.dumps(sys.executable)};
const calls=[]; let changeTool;
const pi={{
  registerTool:(tool)=>{{ if (tool.name === "ts_change") changeTool=tool; }},
  registerCommand:()=>{{}}, registerEntryRenderer:()=>{{}}, on:()=>{{}}, appendEntry:()=>{{}},
  exec:async (command,args)=>{{
    const requestFlag=args.indexOf("--request-file");
    const request=requestFlag >= 0 ? JSON.parse(readFileSync(args[requestFlag+1],"utf8")) : null;
    calls.push({{command,args,request}});
    const result=spawnSync(command,args,{{encoding:"utf8"}});
    return {{code:result.status,stdout:result.stdout,stderr:result.stderr}};
  }},
}};
control(pi);
let error="";
try {{ await changeTool.execute("tool-1",{{root:{json.dumps(str(workspace))},rationale:"Probe registry ownership.",operations:[{{op:"future_science_operation",payload:"kept"}}]}},undefined,undefined,{{cwd:{json.dumps(str(workspace))}}}); }}
catch (caught) {{ error=String(caught.message||caught); }}
process.stdout.write(JSON.stringify({{error,calls}}));
"""
    result = _node_json(script)

    assert "unsupported change operation: future_science_operation" in result["error"]
    workspace_calls = [
        call for call in result["calls"]
        if call["args"] and call["args"][0].endswith("ts_workspace.py")
    ]
    assert len(workspace_calls) == 1
    assert workspace_calls[0]["args"][1] == "change"
    assert workspace_calls[0]["request"]["operations"][0]["op"] == "future_science_operation"
    assert workspace_calls[0]["request"]["operations"][0]["payload"] == "kept"


def test_review_fallback_failure_uses_review_runtime_taxonomy() -> None:
    source = (ROOT / "extensions" / "ts-workflow-review" / "index.ts").read_text(encoding="utf-8")

    assert 'failure_class: "review_runtime_failed"' in source
    assert 'failure_stage: "review_runtime"' in source
    assert 'failure_domain: "review"' in source
    assert "review_operator" not in source


def _workspace_cli(*args: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "ts_workspace.py"), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


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
