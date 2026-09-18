from __future__ import annotations

from pathlib import Path

import pytest

from ts_agent.compute.artifacts import import_calculation_artifact, list_calculation_artifacts, resolve_artifact_ids
from ts_agent.compute.contracts import ComputeContractError
from ts_agent.compute.control import create_calculation_intent, prepare_calculation
from ts_agent.io import read_json, write_json
from ts_agent.research import ResearchKernel
from tests.support.kernel_helpers import compile_change
from ts_agent.workspace.engine import init_workspace
from tests.support.kernel_helpers import apply_compiled_change
from ts_agent.workspace.node_contract import node_contract_digest, node_contract_snapshot


def _open_node(root: Path) -> str:
    current = ResearchKernel(root).load()
    phase_id = f"phase_{len(current.phases) + 1}"
    claim_id = f"claim_{len(current.claims) + 1}"
    node_id = f"node_{len(current.nodes) + 1}"
    drafted = compile_change(
        root,
        {
            "rationale": "Create one bounded calculation node.",
            "basis_refs": [],
            "operations": [
                {"type": "create_phase", "id": phase_id, "title": "Candidate validation", "objective": "Evaluate one transition-state candidate."},
                {"type": "create_claim", "id": claim_id, "statement": "The candidate may be a transition state."},
                {"type": "create_node", "id": node_id, "phase_id": phase_id, "claim_ids": [claim_id], "dependency_ids": [], "title": "Bounded research node", "objective": "Evaluate the candidate with Gaussian."},
            ],
        },
    )
    apply_compiled_change(root, drafted["decision"])
    return drafted["allocated_refs"]["node"]


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
            "schema_version": "ts-calculation-request/5",
            "node_id": node_id,
            "purpose": "Run a bounded Gaussian single point.",
            "attempt_kind": "primary",
            "lineage": None,
            "capability": "gaussian.sp",
            "capability_version": "1",
            "input_artifacts": [{"input_role": "gjf", "artifact_id": artifact["artifact_id"]}],
            "parameters": {},
            "execution_target": {"kind": "local"},
            "dry_run": True,
        },
    )
    assert created["schema_version"] == "ts-calculation-intent-created/4"
    assert created["intent"]["schema_version"] == "ts-calculation-intent/7"
    assert created["intent"]["capability"] == "gaussian.sp"
    assert created["node_id"] == node_id
    assert created["intent_ref"].startswith(f"nodes/{node_id}/attempts/")
    assert created["input_bindings"][0]["artifact_id"] == artifact["artifact_id"]

    prepared = prepare_calculation(root, created["intent_ref"], created["intent_digest"])
    assert prepared["result"]["schema_version"] == "ts-calculation-result/2"
    assert prepared["result"]["node_id"] == node_id
    assert prepared["result"]["state"] == "prepared"


def test_node_contract_digest_tracks_scope_but_not_runtime_state() -> None:
    node = {
        "id": "node_1",
        "phase_id": "phase_1",
        "title": "Locate one saddle",
        "objective": "Locate one first-order saddle for the selected elementary step.",
        "dependency_ids": [],
        "claim_ids": ["claim_1"],
        "state": "open",
        "outcome": None,
        "created_at": "2026-08-28T00:00:00Z",
    }
    initial = node_contract_digest(node)
    node["state"] = "closed"
    node["outcome"] = "completed"

    assert node_contract_digest(node) == initial
    snapshot = node_contract_snapshot(node)
    assert "state" not in snapshot
    assert "outcome" not in snapshot

    node["objective"] = "Determine whether the pathway is dynamically bifurcating."
    assert node_contract_digest(node) != initial


