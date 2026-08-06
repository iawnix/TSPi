from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPUTE_AGENT = ROOT / "src" / "agents" / "compute"
OUTPUT_SCHEMA = COMPUTE_AGENT / "output-schema.cjs"
ACTION_LOG = ROOT / "extensions" / "ts-workflow-compute" / "action-log.cjs"
COMPUTE_EXTENSION = ROOT / "extensions" / "ts-workflow-compute" / "index.ts"
TS_LOADER = ROOT / "tests" / "typescript_loader.mjs"


def test_pi_package_registers_one_compute_operator_extension() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    extensions = package["pi"]["extensions"]

    assert "./extensions/ts-workflow-compute/index.ts" in extensions
    assert [value for value in extensions if "ts-workflow-compute" in value] == [
        "./extensions/ts-workflow-compute/index.ts"
    ]


def test_compute_extension_exposes_one_root_operator_and_private_typed_tools() -> None:
    source = (ROOT / "extensions" / "ts-workflow-compute" / "index.ts").read_text(encoding="utf-8")
    output_schema = OUTPUT_SCHEMA.read_text(encoding="utf-8")
    names = {
        "ts_workspace_compute_prepare",
        "ts_workspace_compute_submit",
        "ts_workspace_compute_status",
        "ts_workspace_compute_tail",
        "ts_workspace_compute_collect",
        "ts_workspace_compute_cancel",
        "ts_workspace_compute_parse",
    }

    for name in names:
        assert f'"{name}"' in source
    for operation, name in {
        "prepare": "ts_workspace_compute_prepare",
        "submit": "ts_workspace_compute_submit",
        "inspect": "ts_workspace_compute_status",
        "collect": "ts_workspace_compute_collect",
        "cancel": "ts_workspace_compute_cancel",
        "parse": "ts_workspace_compute_parse",
    }.items():
        assert f'{operation}: "{name}"' in output_schema
    assert "name: TS_PUBLIC_TOOL_NAMES.subagentCompute" in source
    assert "name: TS_PUBLIC_TOOL_NAMES.mcpInspect" in source
    assert 'pi.registerCommand("ts-mcp"' in source
    assert 'pi.registerEntryRenderer<McpDiagnosticEntryData>("ts-workspace-mcp-diagnostic"' in source
    assert 'pi.appendEntry<McpDiagnosticEntryData>("ts-workspace-mcp-diagnostic"' in source
    assert 'keyHint("app.tools.expand", "to expand")' in source
    assert "MCP_DIAGNOSTIC_WIDGET_KEY" in source
    assert 'ctx.ui.setWidget("ts-workspace-mcp", JSON.stringify' not in source
    assert "Usage: /ts-mcp status|doctor|queues|nodes|cluster" in source
    assert "getArgumentCompletions" in source
    assert "This check is read-only" in source
    assert "about the configured MCP target, use mode=cluster" in source
    assert "never switch between MCP and SSH automatically" in source
    assert "createScopedComputeTools" in source
    assert "runComputeOperator" in source
    assert "completed compute actions" in source
    assert 'operation: Type.Literal("parse")' in source
    assert "intentId: INTENT_ID_PARAMETER" in source
    assert "artifactRef: Type.String" in source
    assert "report_serialization_failed_after_action" in source
    assert "retry_safe: false" in source
    assert 'pi.appendEntry("ts-workspace-compute-operator-failed"' in source
    assert "command:" not in source
    assert "authorizeComputeControl" not in source
    assert "ctx.ui.confirm" not in source
    assert "ctx.hasUI" not in source
    assert "authorized" not in source
    assert "additionalProperties: false" in source
    assert "executionMode: \"sequential\"" in source
    assert "runComputeJson" in source
    assert "runMcpDiagnosticJson" in source
    assert "nodeId: Type.String" in source
    assert source.index("await requireHealthyMcpConnection") < source.index("const actions: ActionLog = []")
    assert 'request.transport === "mcp"' in source
    assert "MCP_PREFLIGHT_OPERATIONS" in source
    assert 'request.operation === "submit" ? "doctor" : "status"' in source
    assert '...(request.backend === "gaussian" ? ["gaussian_profile"] : [])' in source
    assert "required components failed" in source
    assert "server has no gaussian software profile" in source
    assert "gaussian activation script is unavailable" in source
    assert "profile does not allow queue" in source


