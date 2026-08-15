from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ts_workspace import apply_decision, draft_decision, init_workspace
from ts_workspace.context import build_review_snapshot


REPO_ROOT = Path(__file__).resolve().parents[1]
REVIEW_BUNDLE_PROBE = REPO_ROOT / "tests" / "review_v4_bundle_probe.cjs"


def bootstrap_v4_workspace(root: Path) -> Path:
    init_workspace(root)
    return root


def start_research_act(
    root: Path,
    *,
    objective: str = "Run one bounded research operation.",
    claim_type: str = "test",
    claim_statement: str = "A bounded scientific claim requires evaluation.",
) -> dict[str, str]:
    drafted = draft_decision(
        root,
        {
            "rationale": "Create one Claim and one open ResearchAct for a test.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "create_claim",
                    "local_ref": "claim",
                    "claimType": claim_type,
                    "statement": claim_statement,
                },
                {
                    "op": "start_act",
                    "local_ref": "act",
                    "objective": objective,
                    "claimRefs": ["$claim"],
                },
                {
                    "op": "set_focus",
                    "claimRefs": ["$claim"],
                    "actRefs": ["$act"],
                },
            ],
        },
    )
    apply_decision(root, drafted["decision"])
    return {
        "claim_id": drafted["allocated_refs"]["claim"],
        "act_id": drafted["allocated_refs"]["act"],
    }


def accept_research_claim(root: Path) -> dict[str, str]:
    drafted = draft_decision(
        root,
        {
            "rationale": "Create and accept one deterministically validated Claim.",
            "basis_refs": [],
            "operations": [
                {"op": "create_claim", "local_ref": "claim", "claimType": "research", "statement": "A bounded claim is supported."},
                {"op": "start_act", "local_ref": "act", "objective": "Test the bounded Claim.", "claimRefs": ["$claim"]},
                {
                    "op": "record_observation",
                    "local_ref": "observation",
                    "actRef": "$act",
                    "conceptId": "test.confirmed",
                    "subjectRef": "subject",
                    "value": True,
                    "datatype": "boolean",
                    "summary": "The bounded condition was observed.",
                    "provenance": {"producer": "test"},
                },
                {
                    "op": "freeze_validation_spec",
                    "local_ref": "spec",
                    "actRef": "$act",
                    "targetClaimRef": "$claim",
                    "dimension": "test",
                    "title": "Bounded Claim check",
                    "definition": {
                        "checks": [
                            {
                                "check_id": "confirmed",
                                "predicate": "observation.equals",
                                "parameters": {
                                    "selector": {"concept_id": "test.confirmed", "subject_ref": "subject"},
                                    "expected": True,
                                },
                                "blocking": True,
                            }
                        ],
                        "success_policy": {"mode": "all_blocking"},
                    },
                },
                {"op": "evaluate_validation", "local_ref": "result", "actRef": "$act", "specRef": "$spec", "observationRefs": ["$observation"]},
                {
                    "op": "update_claim",
                    "claimRef": "$claim",
                    "status": "supported",
                    "summary": "The frozen validation passed.",
                    "observationRefs": ["$observation"],
                    "validationResultRefs": ["$result"],
                },
                {
                    "op": "accept_claim",
                    "local_ref": "acceptance",
                    "claimRef": "$claim",
                    "profile": {"profileId": "research-claim", "version": "1"},
                    "summary": "The bounded Claim passed its declared validation.",
                },
                {"op": "set_focus", "claimRefs": ["$claim"], "actRefs": ["$act"]},
            ],
        },
    )
    apply_decision(root, drafted["decision"])
    return drafted["allocated_refs"]


def build_review_bundle(
    root: Path,
    refs: dict[str, str],
    task_id: str,
    *,
    question: str = "Assess whether the current graph supports this Claim.",
    artifact_ids: list[str] | None = None,
    artifact_catalog: list[dict] | None = None,
) -> dict:
    request = {
        "runId": task_id,
        "workspaceRoot": str(root),
        "request": {
            "targetClaimRef": refs["claim_id"],
            "question": question,
            "artifactIds": artifact_ids or [],
        },
        "reviewSnapshot": build_review_snapshot(root, target_claim_ref=refs["claim_id"]),
        "artifactCatalog": artifact_catalog or [],
    }
    request_path = root.parent / f"{task_id}.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    completed = subprocess.run(
        ["node", str(REVIEW_BUNDLE_PROBE), str(request_path)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)
