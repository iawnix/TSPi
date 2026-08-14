from __future__ import annotations

import json
import hashlib
import stat
import subprocess
from pathlib import Path

import pytest

from strict_helpers import bootstrap_strict_workspace
from ts_web.normalize import explorer_graph_payload_from_view, normalize_workspace
from ts_workspace import ContractError, report_workspace, update_workspace, validate_decision_dry_run


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
    assert after["operational_summary"]["review_disposition_pending_count"] == 1
    assert after["pending_review_dispositions"][0]["task_id"] == "sub_journal_001"
    assert after["agent_runs"][0]["summary"] == "Independent mechanism review completed."
    assert after["agent_runs"][0]["result_outcome"] is None

    graph = explorer_graph_payload_from_view(normalize_workspace(workspace))
    node = next(row for row in graph["nodes"] if row["id"] == "n000")
    assert node["agent_run_count"] == 1
    assert node["agent_run_status"] == "completed"
    assert graph["evidence_summary"]["count"] == before["evidence_count"]


@pytest.mark.parametrize("disposition", ["accepted", "partially_accepted", "rejected", "deferred"])
def test_review_root_disposition_is_write_once_operational_state(tmp_path: Path, disposition: str) -> None:
    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    packet, documents = _task_packet(workspace, f"sub_disposition_{disposition}", ["n000"])
    _run_journal(
        workspace,
        packet,
        documents,
        "complete",
        {"result": {"summary": "Bounded advisory Review completed."}},
    )
    before = report_workspace(workspace)
    run_ref = f"nodes/n000/agent-runs/{packet['task_id']}"

    completed = _write_disposition(
        workspace,
        {
            "task_id": packet["task_id"],
            "review_run_ref": run_ref,
            "disposition": disposition,
            "response": "Root assessed the advisory result against the primary artifacts.",
            "next_steps": ["Proceed using only the supported portion of the advice."],
        },
    )
    document = json.loads(completed.stdout)

    disposition_path = workspace / run_ref / "root-disposition.json"
    assert document["schema_version"] == "ts-review-root-disposition/1"
    assert stat.S_IMODE(disposition_path.stat().st_mode) == 0o600
    after = report_workspace(workspace)
    assert after["workspace_revision"] == before["workspace_revision"]
    assert after["operational_revision"] != before["operational_revision"]
    assert after["evidence_count"] == before["evidence_count"]
    assert after["review_disposition_count"] == 1
    assert after["pending_review_dispositions"] == []
    assert after["operational_summary"]["review_disposition_pending_count"] == 0
    assert after["agent_runs"][0]["root_disposition"] == disposition
    assert after["agent_runs"][0]["root_disposition_ref"] == f"{run_ref}/root-disposition.json"

    repeated = _write_disposition(workspace, document, check=False)
    assert repeated.returncode == 2
    assert "EEXIST" in repeated.stderr or "file already exists" in repeated.stderr


def test_pending_review_disposition_blocks_validate_and_apply(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    packet, documents = _task_packet(workspace, "sub_mutation_gate_001", ["n000"])
    _run_journal(
        workspace,
        packet,
        documents,
        "complete",
        {"result": {"summary": "Review before a workspace mutation."}},
    )
    report = report_workspace(workspace)
    decision = {
        "schema_version": "ts-decision/2",
        "decision_id": "dec_after_review_001",
        "action": "update_workspace",
        "rationale": "Exercise the pending Review response gate.",
        "evidence_refs": [],
        "report_ref": {"report_id": report["report_id"], "workspace_root": str(workspace)},
        "base_revision": report["workspace_revision"],
        "payload": {"append_provenance": {"source": "review-disposition-test"}},
    }

    with pytest.raises(ContractError, match="call ts_review_disposition first"):
        validate_decision_dry_run(workspace, decision)
    with pytest.raises(ContractError, match="call ts_review_disposition first"):
        update_workspace(workspace, decision)
    assert not (workspace / "decisions" / "dec_after_review_001.json").exists()

    _write_disposition(
        workspace,
        {
            "task_id": packet["task_id"],
            "review_run_ref": f"nodes/n000/agent-runs/{packet['task_id']}",
            "disposition": "partially_accepted",
            "response": "The supported advice is adopted; unsupported claims remain excluded.",
            "next_steps": [],
        },
    )
    result = update_workspace(workspace, decision)
    assert result["appended"]["provenance"] == 1


def test_failed_review_and_non_review_run_cannot_create_response_obligations(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    bootstrap_strict_workspace(workspace)
    failed_packet, failed_documents = _task_packet(workspace, "sub_failed_review_001", ["n000"])
    _run_journal(
        workspace,
        failed_packet,
        failed_documents,
        "fail",
        {"error": {"name": "Error", "message": "provider failed"}},
    )
    report_packet, report_documents = _task_packet(workspace, "agent_report_no_response_001", [])
    _run_journal(
        workspace,
        report_packet,
        report_documents,
        "complete",
        {"result": {"summary": "Report completed."}},
    )

    report = report_workspace(workspace)
    assert report["pending_review_dispositions"] == []
    failed_response = _write_disposition(
        workspace,
        {
            "task_id": failed_packet["task_id"],
            "review_run_ref": f"nodes/n000/agent-runs/{failed_packet['task_id']}",
            "disposition": "deferred",
            "response": "No valid Review was produced.",
            "next_steps": [],
        },
        check=False,
    )
    assert failed_response.returncode == 2
    assert "complete successfully" in failed_response.stderr

    non_review_response = _write_disposition(
        workspace,
        {
            "task_id": report_packet["task_id"],
            "review_run_ref": f"operations/agent-runs/{report_packet['task_id']}",
            "disposition": "accepted",
            "response": "This must not be accepted as a Review response.",
            "next_steps": [],
        },
        check=False,
    )
    assert non_review_response.returncode == 2
    assert "not an advisory Review" in non_review_response.stderr


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


def _write_disposition(
    workspace: Path,
    payload: dict[str, object],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    script = (
        f"const journal=require({json.dumps(str(JOURNAL))});"
        "try{const result=journal.writeReviewRootDisposition(process.argv[1],JSON.parse(process.argv[2]));"
        "process.stdout.write(JSON.stringify(result));}"
        "catch(error){process.stderr.write(error.code || error.message);process.exitCode=2;}"
    )
    return subprocess.run(
        ["node", "-e", script, str(workspace), json.dumps(payload)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )
