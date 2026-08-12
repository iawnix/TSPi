from __future__ import annotations

import json
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
    packet = _task_packet(workspace, "sub_journal_001", ["n000"])

    _run_journal(
        workspace,
        packet,
        "complete",
        {
            "actions": [],
            "result": {"summary": "Independent mechanism review completed."},
            "metadata": {"schema_valid": True},
        },
    )

    run_dir = workspace / "nodes" / "n000" / "agent-runs" / "sub_journal_001"
    assert {path.name for path in run_dir.iterdir()} == {"task.json", "actions.json", "result.json", "run.json"}
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
    packet = _task_packet(workspace, "agent_report_001", [])

    completed = _run_journal(
        workspace,
        packet,
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
    packet = _task_packet(workspace, "sub_invalid_review_001", ["n000"])
    raw = "x" * (20 * 1024)
    script = (
        f"const journal=require({json.dumps(str(JOURNAL))});"
        "const packet=JSON.parse(process.argv[2]);"
        "const handle=journal.beginAgentRun(process.argv[1],packet);"
        "journal.writeInvalidReviewOutput(handle,[{validation_stage:'tool_schema',reason:'risks must be an array',"
        "source:'tool_arguments',raw:process.argv[3]}]);"
        "journal.failAgentRun(handle,{error:new Error('invalid review output')});"
    )
    subprocess.run(
        ["node", "-e", script, str(workspace), json.dumps(packet), raw],
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


def _task_packet(workspace: Path, task_id: str, node_ids: list[str]) -> dict[str, object]:
    return {
        "schema_version": "ts-agent-task/1",
        "task_id": task_id,
        "role": "review" if node_ids else "report",
        "authority": "advisory" if node_ids else "operational",
        "operation": "mechanism" if node_ids else "build",
        "workspace": {"root": str(workspace)},
        "scope": {"node_ids": node_ids},
    }


def _run_journal(
    workspace: Path,
    packet: dict[str, object],
    mode: str,
    payload: dict[str, object],
) -> dict[str, object]:
    script = (
        f"const journal=require({json.dumps(str(JOURNAL))});"
        "const packet=JSON.parse(process.argv[2]);"
        "const payload=JSON.parse(process.argv[3]);"
        "const handle=journal.beginAgentRun(process.argv[1],packet);"
        "if(process.argv[4]==='complete'){journal.completeAgentRun(handle,payload);process.stdout.write('{}');}"
        "else {journal.failAgentRun(handle,payload);let second_error=null;"
        "if(process.argv[4]==='fail_twice'){try{journal.failAgentRun(handle,payload);}catch(error){second_error=error.message;}}"
        "process.stdout.write(JSON.stringify({second_error}));}"
    )
    completed = subprocess.run(
        ["node", "-e", script, str(workspace), json.dumps(packet), json.dumps(payload), mode],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return json.loads(completed.stdout)
