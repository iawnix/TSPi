from __future__ import annotations

import json
import hashlib
import stat
import subprocess
from pathlib import Path

from strict_helpers import bootstrap_strict_workspace
from ts_web.normalize import explorer_graph_payload_from_view, normalize_workspace
from ts_workspace import report_workspace


ROOT = Path(__file__).resolve().parents[1]
JOURNAL = ROOT / "src" / "agent-core" / "run-journal.cjs"


def test_node_agent_run_changes_only_operational_revision(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    before = report_workspace(workspace)
    packet, documents = _task_packet(workspace, "sub_journal_001", ["n000"])

    _run_journal(
        workspace,
        packet,
        documents,
        "complete",
        {
            "actions": [],
            "result": {"summary": "Independent mechanism review completed."},
            "metadata": {"schema_valid": True},
        },
    )

    run_dir = workspace / "nodes" / "n000" / "agent-runs" / "sub_journal_001"
    assert {path.name for path in run_dir.iterdir()} == {
        "task.json", "evidence-snapshot.json", "provider-input.json", "actions.json", "result.json", "run.json"
    }
    for name in ("task.json", "evidence-snapshot.json", "provider-input.json"):
        assert stat.S_IMODE((run_dir / name).stat().st_mode) == 0o600
    assert json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["status"] == "completed"

    after = report_workspace(workspace)
    assert after["workspace_revision"] == before["workspace_revision"]
    assert after["operational_revision"] != before["operational_revision"]
    assert after["evidence_count"] == before["evidence_count"]
    assert after["operational_summary"]["agent_run_count"] == 1
    assert after["agent_runs"][0]["summary"] == "Independent mechanism review completed."
    assert after["agent_runs"][0]["result_outcome"] is None

    graph = explorer_graph_payload_from_view(normalize_workspace(workspace))
    node = next(row for row in graph["nodes"] if row["id"] == "n000")
    assert node["agent_run_count"] == 1
    assert node["agent_run_status"] == "completed"
    assert graph["evidence_summary"]["count"] == before["evidence_count"]


def test_global_failed_agent_run_is_durable_and_write_once(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    packet, documents = _task_packet(workspace, "agent_report_001", [])

    completed = _run_journal(
        workspace,
        packet,
        documents,
        "fail_twice",
        {
            "actions": [{"tool": "ts_workspace_report_build", "result": {"state": "started"}}],
            "error": {"name": "Error", "message": "report build failed", "code": "REPORT_FAILED"},
            "metadata": {"role": "report"},
        },
    )

    assert completed["second_error"] == "agent run is already finalized: agent_report_001"
    run_dir = workspace / "operations" / "agent-runs" / "agent_report_001"
    assert not (run_dir / "result.json").exists()
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "failed"
    assert run["error"]["code"] == "REPORT_FAILED"
    report = report_workspace(workspace)
    assert report["operational_summary"]["agent_run_failed_count"] == 1
    assert report["agent_runs"][0]["run_ref"] == "operations/agent-runs/agent_report_001"


def test_invalid_review_output_is_private_bounded_and_not_scientific_evidence(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    before = report_workspace(workspace)
    packet, documents = _task_packet(workspace, "sub_invalid_review_001", ["n000"])
    raw = "x" * (20 * 1024)
    script = (
        f"const journal=require({json.dumps(str(JOURNAL))});"
        "const packet=JSON.parse(process.argv[2]);"
        "const documents=JSON.parse(process.argv[4]);"
        "const handle=journal.beginAgentRun(process.argv[1],packet,{documents});"
        "journal.writeInvalidReviewOutput(handle,[{validation_stage:'tool_schema',reason:'risks must be an array',"
        "source:'tool_arguments',raw:process.argv[3]}]);"
        "journal.failAgentRun(handle,{error:new Error('invalid review output')});"
    )
    subprocess.run(
        ["node", "-e", script, str(workspace), json.dumps(packet), raw, json.dumps(documents)],
        cwd=ROOT,
        check=True,
    )

    output = workspace / "nodes" / "n000" / "agent-runs" / "sub_invalid_review_001" / "invalid-review-output.json"
    document = json.loads(output.read_text(encoding="utf-8"))
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert document["invalid"] is True
    assert document["attempts"][0]["truncated"] is True
    assert document["attempts"][0]["sha256"].startswith("sha256:")
    assert output.stat().st_size <= 16 * 1024
    assert len(document["attempts"][0]["raw"].encode()) < 16 * 1024

    after = report_workspace(workspace)
    assert after["evidence_count"] == before["evidence_count"]
    assert "invalid-review-output" not in json.dumps(after)


def test_review_journal_rejects_missing_or_mismatched_companions_without_partial_run(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    packet, documents = _task_packet(workspace, "sub_bound_review_001", ["n000"])
    script = (
        f"const journal=require({json.dumps(str(JOURNAL))});"
        "const packet=JSON.parse(process.argv[2]);"
        "const documents=JSON.parse(process.argv[3]);"
        "try{journal.beginAgentRun(process.argv[1],packet,{documents});}"
        "catch(error){process.stderr.write(error.message);process.exitCode=2;}"
    )
    missing = {"evidence_snapshot": documents["evidence_snapshot"]}
    completed = subprocess.run(
        ["node", "-e", script, str(workspace), json.dumps(packet), json.dumps(missing)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 2
    assert "missing bound documents" in completed.stderr

    mismatched = json.loads(json.dumps(documents))
    mismatched["provider_input"]["objective"] = "Tampered provider input."
    completed = subprocess.run(
        ["node", "-e", script, str(workspace), json.dumps(packet), json.dumps(mismatched)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 2
    assert "does not match task binding" in completed.stderr
    parent = workspace / "nodes/n000/agent-runs"
    assert not (parent / "sub_bound_review_001").exists()
    assert not list(parent.glob(".sub_bound_review_001.tmp-*"))


def test_agent_journal_rejects_duplicate_task_id(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    packet, documents = _task_packet(workspace, "agent_duplicate_001", [])
    _run_journal(workspace, packet, documents, "complete", {"result": {"summary": "First."}})
    script = (
        f"const journal=require({json.dumps(str(JOURNAL))});"
        "try{journal.beginAgentRun(process.argv[1],JSON.parse(process.argv[2]),"
        "{documents:JSON.parse(process.argv[3])});}"
        "catch(error){process.stderr.write(error.message);process.exitCode=2;}"
    )
    completed = subprocess.run(
        ["node", "-e", script, str(workspace), json.dumps(packet), json.dumps(documents)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 2
    assert "already exists" in completed.stderr


def test_review_journal_detects_companion_tampering_on_read(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    packet, documents = _task_packet(workspace, "sub_tamper_001", ["n000"])
    script = (
        f"const fs=require('node:fs');const journal=require({json.dumps(str(JOURNAL))});"
        "const handle=journal.beginAgentRun(process.argv[1],JSON.parse(process.argv[2]),"
        "{documents:JSON.parse(process.argv[3])});"
        "fs.appendFileSync(handle.runDir+'/provider-input.json',' ');"
        "try{journal.readAgentRunInputs(handle);}"
        "catch(error){process.stderr.write(error.message);process.exitCode=2;}"
    )
    completed = subprocess.run(
        ["node", "-e", script, str(workspace), json.dumps(packet), json.dumps(documents)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 2
    assert "does not match task binding" in completed.stderr


def _task_packet(
    workspace: Path,
    task_id: str,
    node_ids: list[str],
) -> tuple[dict[str, object], dict[str, object]]:
    role = "review" if node_ids else "report"
    scope = {"report_id": "rep_001", "node_ids": node_ids, "hypothesis_id": None, "pathway_id": None}
    documents: dict[str, object] = {}
    inputs: dict[str, object] = {"basis_allowlist": []}
    if role == "review":
        evidence_snapshot = {
            "schema_version": "ts-review-evidence-snapshot/1",
            "task_id": task_id,
            "operation": "mechanism",
            "scope": scope,
            "context": {"workspace": "bounded", "node": "bounded", "backtrack": None},
            "evidence": [],
            "artifact_excerpts": [],
            "basis_allowlist": [],
            "evidence_ceiling": ["mechanism"],
        }
        provider_input = {
            "schema_version": "ts-review-provider-input/1",
            "task_id": task_id,
            "operation": "mechanism",
            "objective": "Review the bounded mechanism evidence.",
            "scope": scope,
            "workspace_revision": "sha256:" + "1" * 64,
            "context": evidence_snapshot["context"],
            "evidence": [],
            "artifact_excerpts": [],
            "basis_allowlist": [],
            "evidence_ceiling": ["mechanism"],
        }
        documents = {"evidence_snapshot": evidence_snapshot, "provider_input": provider_input}
        inputs = {
            "evidence_snapshot": _document_binding(
                "evidence-snapshot.json", "ts-review-evidence-snapshot/1", evidence_snapshot
            ),
            "provider_input": _document_binding(
                "provider-input.json", "ts-review-provider-input/1", provider_input
            ),
        }
    task = {
        "schema_version": "ts-agent-task/2",
        "task_id": task_id,
        "role": role,
        "authority": "advisory" if role == "review" else "operational",
        "operation": "mechanism" if role == "review" else "build",
        "objective": "Review the bounded mechanism evidence." if role == "review" else "Build the bounded report.",
        "workspace": {"root": str(workspace), "report_id": "rep_001", "revision": "sha256:" + "1" * 64},
        "scope": scope,
        "inputs": inputs,
        "capabilities": [],
        "constraints": {
            "canonical_workspace_mutation": False,
            "scientific_decision": False,
            "recursive_delegation": False,
            "remote_authority": "execution_mirror",
            "external_side_effects": False,
        },
        "output_contract": "ts-agent-result/1",
    }
    return task, documents


def _document_binding(ref: str, schema_version: str, document: dict[str, object]) -> dict[str, object]:
    payload = json.dumps(document, ensure_ascii=False, indent=2, separators=(",", ": ")) + "\n"
    return {
        "ref": ref,
        "schema_version": schema_version,
        "sha256": "sha256:" + hashlib.sha256(payload.encode()).hexdigest(),
        "bytes": len(payload.encode()),
    }


def _run_journal(
    workspace: Path,
    packet: dict[str, object],
    documents: dict[str, object],
    mode: str,
    payload: dict[str, object],
) -> dict[str, object]:
    script = (
        f"const journal=require({json.dumps(str(JOURNAL))});"
        "const packet=JSON.parse(process.argv[2]);"
        "const payload=JSON.parse(process.argv[3]);"
        "const documents=JSON.parse(process.argv[5]);"
        "const handle=journal.beginAgentRun(process.argv[1],packet,{documents});"
        "if(process.argv[4]==='complete'){journal.completeAgentRun(handle,payload);process.stdout.write('{}');}"
        "else {journal.failAgentRun(handle,payload);let second_error=null;"
        "if(process.argv[4]==='fail_twice'){try{journal.failAgentRun(handle,payload);}catch(error){second_error=error.message;}}"
        "process.stdout.write(JSON.stringify({second_error}));}"
    )
    completed = subprocess.run(
        ["node", "-e", script, str(workspace), json.dumps(packet), json.dumps(payload), mode, json.dumps(documents)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return json.loads(completed.stdout)