def test_ts_mcp_command_previews_modes_and_shows_progress_until_result() -> None:
    script = f"""
import installCompute from {json.dumps(COMPUTE_EXTENSION.as_uri())};
process.env.TS_AGENT_PYTHON = "/usr/bin/python3";
const commands = {{}};
const entries = [];
const execCalls = [];
let failNext = false;
const pi = {{
  registerEntryRenderer: () => {{}},
  registerTool: () => {{}},
  registerCommand: (name, command) => {{ commands[name] = command; }},
  exec: async (command, args) => {{
    execCalls.push([command, args]);
    if (failNext) throw new Error("diagnostic process stopped");
    return {{ stdout: JSON.stringify({{
      schema_version: "ts-mcp-diagnostic/1",
      mode: "status",
      ok: true,
      connection: {{ endpoint: "http://127.0.0.1:18766/mcp", authenticated: true }},
      capabilities: {{}},
    }}) }};
  }},
  appendEntry: (type, data) => entries.push([type, data]),
}};
installCompute(pi);
const uiCalls = [];
const ctx = {{
  cwd: "/tmp/tspi-workspace",
  signal: new AbortController().signal,
  ui: {{
    setStatus: (...args) => uiCalls.push(["status", ...args]),
    setWidget: (...args) => uiCalls.push(["widget", ...args]),
    notify: (...args) => uiCalls.push(["notify", ...args]),
  }},
}};
const completions = await commands["ts-mcp"].getArgumentCompletions("");
await commands["ts-mcp"].handler("status", ctx);
const successCalls = uiCalls.splice(0);
failNext = true;
let failureMessage;
try {{
  await commands["ts-mcp"].handler("doctor", ctx);
}} catch (error) {{
  failureMessage = error.message;
}}
process.stdout.write(JSON.stringify({{ completions, successCalls, failureCalls: uiCalls, failureMessage, entries, execCalls }}));
"""
    result = _node_json(script)
    success_calls = result["successCalls"]

    assert [item["value"] for item in result["completions"]] == [
        "status",
        "doctor",
        "queues",
        "nodes",
        "cluster",
    ]
    assert all(item["description"] for item in result["completions"])
    assert ["status", "ts-workspace-mcp-command", "TS MCP · status · checking"] in success_calls
    assert any(
        call[0] == "widget"
        and call[1] == "ts-workspace-mcp"
        and isinstance(call[2], list)
        and call[2][0] == "◌ TS MCP · status · running"
        and call[2][1] == "Read-only · connection and capabilities"
        for call in success_calls
    )
    assert any(
        call[0] == "notify"
        and call[1] == "Check the MCP connection and advertised capabilities. This check is read-only."
        for call in success_calls
    )
    assert success_calls[-2:] == [
        ["status", "ts-workspace-mcp-command", None],
        ["widget", "ts-workspace-mcp", None],
    ]
    assert result["failureMessage"] == "diagnostic process stopped"
    assert [
        "notify",
        "TS Cluster MCP doctor stopped before a result was returned",
        "error",
    ] in result["failureCalls"]
    assert result["failureCalls"][-2:] == [
        ["status", "ts-workspace-mcp-command", None],
        ["widget", "ts-workspace-mcp", None],
    ]
    assert result["entries"][0][0] == "ts-workspace-mcp-diagnostic"
    assert result["entries"][0][1]["result"]["ok"] is True
    assert result["execCalls"][0][1][-2:] == ["--mode", "status"]