def test_attempt_lineage_distinguishes_exact_retry_from_recalculation(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    node_id = _open_node(root)
    _gaussian_input(root)
    artifact_id = list_calculation_artifacts(root)["artifacts"][0]["artifact_id"]
    alternative_path = root / "inputs" / "alternative.gjf"
    alternative_path.write_text(
        "%nprocshared=2\n#p hf/sto-3g sp\n\nH2 alternative\n\n0 1\nH 0 0 0\nH 0 0 0.75\n\n",
        encoding="utf-8",
    )
    alternative_id = next(
        item["artifact_id"]
        for item in list_calculation_artifacts(root)["artifacts"]
        if item["path"] == "inputs/alternative.gjf"
    )

    def request(kind: str, *, source: str | None = None, input_artifact_id: str = artifact_id) -> dict:
        return {
            "schema_version": "ts-calculation-request/5",
            "node_id": node_id,
            "purpose": f"Run the {kind} candidate calculation.",
            "attempt_kind": kind,
            "lineage": None if source is None else {
                "source_node": node_id,
                "source_intent_id": source,
                "relation": kind,
                "reason": "Verify deterministic Attempt lineage.",
            },
            "capability": "gaussian.sp",
            "capability_version": "1",
            "input_artifacts": [{"input_role": "gjf", "artifact_id": input_artifact_id}],
            "parameters": {},
            "execution_target": {"kind": "local"},
            "dry_run": True,
        }

    primary = create_calculation_intent(root, request("primary"))
    retry = create_calculation_intent(root, request("retry", source=primary["intent_id"]))
    assert retry["intent"]["scientific_intent_digest"] == primary["intent"]["scientific_intent_digest"]
    assert retry["intent"]["lineage"]["changed_fields"] == []

    with pytest.raises(ComputeContractError, match="retry must preserve"):
        create_calculation_intent(
            root,
            request("retry", source=primary["intent_id"], input_artifact_id=alternative_id),
        )
    with pytest.raises(ComputeContractError, match="recalculation must change"):
        create_calculation_intent(root, request("recalculation", source=primary["intent_id"]))

    recalculation = create_calculation_intent(
        root,
        request("recalculation", source=primary["intent_id"], input_artifact_id=alternative_id),
    )
    assert recalculation["intent"]["lineage"]["changed_fields"] == ["input_bindings"]


def test_current_intent_rejects_scientific_or_node_contract_drift(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    node_id = _open_node(root)
    _gaussian_input(root)
    artifact_id = list_calculation_artifacts(root)["artifacts"][0]["artifact_id"]
    request = {
        "schema_version": "ts-calculation-request/5",
        "node_id": node_id,
        "purpose": "Bind one immutable calculation.",
        "attempt_kind": "primary",
        "lineage": None,
        "capability": "gaussian.sp",
        "capability_version": "1",
        "input_artifacts": [{"input_role": "gjf", "artifact_id": artifact_id}],
        "parameters": {},
        "execution_target": {"kind": "local"},
        "dry_run": True,
    }
    created = create_calculation_intent(root, request)
    intent_path = root / created["intent_ref"]
    intent = read_json(intent_path)
    intent["input_bindings"][0]["sha256"] = "sha256:" + "0" * 64
    write_json(intent_path, intent)
    with pytest.raises(ComputeContractError, match="scientific_intent_digest"):
        prepare_calculation(root, created["intent_ref"])

    second = create_calculation_intent(root, request)
    research_map = ResearchKernel(root).load()
    research_map.nodes[node_id].objective = "A different principal objective."
    ResearchKernel(root).save(research_map)
    with pytest.raises(ComputeContractError, match="current ResearchNode contract"):
        prepare_calculation(root, second["intent_ref"])


def test_attempt_lineage_cannot_cross_research_nodes(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    first_node = _open_node(root)
    _gaussian_input(root)
    artifact_id = list_calculation_artifacts(root)["artifacts"][0]["artifact_id"]
    primary = create_calculation_intent(
        root,
        {
            "schema_version": "ts-calculation-request/5",
            "node_id": first_node,
            "purpose": "Create the source Attempt.",
            "attempt_kind": "primary",
            "lineage": None,
            "capability": "gaussian.sp",
            "capability_version": "1",
            "input_artifacts": [{"input_role": "gjf", "artifact_id": artifact_id}],
            "parameters": {},
            "execution_target": {"kind": "local"},
            "dry_run": True,
        },
    )
    second_node = _open_node(root)
    with pytest.raises(ComputeContractError, match="same ResearchNode"):
        create_calculation_intent(
            root,
            {
                "schema_version": "ts-calculation-request/5",
                "node_id": second_node,
                "purpose": "This must be a primary Attempt in the successor Node.",
                "attempt_kind": "retry",
                "lineage": {
                    "source_node": first_node,
                    "source_intent_id": primary["intent_id"],
                    "relation": "retry",
                    "reason": "Invalid cross-Node retry.",
                },
                "capability": "gaussian.sp",
                "capability_version": "1",
                "input_artifacts": [{"input_role": "gjf", "artifact_id": artifact_id}],
                "parameters": {},
                "execution_target": {"kind": "local"},
                "dry_run": True,
            },
        )


def test_fresh_workspace_imports_first_artifact_before_compute_prepare(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    node_id = _open_node(root)
    assert list_calculation_artifacts(root)["artifacts"] == []

    imported = import_calculation_artifact(
        root,
        {
            "schema_version": "ts-artifact-import-request/2",
            "node_id": node_id,
            "format": "gaussian_input",
            "input_name": "candidate.gjf",
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
            "schema_version": "ts-calculation-request/5",
            "node_id": node_id,
            "purpose": "Verify first-artifact bootstrap.",
            "attempt_kind": "primary",
            "lineage": None,
            "capability": "gaussian.sp",
            "capability_version": "1",
            "input_artifacts": [{"input_role": "gjf", "artifact_id": artifact_id}],
            "parameters": {},
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
    drafted = compile_change(
        root,
        {
            "rationale": "Close the bounded node.",
            "basis_refs": [],
            "operations": [
                {"type": "set_node_state", "node_id": node_id, "state": "closed", "outcome": "completed", "summary": "No further calculation is needed."}
            ],
        },
    )
    apply_compiled_change(root, drafted["decision"])
    _gaussian_input(root)
    artifact = list_calculation_artifacts(root)["artifacts"][0]
    with pytest.raises(ComputeContractError, match="open ResearchNode"):
        create_calculation_intent(
            root,
            {
                "schema_version": "ts-calculation-request/5",
                "node_id": node_id,
                "purpose": "This should be rejected.",
                "attempt_kind": "primary",
                "lineage": None,
                "capability": "gaussian.sp",
                "capability_version": "1",
                "input_artifacts": [{"input_role": "gjf", "artifact_id": artifact["artifact_id"]}],
                "parameters": {},
                "execution_target": {"kind": "local"},
                "dry_run": True,
            },
        )
