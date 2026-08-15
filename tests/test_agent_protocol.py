from __future__ import annotations

import json
import subprocess
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "src" / "agent-core" / "agent-protocol.cjs"


def _binding(ref: str, schema_version: str, marker: str) -> dict[str, object]:
    return {
        "ref": ref,
        "schema_version": schema_version,
        "sha256": "sha256:" + marker * 64,
        "bytes": 128,
    }


def _task() -> dict[str, object]:
    return {
        "schema_version": "ts-agent-task/2",
        "task_id": "sub_01234567-89ab-cdef-0123-456789abcdef",
        "role": "review",
        "authority": "advisory",
        "operation": "claim_review",
        "objective": "Independently challenge one scientific Claim.",
        "workspace": {
            "root": "/tmp/ws",
            "report_id": "rep_001",
            "revision": "sha256:" + "a" * 64,
        },
        "scope": {
            "report_id": "rep_001",
            "act_refs": ["act_0123456789abcdef01234567"],
            "claim_refs": ["clm_0123456789abcdef01234567"],
        },
        "inputs": {
            "review_snapshot": _binding(
                "review-snapshot.json",
                "ts-review-task-snapshot/1",
                "b",
            ),
            "provider_input": _binding(
                "provider-input.json",
                "ts-review-provider-input/3",
                "c",
            ),
        },
        "capabilities": ["ts_review_result"],
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
        "role": "review",
        "authority": "advisory",
        "operation": "claim_review",
        "outcome": "success",
        "summary": "The cited basis supports the Claim, with one limitation.",
        "scope": task["scope"],
        "facts": [
            {
                "kind": "review",
                "statement": "The current basis is internally consistent.",
                "status": "supported",
                "basis_refs": ["clm_0123456789abcdef01234567"],
            }
        ],
        "artifact_refs": [],
        "program": None,
        "payload": {"missing_evidence": [], "conflicts": [], "options": []},
        "limitations": ["No independent recalculation was performed."],
        "provenance": {"source": "isolated_review"},
    }


def _run(function: str, value: dict, task: dict | None = None) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"value": value, "task": task})
    script = (
        f"const p=require({json.dumps(str(PROTOCOL))});"
        "const x=JSON.parse(process.argv[1]);"
        f"try{{process.stdout.write(JSON.stringify(p.{function}(x.value,x.task)));}}"
        "catch(error){process.stderr.write(String(error.message||error));process.exitCode=2;}"
    )
    return subprocess.run(
        ["node", "-e", script, payload],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_agent_protocol_binds_review_result_to_task() -> None:
    task = _task()
    result = _result(task)
    completed = _run("validateAgentResult", result, task)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == result

    mismatched = _result(task)
    mismatched["scope"] = {**task["scope"], "act_refs": []}
    rejected = _run("validateAgentResult", mismatched, task)
    assert rejected.returncode == 2
    assert "scope does not match agent task" in rejected.stderr


def test_agent_protocol_accepts_only_review_advisory_role() -> None:
    task = _task()
    task["authority"] = "operational"
    rejected = _run("validateAgentTask", task)
    assert rejected.returncode == 2
    assert "authority does not match role review" in rejected.stderr

    task = _task()
    task["role"] = "report"
    rejected = _run("validateAgentTask", task)
    assert rejected.returncode == 2
    assert "invalid role: report" in rejected.stderr


def test_agent_protocol_requires_v2_and_exact_bound_review_documents() -> None:
    task = _task()
    task["schema_version"] = "ts-agent-task/1"
    rejected = _run("validateAgentTask", task)
    assert rejected.returncode == 2
    assert "schema_version" in rejected.stderr

    task = _task()
    task["inputs"] = {"evidence": [], "basis_allowlist": []}
    rejected = _run("validateAgentTask", task)
    assert rejected.returncode == 2
    assert "review inputs contains unknown fields" in rejected.stderr


def test_agent_protocol_rejects_nested_authoritative_fields() -> None:
    task = _task()
    result = _result(task)
    result["payload"] = {"options": [], "claim_status": "supported"}
    rejected = _run("validateAgentResult", result, task)
    assert rejected.returncode == 2
    assert "authoritative field" in rejected.stderr


def test_public_json_schemas_match_review_runtime_contract() -> None:
    task_schema = json.loads((ROOT / "contracts" / "agent_task.schema.json").read_text(encoding="utf-8"))
    result_schema = json.loads((ROOT / "contracts" / "agent_result.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resource(task_schema["$id"], Resource.from_contents(task_schema))
    assert list(Draft202012Validator(task_schema, registry=registry).iter_errors(_task())) == []
    assert list(Draft202012Validator(result_schema, registry=registry).iter_errors(_result(_task()))) == []

    invalid = _task()
    invalid["scope"] = {"report_id": None, "node_ids": ["n001"], "claim_refs": []}
    assert list(Draft202012Validator(task_schema).iter_errors(invalid))
