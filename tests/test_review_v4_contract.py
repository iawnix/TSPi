from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ts_compute.artifacts import list_calculation_artifacts
from ts_workspace.context import build_review_snapshot
from ts_workspace.decision import draft_decision
from ts_workspace.engine import apply_decision, init_workspace


REPO = Path(__file__).resolve().parents[1]
OUTPUT_SCHEMA = REPO / "src" / "agents" / "review" / "output-schema.cjs"


def _apply(root: Path, operations: list[dict]) -> dict[str, str]:
    drafted = draft_decision(root, {"rationale": "Seed Review context.", "basis_refs": [], "operations": operations})
    apply_decision(root, drafted["decision"])
    return drafted["allocated_refs"]


def test_review_bundle_uses_dag_objects_and_logical_artifact_ids(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = _apply(
        root,
        [
            {"op": "create_claim", "local_ref": "claim", "claimType": "mechanism", "statement": "The pathway is concerted."},
            {"op": "start_act", "local_ref": "act", "objective": "Test the concerted pathway.", "claimRefs": ["$claim"]},
        ],
    )
    log = root / "inputs" / "diagnostic.log"
    log.write_text("normal termination\nmode follows the proposed coordinate\n", encoding="utf-8")
    artifact = next(item for item in list_calculation_artifacts(root)["artifacts"] if item["path"] == "inputs/diagnostic.log")
    observation_refs = _apply(
        root,
        [
            {
                "op": "record_observation",
                "local_ref": "observation",
                "actRef": refs["act"],
                "conceptId": "program.normal_termination",
                "subjectRef": "calc_probe",
                "value": True,
                "datatype": "boolean",
                "summary": "The bounded calculation terminated normally.",
                "artifacts": [{"artifactId": artifact["artifact_id"], "sha256": artifact["sha256"]}],
                "provenance": {"producer": "test-parser", "producerVersion": "1"},
            },
            {
                "op": "update_claim",
                "claimRef": refs["claim"],
                "status": "supported",
                "summary": "One supporting observation is available.",
                "observationRefs": ["$observation"],
            },
        ],
    )
    snapshot = build_review_snapshot(root, target_claim_ref=refs["claim"])
    payload = {
        "runId": "sub_12345678-1234-1234-1234-123456789abc",
        "workspaceRoot": str(root),
        "request": {
            "targetClaimRef": refs["claim"],
            "question": "Does the current basis support the concerted-pathway Claim?",
            "artifactIds": [artifact["artifact_id"]],
        },
        "reviewSnapshot": snapshot,
        "artifactCatalog": list_calculation_artifacts(root)["artifacts"],
    }
    request_file = tmp_path / "review-request.json"
    request_file.write_text(json.dumps(payload), encoding="utf-8")
    completed = subprocess.run(
        ["node", str(REPO / "tests/review_v4_bundle_probe.cjs"), str(request_file)],
        cwd=REPO,
        check=True,
        text=True,
        capture_output=True,
    )
    bundle = json.loads(completed.stdout)

    assert bundle["task"]["scope"]["act_refs"] == [refs["act"]]
    assert bundle["task"]["scope"]["claim_refs"] == [refs["claim"]]
    assert bundle["task"]["capabilities"] == ["ts_review_artifact_read", "ts_review_result"]
    assert bundle["documents"]["review_snapshot"]["schema_version"] == "ts-review-task-snapshot/2"
    assert bundle["documents"]["provider_input"]["schema_version"] == "ts-review-provider-input/4"
    assert bundle["documents"]["provider_input"]["observations"][0]["observation_id"] == observation_refs["observation"]
    private_manifest = bundle["documents"]["review_snapshot"]["artifact_manifest"][0]
    provider_manifest = bundle["documents"]["provider_input"]["artifact_manifest"][0]
    assert private_manifest["path"] == "inputs/diagnostic.log"
    assert provider_manifest["artifact_id"] == artifact["artifact_id"]
    assert "path" not in provider_manifest
    assert "text" not in provider_manifest
    assert "normal termination" not in json.dumps(bundle["documents"]["provider_input"])
    serialized = json.dumps(bundle["documents"]["provider_input"])
    assert "node_id" not in serialized
    assert "gate_results" not in serialized
    assert "evidence" not in serialized

    result = {
        "schema_version": "ts-agent-result/1",
        "task_id": bundle["task"]["task_id"],
        "role": "review",
        "authority": "advisory",
        "operation": "claim_review",
        "outcome": "partial",
        "summary": "The selected artifact is relevant only after an explicit read.",
        "scope": bundle["task"]["scope"],
        "facts": [{
            "kind": "review",
            "statement": "The selected artifact terminated normally.",
            "status": "observed",
            "basis_refs": [artifact["artifact_id"]],
        }],
        "artifact_refs": [],
        "program": None,
        "payload": {"missing_evidence": [], "conflicts": [], "options": []},
        "limitations": [],
        "provenance": {"source": "bounded_task_packet"},
    }
    unread = _validate_review_result(bundle, result, [])
    assert unread.returncode == 2
    assert "was not read" in unread.stderr
    read = _validate_review_result(bundle, result, [artifact["artifact_id"]])
    assert read.returncode == 0, read.stderr


def _validate_review_result(bundle: dict, result: dict, read_artifact_ids: list[str]) -> subprocess.CompletedProcess[str]:
    script = (
        f"const schema=require({json.dumps(str(OUTPUT_SCHEMA))});"
        "const bundle=JSON.parse(process.argv[1]);const result=JSON.parse(process.argv[2]);"
        "const reads=JSON.parse(process.argv[3]);"
        "try{process.stdout.write(JSON.stringify(schema.validateReviewResult(result,bundle.task,bundle.documents.review_snapshot,reads)));}"
        "catch(error){process.stderr.write(error.message);process.exitCode=2;}"
    )
    return subprocess.run(
        ["node", "-e", script, json.dumps(bundle), json.dumps(result), json.dumps(read_artifact_ids)],
        cwd=REPO,
        check=False,
        text=True,
        capture_output=True,
    )
