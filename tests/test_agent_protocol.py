from __future__ import annotations

import json
import subprocess
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "src" / "agent-core" / "agent-protocol.cjs"


def _task() -> dict[str, object]:
    return {
        "schema_version": "ts-agent-task/1",
        "task_id": "agent_protocol_001",
        "role": "report",
        "authority": "operational",
        "operation": "assemble",
        "objective": "Assemble a bounded report package.",
        "workspace": {"root": "/tmp/ws", "report_id": "rep_001", "revision": "sha256:001"},
        "scope": {"report_id": "rep_001", "node_ids": ["n001"], "hypothesis_id": "hyp_001", "pathway_id": None},
        "inputs": {"artifact_allowlist": ["reports/context.json"]},
        "capabilities": ["ts_report_assemble"],
        "constraints": {
            "canonical_workspace_mutation": False,
            "scientific_decision": False,
            "recursive_delegation": False,
            "remote_authority": "execution_mirror",
            "external_side_effects": False,
        },
        "output_contract": "ts-agent-result/1",
    }


def _result(task: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "ts-agent-result/1",
        "task_id": task["task_id"],
        "role": "report",
        "authority": "operational",
        "operation": "assemble",
        "outcome": "success",
        "summary": "The report package was assembled from allowlisted inputs.",
        "scope": task["scope"],
        "facts": [],
        "artifact_refs": ["reports/final_report.md"],
        "program": None,
        "payload": {"format": "markdown"},
        "limitations": [],
        "provenance": {"source": "typed_report_tool"},
    }


def test_agent_protocol_json_schemas_are_valid_and_closed() -> None:
    task_schema = json.loads((ROOT / "contracts" / "agent_task.schema.json").read_text(encoding="utf-8"))
    result_schema = json.loads((ROOT / "contracts" / "agent_result.schema.json").read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(task_schema)
    Draft202012Validator.check_schema(result_schema)
    assert task_schema["additionalProperties"] is False
    assert result_schema["additionalProperties"] is False
    assert set(task_schema["properties"]["role"]["enum"]) == {"review", "backend", "render", "report", "email"}


def test_agent_protocol_binds_result_to_task_and_rejects_nested_authority(tmp_path: Path) -> None:
    task = _task()
    result = _result(task)
    payload = tmp_path / "protocol.json"
    payload.write_text(json.dumps({"task": task, "result": result}), encoding="utf-8")
    script = (
        "const fs=require('node:fs');"
        f"const p=require({json.dumps(str(PROTOCOL))});"
        "const x=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));"
        "try{process.stdout.write(JSON.stringify(p.validateAgentResult(x.result,x.task)));}"
        "catch(error){process.stderr.write(String(error.message||error));process.exitCode=2;}"
    )

    completed = subprocess.run(["node", "-e", script, str(payload)], cwd=ROOT, text=True, capture_output=True, check=True)
    assert json.loads(completed.stdout)["task_id"] == task["task_id"]

    result["payload"] = {"nested": {"branch_context": {"relation": "continue_parent"}}}
    payload.write_text(json.dumps({"task": task, "result": result}), encoding="utf-8")
    rejected = subprocess.run(["node", "-e", script, str(payload)], cwd=ROOT, text=True, capture_output=True)
    assert rejected.returncode == 2
    assert "authoritative field" in rejected.stderr


def test_agent_protocol_rejects_role_authority_mismatch(tmp_path: Path) -> None:
    task = _task()
    task["authority"] = "advisory"
    payload = tmp_path / "task.json"
    payload.write_text(json.dumps(task), encoding="utf-8")
    script = (
        "const fs=require('node:fs');"
        f"const p=require({json.dumps(str(PROTOCOL))});"
        "try{p.validateAgentTask(JSON.parse(fs.readFileSync(process.argv[1],'utf8')));}"
        "catch(error){process.stderr.write(String(error.message||error));process.exitCode=2;}"
    )
    rejected = subprocess.run(["node", "-e", script, str(payload)], cwd=ROOT, text=True, capture_output=True)
    assert rejected.returncode == 2
    assert "authority does not match role" in rejected.stderr