def test_compute_contracts_exclude_workspace_verdicts_and_arbitrary_commands() -> None:
    intent = json.loads((ROOT / "ts_compute" / "contracts" / "calculation_intent.schema.json").read_text(encoding="utf-8"))
    result = json.loads((ROOT / "ts_compute" / "contracts" / "calculation_result.schema.json").read_text(encoding="utf-8"))

    assert intent["additionalProperties"] is False
    assert result["additionalProperties"] is False
    assert "command" not in intent["properties"]
    assert "claim_verdict" not in result["properties"]
    forbidden = result["properties"]["parser_facts"]["propertyNames"]["not"]["enum"]
    assert {"claim_verdict", "accepted_ts", "pathway_accepted"} <= set(forbidden)


def test_compute_cli_is_package_relative_and_runtime_aware() -> None:
    shared = (ROOT / "extensions" / "shared" / "workspace-cli.ts").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "ts_compute.py").read_text(encoding="utf-8")

    assert 'resolve(PACKAGE_ROOT, "scripts", "ts_compute.py")' in shared
    assert '"nodes" | "cluster"' in shared
    assert "findRuntimeWorkspaceRoot(cwd)" in shared
    assert 'join(current, ".agents", "runtime", "transition-state-workflow", "env.json")' in shared
    assert "AbortSignal.timeout(timeoutMs)" in shared
    assert "seed_workspace_root_from_argv()" in script
    assert "ensure_runtime_python(ROOT)" in script


def test_compute_operator_runtime_is_fresh_isolated_and_tool_scoped() -> None:
    runtime = (COMPUTE_AGENT / "runtime.ts").read_text(encoding="utf-8")
    prompt = (COMPUTE_AGENT / "prompt.md").read_text(encoding="utf-8")

    assert 'noTools: "builtin"' in runtime
    assert "customTools: options.tools" in runtime
    assert "tools: options.tools.map" in runtime
    assert "SessionManager.inMemory(options.workspaceRoot)" in runtime
    assert "SettingsManager.inMemory" in runtime
    assert "getAgentsFiles: () => ({ agentsFiles: [] })" in runtime
    assert "getSystemPromptSource: () => undefined" in runtime
    assert "getAppendSystemPromptSources: () => []" in runtime
    assert "getSkills: () => ({ skills: [], diagnostics: [] })" in runtime
    assert "withDisposableSession" in runtime
    assert "parseAndValidateOperatorReport" in runtime
    assert "noTools: \"all\"" not in runtime
    assert "Program completion is not evidence" in prompt
    assert "exactly `summary` and `limitations`" in prompt
    assert "The host deterministically generates outcome" in prompt
    assert "not a durable scientific fact" in prompt
    assert "For `submit` or `cancel`" in prompt
    assert "Root Agent has already preflighted and bound the exact operation" in prompt
    assert "loadComputePolicy(options.backend)" in runtime
    assert "Compute operator policy" in runtime


def test_compute_action_failure_replaces_started_record_and_redacts_diagnostics() -> None:
    script = (
        f"const helper=require({json.dumps(str(ACTION_LOG))});"
        "const actions=[];"
        "const action=helper.reserveAction(actions,'ts_workspace_compute_status');"
        "const error=new Error('Bearer abc.def token=topsecret https://user:pass@example.test/status');"
        "const result=helper.failAction(action,error,{intentId:'calc_test',nodeId:'n001',"
        "backend:'gaussian',intentDigest:'sha256:test'});"
        "process.stdout.write(JSON.stringify({actions,result,message:helper.formatFailedActionError(action.tool,result)}));"
    )
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    output = json.loads(completed.stdout)

    assert output["actions"][0]["result"]["action_status"] == "failed"
    assert "action_status" not in output["actions"][0]["result"]["result"]
    assert output["result"]["program_status"] == "not_run"
    assert output["result"]["state"] == "unknown"
    assert output["result"]["error_class"] == "tool_execution_error"
    assert "started" not in json.dumps(output["actions"])
    assert "abc.def" not in output["message"]
    assert "topsecret" not in output["message"]
    assert "user:pass" not in output["message"]
    assert "[REDACTED]" in output["message"]


