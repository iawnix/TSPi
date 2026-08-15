from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from strict_helpers import CLAIM_ID, bootstrap_strict_workspace, make_accepted_workspace
from ts_workspace import build_review_snapshot, report_workspace


ROOT = Path(__file__).resolve().parents[1]
AGENT_CORE = ROOT / "src" / "agent-core"
REVIEW_AGENT = ROOT / "src" / "agents" / "review"
TASK_PACKET = REVIEW_AGENT / "task-packet.cjs"
OUTPUT_SCHEMA = REVIEW_AGENT / "output-schema.cjs"
RESULT_TOOL = REVIEW_AGENT / "result-tool.ts"
SESSION_LIFECYCLE = AGENT_CORE / "session-lifecycle.cjs"


class ReviewTaskFixture(dict[str, object]):
    def __init__(self, bundle: dict[str, object]) -> None:
        task = bundle["task"]
        documents = bundle["documents"]
        assert isinstance(task, dict) and isinstance(documents, dict)
        super().__init__(task)
        self.documents = documents


def _node(script: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "-e", script, *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def _packet(
    tmp_path: Path,
    *,
    artifact_ref: str | None = None,
    accepted_workspace: bool = False,
) -> ReviewTaskFixture:
    workspace = tmp_path / "ws"
    if accepted_workspace:
        make_accepted_workspace(workspace)
    else:
        bootstrap_strict_workspace(workspace)
    payload = {
        "runId": "sub_test_001",
        "workspaceRoot": str(workspace),
        "request": {
            "targetClaimRef": CLAIM_ID,
            "question": "Which assumptions still require a discriminating test?",
            "nodeIds": ["n000"],
            "artifactRefs": [artifact_ref or "nodes/n000/outputs/endpoint-summary.json"],
        },
        "workspaceReport": report_workspace(workspace),
        "reviewSnapshot": build_review_snapshot(
            workspace,
            target_claim_ref=CLAIM_ID,
            node_ids=["n000"],
        ),
    }
    source = tmp_path / "packet-input.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    script = (
        "const fs=require('node:fs');"
        f"const helper=require({json.dumps(str(TASK_PACKET))});"
        "const input=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));"
        "process.stdout.write(JSON.stringify(helper.buildReviewTaskBundle(input)));"
    )
    return ReviewTaskFixture(json.loads(_node(script, str(source)).stdout))


def _valid_result(packet: ReviewTaskFixture) -> dict[str, object]:
    return {
        "schema_version": "ts-agent-result/1",
        "task_id": packet["task_id"],
        "role": "review",
        "authority": "advisory",
        "operation": "claim_review",
        "outcome": "success",
        "summary": "Endpoint declaration alone does not establish the transition path.",
        "scope": packet["scope"],
        "facts": [
            {
                "kind": "review",
                "statement": "The focus Claim still requires its declared Gates.",
                "status": "uncertain",
                "basis_refs": [CLAIM_ID, "ev_endpoint_0001"],
            }
        ],
        "artifact_refs": [],
        "program": None,
        "payload": {
            "missing_evidence": ["Passed TS/Freq and connectivity Gate results."],
            "conflicts": [],
            "options": [
                {
                    "action": "Obtain evidence selected by the Root Agent.",
                    "discriminator": "Whether the required Gates pass.",
                    "risks": ["The selected method may remain inconclusive."],
                }
            ],
        },
        "limitations": ["Advisory review only."],
        "provenance": {"source": "bounded_task_packet"},
    }


