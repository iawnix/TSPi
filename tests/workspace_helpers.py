from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ts_agent.io import sha256_json
from ts_agent.workspace import change_workspace, init_workspace
from ts_agent.workspace.context import build_review_snapshot
from tests.kernel_helpers import complete_request


REPO_ROOT = Path(__file__).resolve().parents[1]
REVIEW_BUNDLE_PROBE = REPO_ROOT / "tests" / "review_bundle_probe.cjs"
_DIGEST_A = "sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64


def apply_change(root: Path, request: dict[str, Any]) -> dict[str, Any]:
    return change_workspace(root, complete_request(request))


def bootstrap_workspace_fixture(root: Path) -> Path:
    init_workspace(root)
    return root


def calculation_intent_fixture(node_id: str, intent_id: str) -> dict[str, Any]:
    """Return one schema-valid local Attempt intent for lifecycle tests."""

    return {
        "schema_version": "ts-calculation-intent/7",
        "intent_id": intent_id,
        "node_id": node_id,
        "node_contract_digest": _DIGEST_A,
        "scientific_intent_digest": _DIGEST_B,
        "purpose": "Exercise one bounded calculation Attempt lifecycle.",
        "attempt_kind": "primary",
        "lineage": None,
        "capability": "gaussian.opt_freq",
        "capability_version": "1",
        "capability_descriptor_digest": _DIGEST_A,
        "expected_output_roles": ["program_log"],
        "backend": "gaussian",
        "task_type": "opt_freq",
        "input_refs": {"gjf": "inputs/candidate.gjf"},
        "input_bindings": [{
            "input_role": "gjf",
            "artifact_id": "art_" + "a" * 24,
            "path": "inputs/candidate.gjf",
            "sha256": _DIGEST_B,
            "owner_node": node_id,
            "source_intent_id": None,
        }],
        "parameters": {},
        "expected_artifacts": [
            f"nodes/{node_id}/attempts/{intent_id}/outputs/gaussian.out",
        ],
        "execution_target": {"kind": "local"},
        "dry_run": True,
    }


def calculation_result_fixture(
    intent: dict[str, Any],
    *,
    state: str,
    program_status: str,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Return one schema-valid result bound to ``calculation_intent_fixture``."""

    result = {
        "schema_version": "ts-calculation-result/2",
        "job_id": job_id,
        "intent_id": intent["intent_id"],
        "node_id": intent["node_id"],
        "capability": intent["capability"],
        "capability_version": intent["capability_version"],
        "expected_output_roles": list(intent["expected_output_roles"]),
        "state": state,
        "program_status": program_status,
        "exit_status": None,
        "artifact_refs": [],
        "parser_facts": {},
        "error_class": None,
        "provenance": {
            "intent_digest": sha256_json(intent),
            "capability": intent["capability"],
            "capability_version": intent["capability_version"],
            "capability_descriptor_digest": intent["capability_descriptor_digest"],
        },
    }
    if state == "parsed":
        result["task_validation"] = {"status": "completed", "failures": []}
    return result


def calculation_prepared_fixture(intent: dict[str, Any]) -> dict[str, Any]:
    """Return the smallest valid preparation binding for lifecycle fixtures."""

    return {
        "schema_version": "ts-compute-prepared/1",
        "intent_id": intent["intent_id"],
        "node_id": intent["node_id"],
        "intent_ref": (
            f"nodes/{intent['node_id']}/attempts/{intent['intent_id']}/intent.json"
        ),
        "intent_digest": sha256_json(intent),
        "prepared_task": {},
        "execution_policy": {"kind": "local"},
    }


def start_research_node(
    root: Path,
    *,
    title: str = "Bounded research node",
    objective: str = "Run one bounded research operation.",
    deliverable: str = "One bounded research result.",
    claim_type: str = "test",
    claim_statement: str = "A bounded scientific claim requires evaluation.",
) -> dict[str, str]:
    changed = apply_change(
        root,
        {
            "rationale": "Create one Claim and one open ResearchNode for a test.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "create_phase",
                    "local_ref": "phase",
                    "title": "Test phase",
                    "objective": "Contain the bounded test research.",
                },
                {
                    "op": "create_claim",
                    "local_ref": "claim",
                    "claimType": claim_type,
                    "statement": claim_statement,
                },
                {
                    "op": "start_node",
                    "local_ref": "node",
                    "phaseRef": "$phase",
                    "title": title,
                    "objective": objective,
                    "deliverable": deliverable,
                    "primaryClaimRef": "$claim",
                    "claimRefs": ["$claim"],
                },
                {
                    "op": "set_focus",
                    "claimRefs": ["$claim"],
                    "nodeRefs": ["$node"],
                },
            ],
        },
    )
    return {
        "phase_id": changed["allocated_refs"]["phase"],
        "claim_id": changed["allocated_refs"]["claim"],
        "node_id": changed["allocated_refs"]["node"],
    }


def accept_research_claim(root: Path) -> dict[str, str]:
    changed = apply_change(
        root,
        {
            "rationale": "Create and accept one deterministically validated Claim.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "create_phase",
                    "local_ref": "phase",
                    "title": "Validation phase",
                    "objective": "Validate and accept one bounded scientific Claim.",
                },
                {
                    "op": "create_claim",
                    "local_ref": "claim",
                    "question": "Does the bounded observation support this Claim?",
                    "claimType": "research",
                    "statement": "A bounded claim is supported.",
                    "scope": "The single deterministic test observation.",
                    "uncertainty": "The observation has not yet been evaluated.",
                    "predictions": ["test.confirmed is true."],
                    "falsifiers": ["test.confirmed is false or unavailable."],
                },
                {
                    "op": "start_node",
                    "local_ref": "node",
                    "phaseRef": "$phase",
                    "title": "Bounded Claim validation",
                    "objective": "Test the bounded Claim.",
                    "deliverable": "One frozen validation result for the Claim.",
                    "primaryClaimRef": "$claim",
                    "claimRefs": ["$claim"],
                },
                {
                    "op": "record_observation",
                    "local_ref": "observation",
                    "nodeRef": "$node",
                    "conceptId": "test.confirmed",
                    "subjectRef": "subject",
                    "value": True,
                    "datatype": "boolean",
                    "summary": "The bounded condition was observed.",
                    "provenance": {"producer": "test"},
                },
                {
                    "op": "freeze_proof_spec",
                    "local_ref": "spec",
                    "nodeRef": "$node",
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
                {"op": "evaluate_proof", "local_ref": "result", "nodeRef": "$node", "proofRef": "$spec", "observationRefs": ["$observation"]},
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
                {"op": "set_focus", "claimRefs": ["$claim"], "nodeRefs": ["$node"]},
            ],
        },
    )
    return changed["allocated_refs"]


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