def test_compute_action_log_marks_ambiguous_control_as_unknown() -> None:
    script = (
        f"const helper=require({json.dumps(str(ACTION_LOG))});"
        "const actions=[];"
        "const action=helper.reserveAction(actions,'ts_workspace_compute_submit');"
        "helper.completeAction(action,{state:'unknown',program_status:'not_run',"
        "error_class:'submission_ambiguous',artifact_refs:[],control:{effect_outcome:'unknown'}},action.tool);"
        "process.stdout.write(JSON.stringify(actions[0]));"
    )
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    action = json.loads(completed.stdout)
    assert action["result"]["action_status"] == "unknown"
    assert action["result"]["result"]["state"] == "unknown"


def test_compute_control_has_no_interactive_authorization_gate() -> None:
    source = (ROOT / "extensions" / "ts-workflow-compute" / "index.ts").read_text(encoding="utf-8")
    prompt = (COMPUTE_AGENT / "prompt.md").read_text(encoding="utf-8")

    assert not (ROOT / "extensions" / "ts-workflow-compute" / "authorization.cjs").exists()
    assert "authorizeComputeControl" not in source
    assert "ctx.ui.confirm" not in source
    assert "interactive Pi host confirmation" not in source
    assert "Root Agent has already preflighted and bound the exact operation" in prompt


def test_compute_backend_policies_are_packaged_but_not_registered_as_skills() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert package["pi"]["skills"] == ["./skills/transition-state-workflow"]
    policies = {path.stem for path in (COMPUTE_AGENT / "backends").glob("*.md")}
    assert policies == {"gaussian", "ase", "qbics", "rdkit", "xtb"}
    assert "src/agents/compute/backends/*.md" in package["files"]
    assert not list(COMPUTE_AGENT.rglob("SKILL.md"))