def _validate_result(
    tmp_path: Path,
    packet: ReviewTaskFixture,
    result: dict[str, object],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    packet_path = tmp_path / "packet.json"
    snapshot_path = tmp_path / "snapshot.json"
    result_path = tmp_path / "result.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    snapshot_path.write_text(json.dumps(packet.documents["evidence_snapshot"]), encoding="utf-8")
    result_path.write_text(json.dumps(result), encoding="utf-8")
    script = (
        "const fs=require('node:fs');"
        f"const helper=require({json.dumps(str(OUTPUT_SCHEMA))});"
        "const task=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));"
        "const result=fs.readFileSync(process.argv[2],'utf8');"
        "const snapshot=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));"
        "try{process.stdout.write(JSON.stringify(helper.parseAndValidateReviewResult(result,task,snapshot)));}"
        "catch(error){process.stderr.write(error.message);process.exitCode=2;}"
    )
    return _node(script, str(packet_path), str(result_path), str(snapshot_path), check=check)


def test_task_packet_is_claim_scoped_bounded_and_advisory(tmp_path: Path) -> None:
    packet = _packet(tmp_path)
    snapshot = packet.documents["evidence_snapshot"]
    provider = packet.documents["provider_input"]

    assert packet["schema_version"] == "ts-agent-task/2"
    assert packet["role"] == "review"
    assert packet["authority"] == "advisory"
    assert packet["operation"] == "claim_review"
    assert packet["scope"]["claim_refs"] == [CLAIM_ID]
    assert packet["constraints"]["scientific_decision"] is False
    assert snapshot["schema_version"] == "ts-review-evidence-snapshot/2"
    assert snapshot["target_claim_ref"] == CLAIM_ID
    assert snapshot["basis_allowlist"] == [
        CLAIM_ID,
        "ev_endpoint_0001",
        "nodes/n000/outputs/endpoint-summary.json",
    ]
    assert provider["schema_version"] == "ts-review-provider-input/2"
    assert len(json.dumps(provider, separators=(",", ":")).encode()) <= 24 * 1024
    assert "workspace" not in provider
    assert "constraints" not in provider


def test_review_basis_allowlist_is_order_independent_and_canonical(tmp_path: Path) -> None:
    packet = _packet(tmp_path, accepted_workspace=True)
    snapshot = packet.documents["evidence_snapshot"]
    basis = snapshot["basis_allowlist"]

    assert basis == sorted(basis)
    assert set(basis) == {
        CLAIM_ID,
        "ev_conn_001",
        "ev_endpoint_0001",
        "ev_tsfreq_001",
        "gr_conn_001",
        "gr_tsfreq_001",
        "nodes/n000/outputs/endpoint-summary.json",
    }

    reordered = {**snapshot, "basis_allowlist": list(reversed(basis))}
    task_path = tmp_path / "task-order.json"
    snapshot_path = tmp_path / "snapshot-order.json"
    task_path.write_text(json.dumps(packet), encoding="utf-8")
    snapshot_path.write_text(json.dumps(reordered), encoding="utf-8")
    script = (
        "const fs=require('node:fs');"
        f"const helper=require({json.dumps(str(TASK_PACKET))});"
        "const task=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));"
        "const snapshot=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));"
        "process.stdout.write(JSON.stringify(helper.validateEvidenceSnapshot(snapshot,task).basis_allowlist));"
    )
    validated = json.loads(_node(script, str(task_path), str(snapshot_path)).stdout)
    assert validated == list(reversed(basis))


@pytest.mark.parametrize("artifact_ref", ["../outside.txt", "/tmp/outside.txt", "nodes/n999/output.log"])
def test_task_packet_rejects_unscoped_artifacts(tmp_path: Path, artifact_ref: str) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        _packet(tmp_path, artifact_ref=artifact_ref)


def test_review_result_accepts_only_bound_advisory_facts(tmp_path: Path) -> None:
    packet = _packet(tmp_path)
    valid = json.loads(_validate_result(tmp_path, packet, _valid_result(packet)).stdout)
    assert valid["facts"][0]["basis_refs"] == [CLAIM_ID, "ev_endpoint_0001"]

    unknown_basis = _valid_result(packet)
    unknown_basis["facts"][0]["basis_refs"] = ["ev_invented"]
    failed = _validate_result(tmp_path, packet, unknown_basis, check=False)
    assert failed.returncode == 2
    assert "outside task packet" in failed.stderr

    authoritative = _valid_result(packet)
    authoritative["payload"]["claim_status"] = "supported"
    failed = _validate_result(tmp_path, packet, authoritative, check=False)
    assert failed.returncode == 2
    assert "authoritative field" in failed.stderr or "unknown fields" in failed.stderr


def test_review_result_rejects_string_risks_and_task_identity_mismatch(tmp_path: Path) -> None:
    packet = _packet(tmp_path)
    invalid = _valid_result(packet)
    invalid["payload"]["options"][0]["risks"] = "Method dependence."
    failed = _validate_result(tmp_path, packet, invalid, check=False)
    assert failed.returncode == 2
    assert "risks must be an array" in failed.stderr

    invalid = _valid_result(packet)
    invalid["operation"] = "connectivity"
    failed = _validate_result(tmp_path, packet, invalid, check=False)
    assert failed.returncode == 2
    assert "operation does not match" in failed.stderr


def test_review_implementation_has_one_prompt_and_no_provider_strict_mode() -> None:
    prompt_dir = REVIEW_AGENT / "prompts"
    assert {path.name for path in prompt_dir.glob("*.md")} == {"core.md", "claim-review.md"}
    assert not list(REVIEW_AGENT.rglob("SKILL.md"))
    assert "constrainedSampling" not in RESULT_TOOL.read_text(encoding="utf-8")
    core = (prompt_dir / "core.md").read_text(encoding="utf-8")
    assert "ts_review_result" in core
    assert "no authority to mutate" in core
    assert "allowlisted basis" in core


def test_agent_directories_separate_shared_protocol_from_review_runtime() -> None:
    assert {path.name for path in AGENT_CORE.iterdir()} == {
        "agent-protocol.cjs",
        "fact-kinds.cjs",
        "failure-taxonomy.cjs",
        "run-journal.cjs",
        "session-lifecycle.cjs",
    }
    assert {path.name for path in REVIEW_AGENT.iterdir()} == {
        "output-schema.cjs",
        "prompts",
        "result-tool.ts",
        "runtime.ts",
        "task-packet.cjs",
    }


def test_session_lifecycle_success_disables_prompt_expansion() -> None:
    script = (
        f"const helper=require({json.dumps(str(SESSION_LIFECYCLE))});"
        "const session={options:null,prompt:async(_p,o)=>{session.options=o;},abort:async()=>{}};"
        "helper.promptWithDeadline(session,'review',{timeoutMs:1000}).then(()=>"
        "process.stdout.write(JSON.stringify(session.options)));"
    )
    assert json.loads(_node(script).stdout) == {"expandPromptTemplates": False}


@pytest.mark.parametrize(("mode", "expected_code"), [("timeout", "TS_SUBAGENT_TIMEOUT"), ("abort", "TS_SUBAGENT_ABORTED")])
def test_session_lifecycle_waits_for_abort_and_disposes(mode: str, expected_code: str) -> None:
    script = (
        f"const helper=require({json.dumps(str(SESSION_LIFECYCLE))});"
        "const controller=new AbortController();"
        "const session={aborted:false,disposed:false,prompt:()=>new Promise(()=>{}),"
        "abort:()=>new Promise((resolve)=>setTimeout(()=>{session.aborted=true;resolve();},10)),"
        "dispose:()=>{session.disposed=true;}};"
        f"if({json.dumps(mode)}==='abort')setTimeout(()=>controller.abort(),5);"
        "helper.withDisposableSession(async()=>({session}),async(created)=>"
        f"helper.promptWithDeadline(created.session,'review',{{timeoutMs:{20 if mode == 'timeout' else 1000},signal:controller.signal}}))"
        ".catch((error)=>process.stdout.write(JSON.stringify({code:error.code,aborted:session.aborted,disposed:session.disposed})));"
    )
    result = json.loads(_node(script).stdout)
    assert result == {"code": expected_code, "aborted": True, "disposed": True}


def test_pi_review_runtime_enforces_isolation_and_provider_failure_priority() -> None:
    runtime = (REVIEW_AGENT / "runtime.ts").read_text(encoding="utf-8")
    extension = (ROOT / "extensions" / "ts-workflow-review" / "index.ts").read_text(encoding="utf-8")

    for expected in (
        'noTools: "builtin"',
        "SessionManager.inMemory(options.workspaceRoot)",
        "SettingsManager.inMemory",
        "noExtensions: true",
        "noSkills: true",
        "noContextFiles: true",
        "forceReviewResultToolChoice",
        "assertProviderTurnSucceeded",
        "withDisposableSession",
    ):
        assert expected in runtime
    assert "provider request failed" in runtime
    assert "writeReviewRootDisposition" in extension
    assert 'executionMode: "sequential"' in extension
