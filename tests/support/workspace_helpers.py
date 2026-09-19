from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ts_agent.io import sha256_json
from ts_agent.workspace import init_workspace
from ts_agent.research import ResearchKernel
from tests.support.kernel_helpers import apply_compiled_change, compile_change


REPO_ROOT = Path(__file__).resolve().parents[2]
REVIEW_BUNDLE_PROBE = REPO_ROOT / "tools" / "test" / "probes" / "review_bundle_probe.cjs"
_DIGEST_A = "sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64


def apply_change(root: Path, request: dict[str, Any]) -> dict[str, Any]:
    drafted = compile_change(root, request)
    return apply_compiled_change(root, drafted["decision"])


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
    changed = apply_change(root, {
        "operations": [
            {"type": "create_phase", "id": "phase_1", "title": "Test phase", "objective": "Contain the bounded test research."},
            {"type": "create_claim", "id": "claim_1", "statement": claim_statement},
            {"type": "create_node", "id": "node_1", "phase_id": "phase_1", "claim_ids": ["claim_1"], "title": title, "objective": objective, "dependency_ids": []},
            {"type": "set_focus", "claim_ids": ["claim_1"], "node_ids": ["node_1"]},
        ],
    })
    research_map = ResearchKernel(root).load()
    node = next(node for node in research_map.nodes.values() if node.id in changed.get("created_ids", []))
    claim = research_map.claims[node.claim_ids[0]]
    phase = research_map.phases[node.phase_id] if node.phase_id else None
    return {
        "phase_id": phase.id if phase else "",
        "claim_id": claim.id,
        "node_id": node.id,
    }


def accept_research_claim(root: Path) -> dict[str, str]:
    refs = start_research_node(root, title="Bounded Claim validation", objective="Test the bounded Claim.")
    apply_change(root, {"operations": [{"type": "create_finding", "id": "finding_1", "node_id": refs["node_id"], "claim_ids": [refs["claim_id"]], "statement": "The bounded condition was observed.", "kind": "fact", "value": True, "datatype": "boolean"}, {"type": "set_claim_status", "claim_id": refs["claim_id"], "status": "supported"}]})
    return refs


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
            "targetClaimId": refs["claim_id"],
            "question": question,
            "artifactIds": artifact_ids or [],
        },
        "researchMap": ResearchKernel(root).load().to_dict(),
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