def test_compute_operator_output_is_bound_to_actual_tool_result(tmp_path: Path) -> None:
    packet = {
        "schema_version": "ts-agent-task/1",
        "task_id": "agent_compute_001",
        "role": "backend",
        "authority": "operational",
        "operation": "prepare",
        "objective": "Prepare the bound Gaussian calculation.",
        "workspace": {"root": "/tmp/ws", "report_id": "rep_001", "revision": "rev_001"},
        "scope": {"report_id": "rep_001", "node_ids": ["n001"], "hypothesis_id": None, "pathway_id": None},
        "inputs": {
            "intent_id": None,
            "intent_ref": "nodes/n001/scratch/intent.json",
            "intent_digest": "sha256:test",
            "node_id": "n001",
            "backend": "gaussian",
            "basis_allowlist": [],
        },
        "capabilities": ["ts_workspace_compute_prepare"],
        "constraints": {
            "canonical_workspace_mutation": False,
            "scientific_decision": False,
            "recursive_delegation": False,
            "remote_authority": "execution_mirror",
            "external_side_effects": False,
        },
        "output_contract": "ts-agent-result/1",
    }
    action = {
        "tool": "ts_workspace_compute_prepare",
        "result": {
            "result": {
                "intent_id": "calc_test",
                "node_id": "n001",
                "state": "prepared",
                "program_status": "not_run",
                "error_class": None,
                "artifact_refs": ["nodes/n001/inputs/calculations/calc_test.json"],
                "exit_status": None,
                "provenance": {"backend": "gaussian", "intent_digest": "sha256:test"},
            }
        },
    }
    report = {
        "schema_version": "ts-agent-result/1",
        "task_id": "agent_compute_001",
        "role": "backend",
        "authority": "operational",
        "operation": "prepare",
        "outcome": "success",
        "summary": "The dry-run intent was prepared.",
        "scope": packet["scope"],
        "facts": [],
        "artifact_refs": ["nodes/n001/inputs/calculations/calc_test.json"],
        "program": {"outcome": "not_run", "state": "prepared", "error_class": None, "exit_status": None},
        "payload": {"intent_id": "calc_test", "node_id": "n001", "backend": "gaussian"},
        "limitations": ["No job was submitted."],
        "provenance": {},
    }
    completed = _validate_operator_output(tmp_path, packet, [action], report)
    assert json.loads(completed.stdout)["authority"] == "operational"

    completed = _validate_operator_output(tmp_path, packet, [action], report, fenced=True)
    assert json.loads(completed.stdout)["program"]["state"] == "prepared"

    basis_ref = "nodes/n001/inputs/calculations/calc_test.json"
    for alias in {
        "preparation",
        "compute_preparation",
        "submission",
        "artifact_collection",
        "collection",
        "program",
        "program_status",
        "parser",
    }:
        report["facts"] = [{
            "kind": alias,
            "layer": None,
            "statement": "Typed compute fact.",
            "status": "observed",
            "basis_refs": [basis_ref],
        }]
        completed = _validate_operator_output(tmp_path, packet, [action], report)
        deterministic = json.loads(completed.stdout)
        assert deterministic["facts"][0]["kind"] == "compute_preparation"
        assert deterministic["facts"][0]["status"] == "observed"
    report["facts"][0]["status"] = "unknown"
    completed = _validate_operator_output(tmp_path, packet, [action], report)
    assert json.loads(completed.stdout)["facts"][0]["status"] == "observed"
    report["facts"] = []

    report["program"]["state"] = "completed"
    completed = _validate_operator_output(tmp_path, packet, [action], report)
    assert json.loads(completed.stdout)["program"]["state"] == "prepared"

    completed = _validate_operator_output(tmp_path, packet, [action], "not valid JSON")
    deterministic = json.loads(completed.stdout)
    assert deterministic["summary"] == "The typed prepare action returned state prepared."
    assert deterministic["limitations"] == []

    report["program"]["state"] = "prepared"
    action["result"]["result"]["provenance"]["intent_digest"] = "sha256:changed"
    completed = _validate_operator_output(tmp_path, packet, [action], report, check=False)
    assert "intent digest does not match" in completed.stderr

    action["result"] = {"action_status": "started", "result": None}
    completed = _validate_operator_output(tmp_path, packet, [action], report, check=False)
    assert "incomplete typed action" in completed.stderr


def test_compute_operator_maps_ambiguous_submit_to_unknown_action_outcome(tmp_path: Path) -> None:
    packet = {
        "schema_version": "ts-agent-task/1",
        "task_id": "agent_compute_ambiguous_001",
        "role": "backend",
        "authority": "operational",
        "operation": "submit",
        "objective": "Submit the bound Gaussian calculation.",
        "workspace": {"root": "/tmp/ws", "report_id": "rep_001", "revision": "rev_001"},
        "scope": {"report_id": "rep_001", "node_ids": ["n001"], "hypothesis_id": None, "pathway_id": None},
        "inputs": {
            "intent_id": "calc_test",
            "intent_ref": "nodes/n001/attempts/calc_test/intent.json",
            "intent_digest": "sha256:test",
            "node_id": "n001",
            "backend": "gaussian",
            "basis_allowlist": [],
        },
        "capabilities": ["ts_workspace_compute_submit"],
        "constraints": {
            "canonical_workspace_mutation": False,
            "scientific_decision": False,
            "recursive_delegation": False,
            "remote_authority": "execution_mirror",
            "external_side_effects": True,
        },
        "output_contract": "ts-agent-result/1",
    }
    raw_result = {
        "intent_id": "calc_test",
        "node_id": "n001",
        "state": "unknown",
        "program_status": "not_run",
        "error_class": "submission_ambiguous",
        "artifact_refs": [],
        "exit_status": None,
        "control": {
            "effect_outcome": "unknown",
            "retry_disposition": "reconcile_only",
        },
        "provenance": {"backend": "gaussian", "intent_digest": "sha256:test"},
    }
    action = {
        "tool": "ts_workspace_compute_submit",
        "result": {"action_status": "unknown", "result": raw_result},
    }

    completed = _validate_operator_output(
        tmp_path,
        packet,
        [action],
        {"summary": "Submission requires reconciliation.", "limitations": []},
    )
    report = json.loads(completed.stdout)

    assert report["outcome"] == "partial"
    assert report["facts"][0]["kind"] == "submission"
    assert report["facts"][0]["status"] == "uncertain"
    assert report["program"]["state"] == "unknown"
    assert report["program"]["error_class"] == "submission_ambiguous"


