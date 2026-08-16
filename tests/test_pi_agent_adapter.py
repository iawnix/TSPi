from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.v4_helpers import bootstrap_v4_workspace, start_research_act


ROOT = Path(__file__).resolve().parents[1]
TS_LOADER = ROOT / "tests" / "typescript_loader.mjs"
EXPECTED_TOOLS = {
    "ts_workspace_context",
    "ts_workspace_decision_draft",
    "ts_workspace_decision_validate",
    "ts_workspace_decision_apply",
    "ts_remote_inspect",
    "ts_subagent_review",
    "ts_review_disposition",
    "ts_compute",
    "ts_structure_seed",
    "ts_artifact_import",
    "ts_render",
    "ts_report",
    "ts_notify_user",
}
EXPECTED_COMMANDS = {"ts-context", "ts-validate", "ts-remote", "ts-subagent-history"}


def test_package_manifest_and_profile_expose_one_skill_five_extensions_one_theme() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert package["version"] == "0.10.1"
    assert package["pi"]["skills"] == ["./skills/transition-state-workflow"]
    assert len(package["pi"]["extensions"]) == 5
    assert package["pi"]["themes"] == ["./themes/ts-theme.json"]
    assert all("src/agents/compute" not in item and "src/agents/artifacts" not in item for item in package["files"])


def test_loaded_extension_inventory_has_one_child_agent_and_direct_host_tools() -> None:
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
    assert [name for name, mode in result["execution"].items() if mode == "child_agent"] == ["ts_subagent_review"]
    assert result["execution"]["ts_compute"] == "deterministic_execution"
    assert result["execution"]["ts_structure_seed"] == "deterministic_artifact"
    assert result["execution"]["ts_artifact_import"] == "deterministic_artifact"
    assert result["execution"]["ts_render"] == "deterministic_artifact"
    assert result["execution"]["ts_report"] == "deterministic_artifact"


def test_public_parameters_use_research_act_and_logical_artifact_vocabulary() -> None:
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
    assert "actId" in schemas["ts_compute"]
    assert "smiles" in schemas["ts_structure_seed"]
    assert "optimization" in schemas["ts_structure_seed"]
    assert "actId" in schemas["ts_artifact_import"]
    assert "content" in schemas["ts_artifact_import"]
    assert "actId" in schemas["ts_render"]
    assert "inputArtifactIds" in schemas["ts_render"]
    assert "packageName" in schemas["ts_report"]
    assert "targetClaimRef" in schemas["ts_subagent_review"]
    serialized = json.dumps(schemas)
    assert "nodeId" not in serialized
    assert "inputRefs" not in serialized
    assert "outputRef" not in serialized


def test_root_skill_and_public_tool_contracts_stay_within_context_budget() -> None:
    skill_bytes = len((ROOT / "skills/transition-state-workflow/SKILL.md").read_bytes())
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
    assert by_name["ts_compute"]["schema"] <= 3_100
    assert measured["total"] <= 13_000
    assert skill_bytes + measured["total"] + measured["systemPromptBytes"] <= 19_800


def test_workspace_cli_compiles_v4_frontier_and_focused_act(tmp_path: Path) -> None:
    workspace = bootstrap_v4_workspace(tmp_path / "workspace")
    refs = start_research_act(workspace)
    frontier = _workspace_cli("context", "--root", str(workspace), "--mode", "frontier")
    act = _workspace_cli("context", "--root", str(workspace), "--mode", "act", "--act-ref", refs["act_id"])
    assert frontier["schema_version"] == "ts-context-projection/1"
    assert frontier["focus"]["act_refs"] == [refs["act_id"]]
    assert act["research_acts"][0]["act_id"] == refs["act_id"]
    assert "node_index" not in frontier
    assert "gate_results" not in frontier


def test_control_prompt_injection_states_v4_authority_without_prescribing_sequence(tmp_path: Path) -> None:
    workspace = bootstrap_v4_workspace(tmp_path / "workspace")
    script = f"""
import install from {json.dumps((ROOT / 'extensions/ts-workflow-control/index.ts').as_uri())};
const handlers={{}};const pi={{registerTool:()=>{{}},registerCommand:()=>{{}},registerEntryRenderer:()=>{{}},on:(name,handler)=>handlers[name]=handler}};
install(pi);
const result=await handlers.before_agent_start({{systemPrompt:"BASE"}},{{cwd:{json.dumps(str(workspace))}}});
process.stdout.write(JSON.stringify(result));
"""
    result = _node_json(script)
    prompt = result["systemPrompt"]
    assert "TS v4 workspace active" in prompt
    assert "ts_workspace_context" in prompt
    assert "ts_workspace_decision_apply" in prompt
    assert "start_node" not in prompt
    assert "workflow phase" not in prompt.lower()


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
