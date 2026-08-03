from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_SCHEMA = ROOT / "compute-agent" / "output-schema.cjs"
AUTHORIZATION = ROOT / "extensions" / "ts-workflow-compute" / "authorization.cjs"


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
    assert 'name: "ts_workspace_compute_operator"' in source
    assert 'name: "ts_workspace_mcp_status"' in source
    assert 'pi.registerCommand("ts-mcp"' in source
    assert "Usage: /ts-mcp status|doctor|queues|nodes|cluster" in source
    assert "about the configured MCP target, use mode=cluster" in source
    assert "never switch between MCP and SSH automatically" in source
    assert "createScopedComputeTools" in source
    assert "runComputeOperator" in source
    assert "completed compute actions" in source
    assert 'pi.appendEntry("ts-workspace-compute-operator-failed"' in source
    assert "command:" not in source
    assert "authorizeComputeControl(ctx, request)" in source
    assert "ctx.hasUI" not in source
    assert "authorized" not in source
    assert "additionalProperties: false" in source
    assert "executionMode: \"sequential\"" in source
    assert "runComputeJson" in source
    assert "runMcpDiagnosticJson" in source
    assert "nodeId: Type.String" in source
    assert source.index("await requireHealthyMcpConnection") < source.index("await authorizeComputeControl")
    assert 'request.transport === "mcp"' in source
    assert "MCP_PREFLIGHT_OPERATIONS" in source


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
    runtime = (ROOT / "compute-agent" / "runtime.ts").read_text(encoding="utf-8")
    prompt = (ROOT / "compute-agent" / "prompt.md").read_text(encoding="utf-8")

    assert 'noTools: "builtin"' in runtime
    assert "customTools: options.tools" in runtime
    assert "tools: options.tools.map" in runtime
    assert "SessionManager.inMemory(options.workspaceRoot)" in runtime
    assert "SettingsManager.inMemory" in runtime
    assert "getAgentsFiles: () => ({ agentsFiles: [] })" in runtime
    assert "getSkills: () => ({ skills: [], diagnostics: [] })" in runtime
    assert "withDisposableSession" in runtime
    assert "parseAndValidateOperatorReport" in runtime
    assert "noTools: \"all\"" not in runtime
    assert "Program completion is not evidence" in prompt
    assert "For `submit` or `cancel`" in prompt
    assert "never infer, request, copy, or return authorization data" in prompt
    assert "loadBackendSkill(options.backend)" in runtime
    assert "Selected private backend skill" in runtime


def test_compute_control_authorization_fails_closed_and_is_request_scoped(tmp_path: Path) -> None:
    script = (
        f"const helper=require({json.dumps(str(AUTHORIZATION))});"
        "const mode=process.argv[1];"
        "const calls=[];"
        "const request={operation:mode==='cancel'?'cancel':'submit',intentId:'calc_test',"
        "intentDigest:'sha256:'+('a'.repeat(64)),backend:'gaussian',nodeId:'n001',"
        "transport:'mcp',remoteDir:'runs/n001',jobId:'42001.cluster',"
        "executionSummary:{kind:'remote',transport:'mcp',remote_dir:'runs/n001',queue:'workq'}};"
        "const ctx=mode==='headless'?{hasUI:false,ui:{confirm:async()=>{calls.push('bad');return true;}}}:"
        "{hasUI:true,ui:{confirm:async(title,message)=>{calls.push({title,message});return mode==='approve'||mode==='cancel';}}};"
        "helper.authorizeComputeControl(ctx,request).then(value=>{"
        "process.stdout.write(JSON.stringify({ok:true,value:value===undefined?'undefined':value,calls}));"
        "}).catch(error=>{process.stdout.write(JSON.stringify({ok:false,error:String(error.message||error),calls}));});"
    )

    def invoke(mode: str) -> dict[str, object]:
        completed = subprocess.run(
            ["node", "-e", script, mode],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return json.loads(completed.stdout)

    headless = invoke("headless")
    assert headless["ok"] is False
    assert "interactive Pi host confirmation" in headless["error"]
    assert headless["calls"] == []

    denied = invoke("deny")
    assert denied["ok"] is False
    assert "not authorized by the user" in denied["error"]
    assert len(denied["calls"]) == 1

    approved = invoke("approve")
    assert approved["ok"] is True
    assert approved["value"] == "undefined"
    assert len(approved["calls"]) == 1
    message = approved["calls"][0]["message"]
    assert "Intent: calc_test" in message
    assert "queue" in message
    assert "applies only to this call" in message
    assert "token" not in message.lower()

    cancelled = invoke("cancel")
    assert cancelled["ok"] is True
    assert "Bound job: 42001.cluster" in cancelled["calls"][0]["message"]

    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert package["pi"]["skills"] == ["."]
    private_skills = {path.parent.name for path in (ROOT / "agent-skills").glob("*/SKILL.md")}
    assert {"backend-gaussian", "backend-ase", "backend-rdkit", "backend-xtb"} <= private_skills


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

    report["program"]["state"] = "completed"
    completed = _validate_operator_output(tmp_path, packet, [action], report, check=False)
    assert completed.returncode == 2
    assert "program does not match" in completed.stderr

    report["program"]["state"] = "prepared"
    action["result"]["result"]["provenance"]["intent_digest"] = "sha256:changed"
    completed = _validate_operator_output(tmp_path, packet, [action], report, check=False)
    assert "intent digest does not match" in completed.stderr

    action["result"] = {
        "action_status": "started",
        "state": "started",
        "program_status": "not_run",
        "artifact_refs": [],
    }
    completed = _validate_operator_output(tmp_path, packet, [action], report, check=False)
    assert "incomplete typed action" in completed.stderr


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


def _validate_operator_output(
    tmp_path: Path,
    packet: dict[str, object],
    actions: list[dict[str, object]],
    report: dict[str, object],
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
        "const text=JSON.stringify(input.report);"
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
