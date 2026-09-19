from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.support.workspace_helpers import bootstrap_workspace_fixture, start_research_node
from scripts.check_package import SKILL_ENTRIES, validate_version_surfaces


ROOT = Path(__file__).resolve().parents[2]
TS_LOADER = ROOT / "tests" / "support" / "typescript_loader.mjs"
EXPECTED_TOOLS = {
    "sys_prompt",
    "ts_state",
    "ts_change",
    "ts_environment",
    "ts_review",
    "ts_reply",
    "ts_calc",
    "ts_seed",
    "ts_compare",
    "ts_analyze",
    "ts_dispatch",
    "ts_import",
    "ts_render",
    "ts_report",
    "ts_notify",
}
EXPECTED_COMMANDS = {"research", "compute", "runs", "debug"}


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
import research from {json.dumps((ROOT / 'extensions/pi/research/index.ts').as_uri())};
import ui from {json.dumps((ROOT / 'extensions/pi/ui/index.ts').as_uri())};
import review from {json.dumps((ROOT / 'extensions/pi/review/index.ts').as_uri())};
import compute from {json.dumps((ROOT / 'extensions/pi/compute/index.ts').as_uri())};
import artifacts from {json.dumps((ROOT / 'extensions/pi/artifacts/index.ts').as_uri())};
import {{ PUBLIC_TOOL_EXECUTION }} from {json.dumps((ROOT / 'packages/ts-agent-runtime/host-api/tools.mjs').as_uri())};
const tools=[];const commands=[];const handlers={{}};
const pi={{
  registerTool:(tool)=>tools.push(tool),registerCommand:(name)=>commands.push(name),
  registerEntryRenderer:()=>{{}},on:(name,handler)=>{{handlers[name]=handler}},
  appendEntry:()=>{{}},sendMessage:()=>{{}},getThinkingLevel:()=>"high",
  events:{{on:()=>()=>{{}}}},exec:async()=>({{code:0,stdout:"{{}}",stderr:""}}),
}};
for (const install of [research,ui,review,compute,artifacts]) install(pi);
process.stdout.write(JSON.stringify({{
  tools:tools.map((tool)=>({{name:tool.name,properties:Object.keys(tool.parameters?.properties||{{}})}})),
  commands,execution:PUBLIC_TOOL_EXECUTION,
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
    assert result["execution"]["ts_analyze"] == "deterministic_artifact"
    assert result["execution"]["ts_import"] == "deterministic_artifact"
    assert result["execution"]["ts_render"] == "deterministic_artifact"
    assert result["execution"]["ts_report"] == "deterministic_artifact"
    context = next(item for item in result["tools"] if item["name"] == "ts_state")
    assert "query" in context["properties"]
    assert "mode" in context["properties"]
    assert not any(name.startswith("ts_workspace_") or name.startswith("ts_subagent_") for name in EXPECTED_TOOLS)


def test_pi_extensions_register_only_their_owned_tools() -> None:
    script = f"""
import research from {json.dumps((ROOT / 'extensions/pi/research/index.ts').as_uri())};
import review from {json.dumps((ROOT / 'extensions/pi/review/index.ts').as_uri())};
import compute from {json.dumps((ROOT / 'extensions/pi/compute/index.ts').as_uri())};
import artifacts from {json.dumps((ROOT / 'extensions/pi/artifacts/index.ts').as_uri())};
function collect(install) {{
  const tools=[];
  const pi={{
    registerTool:(tool)=>tools.push(tool.name),registerCommand:()=>{{}},registerEntryRenderer:()=>{{}},
    on:()=>{{}},appendEntry:()=>{{}},getThinkingLevel:()=>"off",events:{{on:()=>()=>{{}}}},
  }};
  install(pi);
  return tools;
}}
process.stdout.write(JSON.stringify({{
  research:collect(research),review:collect(review),compute:collect(compute),artifacts:collect(artifacts),
}}));
"""
    result = _node_json(script)

    assert set(result["research"]) == {"sys_prompt", "ts_state", "ts_change", "ts_notify"}
    assert set(result["review"]) == {"ts_review", "ts_reply"}
    assert set(result["compute"]) == {"ts_environment", "ts_dispatch", "ts_calc"}
    assert set(result["artifacts"]) == {
        "ts_seed", "ts_import", "ts_compare", "ts_analyze", "ts_render", "ts_report"
    }


def test_pi_and_native_public_tools_share_names_and_parameter_schemas() -> None:
    script = f"""
import research from {json.dumps((ROOT / 'extensions/pi/research/index.ts').as_uri())};
import review from {json.dumps((ROOT / 'extensions/pi/review/index.ts').as_uri())};
import compute from {json.dumps((ROOT / 'extensions/pi/compute/index.ts').as_uri())};
import artifacts from {json.dumps((ROOT / 'extensions/pi/artifacts/index.ts').as_uri())};
import {{ createTspiTools }} from {json.dumps((ROOT / 'apps/app-server/pi-native-tools.mjs').as_uri())};
import {{ createSystemPromptTool }} from {json.dumps((ROOT / 'apps/app-server/system-prompt.mjs').as_uri())};
const extensionTools=[];
const pi={{
  registerTool:(tool)=>extensionTools.push(tool),registerCommand:()=>{{}},registerEntryRenderer:()=>{{}},
  on:()=>{{}},appendEntry:()=>{{}},getThinkingLevel:()=>"off",events:{{on:()=>()=>{{}}}},
}};
for (const install of [research,review,compute,artifacts]) install(pi);
const nativeTools=[createSystemPromptTool({{}}),...createTspiTools()];
const schemas=(tools)=>Object.fromEntries(tools.map((tool)=>[tool.name,JSON.parse(JSON.stringify(tool.parameters))]));
process.stdout.write(JSON.stringify({{extension:schemas(extensionTools),native:schemas(nativeTools)}}));
"""
    result = _node_json(script)

    assert set(result["extension"]) == EXPECTED_TOOLS
    assert set(result["native"]) == EXPECTED_TOOLS
    assert result["extension"] == result["native"]


def test_slash_commands_map_to_canonical_commands_and_reject_removed_aliases() -> None:
    script = f"""
import {{ parseSlashCommand }} from {json.dumps((ROOT / 'packages/ts-agent-runtime/host-api/commands.mjs').as_uri())};
import {{ createPublicToolContracts }} from {json.dumps((ROOT / 'packages/ts-agent-runtime/host-api/tools.mjs').as_uri())};
import {{ Type }} from "typebox";
const cases=[
  ["research",""],
  ["research","detail node node_1"],
  ["research","locate activation barrier"],
  ["compute",""],
  ["compute","show local"],
  ["runs",""],
].map(([name,input])=>parseSlashCommand(name,input));
let removedAlias;
try {{ parseSlashCommand("research","find activation barrier"); }}
catch (error) {{ removedAlias={{name:error.name,message:error.message}}; }}
function constants(schema) {{
  if (Object.hasOwn(schema||{{}},"const")) return [schema.const];
  return [...(schema?.anyOf||[]),...(schema?.oneOf||[])].flatMap(constants);
}}
const stateModes=constants(createPublicToolContracts(Type).state.parameters.properties.mode);
process.stdout.write(JSON.stringify({{cases,removedAlias,stateModes}}));
"""
    result = _node_json(script)

    assert result["cases"] == [
        {"command": "research.summary", "params": {}},
        {"command": "research.detail", "params": {"kind": "node", "id": "node_1"}},
        {"command": "research.locate", "params": {"query": "activation barrier"}},
        {"command": "compute.environments", "params": {}},
        {"command": "compute.environment", "params": {"name": "local"}},
        {"command": "compute.runs", "params": {}},
    ]
    assert result["removedAlias"]["name"] == "CommandUsageError"
    assert all(alias not in result["stateModes"] for alias in ("claim", "node", "finding", "gate"))


def test_model_icons_identify_known_providers_and_fall_back_for_unknown_models() -> None:
    script = f"""
import {{ tspiIcon, tspiIconStyle, tspiModelIconName, tspiModelIconLabel }} from {json.dumps((ROOT / 'extensions/pi/shared/icons.ts').as_uri())};
const models=[
  {{provider:"deepseek",id:"deepseek-chat"}},
  {{provider:"openai",id:"gpt-5.5"}},
  {{provider:"zai-coding-cn",id:"glm-4.5"}},
  {{provider:"volcengine",id:"doubao-seed-1.6"}},
  {{provider:"custom",id:"local-model"}},
  undefined,
];
process.stdout.write(JSON.stringify({{models:models.map((model)=>({{name:tspiModelIconName(model),label:tspiModelIconLabel(model,"unicode")}})),tspi:tspiIcon("deepseek","tspi"),fallback:tspiIcon("session","tspi"),style:tspiIconStyle("custom")}}));
"""
    result = _node_json(script)
    assert [item["name"] for item in result["models"]] == ["deepseek", "gpt", "glm", "seeddance", "model", "model"]
    assert result["models"][0]["label"].endswith("deepseek-chat")
    assert result["models"][4]["label"].endswith("local-model")
    assert result["models"][5]["label"].endswith("Default model")
    assert ord(result["tspi"]) == 0xF0000
    assert result["fallback"] == "◆"
    assert result["style"] == "tspi"


def test_public_parameters_use_research_node_and_logical_artifact_vocabulary() -> None:
    script = f"""
import review from {json.dumps((ROOT / 'extensions/pi/review/index.ts').as_uri())};
import compute from {json.dumps((ROOT / 'extensions/pi/compute/index.ts').as_uri())};
import artifacts from {json.dumps((ROOT / 'extensions/pi/artifacts/index.ts').as_uri())};
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
    assert "inputName" in schemas["ts_import"]
    assert "content" in schemas["ts_import"]
    assert "nodeId" in schemas["ts_render"]
    assert "inputArtifactIds" in schemas["ts_render"]
    assert "packageName" in schemas["ts_report"]
    assert "targetClaimId" in schemas["ts_review"]
    public_fields = {field for fields in schemas.values() for field in fields}
    assert "actId" not in public_fields
    assert "inputRefs" not in public_fields
    assert "outputRef" not in public_fields


def test_root_skill_and_public_tool_contracts_stay_within_context_budget() -> None:
    skill_bytes = len((ROOT / "skills/tspi-orchestration/SKILL.md").read_bytes())
    script = f"""
import research from {json.dumps((ROOT / 'extensions/pi/research/index.ts').as_uri())};
import review from {json.dumps((ROOT / 'extensions/pi/review/index.ts').as_uri())};
import compute from {json.dumps((ROOT / 'extensions/pi/compute/index.ts').as_uri())};
import artifacts from {json.dumps((ROOT / 'extensions/pi/artifacts/index.ts').as_uri())};
import {{ packageSourceSystemPrompt }} from {json.dumps((ROOT / 'extensions/pi/shared/package-source-policy.ts').as_uri())};
const tools=[];const pi={{registerTool:(tool)=>tools.push(tool),registerCommand:()=>{{}},registerEntryRenderer:()=>{{}},on:()=>{{}},events:{{on:()=>()=>{{}}}}}};
for (const install of [research,review,compute,artifacts]) install(pi);
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
    # Preserve the previous surface budget; new analyses share one small
    # envelope with domain schemas loaded through the capability catalog.
    analysis_bytes = by_name["ts_analyze"]["total"]
    management_bytes = by_name["ts_dispatch"]["total"]
    assert analysis_bytes <= 900
    assert management_bytes <= 500
    assert measured["total"] - analysis_bytes - management_bytes <= 13_000
    assert skill_bytes + measured["total"] - analysis_bytes - management_bytes + measured["systemPromptBytes"] <= 19_800


def test_workspace_cli_compiles_frontier_and_focused_node(tmp_path: Path) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    refs = start_research_node(workspace)
    summary = _api_cli("research.summary", workspace)
    node = _api_cli("research.detail", workspace, "--kind", "node", "--id", refs["node_id"])
    assert summary["schema_version"] == "research-summary/1"
    assert summary["progress"]["node_count"] == 1
    assert summary["focus_node_ids"] == [refs["node_id"]]
    assert node["schema_version"] == "research-detail/1"
    assert node["object"]["id"] == refs["node_id"]
    assert node["object"]["type"] == "research_node"


def test_context_summary_uses_unified_agent_run_counts() -> None:
    script = f"""
import summary from {json.dumps((ROOT / 'extensions/pi/shared/tool-runtime.cjs').as_uri())};
const {{buildContextDetails,buildContextSummary}}=summary;
    const context={{schema_version:"research-summary/1",map_id:"map_1",title:"Locate saddle",revision:3,progress:{{phase_count:1,claim_count:1,node_count:1,finding_count:0,gate_count:0,closed_node_count:0,open_issue_count:0}},focus_claim_ids:["claim_1"],focus_node_ids:["node_1"]}};
process.stdout.write(JSON.stringify({{details:buildContextDetails(context),summary:buildContextSummary(context)}}));
"""
    result = _node_json(script)
    assert result["details"]["mapId"] == "map_1"
    assert result["details"]["focusNodeIds"] == ["node_1"]
    assert "ResearchMap context:" in result["summary"]
    assert "map_1" in result["summary"]


def test_research_prompt_injection_states_authority_without_prescribing_sequence(tmp_path: Path) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    script = f"""
import install from {json.dumps((ROOT / 'extensions/pi/research/index.ts').as_uri())};
const handlers={{}};const pi={{registerTool:()=>{{}},registerCommand:()=>{{}},registerEntryRenderer:()=>{{}},on:(name,handler)=>handlers[name]=handler}};
install(pi);
const result=await handlers.before_agent_start({{systemPrompt:"BASE"}},{{cwd:{json.dumps(str(workspace))}}});
process.stdout.write(JSON.stringify(result));
"""
    result = _node_json(script)
    prompt = result["systemPrompt"]
    assert "ResearchMap workspace active" in prompt
    assert "ts_state" in prompt
    assert "ts_change" in prompt
    assert "ResearchPhase, ResearchNode, ResearchClaim, Finding, and Gate are map objects" in prompt
    assert "Query ts_state mode=operations before using an unfamiliar map operation" in prompt
    assert "workflow phase" not in prompt.lower()


def test_sys_prompt_reports_exact_pi_prompt_and_honest_extension_provenance(tmp_path: Path) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    visible_path = str(tmp_path / "skills" / "visible" / "SKILL.md")
    hidden_path = str(tmp_path / "skills" / "hidden" / "SKILL.md")
    script = f"""
import install from {json.dumps((ROOT / 'extensions/pi/research/index.ts').as_uri())};
import {{ formatSkillsForPrompt }} from "@earendil-works/pi-coding-agent";
const handlers={{}};const tools={{}};
const pi={{
  registerTool:(tool)=>tools[tool.name]=tool,registerCommand:()=>{{}},registerEntryRenderer:()=>{{}},
  on:(name,handler)=>handlers[name]=handler,
}};
install(pi);
const sourceInfo={{path:"package",source:"test-package",scope:"project",origin:"package"}};
const visible={{name:"visible",description:"Visible skill",filePath:{json.dumps(visible_path)},baseDir:"/skills/visible",sourceInfo,disableModelInvocation:false}};
const hidden={{name:"hidden",description:"Hidden skill",filePath:{json.dumps(hidden_path)},baseDir:"/skills/hidden",sourceInfo,disableModelInvocation:true}};
const options={{
  cwd:{json.dumps(str(workspace))},selectedTools:["read","sys_prompt","ts_state"],
  toolSnippets:{{sys_prompt:"Inspect prompt"}},promptGuidelines:["One guideline"],
  contextFiles:[{{path:"/workspace/AGENTS.md",content:"Workspace instructions"}}],skills:[visible,hidden],
}};
const before=`PI NATIVE${{formatSkillsForPrompt(options.skills,"read")}}`;
const tspi=await handlers.before_agent_start({{systemPrompt:before,systemPromptOptions:options}},{{cwd:options.cwd}});
const effective=`${{tspi.systemPrompt}}\n\nTHIRD PARTY EXTENSION`;
const result=await tools.sys_prompt.execute("prompt-1",{{}},undefined,undefined,{{getSystemPrompt:()=>effective}});
process.stdout.write(JSON.stringify({{manifest:JSON.parse(result.content[0].text),details:result.details,effective}}));
"""
    result = _node_json(script)
    manifest = result["manifest"]

    assert manifest["schema_version"] == "tspi-system-prompt/2"
    assert manifest["runtime"] == "pi-extension"
    assert manifest["effective"] == result["effective"]
    assert manifest["provenance_complete"] is False
    assert result["details"]["provenanceComplete"] is False
    by_origin = {}
    for contributor in manifest["contributors"]:
        by_origin.setdefault(contributor["origin"], []).append(contributor)
    assert by_origin["native"][0]["attribution"] == "structured"
    assert by_origin["native"][0]["metadata"]["context_files"] == ["/workspace/AGENTS.md"]
    assert by_origin["skill"][0]["attribution"] == "exact"
    assert by_origin["skill"][0]["inputs"] == [visible_path]
    assert hidden_path not in json.dumps(manifest)
    assert by_origin["extension"][0]["attribution"] == "exact"
    assert "ResearchMap workspace active" in by_origin["extension"][0]["text"]
    assert any(item.get("text") == "\n\nTHIRD PARTY EXTENSION" for item in by_origin["unknown"])
    assert not any("THIRD PARTY EXTENSION" in item.get("text", "") for item in by_origin["native"])


def test_sys_prompt_command_renders_the_same_manifest_as_the_tool() -> None:
    script = f"""
import install from {json.dumps((ROOT / 'extensions/pi/research/index.ts').as_uri())};
const commands={{}}; const entries=[]; const notices=[];
const pi={{
  registerTool:()=>{{}}, registerCommand:(name,command)=>commands[name]=command,
  registerEntryRenderer:()=>{{}}, on:()=>{{}},
  appendEntry:(type,data)=>entries.push({{type,data}}),
}};
install(pi);
const ctx={{
  signal:undefined, getSystemPrompt:()=>"ACTIVE PROMPT",
  ui:{{notify:(message,level)=>notices.push({{message,level}})}},
}};
await commands.debug.handler("prompt",ctx);
await commands.debug.handler("unexpected",ctx);
process.stdout.write(JSON.stringify({{entries,notices,description:commands.debug.description}}));
"""
    result = _node_json(script)
    assert result["description"].startswith("Inspect TSPi runtime diagnostics")
    assert len(result["entries"]) == 1
    assert result["entries"][0]["type"] == "ts-system-prompt"
    manifest = result["entries"][0]["data"]["manifest"]
    assert manifest["schema_version"] == "tspi-system-prompt/2"
    assert manifest["effective"] == "ACTIVE PROMPT"
    assert result["notices"] == [{"message": "Usage: /debug prompt", "level": "warning"}]


def test_extension_turn_refreshes_bounded_science_without_appending_history(tmp_path: Path) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    script = f"""
import install from {json.dumps((ROOT / 'extensions/pi/research/index.ts').as_uri())};
const handlers={{}}; const tools={{}}; let reads=0; let unavailable=false;
const pi={{registerTool:(tool)=>tools[tool.name]=tool,registerCommand:()=>{{}},registerEntryRenderer:()=>{{}},
  on:(name,handler)=>handlers[name]=handler,
  exec:async (command,args)=>{{
    if (args[0].endsWith("ts_runtime.py")) return {{stdout:JSON.stringify({{configured:true,python_executable:{json.dumps(sys.executable)}}})}};
    if (args[0].endsWith("ts_api.py") && args[1] === "research.summary") {{
      if (unavailable) throw new Error("private diagnostic");
      reads++;
      return {{stdout:JSON.stringify({{schema_version:"research-summary/1",valid:true,revision:reads,
        focus_claim_ids:["claim_"+reads],focus_node_ids:["node_"+reads],progress:{{node_count:reads}}}})}};
    }}
    throw new Error("unexpected command");
  }},
}};
install(pi);
const inspect=async (prompt,index)=>JSON.parse((await tools.sys_prompt.execute(`prompt-${{index}}`,{{}},undefined,undefined,{{getSystemPrompt:()=>prompt.systemPrompt}})).content[0].text);
const first=await handlers.before_agent_start({{systemPrompt:"BASE"}},{{cwd:{json.dumps(str(workspace))}}});
const firstManifest=await inspect(first,1);
const second=await handlers.before_agent_start({{systemPrompt:"BASE"}},{{cwd:{json.dumps(str(workspace))}}});
const secondManifest=await inspect(second,2);
unavailable=true;
const failed=await handlers.before_agent_start({{systemPrompt:"BASE"}},{{cwd:{json.dumps(str(workspace))}}});
const failedManifest=await inspect(failed,3);
const standalone=await handlers.before_agent_start({{systemPrompt:"BASE"}},{{cwd:{json.dumps(str(workspace))}}});
const standaloneManifest=await inspect(standalone,4);
process.stdout.write(JSON.stringify({{first,second,failed,standalone,firstManifest,secondManifest,failedManifest,standaloneManifest,reads}}));
"""
    result = _node_json(script)
    assert result["reads"] == 2
    assert '"revision": 1' in result["first"]["systemPrompt"]
    assert '"revision": 2' in result["second"]["systemPrompt"]
    assert '"revision": 1' not in result["second"]["systemPrompt"]
    assert "node_2" in result["second"]["systemPrompt"]
    assert "Current workspace snapshot is unavailable" in result["failed"]["systemPrompt"]
    assert "private diagnostic" not in result["failed"]["systemPrompt"]
    assert "Current workspace snapshot is unavailable" in result["standalone"]["systemPrompt"]
    assert all(set(result[key]) == {"systemPrompt"} for key in ["first", "second", "failed", "standalone"])
    for prompt_key, manifest_key in [
        ("first", "firstManifest"),
        ("second", "secondManifest"),
        ("failed", "failedManifest"),
        ("standalone", "standaloneManifest"),
    ]:
        manifest = result[manifest_key]
        assert manifest["effective"] == result[prompt_key]["systemPrompt"]
        assert manifest["runtime"] == "pi-extension"
        assert manifest["provenance_complete"] is False
        extension = next(item for item in manifest["contributors"] if item["origin"] == "extension")
        assert extension["attribution"] == "exact"
    assert '"revision": 1' in next(
        item for item in result["firstManifest"]["contributors"] if item["origin"] == "extension"
    )["text"]
    assert "Current workspace snapshot is unavailable" in next(
        item for item in result["failedManifest"]["contributors"] if item["origin"] == "extension"
    )["text"]
    assert "Current workspace snapshot is unavailable" in next(
        item for item in result["standaloneManifest"]["contributors"] if item["origin"] == "extension"
    )["text"]


def test_state_operations_routes_to_the_kernel_without_leaking_other_selectors(tmp_path: Path) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    script = f"""
import research from {json.dumps((ROOT / 'extensions/pi/research/index.ts').as_uri())};
const calls=[];
const pi={{
  registerTool:(tool)=>{{ if (tool.name === "ts_state") globalThis.stateTool=tool; }},
  registerCommand:()=>{{}}, registerEntryRenderer:()=>{{}}, on:()=>{{}}, appendEntry:()=>{{}},
  exec:async (command,args)=>{{
    calls.push([command,args]);
    if (args[0].endsWith("ts_runtime.py")) return {{stdout:JSON.stringify({{configured:true,python_executable:{json.dumps(sys.executable)}}})}};
    if (args[0].endsWith("ts_api.py") && args[1] === "research.operations") return {{stdout:JSON.stringify({{schema_version:"research-operation-catalog/1",operations:[]}})}};
    throw new Error("unexpected command");
  }},
}};
research(pi);
const result=await globalThis.stateTool.execute("tool-1", {{mode:"operations",root:{json.dumps(str(workspace))}}}, undefined, undefined, {{cwd:{json.dumps(str(workspace))}}});
let rejected=false;
try {{ await globalThis.stateTool.execute("tool-2", {{mode:"operations",root:{json.dumps(str(workspace))},capabilityKind:"compute"}}, undefined, undefined, {{cwd:{json.dumps(str(workspace))}}}); }}
catch (error) {{ rejected=String(error.message).includes("does not accept capability selectors"); }}
process.stdout.write(JSON.stringify({{result,calls,rejected}}));
"""
    result = _node_json(script)
    assert result["result"]["details"]["result"]["schema_version"] == "research-operation-catalog/1"
    workspace_calls = [args for command, args in result["calls"] if args and args[0].endswith("ts_api.py")]
    assert workspace_calls and workspace_calls[-1][1:4] == ["research.operations", "--root", str(workspace)]
    assert result["rejected"] is True


def test_ts_change_forwards_unknown_operation_to_kernel_for_explicit_registry_error(tmp_path: Path) -> None:
    """The public envelope stays open; the ResearchKernel owns support errors."""

    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    script = f"""
import {{ readFileSync }} from "node:fs";
import {{ spawnSync }} from "node:child_process";
import research from {json.dumps((ROOT / 'extensions/pi/research/index.ts').as_uri())};
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
research(pi);
let error="";
try {{ await changeTool.execute("tool-1",{{root:{json.dumps(str(workspace))},rationale:"Probe kernel ownership.",operations:[{{type:"future_science_operation",payload:"kept"}}]}},undefined,undefined,{{cwd:{json.dumps(str(workspace))}}}); }}
catch (caught) {{ error=String(caught.message||caught); }}
process.stdout.write(JSON.stringify({{error,calls}}));
"""
    result = _node_json(script)

    assert "unsupported ResearchMap operation: future_science_operation" in result["error"]
    workspace_calls = [
        call for call in result["calls"]
        if call["args"] and call["args"][0].endswith("ts_api.py")
    ]
    assert len(workspace_calls) == 1
    assert workspace_calls[0]["args"][1] == "research.change"
    assert workspace_calls[0]["request"]["operations"][0]["type"] == "future_science_operation"
    assert workspace_calls[0]["request"]["operations"][0]["payload"] == "kept"


def test_review_fallback_failure_uses_review_runtime_taxonomy() -> None:
    source = (ROOT / "extensions" / "pi" / "review" / "tools.ts").read_text(encoding="utf-8")

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


def _api_cli(command: str, root: Path, *args: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "ts_api.py"), command, "--root", str(root), *args],
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
