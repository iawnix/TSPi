from __future__ import annotations

from pathlib import Path

import pytest

from ts_agent.compute.artifacts import import_calculation_artifact, list_calculation_artifacts, resolve_artifact_ids
from ts_agent.compute.contracts import ComputeContractError
from ts_agent.compute.control import create_calculation_intent, prepare_calculation
from ts_agent.workspace.decision import draft_decision
from ts_agent.workspace.engine import apply_decision, init_workspace


def _open_node(root: Path) -> str:
    drafted = draft_decision(
        root,
        {
            "rationale": "Create one bounded calculation node.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "create_phase",
                    "local_ref": "phase",
                    "title": "Candidate validation",
                    "objective": "Evaluate one transition-state candidate.",
                },
                {
                    "op": "create_claim",
                    "local_ref": "claim",
                    "claimType": "transition_state",
                    "statement": "The candidate may be a transition state.",
                },
                {
                    "op": "start_node",
                    "local_ref": "calculation",
                    "phaseRef": "$phase",
                    "title": "Bounded research node",
                    "deliverable": "One bounded research result.",
                    "objective": "Evaluate the candidate with Gaussian.",
                    "primaryClaimRef": "$claim",
                    "claimRefs": ["$claim"],
                },
            ],
        },
    )
    apply_decision(root, drafted["decision"])
    return drafted["allocated_refs"]["calculation"]


def _gaussian_input(root: Path) -> Path:
    path = root / "inputs" / "candidate.gjf"
    path.write_text(
        "%nprocshared=2\n#p hf/sto-3g sp\n\nH2\n\n0 1\nH 0 0 0\nH 0 0 0.74\n\n",
        encoding="utf-8",
    )
    return path


def test_artifact_to_prepared_intent_is_research_node_scoped(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    node_id = _open_node(root)
    _gaussian_input(root)

    catalog = list_calculation_artifacts(root)
    artifact = next(item for item in catalog["artifacts"] if item["path"] == "inputs/candidate.gjf")
    assert artifact["artifact_id"].startswith("art_")
    assert resolve_artifact_ids(root, [artifact["artifact_id"]]) == [artifact]

    created = create_calculation_intent(
        root,
        {
            "schema_version": "ts-calculation-request/3",
            "node_id": node_id,
            "purpose": "Run a bounded Gaussian single point.",
            "attempt_kind": "primary",
            "recalculation_ref": None,
            "backend": "gaussian",
            "task_type": "sp",
            "input_artifacts": [{"input_role": "gjf", "artifact_id": artifact["artifact_id"]}],
            "settings": {},
            "execution_target": {"kind": "local"},
            "dry_run": True,
        },
    )
    assert created["schema_version"] == "ts-calculation-intent-created/3"
    assert created["intent"]["schema_version"] == "ts-calculation-intent/5"
    assert created["node_id"] == node_id
    assert created["intent_ref"].startswith(f"nodes/{node_id}/attempts/")
    assert created["input_bindings"][0]["artifact_id"] == artifact["artifact_id"]

    prepared = prepare_calculation(root, created["intent_ref"], created["intent_digest"])
    assert prepared["result"]["schema_version"] == "ts-calculation-result/2"
    assert prepared["result"]["node_id"] == node_id
    assert prepared["result"]["state"] == "prepared"


def test_fresh_workspace_imports_first_artifact_before_compute_prepare(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    node_id = _open_node(root)
    assert list_calculation_artifacts(root)["artifacts"] == []

    imported = import_calculation_artifact(
        root,
        {
            "schema_version": "ts-artifact-import-request/1",
            "node_id": node_id,
            "format": "gaussian_input",
            "content": "#p hf/sto-3g sp\n\nH2\n\n0 1\nH 0 0 0\nH 0 0 0.74\n\n",
            "charge": 0,
            "multiplicity": 1,
        },
    )
    artifact_id = imported["artifact"]["artifact_id"]
    catalog = list_calculation_artifacts(root, node_id=node_id)
    assert [item["artifact_id"] for item in catalog["artifacts"]] == [artifact_id]

    created = create_calculation_intent(
        root,
        {
            "schema_version": "ts-calculation-request/3",
            "node_id": node_id,
            "purpose": "Verify first-artifact bootstrap.",
            "attempt_kind": "primary",
            "recalculation_ref": None,
            "backend": "gaussian",
            "task_type": "sp",
            "input_artifacts": [{"input_role": "gjf", "artifact_id": artifact_id}],
            "settings": {},
            "execution_target": {"kind": "local"},
            "dry_run": True,
        },
    )
    prepared = prepare_calculation(root, created["intent_ref"], created["intent_digest"])
    assert prepared["result"]["state"] == "prepared"


def test_closed_research_node_cannot_create_a_calculation(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    node_id = _open_node(root)
    drafted = draft_decision(
        root,
        {
            "rationale": "Close the bounded node.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "complete_node",
                    "nodeRef": node_id,
                    "outcome": "completed",
                    "summary": "No further calculation is needed.",
                }
            ],
        },
    )
    apply_decision(root, drafted["decision"])
    _gaussian_input(root)
    artifact = list_calculation_artifacts(root)["artifacts"][0]
    with pytest.raises(ComputeContractError, match="open ResearchNode"):
        create_calculation_intent(
            root,
            {
                "schema_version": "ts-calculation-request/3",
                "node_id": node_id,
                "purpose": "This should be rejected.",
                "attempt_kind": "primary",
                "recalculation_ref": None,
                "backend": "gaussian",
                "task_type": "sp",
                "input_artifacts": [{"input_role": "gjf", "artifact_id": artifact["artifact_id"]}],
                "settings": {},
                "execution_target": {"kind": "local"},
                "dry_run": True,
            },
        )
