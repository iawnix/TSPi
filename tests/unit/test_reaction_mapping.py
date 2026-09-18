from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.support.workspace_helpers import apply_change, bootstrap_workspace_fixture, start_research_node
from ts_agent.compute import (
    ComputeContractError,
    create_reaction_mapping_validation_artifact,
    import_calculation_artifact,
    list_calculation_artifacts,
)
from ts_agent.workspace import validate_workspace
from ts_agent.workspace.candidates import load_observation_candidate, ObservationCandidateError
from ts_agent.reaction.mapping import validate_atom_mapping
from ts_agent.compute.analysis import analysis_capabilities, resolve_analysis_capability, run_analysis


def _xyz(symbol: str, comment: str) -> str:
    return f"1\n{comment}\n{symbol} 0.0 0.0 0.0\n"


def _fixture(tmp_path: Path) -> tuple[Path, str, str, str]:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    node_id = start_research_node(workspace)["node_id"]
    reactant = import_calculation_artifact(
        workspace,
        {
            "schema_version": "ts-artifact-import-request/2",
            "node_id": node_id,
            "format": "xyz_structure",
            "input_name": "reactant.xyz",
            "content": _xyz("C", "reactant"),
            "charge": 0,
            "multiplicity": 1,
        },
    )["artifact"]["artifact_id"]
    product = import_calculation_artifact(
        workspace,
        {
            "schema_version": "ts-artifact-import-request/2",
            "node_id": node_id,
            "format": "xyz_structure",
            "input_name": "product.xyz",
            "content": _xyz("C", "product"),
            "charge": 0,
            "multiplicity": 1,
        },
    )["artifact"]["artifact_id"]
    return workspace, node_id, reactant, product


def _pair() -> list[dict[str, dict[str, int]]]:
    return [{"reactant": {"species": 0, "atom": 0}, "product": {"species": 0, "atom": 0}}]


def test_explicit_mapping_validation_writes_node_owned_analysis(tmp_path: Path) -> None:
    workspace, node_id, reactant, product = _fixture(tmp_path)

    result = create_reaction_mapping_validation_artifact(
        workspace,
        {
            "schema_version": "ts-reaction-mapping-validate-request/1",
            "node_id": node_id,
            "reactants": [{"artifact_id": reactant}],
            "products": [{"artifact_id": product}],
            "mapping": _pair(),
        },
    )

    assert result["capability"] == "reaction.mapping.validate"
    assert result["verdict"] == "valid"
    assert result["valid"] is True
    assert result["analysis_artifact"]["owner_node"] == node_id
    assert result["analysis_artifact"]["path"].startswith(f"nodes/{node_id}/outputs/analysis/")
    document = json.loads((workspace / result["analysis_artifact"]["path"]).read_text())
    assert document["inputs"]["reactants"][0]["artifact_id"] == reactant
    assert document["inputs"]["products"][0]["artifact_id"] == product
    assert document["provenance"]["input_digests"] == [
        document["inputs"][side][0]["sha256"] for side in ("reactants", "products")
    ]
    assert validate_workspace(workspace)["valid"] is True


def test_empty_mapping_is_invalid_and_retains_unmapped_atoms(tmp_path: Path) -> None:
    workspace, node_id, reactant, product = _fixture(tmp_path)
    result = create_reaction_mapping_validation_artifact(
        workspace,
        {
            "schema_version": "ts-reaction-mapping-validate-request/1",
            "node_id": node_id,
            "reactants": [{"artifact_id": reactant}],
            "products": [{"artifact_id": product}],
            "mapping": [],
        },
    )

    assert result["verdict"] == "invalid"
    assert result["valid"] is False
    assert "unmapped" in " ".join(result["diagnostics"])


def test_mapping_rejects_unknown_artifacts(tmp_path: Path) -> None:
    workspace, node_id, _reactant, _product = _fixture(tmp_path)

    with pytest.raises(ComputeContractError, match="unknown artifact_id"):
        create_reaction_mapping_validation_artifact(
            workspace,
            {
                "schema_version": "ts-reaction-mapping-validate-request/1",
                "node_id": node_id,
                "reactants": [{"artifact_id": "art_000000000000000000000000"}],
                "products": [{"artifact_id": "art_111111111111111111111111"}],
                "mapping": _pair(),
            },
        )


