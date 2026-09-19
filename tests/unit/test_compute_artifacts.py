from __future__ import annotations

import hashlib
import json
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.support.workspace_helpers import bootstrap_workspace_fixture, start_research_node
from ts_agent.compute import (
    ComputeContractError,
    create_calculation_intent,
    create_structure_comparison_artifact,
    create_structure_seed_artifact,
    import_calculation_artifact,
    list_calculation_artifacts,
    prepare_calculation,
    submit_calculation,
)
from ts_agent.compute.cli import main as compute_cli_main
from ts_agent.remote.errors import RemoteError
from ts_agent.structures import StructureSeedError, generate_smiles_seed


def _workspace(tmp_path: Path) -> tuple[Path, str]:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    refs = start_research_node(
        workspace,
        objective="Exercise deterministic calculation artifact binding.",
    )
    return workspace, refs["node_id"]


def _artifact(catalog: dict, path: str) -> dict:
    return next(item for item in catalog["artifacts"] if item["path"] == path)


def _request(
    node_id: str,
    artifact_id: str,
    *,
    dry_run: bool = True,
    execution_target: dict | None = None,
) -> dict:
    return {
        "schema_version": "ts-calculation-request/5",
        "node_id": node_id,
        "purpose": "Exercise deterministic calculation artifact binding.",
        "attempt_kind": "primary",
        "lineage": None,
        "capability": "gaussian.sp",
        "capability_version": "1",
        "input_artifacts": [{"input_role": "gjf", "artifact_id": artifact_id}],
        "parameters": {},
        "execution_target": execution_target or {"kind": "local"},
        "dry_run": dry_run,
    }


def _structure_comparison_request(node_id: str, reference_id: str, target_id: str) -> dict:
    return {
        "schema_version": "ts-structure-compare-request/1",
        "node_id": node_id,
        "reference_artifact_id": reference_id,
        "target_artifact_id": target_id,
        "parameters": {
            "atomMapping": None,
            "reactionCenterAtoms": [0, 1, 2],
            "keyBonds": [[0, 1], [0, 2]],
            "keyAngles": [[1, 0, 2]],
            "keyDihedrals": [],
            "stereochemicalChecks": [],
            "rmsdThreshold": 0.5,
            "reactionCenterThreshold": 0.25,
        },
    }


def test_artifact_id_binds_path_and_content(tmp_path: Path) -> None:
    workspace, _ = _workspace(tmp_path)
    source = workspace / "inputs" / "source.gjf"
    source.write_text("# HF/STO-3G\n\nSP\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")

    first = _artifact(list_calculation_artifacts(workspace), "inputs/source.gjf")
    renamed = source.with_name("renamed.com")
    source.rename(renamed)
    second = _artifact(list_calculation_artifacts(workspace), "inputs/renamed.com")
    assert second["artifact_id"] != first["artifact_id"]
    assert second["sha256"] == first["sha256"]

    renamed.write_text("# HF/STO-3G\n\nSP changed\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")
    third = _artifact(list_calculation_artifacts(workspace), "inputs/renamed.com")
    assert third["artifact_id"] != second["artifact_id"]
    assert third["sha256"] != second["sha256"]


def test_artifact_import_uses_safe_semantic_name_and_is_idempotent(tmp_path: Path) -> None:
    workspace, node_id = _workspace(tmp_path)
    request = {
        "schema_version": "ts-artifact-import-request/2",
        "node_id": node_id,
        "format": "xyz_structure",
        "input_name": "h2-reference.xyz",
        "content": "2\nH2\nH 0 0 0\nH 0 0 0.74\n",
        "charge": 0,
        "multiplicity": 1,
    }

    first = import_calculation_artifact(workspace, request)
    second = import_calculation_artifact(workspace, request)
    artifact = first["artifact"]
    path = workspace / artifact["path"]

    assert first["schema_version"] == "ts-artifact-import-result/1"
    assert first["created"] is True
    assert second["created"] is False
    assert second["artifact"] == artifact
    assert artifact["artifact_id"].startswith("art_")
    assert artifact["owner_node"] == node_id
    assert artifact["input_roles"] == ["product", "reactant", "xyz"]
    assert artifact["path"] == f"nodes/{node_id}/inputs/h2-reference.xyz"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert first["chemical_metadata"]["atom_order"] == ["H", "H"]
    assert list_calculation_artifacts(workspace, node_id=node_id)["artifacts"] == [artifact]


