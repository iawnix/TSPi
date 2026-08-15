from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ts_compute.artifacts import list_calculation_artifacts
from ts_workspace.context import build_review_snapshot
from ts_workspace.decision import draft_decision
from ts_workspace.engine import apply_decision, init_workspace


REPO = Path(__file__).resolve().parents[1]


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
    assert bundle["documents"]["review_snapshot"]["schema_version"] == "ts-review-task-snapshot/1"
    assert bundle["documents"]["provider_input"]["schema_version"] == "ts-review-provider-input/3"
    assert bundle["documents"]["provider_input"]["observations"][0]["observation_id"] == observation_refs["observation"]
    excerpt = bundle["documents"]["provider_input"]["artifact_excerpts"][0]
    assert excerpt["artifact_id"] == artifact["artifact_id"]
    assert "normal termination" in excerpt["text"]
    serialized = json.dumps(bundle["documents"]["provider_input"])
    assert "node_id" not in serialized
    assert "gate_results" not in serialized
    assert "evidence" not in serialized