@pytest.mark.parametrize(("reactants", "products", "mapping", "verdict", "diagnostic"), [
    ([["H", "H"]], [["H", "H"]], _pair(), "inconclusive", "unmapped"),
    ([["H", "H"]], [["H", "H"]], _pair() * 2, "invalid", "more than once"),
    ([["H", "C"]], [["C", "H"]], _pair(), "invalid", "changes element"),
    ([["H", "C"]], [["H", "N"]], _pair(), "invalid", "element counts differ"),
    ([["H"]], [["H"]], [{"reactant": {"species": 1, "atom": 0}, "product": {"species": 0, "atom": 0}}], "invalid", "out of range"),
    ([["H"]], [["H"]], [{"reactant": {"species": 0, "atom": True}, "product": {"species": 0, "atom": 0}}], "invalid", "non-integer"),
    ([["H"]], [["H"]], [None], "invalid", "reactant and product only"),
])
def test_mapping_verdict_distinguishes_missing_evidence_from_contradictions(
    reactants, products, mapping, verdict, diagnostic,
) -> None:
    result = validate_atom_mapping(reactants, products, mapping)
    assert result["valid"] is False
    assert result["verdict"] == verdict
    assert diagnostic in " ".join(result["diagnostics"])


def test_multi_species_mapping_tracks_local_indices() -> None:
    # Explicit H abstraction: H2 + Cl -> H + HCl.
    pairs = [
        {"reactant": {"species": 0, "atom": 0}, "product": {"species": 0, "atom": 0}},
        {"reactant": {"species": 0, "atom": 1}, "product": {"species": 1, "atom": 0}},
        {"reactant": {"species": 1, "atom": 0}, "product": {"species": 1, "atom": 1}},
    ]
    result = validate_atom_mapping([["H", "H"], ["Cl"]], [["H"], ["H", "Cl"]], pairs)
    assert result["valid"] is True
    assert result["unmapped"] == {"reactant": [], "product": []}


def test_unknown_element_is_not_accepted_as_chemical_evidence() -> None:
    with pytest.raises(ValueError, match="not a supported element"):
        validate_atom_mapping([["Xx"]], [["Xx"]], _pair())


def test_analysis_catalog_is_compact_and_details_are_version_bound() -> None:
    catalog = analysis_capabilities()
    assert "parameter_schema" not in catalog["capabilities"][0]
    detail = resolve_analysis_capability("reaction.mapping.validate", "1")
    assert detail["parameter_schema"]["properties"]["mapping"]["maxItems"] == 4096
    detail["parameter_schema"].clear()
    assert resolve_analysis_capability("reaction.mapping.validate", "1")["parameter_schema"]
    assert resolve_analysis_capability("reaction.mapping.validate", "2")["ok"] is False
    assert resolve_analysis_capability("invented.analysis")["reason"] == "capability_unavailable"


def test_analysis_accepts_repeated_species_and_replays_without_duplicate_artifacts(tmp_path: Path) -> None:
    workspace, node_id, reactant, _product = _fixture(tmp_path)
    request = {
        "schema_version": "ts-analysis-request/1", "node_id": node_id,
        "capability": "reaction.mapping.validate", "capability_version": "1",
        "input_artifacts": {"reactants": [reactant, reactant], "products": [reactant, reactant]},
        "parameters": {"mapping": [
            {"reactant": {"species": i, "atom": 0}, "product": {"species": i, "atom": 0}}
            for i in range(2)
        ]},
    }
    first = run_analysis(workspace, request)
    second = run_analysis(workspace, request)
    assert first["valid"] is True
    assert first["created"] is True and second["created"] is False
    assert first["analysis_artifact"] == second["analysis_artifact"]
    artifact_count = list_calculation_artifacts(workspace)["artifact_count"]
    request["capability_version"] = "2"
    assert run_analysis(workspace, request)["reason"] == "capability_unavailable"
    assert list_calculation_artifacts(workspace)["artifact_count"] == artifact_count
    request["capability_version"] = "1"
    request["parameters"]["extra"] = "ignored?"
    with pytest.raises(ComputeContractError, match="analysis parameters"):
        run_analysis(workspace, request)
    request["parameters"].pop("extra")
    request["input_artifacts"]["reactants"] = [reactant] * 65
    with pytest.raises(ComputeContractError, match="input_artifacts.reactants"):
        run_analysis(workspace, request)


