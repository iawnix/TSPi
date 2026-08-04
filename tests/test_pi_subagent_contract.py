from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from strict_helpers import bootstrap_strict_workspace
from ts_workspace import report_node, report_workspace


ROOT = Path(__file__).resolve().parents[1]
TASK_PACKET = ROOT / "subagents" / "task-packet.cjs"
OUTPUT_SCHEMA = ROOT / "subagents" / "output-schema.cjs"
SESSION_LIFECYCLE = ROOT / "subagents" / "session-lifecycle.cjs"


def _node_json(script: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "-e", script, *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def _packet(tmp_path: Path, *, artifact_ref: str | None = None) -> dict[str, object]:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    artifact = workspace / "nodes" / "n000" / "outputs" / "endpoint-summary.json"
    artifact.write_text('{"endpoint":"supported"}\n', encoding="utf-8")

    payload = {
        "runId": "sub_test_001",
        "workspaceRoot": str(workspace),
        "request": {
            "reviewType": "mechanism",
            "question": "What assumptions still require a discriminating test?",
            "nodeId": "n000",
            "evidenceRefs": ["ev_endpoint_0001"],
            "artifactRefs": [artifact_ref or "nodes/n000/outputs/endpoint-summary.json"],
        },
        "workspaceReport": report_workspace(workspace),
        "nodeContext": report_node(workspace, "n000"),
        "branchContext": None,
    }
    payload_file = tmp_path / "packet-input.json"
    payload_file.write_text(json.dumps(payload), encoding="utf-8")
    script = (
        "const fs=require('node:fs');"
        f"const helper=require({json.dumps(str(TASK_PACKET))});"
        "const input=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));"
        "process.stdout.write(JSON.stringify(helper.buildTaskPacket(input)));"
    )
    completed = _node_json(script, str(payload_file))
    return json.loads(completed.stdout)


def _validate_result(tmp_path: Path, packet: dict[str, object], result: dict[str, object], *, check: bool = True):
    packet_file = tmp_path / "packet.json"
    advice_file = tmp_path / "advice.json"
    packet_file.write_text(json.dumps(packet), encoding="utf-8")
    advice_file.write_text(json.dumps(result), encoding="utf-8")
    script = (
        "const fs=require('node:fs');"
        f"const helper=require({json.dumps(str(OUTPUT_SCHEMA))});"
        "const packet=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));"
        "const advice=fs.readFileSync(process.argv[2],'utf8');"
        "try { process.stdout.write(JSON.stringify(helper.parseAndValidateReviewResult(advice,packet))); }"
        "catch (error) { process.stderr.write(String(error.message||error)); process.exitCode=2; }"
    )
    return _node_json(script, str(packet_file), str(advice_file), check=check)


def _valid_result(packet: dict[str, object]) -> dict[str, object]:
    scope = packet["scope"]
    assert isinstance(scope, dict)
    return {
        "schema_version": "ts-agent-result/1",
        "task_id": packet["task_id"],
        "role": "review",
        "authority": "advisory",
        "operation": "mechanism",
        "outcome": "success",
        "summary": "The endpoint evidence leaves the electronic timing unresolved.",
        "scope": {
            "report_id": scope["report_id"],
            "node_ids": scope["node_ids"],
            "hypothesis_id": scope["hypothesis_id"],
            "pathway_id": scope["pathway_id"],
        },
        "facts": [
            {
                "kind": "review",
                "layer": "mechanism",
                "statement": "Endpoint support does not establish electronic timing.",
                "status": "uncertain",
                "basis_refs": ["ev_endpoint_0001"],
            }
        ],
        "artifact_refs": [],
        "program": None,
        "payload": {
            "missing_evidence": ["A discriminating electronic-structure diagnostic."],
            "conflicts": [],
            "options": [
                {
                    "action": "Evaluate one method-appropriate electronic diagnostic.",
                    "discriminator": "Whether it contradicts the proposed timing model.",
                    "risks": ["Method dependence."],
                }
            ],
        },
        "limitations": ["Advisory review only."],
        "provenance": {"source": "bounded_task_packet"},
    }


def test_task_packet_is_report_derived_bounded_and_advisory(tmp_path: Path) -> None:
    packet = _packet(tmp_path)

    assert packet["schema_version"] == "ts-agent-task/1"
    assert packet["role"] == "review"
    assert packet["authority"] == "advisory"
    assert packet["operation"] == "mechanism"
    assert packet["inputs"]["evidence_ceiling"] == ["mechanism"]
    assert packet["workspace"]["root"] == str(tmp_path / "ws")
    assert "workspace_root" not in packet["scope"]
    assert packet["scope"]["node_ids"] == ["n000"]
    assert packet["inputs"]["evidence"][0]["evidence_id"] == "ev_endpoint_0001"
    assert packet["inputs"]["artifact_excerpts"][0]["ref"] == "nodes/n000/outputs/endpoint-summary.json"
    assert packet["inputs"]["artifact_excerpts"][0]["text"] == '{"endpoint":"supported"}\n'
    assert packet["inputs"]["basis_allowlist"] == [
        "ev_endpoint_0001",
        "nodes/n000/outputs/endpoint-summary.json",
    ]
    assert "TS workspace context:" in packet["inputs"]["context"]["workspace"]
    assert "TS historical node context:" in packet["inputs"]["context"]["node"]
    assert packet["constraints"]["scientific_decision"] is False
    assert packet["constraints"]["remote_authority"] == "execution_mirror"


@pytest.mark.parametrize(
    "artifact_ref",
    ["../outside.txt", "/tmp/outside.txt", "nodes/n999/outputs/foreign.log"],
)
def test_task_packet_rejects_unscoped_artifacts(tmp_path: Path, artifact_ref: str) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        _packet(tmp_path, artifact_ref=artifact_ref)


def test_advice_validation_accepts_bounded_evidence_referenced_output(tmp_path: Path) -> None:
    packet = _packet(tmp_path)
    completed = _validate_result(tmp_path, packet, _valid_result(packet))
    result = json.loads(completed.stdout)

    assert result["authority"] == "advisory"
    assert result["facts"][0]["basis_refs"] == ["ev_endpoint_0001"]


def test_advice_parse_boundary_normalizes_legacy_completed_and_artifact_ref(tmp_path: Path) -> None:
    packet = _packet(tmp_path)
    advice = _valid_result(packet)
    advice["outcome"] = "completed"
    fact = advice["facts"][0]
    fact["artifact_ref"] = fact.pop("basis_refs")[0]

    completed = _validate_result(tmp_path, packet, advice)
    result = json.loads(completed.stdout)

    assert result["outcome"] == "success"
    assert result["facts"][0]["basis_refs"] == ["ev_endpoint_0001"]
    assert "artifact_ref" not in result["facts"][0]


def test_advice_validation_rejects_cross_layer_claim(tmp_path: Path) -> None:
    packet = _packet(tmp_path)
    advice = _valid_result(packet)
    advice["facts"][0]["layer"] = "connectivity"

    completed = _validate_result(tmp_path, packet, advice, check=False)

    assert completed.returncode == 2
    assert "evidence ceiling" in completed.stderr


def test_advice_validation_rejects_unknown_basis_and_authoritative_fields(tmp_path: Path) -> None:
    packet = _packet(tmp_path)
    advice = _valid_result(packet)
    advice["facts"][0]["basis_refs"] = ["ev_invented"]
    completed = _validate_result(tmp_path, packet, advice, check=False)
    assert completed.returncode == 2
    assert "outside task packet" in completed.stderr

    advice = _valid_result(packet)
    advice["payload"]["hypothesis_status"] = "supported"
    completed = _validate_result(tmp_path, packet, advice, check=False)
    assert completed.returncode == 2
    assert "authoritative field" in completed.stderr


def test_advice_validation_rejects_uncited_and_oversized_output(tmp_path: Path) -> None:
    packet = _packet(tmp_path)
    advice = _valid_result(packet)
    advice["facts"][0]["basis_refs"] = []
    completed = _validate_result(tmp_path, packet, advice, check=False)
    assert completed.returncode == 2
    assert "must cite task packet evidence" in completed.stderr

    oversized = _valid_result(packet)
    oversized["limitations"] = ["x" * (16 * 1024)]
    completed = _validate_result(tmp_path, packet, oversized, check=False)
    assert completed.returncode == 2
    assert "output exceeds" in completed.stderr


def test_prompt_modules_are_private_and_define_all_review_modes() -> None:
    prompt_dir = ROOT / "subagents" / "prompts"
    assert {path.name for path in prompt_dir.glob("*.md")} == {
        "core.md",
        "mechanism.md",
        "candidate.md",
        "tsfreq.md",
        "connectivity.md",
        "final-audit.md",
        "program-failure.md",
    }
    assert not list((ROOT / "subagents").rglob("SKILL.md"))
    core = (prompt_dir / "core.md").read_text(encoding="utf-8")
    assert "Return exactly one JSON object" in core
    assert "no authority to mutate" in core
    assert "payload.missing_evidence" in core
    assert "Every fact must cite at least one allowlisted basis" in core
    assert "never use `completed`" in core
    assert "never use singular `artifact_ref`" in core


def test_session_lifecycle_success_disables_prompt_expansion() -> None:
    script = (
        f"const helper=require({json.dumps(str(SESSION_LIFECYCLE))});"
        "const session={aborted:false,options:null,prompt:async(_p,o)=>{session.options=o;},abort:async()=>{session.aborted=true;}};"
        "helper.promptWithDeadline(session,'review',{timeoutMs:1000}).then(()=>{"
        "process.stdout.write(JSON.stringify(session));"
        "}).catch((error)=>{process.stderr.write(String(error));process.exitCode=2;});"
    )
    completed = _node_json(script)
    result = json.loads(completed.stdout)
    assert result["aborted"] is False
    assert result["options"] == {"expandPromptTemplates": False}


@pytest.mark.parametrize(
    ("mode", "expected_code"),
    [("timeout", "TS_SUBAGENT_TIMEOUT"), ("abort", "TS_SUBAGENT_ABORTED")],
)
def test_session_lifecycle_waits_for_abort_and_disposes(mode: str, expected_code: str) -> None:
    script = (
        f"const helper=require({json.dumps(str(SESSION_LIFECYCLE))});"
        "const controller=new AbortController();"
        "const started=Date.now();"
        "const session={aborted:false,disposed:false,prompt:()=>new Promise(()=>{}),"
        "abort:()=>new Promise((resolve)=>setTimeout(()=>{session.aborted=true;resolve();},15)),"
        "dispose:()=>{session.disposed=true;}};"
        f"if ({json.dumps(mode)}==='abort') setTimeout(()=>controller.abort(),5);"
        "helper.withDisposableSession(async()=>({session}),async(created)=>"
        f"helper.promptWithDeadline(created.session,'review',{{timeoutMs:{20 if mode == 'timeout' else 1000},signal:controller.signal}}))"
        ".then(()=>{process.stderr.write('unexpected success');process.exitCode=3;})"
        ".catch((error)=>{process.stdout.write(JSON.stringify({"
        "code:error.code,aborted:session.aborted,disposed:session.disposed,elapsed:Date.now()-started}));});"
    )
    completed = _node_json(script)
    result = json.loads(completed.stdout)
    assert result["code"] == expected_code
    assert result["aborted"] is True
    assert result["disposed"] is True
    assert result["elapsed"] >= 15


@pytest.mark.parametrize("mode", ["success", "error"])
def test_disposable_session_covers_success_and_error(mode: str) -> None:
    script = (
        f"const helper=require({json.dumps(str(SESSION_LIFECYCLE))});"
        "const session={disposed:false,dispose:()=>{session.disposed=true;}};"
        f"helper.withDisposableSession(async()=>({{session}}),async()=>{{if({json.dumps(mode)}==='error')throw new Error('boom');return 'ok';}})"
        ".then((value)=>process.stdout.write(JSON.stringify({value,disposed:session.disposed})))"
        ".catch((error)=>process.stdout.write(JSON.stringify({error:error.message,disposed:session.disposed})));"
    )
    completed = _node_json(script)
    result = json.loads(completed.stdout)
    assert result["disposed"] is True
    assert result.get("value") == ("ok" if mode == "success" else None)
    assert result.get("error") == ("boom" if mode == "error" else None)


def test_pi_subagent_runtime_and_extension_enforce_isolation() -> None:
    runtime = (ROOT / "subagents" / "runtime.ts").read_text(encoding="utf-8")
    extension = (ROOT / "extensions" / "ts-workflow-subagent" / "index.ts").read_text(encoding="utf-8")

    assert 'noTools: "all"' in runtime
    assert "SessionManager.inMemory(options.workspaceRoot)" in runtime
    assert "SettingsManager.inMemory" in runtime
    assert "getAgentsFiles: () => ({ agentsFiles: [] })" in runtime
    assert "const extensionsResult = { extensions: [], errors: [], runtime: createExtensionRuntime() }" in runtime
    assert "withDisposableSession" in runtime
    assert "parseAndValidateReviewResult" in runtime
    assert "setRuntimeApiKey" in runtime
    assert 'name: "ts_workspace_subagent"' in extension
    assert 'executionMode: "sequential"' in extension
    assert 'pi.appendEntry("ts-workspace-subagent-run"' in extension
    assert "getApiKeyAndHeaders" in extension
    assert "parentApiKey" not in (ROOT / "subagents" / "task-packet.cjs").read_text(encoding="utf-8")