def test_compute_operator_rejects_scientific_fields_and_missing_required_action(tmp_path: Path) -> None:
    packet = {
        "schema_version": "ts-agent-task/1",
        "task_id": "agent_compute_002",
        "role": "backend",
        "authority": "operational",
        "operation": "inspect",
        "objective": "Inspect the bound Gaussian calculation.",
        "workspace": {"root": "/tmp/ws", "report_id": "rep_001", "revision": "rev_001"},
        "scope": {"report_id": "rep_001", "node_ids": ["n001"], "hypothesis_id": None, "pathway_id": None},
        "inputs": {
            "intent_id": "calc_test",
            "intent_ref": "nodes/n001/attempts/calc_test/intent.json",
            "intent_digest": "sha256:test",
            "node_id": "n001",
            "backend": "gaussian",
            "basis_allowlist": [],
        },
        "capabilities": ["ts_workspace_compute_status", "ts_workspace_compute_tail"],
        "constraints": {
            "canonical_workspace_mutation": False,
            "scientific_decision": False,
            "recursive_delegation": False,
            "remote_authority": "execution_mirror",
            "external_side_effects": False,
        },
        "output_contract": "ts-agent-result/1",
    }
    report = {
        "schema_version": "ts-agent-result/1",
        "task_id": "agent_compute_002",
        "role": "backend",
        "authority": "operational",
        "operation": "inspect",
        "outcome": "success",
        "summary": "Inspection complete.",
        "scope": packet["scope"],
        "facts": [],
        "artifact_refs": [],
        "program": {"outcome": "not_run", "state": "running", "error_class": None, "exit_status": None},
        "payload": {"intent_id": "calc_test", "node_id": "n001", "backend": "gaussian"},
        "limitations": [],
        "provenance": {},
    }
    report["payload"]["claim_verdict"] = "supported"
    completed = _validate_operator_output(tmp_path, packet, [], report, check=False)
    assert completed.returncode == 2
    assert "authoritative field" in completed.stderr

    del report["payload"]["claim_verdict"]
    completed = _validate_operator_output(tmp_path, packet, [], report, check=False)
    assert completed.returncode == 2
    assert "execute one or two" in completed.stderr


