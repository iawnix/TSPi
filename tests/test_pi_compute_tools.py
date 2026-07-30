from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_SCHEMA = ROOT / "compute-agent" / "output-schema.cjs"


def test_pi_package_registers_only_non_submit_compute_extension() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    extensions = package["pi"]["extensions"]

    assert "./extensions/ts-workflow-compute/index.ts" in extensions
    assert not [value for value in extensions if "submit" in value or "cancel" in value]


def test_compute_extension_exposes_one_root_operator_and_private_typed_tools() -> None:
    source = (ROOT / "extensions" / "ts-workflow-compute" / "index.ts").read_text(encoding="utf-8")
    names = {
        "ts_workspace_compute_prepare",
        "ts_workspace_compute_status",
        "ts_workspace_compute_tail",
        "ts_workspace_compute_collect",
        "ts_workspace_compute_parse",
    }

    for name in names:
        assert f'"{name}"' in source
    assert 'name: "ts_workspace_compute_operator"' in source
    assert "createScopedComputeTools" in source
    assert "runComputeOperator" in source
    assert "completed compute actions" in source
    assert 'pi.appendEntry("ts-workspace-compute-operator-failed"' in source
    assert "ts_workspace_compute_submit" not in source
    assert "ts_workspace_compute_cancel" not in source
    assert "command:" not in source
    assert "authorization" not in source
    assert "executionMode: \"sequential\"" in source
    assert "runComputeJson" in source
    assert "nodeId: Type.String" in source


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
    assert "submit or cancel" in prompt
    assert "loadBackendSkill(options.backend)" in runtime
    assert "Selected private backend skill" in runtime

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
        "inputs": {"intent_id": None, "node_id": "n001", "backend": "gaussian", "basis_allowlist": []},
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
                "provenance": {"backend": "gaussian"},
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
        "inputs": {"intent_id": "calc_test", "node_id": "n001", "backend": "gaussian", "basis_allowlist": []},
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
