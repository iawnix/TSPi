from __future__ import annotations

from pathlib import Path

import pytest

from ts_compute.artifacts import list_calculation_artifacts, resolve_artifact_ids
from ts_compute.contracts import ComputeContractError
from ts_compute.control import create_calculation_intent, prepare_calculation
from ts_workspace.decision import draft_decision
from ts_workspace.engine import apply_decision, init_workspace


def _open_act(root: Path) -> str:
    drafted = draft_decision(
        root,
        {
            "rationale": "Create one bounded calculation act.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "create_claim",
                    "local_ref": "claim",
                    "claimType": "transition_state",
                    "statement": "The candidate may be a transition state.",
                },
                {
                    "op": "start_act",
                    "local_ref": "calculation",
                    "objective": "Evaluate the candidate with Gaussian.",
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


def test_v4_artifact_to_prepared_intent_is_research_act_scoped(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    act_id = _open_act(root)
    _gaussian_input(root)

    catalog = list_calculation_artifacts(root)
    artifact = next(item for item in catalog["artifacts"] if item["path"] == "inputs/candidate.gjf")
    assert artifact["artifact_id"].startswith("art_")
    assert resolve_artifact_ids(root, [artifact["artifact_id"]]) == [artifact]

    created = create_calculation_intent(
        root,
        {
            "schema_version": "ts-calculation-request/2",
            "act_id": act_id,
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
    assert created["schema_version"] == "ts-calculation-intent-created/2"
    assert created["intent"]["schema_version"] == "ts-calculation-intent/4"
    assert created["act_id"] == act_id
    assert created["intent_ref"].startswith(f"acts/{act_id}/attempts/")
    assert created["input_bindings"][0]["artifact_id"] == artifact["artifact_id"]

    prepared = prepare_calculation(root, created["intent_ref"], created["intent_digest"])
    assert prepared["result"]["schema_version"] == "ts-calculation-result/2"
    assert prepared["result"]["act_id"] == act_id
    assert prepared["result"]["state"] == "prepared"


def test_closed_research_act_cannot_create_a_calculation(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    act_id = _open_act(root)
    drafted = draft_decision(
        root,
        {
            "rationale": "Close the bounded act.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "complete_act",
                    "actRef": act_id,
                    "outcome": "completed",
                    "summary": "No further calculation is needed.",
                }
            ],
        },
    )
    apply_decision(root, drafted["decision"])
    _gaussian_input(root)
    artifact = list_calculation_artifacts(root)["artifacts"][0]
    with pytest.raises(ComputeContractError, match="open ResearchAct"):
        create_calculation_intent(
            root,
            {
                "schema_version": "ts-calculation-request/2",
                "act_id": act_id,
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
