from __future__ import annotations

import subprocess
from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "packages" / "ts-agent-runtime" / "agent-core" / "agent-protocol.cjs"


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
        "task_id": "sub_1",
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
            "node_refs": ["node_1"],
            "claim_refs": ["claim_1"],
        },
        "inputs": {
            "review_snapshot": _binding(
                "review-snapshot.json",
                "ts-review-task-snapshot/3",
                "b",
            ),
            "provider_input": _binding(
                "provider-input.json",
                "ts-review-provider-input/5",
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
                "basis_refs": ["claim_1"],
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
    mismatched["scope"] = {**task["scope"], "node_refs": []}
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


def test_agent_protocol_rejects_noncanonical_subagent_run_ids() -> None:
    task = _task()
    task["task_id"] = "sub_028def15-cbb5-42b4-bbfc-cfbd256c4a0b"

    rejected = _run("validateAgentTask", task)

    assert rejected.returncode == 2
    assert "subagent run ID" in rejected.stderr


def test_agent_protocol_requires_current_schema_and_exact_bound_review_documents() -> None:
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


def test_runtime_validator_is_the_single_agent_envelope_contract() -> None:
    task = _task()
    validated_task = _run("validateAgentTask", task)
    assert validated_task.returncode == 0, validated_task.stderr
    assert json.loads(validated_task.stdout) == task

    invalid_task = _task()
    invalid_task["scope"] = {"report_id": None, "node_ids": ["node_1"], "claim_refs": []}
    rejected_task = _run("validateAgentTask", invalid_task)
    assert rejected_task.returncode == 2
    assert "scope contains unknown fields" in rejected_task.stderr

    invalid_result = _result(task)
    invalid_result["facts"][0]["unexpected"] = True
    rejected_result = _run("validateAgentResult", invalid_result, task)
    assert rejected_result.returncode == 2
    assert "facts[0] contains unknown fields" in rejected_result.stderr