def test_concurrent_identical_named_import_creates_one_artifact(tmp_path: Path) -> None:
    workspace, node_id = _workspace(tmp_path)
    request = {
        "schema_version": "ts-artifact-import-request/2",
        "node_id": node_id,
        "format": "xyz_structure",
        "input_name": "h2-reference.xyz",
        "content": "2\nH2\nH 0 0 0\nH 0 0 0.74\n",
        "charge": 0,
        "multiplicity": 1,
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: import_calculation_artifact(workspace, request), range(2)))

    assert sorted(result["created"] for result in results) == [False, True]
    assert results[0]["artifact"] == results[1]["artifact"]
    assert len(list_calculation_artifacts(workspace, node_id=node_id)["artifacts"]) == 1


def test_artifact_import_rejects_unsafe_name_extension_and_overwrite(tmp_path: Path) -> None:
    workspace, node_id = _workspace(tmp_path)
    request = {
        "schema_version": "ts-artifact-import-request/2",
        "node_id": node_id,
        "format": "gaussian_input",
        "input_name": "candidate.gjf",
        "content": "#p hf/sto-3g sp\n\nH2\n\n0 1\nH 0 0 0\nH 0 0 0.74\n\n",
        "charge": 0,
        "multiplicity": 1,
    }

    for input_name in ("../escape.gjf", "/tmp/escape.gjf", "candidate input.gjf"):
        with pytest.raises(ComputeContractError, match="safe filename"):
            import_calculation_artifact(workspace, {**request, "input_name": input_name})
    with pytest.raises(ComputeContractError, match=r"must end with \.com or \.gjf"):
        import_calculation_artifact(workspace, {**request, "input_name": "candidate.log"})

    imported = import_calculation_artifact(workspace, request)
    path = workspace / imported["artifact"]["path"]
    original = path.read_bytes()
    with pytest.raises(ComputeContractError, match="already contains different content"):
        import_calculation_artifact(
            workspace,
            {**request, "content": request["content"].replace("0.74", "0.75")},
        )
    assert path.read_bytes() == original
    assert not (tmp_path / "escape.gjf").exists()


def test_rdkit_structure_seed_is_deterministic_and_explicit_about_limitations() -> None:
    first = generate_smiles_seed(
        "C1=CCCCC1",
        charge=0,
        multiplicity=1,
        optimization="uff",
    )
    second = generate_smiles_seed(
        "C1=CCCCC1",
        charge=0,
        multiplicity=1,
        optimization="uff",
    )

    assert first == second
    assert first["schema_version"] == "ts-structure-seed/1"
    assert first["chemical_metadata"]["formula"] == "C6H10"
    assert first["chemical_metadata"]["atom_count"] == 16
    assert first["parameters"]["random_seed"] == 61_453
    assert first["parameters"]["optimization"] == "uff"
    assert first["xyz"].startswith("16\nts-structure-seed/1 ")
    assert any("not a stationary point" in item for item in first["limitations"])


def test_structure_seed_provenance_distinguishes_submitted_and_normalized_smiles() -> None:
    submitted = " CCO "
    result = generate_smiles_seed(
        submitted,
        charge=0,
        multiplicity=1,
        optimization="none",
    )

    assert result["source"]["submitted_sha256"] == (
        "sha256:" + hashlib.sha256(submitted.encode("ascii")).hexdigest()
    )
    assert result["source"]["normalized_sha256"] == (
        "sha256:" + hashlib.sha256(b"CCO").hexdigest()
    )
    with pytest.raises(StructureSeedError, match="one ASCII line"):
        generate_smiles_seed("CCO\n", charge=0, multiplicity=1, optimization="none")