def test_compute_inspect_accepts_failed_status_plus_tail_as_partial_diagnostic(tmp_path: Path) -> None:
    packet = {
        "schema_version": "ts-agent-task/1",
        "task_id": "agent_fe328914-a6da-4d2c-8dcc-5048afded0d5",
        "role": "backend",
        "authority": "operational",
        "operation": "inspect",
        "objective": "Inspect the bound Gaussian calculation.",
        "workspace": {"root": "/tmp/ws", "report_id": "rep_001", "revision": "rev_001"},
        "scope": {"report_id": "rep_001", "node_ids": ["n002"], "hypothesis_id": None, "pathway_id": None},
        "inputs": {
            "intent_id": "calc_n002_ma_optfreq_001",
            "intent_ref": "nodes/n002/attempts/calc_n002_ma_optfreq_001/intent.json",
            "intent_digest": "sha256:test",
            "node_id": "n002",
            "backend": "gaussian",
            "basis_allowlist": [],
        },
        "capabilities": ["ts_workspace_compute_status", "ts_workspace_compute_tail"],
        "constraints": {
            "canonical_workspace_mutation": False,
            "scientific_decision": False,
            "recursive_delegation": False,
            "remote_authority": "execution_mirror",
            "external_side_effects": False,
        },
        "output_contract": "ts-agent-result/1",
    }
    actions = [
        {
            "tool": "ts_workspace_compute_status",
            "result": {
                "action_status": "failed",
                "state": "unknown",
                "program_status": "not_run",
                "error_class": "tool_execution_error",
                "exit_status": None,
                "intent_id": "calc_n002_ma_optfreq_001",
                "node_id": "n002",
                "artifact_refs": [],
                "provenance": {"backend": "gaussian", "intent_digest": "sha256:test"},
            },
        },
        {
            "tool": "ts_workspace_compute_tail",
            "result": {
                "schema_version": "ts-calculation-tail/1",
                "intent_id": "calc_n002_ma_optfreq_001",
                "node_id": "n002",
                "artifact": "remote_job.stderr",
                "lines": 100,
                "truncated": False,
                "text": "exec: g16: not found",
            },
        },
    ]
    report = {
        "schema_version": "ts-agent-result/1",
        "task_id": packet["task_id"],
        "role": "backend",
        "authority": "operational",
        "operation": "inspect",
        "outcome": "partial",
        "summary": "Status failed, but the bounded stderr tail identified a launcher error.",
        "scope": packet["scope"],
        "facts": [
            {
                "kind": "program",
                "layer": "program",
                "statement": "The remote launcher reported that g16 was not found.",
                "status": "observed",
                "artifact_ref": "remote_job.stderr",
            }
        ],
        "artifact_refs": [],
        "program": {"outcome": "not_run", "state": "unknown", "error_class": "tool_execution_error", "exit_status": None},
        "payload": {"intent_id": "calc_n002_ma_optfreq_001", "node_id": "n002", "backend": "gaussian"},
        "limitations": ["The failed status action did not establish a canonical program state."],
        "provenance": {},
    }

    completed = _validate_operator_output(tmp_path, packet, actions, report)
    result = json.loads(completed.stdout)
    expected_ref = f"nodes/n002/agent-runs/{packet['task_id']}/actions.json#/actions/0/result"

    assert result["outcome"] == "partial"
    assert result["facts"][0]["basis_refs"] == [expected_ref]
    assert result["facts"][0]["kind"] == "inspection"
    assert result["facts"][0]["status"] == "observed"
    assert "artifact_ref" not in result["facts"][0]
    assert result["program"]["outcome"] == "not_run"
    assert not ({"claim_verdict", "hypothesis_status", "accepted_ts"} & set(result))


def _validate_operator_output(
    tmp_path: Path,
    packet: dict[str, object],
    actions: list[dict[str, object]],
    report: dict[str, object] | str,
    *,
    check: bool = True,
    fenced: bool = False,
) -> subprocess.CompletedProcess[str]:
    input_path = tmp_path / "operator-output.json"
    input_path.write_text(json.dumps({"packet": packet, "actions": actions, "report": report}), encoding="utf-8")
    script = (
        "const fs=require('node:fs');"
        f"const helper=require({json.dumps(str(OUTPUT_SCHEMA))});"
        "const input=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));"
        "const text=typeof input.report==='string' ? input.report : JSON.stringify(input.report);"
        f"const output={json.dumps(fenced)} ? '```json\\n'+text+'\\n```' : text;"
        "try { process.stdout.write(JSON.stringify(helper.parseAndValidateOperatorReport(output,input.packet,input.actions))); }"
        "catch(error){ process.stderr.write(String(error.message||error)); process.exitCode=2; }"
    )
    return subprocess.run(
        ["node", "-e", script, str(input_path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def _node_json(script: str):
    completed = subprocess.run(
        ["node", "--experimental-loader", str(TS_LOADER), "--input-type=module", "--eval", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)