def test_mapping_requires_open_node(tmp_path: Path) -> None:
    workspace, node_id, reactant, product = _fixture(tmp_path)
    from tests.support.workspace_helpers import apply_change

    apply_change(
        workspace,
        {
            "rationale": "Close the node before checking the write guard.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "complete_node",
                    "nodeRef": node_id,
                    "outcome": "stopped",
                    "summary": "Stopped for the contract test.",
                }
            ],
        },
    )
    with pytest.raises(ComputeContractError, match="open ResearchNode"):
        create_reaction_mapping_validation_artifact(
            workspace,
            {
                "schema_version": "ts-reaction-mapping-validate-request/1",
                "node_id": node_id,
                "reactants": [{"artifact_id": reactant}],
                "products": [{"artifact_id": product}],
                "mapping": _pair(),
            },
        )


def _analysis_result(workspace, node_id, reactant, product):
    return run_analysis(workspace, {
        "schema_version": "ts-analysis-request/1", "node_id": node_id,
        "capability": "reaction.mapping.validate", "capability_version": "1",
        "input_artifacts": {"reactants": [reactant], "products": [product]},
        "parameters": {"mapping": _pair()},
    })


def test_analysis_candidates_promote_through_existing_change_and_retain_sources(tmp_path: Path) -> None:
    workspace, node_id, reactant, product = _fixture(tmp_path)
    result = _analysis_result(workspace, node_id, reactant, product)
    selected = result["candidate_refs"][0]
    assert selected["conceptId"] == "reaction.mapping.element_bijection"
    assert json.loads((workspace / "observations.json").read_text())["observations"] == []
    apply_change(workspace, {
        "rationale": "Use the checked element correspondence as evidence, without claiming mechanism identity.",
        "basis_refs": [selected["artifactId"]],
        "operations": [{
            "op": "record_observation", "local_ref": "mapping", "nodeRef": node_id,
            "candidate": {key: selected[key] for key in ("artifactId", "candidateId")},
            "conceptId": selected["conceptId"], "subjectRef": "explicit_reaction_mapping",
            "summary": "All supplied atoms have one element-preserving correspondence.",
        }],
    })
    observation = json.loads((workspace / "observations.json").read_text())["observations"][0]
    assert observation["value"] is True
    assert observation["qualifiers"]["producer_kind"] == "analysis"
    assert set(observation["artifact_refs"]) == {reactant, product, selected["artifactId"]}
    assert observation["provenance"]["producer_version"] == "ts.reaction.mapping/1"
    assert validate_workspace(workspace)["valid"] is True


@pytest.mark.parametrize("mutation", ["value", "type", "source", "owner"])
def test_analysis_candidate_rejects_tampering_stale_sources_and_wrong_node(tmp_path: Path, mutation: str) -> None:
    workspace, node_id, reactant, product = _fixture(tmp_path)
    result = _analysis_result(workspace, node_id, reactant, product)
    artifact = result["analysis_artifact"]
    path = workspace / artifact["path"]
    if mutation in {"value", "type"}:
        document = json.loads(path.read_text())
        document["observation_candidates"]["candidates"][0]["value"] = False if mutation == "value" else 1
        path.write_text(json.dumps(document))
        # Even rebinding to the altered artifact's new ID cannot promote it.
        artifact = next(item for item in list_calculation_artifacts(workspace)["artifacts"] if item["path"] == artifact["path"])
    elif mutation == "source":
        (workspace / f"nodes/{node_id}/inputs/reactant.xyz").write_text(_xyz("N", "changed"))
    with pytest.raises(ObservationCandidateError):
        load_observation_candidate(
            workspace, node_id="node_2" if mutation == "owner" else node_id,
            artifact_id=artifact["artifact_id"], artifact_sha256=None, candidate_id="candidate_1",
        )