def test_structure_seed_artifact_is_private_content_addressed_and_idempotent(tmp_path: Path) -> None:
    workspace, node_id = _workspace(tmp_path)
    request = {
        "schema_version": "ts-structure-seed-request/1",
        "node_id": node_id,
        "smiles": "C1=CCCCC1",
        "charge": 0,
        "multiplicity": 1,
        "optimization": "uff",
    }

    first = create_structure_seed_artifact(workspace, request)
    second = create_structure_seed_artifact(workspace, request)
    artifact = first["artifact"]
    provenance_artifact = first["provenance_artifact"]
    xyz_path = workspace / artifact["path"]
    provenance_path = workspace / provenance_artifact["path"]
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))

    assert first["schema_version"] == "ts-structure-seed-result/1"
    assert first["created"] is True
    assert second["created"] is False
    assert second["artifact"] == artifact
    assert second["provenance_artifact"] == provenance_artifact
    assert artifact["owner_node"] == node_id
    assert artifact["input_roles"] == ["product", "reactant", "xyz"]
    assert artifact["path"].startswith(f"nodes/{node_id}/inputs/structure_seed_")
    assert provenance_artifact["input_roles"] == ["config"]
    assert provenance["source"]["canonical_smiles"] == "C1=CCCCC1"
    assert provenance["output"]["artifact_id"] == artifact["artifact_id"]
    assert provenance["output"]["sha256"] == artifact["sha256"]
    assert stat.S_IMODE(xyz_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(provenance_path.stat().st_mode) == 0o600
    assert len(list_calculation_artifacts(workspace, node_id=node_id)["artifacts"]) == 2


def test_structure_seed_rejects_chemical_and_contract_mismatches(tmp_path: Path) -> None:
    workspace, node_id = _workspace(tmp_path)
    base = {
        "schema_version": "ts-structure-seed-request/1",
        "node_id": node_id,
        "smiles": "CC",
        "charge": 0,
        "multiplicity": 1,
        "optimization": "none",
    }

    with pytest.raises(ComputeContractError, match="formal charge"):
        create_structure_seed_artifact(workspace, {**base, "charge": 1})
    with pytest.raises(ComputeContractError, match="one connected molecule"):
        create_structure_seed_artifact(workspace, {**base, "smiles": "C.C"})
    with pytest.raises(ComputeContractError, match=r"unexpected=\['output_path'\]"):
        create_structure_seed_artifact(workspace, {**base, "output_path": "/tmp/seed.xyz"})
    with pytest.raises(StructureSeedError, match="electron-count parity"):
        generate_smiles_seed("CC", charge=0, multiplicity=2, optimization="none")


def test_structure_comparison_is_content_addressed_idempotent_and_operational(tmp_path: Path) -> None:
    workspace, node_id = _workspace(tmp_path)
    reference = workspace / "inputs" / "reference.xyz"
    target = workspace / "inputs" / "target.xyz"
    reference.write_text(
        "3\nwater reference\nO 0.0 0.0 0.0\nH 0.96 0.0 0.0\nH -0.24 0.93 0.0\n",
        encoding="utf-8",
    )
    target.write_text(
        "3\nwater target\nO 2.0 -1.0 0.5\nH 2.96 -1.0 0.5\nH 1.76 -0.07 0.5\n",
        encoding="utf-8",
    )
    catalog = list_calculation_artifacts(workspace)
    reference_id = _artifact(catalog, "inputs/reference.xyz")["artifact_id"]
    target_id = _artifact(catalog, "inputs/target.xyz")["artifact_id"]
    request = _structure_comparison_request(node_id, reference_id, target_id)

    first = create_structure_comparison_artifact(workspace, request)
    second = create_structure_comparison_artifact(workspace, request)
    artifact = first["comparison_artifact"]
    output = workspace / artifact["path"]
    document = json.loads(output.read_text(encoding="utf-8"))

    assert first["schema_version"] == "ts-structure-compare-result/1"
    assert first["verdict"] == "matched"
    assert first["created"] is True
    assert second["created"] is False
    assert second["comparison_artifact"] == artifact
    assert artifact["owner_node"] == node_id
    assert artifact["path"].startswith(f"nodes/{node_id}/outputs/analysis/structure_compare_")
    assert artifact["input_roles"] == ["config"]
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert document["schema_version"] == "ts-structure-comparison/1"
    assert document["inputs"]["reference"]["artifact_id"] == reference_id
    assert document["inputs"]["target"]["artifact_id"] == target_id
    assert document["inputs"]["reference"]["sha256"].startswith("sha256:")
    assert document["parameters"]["key_bonds"] == [[0, 1], [0, 2]]
    assert document["units"] == {"angle": "degree", "distance": "angstrom"}
    assert document["provenance"]["producer"] == "ts_agent.structures.compare_structures"
    assert document["metrics"]["heavy_atom_rmsd"] == 0.0
    assert not (workspace / "observations.json").exists()


def test_structure_comparison_rejects_unregistered_shapes_and_invalid_parameters(tmp_path: Path) -> None:
    workspace, node_id = _workspace(tmp_path)
    xyz = workspace / "inputs" / "source.xyz"
    config = workspace / "inputs" / "source.json"
    xyz.write_text("1\nH\nH 0 0 0\n", encoding="utf-8")
    config.write_text("{}\n", encoding="utf-8")
    catalog = list_calculation_artifacts(workspace)
    xyz_id = _artifact(catalog, "inputs/source.xyz")["artifact_id"]
    config_id = _artifact(catalog, "inputs/source.json")["artifact_id"]

    with pytest.raises(ComputeContractError, match="two distinct artifacts"):
        create_structure_comparison_artifact(
            workspace, _structure_comparison_request(node_id, xyz_id, xyz_id)
        )
    with pytest.raises(ComputeContractError, match="target artifact must be XYZ"):
        create_structure_comparison_artifact(
            workspace, _structure_comparison_request(node_id, xyz_id, config_id)
        )
    invalid = _structure_comparison_request(node_id, xyz_id, config_id)
    invalid["parameters"]["keyBonds"] = [[0, 0]]
    with pytest.raises(ComputeContractError, match="atom indices must be distinct"):
        create_structure_comparison_artifact(workspace, invalid)
    unknown = _structure_comparison_request(node_id, xyz_id, config_id)
    unknown["parameters"]["rmsd_threshold"] = 0.5
    with pytest.raises(ComputeContractError, match=r"unexpected=\['rmsd_threshold'\]"):
        create_structure_comparison_artifact(workspace, unknown)
    nested_unknown = _structure_comparison_request(node_id, xyz_id, config_id)
    nested_unknown["parameters"]["stereochemicalChecks"] = [{
        "type": "dihedral",
        "atoms": [0, 1, 2, 3],
        "policy": "retain",
        "max_delta_degrees": 20,
    }]
    with pytest.raises(ComputeContractError, match=r"unexpected=\['max_delta_degrees'\]"):
        create_structure_comparison_artifact(workspace, nested_unknown)


def test_seed_import_rejects_invalid_metadata_content_and_symlink_root(tmp_path: Path) -> None:
    workspace, node_id = _workspace(tmp_path)
    base = {
        "schema_version": "ts-artifact-import-request/2",
        "node_id": node_id,
        "format": "gaussian_input",
        "input_name": "candidate.gjf",
        "content": "#p hf/sto-3g sp\n\nH2\n\n0 1\nH 0 0 0\nH 0 0 0.74\n\n",
        "charge": 0,
        "multiplicity": 1,
    }
    with pytest.raises(ComputeContractError, match="does not match declared"):
        import_calculation_artifact(workspace, {**base, "multiplicity": 3})
    with pytest.raises(ComputeContractError, match="Cartesian coordinates"):
        import_calculation_artifact(
            workspace,
            {**base, "content": base["content"].replace("H 0 0 0.74", "H R1 0 0")},
        )
    with pytest.raises(ComputeContractError, match="exactly one job"):
        import_calculation_artifact(
            workspace,
            {**base, "content": base["content"] + "--Link1--\n%chk=/tmp/escape.chk\n"},
        )
    with pytest.raises(ComputeContractError, match="cannot select filesystem paths"):
        import_calculation_artifact(
            workspace,
            {**base, "content": base["content"] + "%oldchk=../outside.chk\n"},
        )

    unsafe = tmp_path / "outside"
    unsafe.mkdir()
    node_root = workspace / "nodes" / node_id
    node_root.mkdir()
    (node_root / "inputs").symlink_to(unsafe, target_is_directory=True)
    with pytest.raises(ComputeContractError, match="input root is unsafe"):
        import_calculation_artifact(workspace, base)


def test_gaussian_qst_import_validates_every_structure_and_atom_mapping(tmp_path: Path) -> None:
    workspace, node_id = _workspace(tmp_path)
    qst2 = {
        "schema_version": "ts-artifact-import-request/2",
        "node_id": node_id,
        "format": "gaussian_input",
        "input_name": "qst-candidate.gjf",
        "content": (
            "#p hf/sto-3g opt=(qst2,calcfc)\n\nReactant\n\n0 1\n"
            "C 0 0 0\nH 0 0 1\n\nProduct\n\n0 1\nC 0 0 0\nH 0 1 0\n\n"
        ),
        "charge": 0,
        "multiplicity": 1,
    }

    imported = import_calculation_artifact(workspace, qst2)
    assert imported["chemical_metadata"]["structure_count"] == 2
    assert imported["chemical_metadata"]["atom_order"] == ["C", "H"]

    wrong_order = qst2["content"].replace(
        "Product\n\n0 1\nC 0 0 0\nH 0 1 0",
        "Product\n\n0 1\nH 0 1 0\nC 0 0 0",
    )
    with pytest.raises(ComputeContractError, match="atom order does not match"):
        import_calculation_artifact(workspace, {**qst2, "content": wrong_order})

    wrong_spin = qst2["content"].replace("Product\n\n0 1", "Product\n\n0 3")
    with pytest.raises(ComputeContractError, match="does not match declared"):
        import_calculation_artifact(workspace, {**qst2, "content": wrong_spin})

    qst3_missing_guess = qst2["content"].replace("qst2", "qst3")
    with pytest.raises(ComputeContractError, match="title section 3 of 3"):
        import_calculation_artifact(workspace, {**qst2, "content": qst3_missing_guess})


def test_catalog_uses_workspace_and_research_node_ownership(tmp_path: Path) -> None:
    workspace, node_id = _workspace(tmp_path)
    root_input = workspace / "inputs" / "source.xyz"
    root_input.write_text("1\nsource\nH 0 0 0\n", encoding="utf-8")
    root_input.with_name("linked.xyz").symlink_to(root_input)
    node_output = workspace / "nodes" / node_id / "outputs" / "candidate.xyz"
    node_output.parent.mkdir(parents=True)
    node_output.write_text("1\ncandidate\nH 0 0 0\n", encoding="utf-8")

    with pytest.raises(ComputeContractError, match="unknown ResearchNode"):
        list_calculation_artifacts(workspace, node_id="node_999")

    catalog = list_calculation_artifacts(workspace)
    assert [item["path"] for item in catalog["artifacts"]] == [
        "inputs/source.xyz",
        f"nodes/{node_id}/outputs/candidate.xyz",
    ]
    owned = _artifact(catalog, f"nodes/{node_id}/outputs/candidate.xyz")
    shared = _artifact(catalog, "inputs/source.xyz")
    assert owned["owner_node"] == node_id
    assert shared["owner_node"] is None
    assert shared["input_roles"] == ["product", "reactant", "xyz"]
    assert list_calculation_artifacts(workspace, node_id=node_id)["artifacts"] == [owned]


def test_binding_rejects_unknown_incompatible_and_incomplete_roles(tmp_path: Path) -> None:
    workspace, node_id = _workspace(tmp_path)
    gjf = workspace / "inputs" / "source.gjf"
    gjf.write_text("# HF/STO-3G\n\nSP\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")
    xyz = workspace / "inputs" / "source.xyz"
    xyz.write_text("1\nsource\nH 0 0 0\n", encoding="utf-8")
    catalog = list_calculation_artifacts(workspace)
    gjf_artifact = _artifact(catalog, "inputs/source.gjf")
    xyz_artifact = _artifact(catalog, "inputs/source.xyz")

    with pytest.raises(ComputeContractError, match="unknown artifact_id"):
        create_calculation_intent(workspace, _request(node_id, "art_000000000000000000000000"))
    with pytest.raises(ComputeContractError, match="not compatible with input role gjf"):
        create_calculation_intent(workspace, _request(node_id, xyz_artifact["artifact_id"]))

    incomplete = _request(node_id, xyz_artifact["artifact_id"])
    incomplete["capability"] = "xtb.scan"
    incomplete["input_artifacts"] = [
        {"input_role": "xyz", "artifact_id": xyz_artifact["artifact_id"]}
    ]
    with pytest.raises(ComputeContractError, match=r"missing=\['control'\]"):
        create_calculation_intent(workspace, incomplete)

    second_gjf = workspace / "inputs" / "second.gjf"
    second_gjf.write_text("# HF/STO-3G\n\nSecond\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")
    second_artifact = _artifact(list_calculation_artifacts(workspace), "inputs/second.gjf")
    duplicate = _request(node_id, gjf_artifact["artifact_id"])
    duplicate["input_artifacts"].append(
        {"input_role": "gjf", "artifact_id": second_artifact["artifact_id"]}
    )
    with pytest.raises(ComputeContractError, match="duplicate calculation input role"):
        create_calculation_intent(workspace, duplicate)


def test_open_research_node_can_run_any_supported_root_selected_task(tmp_path: Path) -> None:
    workspace, node_id = _workspace(tmp_path)
    source = workspace / "inputs" / "source.gjf"
    source.write_text("# HF/STO-3G opt\n\nOpt\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")
    artifact = _artifact(list_calculation_artifacts(workspace), "inputs/source.gjf")
    request = _request(node_id, artifact["artifact_id"])
    request["capability"] = "gaussian.opt"

    created = create_calculation_intent(workspace, request)
    assert created["node_id"] == node_id
    assert created["intent"]["capability"] == "gaussian.opt"
    assert created["intent"]["backend"] == "gaussian"
    assert created["intent"]["task_type"] == "opt"
    assert created["intent_ref"].startswith(f"nodes/{node_id}/attempts/")


def test_list_artifacts_cli_returns_catalog_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace, node_id = _workspace(tmp_path)
    source = workspace / "nodes" / node_id / "inputs" / "source.xyz"
    source.parent.mkdir(parents=True)
    source.write_text("1\nsource\nH 0 0 0\n", encoding="utf-8")

    assert compute_cli_main([
        "list-artifacts",
        "--root",
        str(workspace),
        "--node-id",
        node_id,
    ]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert '"schema_version": "ts-artifact-catalog/3"' in output.out
    assert f'"path": "nodes/{node_id}/inputs/source.xyz"' in output.out


def test_import_artifact_cli_uses_bounded_request_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace, node_id = _workspace(tmp_path)
    request = tmp_path / "import.json"
    request.write_text(
        json.dumps({
            "schema_version": "ts-artifact-import-request/2",
            "node_id": node_id,
            "format": "xyz_structure",
            "input_name": "hydrogen.xyz",
            "content": "1\nH\nH 0 0 0\n",
            "charge": 0,
            "multiplicity": 2,
        }),
        encoding="utf-8",
    )
    request.chmod(0o600)

    assert compute_cli_main([
        "import-artifact",
        "--root",
        str(workspace),
        "--request-file",
        str(request),
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["artifact"]["artifact_id"].startswith("art_")
    assert result["chemical_metadata"]["multiplicity"] == 2

    request.chmod(0o644)
    assert compute_cli_main([
        "import-artifact",
        "--root",
        str(workspace),
        "--request-file",
        str(request),
    ]) == 2
    assert "must be private" in capsys.readouterr().err


def test_structure_seed_cli_uses_private_bounded_request_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, node_id = _workspace(tmp_path)
    request = tmp_path / "structure-seed.json"
    request.write_text(
        json.dumps({
            "schema_version": "ts-structure-seed-request/1",
            "node_id": node_id,
            "smiles": "CCO",
            "charge": 0,
            "multiplicity": 1,
            "optimization": "uff",
        }),
        encoding="utf-8",
    )
    request.chmod(0o600)

    assert compute_cli_main([
        "structure-seed",
        "--root",
        str(workspace),
        "--request-file",
        str(request),
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["artifact"]["artifact_id"].startswith("art_")
    assert result["chemical_metadata"]["formula"] == "C2H6O"

    request.chmod(0o644)
    assert compute_cli_main([
        "structure-seed",
        "--root",
        str(workspace),
        "--request-file",
        str(request),
    ]) == 2
    assert "must be private" in capsys.readouterr().err


def test_structure_compare_cli_uses_private_bounded_request_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, node_id = _workspace(tmp_path)
    (workspace / "inputs" / "reference.xyz").write_text(
        "1\nreference\nH 0 0 0\n", encoding="utf-8"
    )
    (workspace / "inputs" / "target.xyz").write_text(
        "1\ntarget\nH 1 2 3\n", encoding="utf-8"
    )
    catalog = list_calculation_artifacts(workspace)
    request = tmp_path / "structure-compare.json"
    comparison_request = _structure_comparison_request(
        node_id,
        _artifact(catalog, "inputs/reference.xyz")["artifact_id"],
        _artifact(catalog, "inputs/target.xyz")["artifact_id"],
    )
    comparison_request["parameters"].update({
        "reactionCenterAtoms": [0],
        "keyBonds": [],
        "keyAngles": [],
    })
    request.write_text(json.dumps(comparison_request), encoding="utf-8")
    request.chmod(0o600)

    assert compute_cli_main([
        "structure-compare",
        "--root",
        str(workspace),
        "--request-file",
        str(request),
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["comparison_artifact"]["artifact_id"].startswith("art_")

    request.chmod(0o644)
    assert compute_cli_main([
        "structure-compare",
        "--root",
        str(workspace),
        "--request-file",
        str(request),
    ]) == 2
    assert "must be private" in capsys.readouterr().err


def test_compute_cli_serializes_remote_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_remote(_args) -> dict:
        raise RemoteError("remote status unavailable")

    monkeypatch.setattr("ts_agent.compute.cli._dispatch", fail_remote)
    assert compute_cli_main(["capabilities"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {"ok": False, "error": "remote status unavailable"}


def test_compute_cli_preserves_structured_capability_gap_after_api_normalization(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, node_id = _workspace(tmp_path)
    source = workspace / "inputs" / "source.gjf"
    source.write_text("# HF/STO-3G sp\n\nSP\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")
    artifact_id = _artifact(list_calculation_artifacts(workspace), "inputs/source.gjf")["artifact_id"]
    request = _request(node_id, artifact_id)
    request["capability"] = "photochemistry.surface_hop"

    assert compute_cli_main([
        "create-intent",
        "--root",
        str(workspace),
        "--request-json",
        json.dumps(request),
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema_version"] == "ts-capability-gap/1"
    assert result["reason"] == "capability_unavailable"
    assert result["retryable"] is False
    assert not (workspace / "nodes" / node_id / "attempts").exists()


def test_prepare_and_submit_reject_stale_input_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, node_id = _workspace(tmp_path)
    gjf = workspace / "inputs" / "source.gjf"
    original = "# HF/STO-3G\n\nSP\n\n0 1\nH 0 0 0\n\n"
    gjf.write_text(original, encoding="utf-8")
    artifact_id = _artifact(list_calculation_artifacts(workspace), "inputs/source.gjf")["artifact_id"]

    stale_before_prepare = create_calculation_intent(workspace, _request(node_id, artifact_id))
    gjf.write_text(original.replace("SP", "changed"), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="input binding changed.*artifact_id mismatch"):
        prepare_calculation(workspace, stale_before_prepare["intent_ref"])

    gjf.write_text(original, encoding="utf-8")
    current_id = _artifact(list_calculation_artifacts(workspace), "inputs/source.gjf")["artifact_id"]
    ssh_config = tmp_path / "ssh_config"
    ssh_config.write_text("Host login.test\n  HostName login.test\n", encoding="utf-8")
    remote_config = tmp_path / "compute.toml"
    remote_config.write_text(
        f'''default_environment = "local"

[environments.local]
kind = "local"

[environments.local.backends.gaussian]
command = "g16"

[environments.cluster]
kind = "remote"
ssh_host = "login.test"
ssh_config = "{ssh_config}"
scheduler = "torque"
remote_root = "/remote/ts"
allowed_queues = ["batch"]
max_nodes = 1

[environments.cluster.backends.gaussian]
command = ["g16"]
allowed_queues = ["batch"]
''',
        encoding="utf-8",
    )
    monkeypatch.setenv("TS_COMPUTE_CONFIG", str(remote_config))
    stale_before_submit = create_calculation_intent(
        workspace,
        _request(
            node_id,
            current_id,
            dry_run=False,
            execution_target={
                "kind": "remote",
                "environment": "cluster",
                "resources": {
                    "queue": "batch",
                    "nodes": 1,
                    "ncpus": 8,
                    "memory": "16gb",
                    "walltime": "04:00:00",
                    "ngpus": 0,
                    "mpiprocs": None,
                    "ompthreads": 8,
                },
            },
        ),
    )
    prepare_calculation(workspace, stale_before_submit["intent_ref"])
    gjf.write_text(original.replace("SP", "changed again"), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="input binding changed.*artifact_id mismatch"):
        submit_calculation(workspace, stale_before_submit["intent_id"])
