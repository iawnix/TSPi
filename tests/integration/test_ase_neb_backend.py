from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms
from ase.calculators.lj import LennardJones
from ase.units import Bohr, Hartree

from tests.support.workspace_helpers import bootstrap_workspace_fixture, start_research_node
from ts_agent.backends.ase_neb import (
    ASE_NEB_ARTIFACTS,
    parse_ase_neb_artifacts,
    prepare_ase_neb,
    validate_ase_neb_endpoints,
)
from ts_agent.backends.ase_neb_runner import NebRunConfig, XtbCliCalculator, run_ase_neb
from ts_agent.backends.base import BackendTask
from ts_agent.compute import (
    ComputeContractError,
    create_calculation_intent,
    list_calculation_artifacts,
    parse_calculation,
    prepare_calculation,
)
from ts_agent.compute.task_validation import validate_parsed_task


def test_ase_neb_preparer_emits_bounded_explicit_runner_command() -> None:
    prepared = prepare_ase_neb(
        BackendTask(
            node_id="node_1",
            task_type="neb",
            work_dir="nodes/node_1",
            inputs={"reactant": "reactant.xyz", "product": "product.xyz"},
            settings={
                "images": "9",
                "fmax": "0.03",
                "max_steps": "800",
                "spring_constant": "0.2",
                "interpolation": "linear",
                "method": "gfn1",
                "charge": "-1",
                "uhf": "1",
                "climb": "true",
                "remove_rotation_and_translation": "false",
                "accuracy": "0.5",
                "electronic_temperature": "300",
                "solvent_model": "alpb",
                "solvent": "water",
            },
        )
    )

    assert prepared.backend == "ase_neb"
    assert prepared.command[1:5] == [
        "-m",
        "ts_agent.backends.ase_neb_runner",
        "--reactant",
        "reactant.xyz",
    ]
    assert prepared.command[5:7] == ["--product", "product.xyz"]
    assert prepared.command[-8:] == [
        "--accuracy",
        "0.5",
        "--electronic-temperature",
        "300",
        "--solvent-model",
        "alpb",
        "--solvent",
        "water",
    ]
    assert prepared.input_paths == ["reactant.xyz", "product.xyz"]
    assert prepared.expected_artifacts == list(ASE_NEB_ARTIFACTS)


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"images": "2"}, "images must be between"),
        ({"method": "gfnff"}, "method"),
        ({"solvent": "water"}, "provided together"),
        ({"shell": "arbitrary"}, "unsupported.*settings"),
    ],
)
def test_ase_neb_preparer_rejects_unsupported_settings(
    settings: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        prepare_ase_neb(
            BackendTask(
                node_id="node_1",
                task_type="neb",
                work_dir="nodes/node_1",
                inputs={"reactant": "reactant.xyz", "product": "product.xyz"},
                settings=settings,
            )
        )


def test_ase_neb_endpoint_validation_binds_atom_identity_and_order(tmp_path: Path) -> None:
    reactant, product = _endpoints(tmp_path)
    assert validate_ase_neb_endpoints(reactant, product) == {
        "atom_count": 2,
        "symbols": ["H", "H"],
    }

    product.write_text("2\nproduct\nH 0 0 0\nHe 0 0 0.9\n", encoding="utf-8")
    with pytest.raises(ValueError, match="identities and ordering"):
        validate_ase_neb_endpoints(reactant, product)


def test_xtb_cli_calculator_parses_energy_and_converts_gradient_to_forces(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "fake-xtb"
    executable.write_text(
        f"""#!{sys.executable}
from pathlib import Path
Path('gradient').write_text('''$grad
 cycle = 1 SCF energy = -1.25
 0.0 0.0 0.0
 1.0 0.0 0.0
 0.1 0.0 0.0
 -0.1 0.0 0.0
$end
''')
print('* xtb version 6.7.1 (test)')
print('| TOTAL ENERGY -1.250000000000 Eh |')
print('* finished run on 2026/09/15 at 00:00:00')
""",
        encoding="utf-8",
    )
    executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    calculator = XtbCliCalculator(
        executable=str(executable),
        method="gfn2",
        charge=0,
        uhf=0,
        accuracy=0.5,
        electronic_temperature=300.0,
        solvent_model="alpb",
        solvent="water",
    )
    atoms = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.74, 0.0, 0.0]])
    atoms.calc = calculator

    assert atoms.get_potential_energy() == pytest.approx(-1.25 * Hartree)
    assert atoms.get_forces() == pytest.approx(
        np.asarray([[-0.1, 0.0, 0.0], [0.1, 0.0, 0.0]]) * Hartree / Bohr
    )
    assert calculator.program_version == "6.7.1"


def test_ase_neb_runner_generates_complete_artifact_set(tmp_path: Path) -> None:
    reactant = tmp_path / "reactant.xyz"
    product = tmp_path / "product.xyz"
    reactant.write_text("2\nreactant\nAr 0 0 0\nAr 1.2 0 0\n", encoding="utf-8")
    product.write_text("2\nproduct\nAr 0 0 0\nAr 1.4 0 0\n", encoding="utf-8")
    output_dir = tmp_path / "outputs"
    config = NebRunConfig(
        reactant=reactant,
        product=product,
        images=3,
        fmax=10.0,
        max_steps=2,
        spring_constant=0.1,
        interpolation="linear",
        method="gfn2",
        charge=0,
        uhf=0,
        climb=False,
        remove_rotation_and_translation=True,
    )

    summary = run_ase_neb(
        config,
        output_dir=output_dir,
        calculator_factory=lambda _index: LennardJones(),
    )

    assert summary["execution_completed"] is True
    assert summary["converged"] is True
    assert summary["image_count"] == 3
    assert (output_dir / "neb.traj").is_file()
    assert (output_dir / "neb_path.xyz").is_file()
    assert json.loads((output_dir / "neb_summary.json").read_text(encoding="utf-8")) == summary
    (output_dir / "ase_neb.out").write_text("ASE_NEB_RUN_COMPLETED {}\n", encoding="utf-8")
    parsed = parse_ase_neb_artifacts(
        {path.name: path for path in output_dir.iterdir()},
        reactant=reactant,
        product=product,
    )
    assert parsed["summary"]["endpoint_match"] is True


def test_ase_neb_parser_cross_checks_summary_path_endpoints_and_convergence(
    tmp_path: Path,
) -> None:
    reactant, product = _endpoints(tmp_path)
    output_dir = tmp_path / "outputs"
    _synthetic_outputs(output_dir, converged=True)
    artifacts = {path.name: path for path in output_dir.iterdir()}

    parsed = parse_ase_neb_artifacts(
        artifacts,
        reactant=reactant,
        product=product,
        expected_settings={
            "images": "3",
            "fmax": "0.05",
            "max_steps": "500",
            "spring_constant": "0.1",
            "interpolation": "linear",
        },
    )
    facts = parsed["summary"]

    assert facts["execution_completed"] is True
    assert facts["path_complete"] is True
    assert facts["endpoint_match"] is True
    assert facts["image_energies_complete"] is True
    assert facts["force_threshold_satisfied"] is True
    assert validate_parsed_task("ase_neb", "neb", facts) == {
        "status": "completed",
        "failures": [],
    }

    run = json.loads((output_dir / "neb_summary.json").read_text(encoding="utf-8"))
    run["converged"] = False
    (output_dir / "neb_summary.json").write_text(json.dumps(run), encoding="utf-8")
    facts = parse_ase_neb_artifacts(
        artifacts,
        reactant=reactant,
        product=product,
        expected_settings={
            "images": "3",
            "fmax": "0.05",
            "max_steps": "500",
            "spring_constant": "0.1",
            "interpolation": "linear",
        },
    )["summary"]
    assert validate_parsed_task("ase_neb", "neb", facts) == {
        "status": "incomplete",
        "failures": ["neb_not_converged"],
    }


def test_ase_neb_parser_rejects_run_settings_that_differ_from_intent(
    tmp_path: Path,
) -> None:
    reactant, product = _endpoints(tmp_path)
    output_dir = tmp_path / "outputs"
    _synthetic_outputs(output_dir, converged=True)
    artifacts = {path.name: path for path in output_dir.iterdir()}

    facts = parse_ase_neb_artifacts(
        artifacts,
        reactant=reactant,
        product=product,
        expected_settings={"images": "5", "interpolation": "linear"},
    )["summary"]

    assert facts["settings_match"] is False
    assert validate_parsed_task("ase_neb", "neb", facts) == {
        "status": "incomplete",
        "failures": ["run_settings_differ_from_intent"],
    }


def test_ase_neb_compute_flow_prepares_and_parses_bound_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compute_config = tmp_path / "compute.toml"
    compute_config.write_text(
        """default_profile = \"local\"\n\n[profiles.local]\nkind = \"local\"\n\n[profiles.local.software.ase_neb_xtb]\ncommand = \"/bin/true\"\n""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TS_COMPUTE_CONFIG", str(compute_config))
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    node_id = start_research_node(
        workspace,
        objective="Compute and validate one ASE NEB reaction path.",
    )["node_id"]
    inputs = workspace / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    reactant, product = _endpoints(inputs)
    catalog = {item["path"]: item for item in list_calculation_artifacts(workspace)["artifacts"]}
    created = create_calculation_intent(
        workspace,
        {
            "schema_version": "ts-calculation-request/5",
            "node_id": node_id,
            "purpose": "Compute a bounded xTB-backed ASE NEB path.",
            "attempt_kind": "primary",
            "lineage": None,
            "capability": "ase.neb",
            "capability_version": "1",
            "input_artifacts": [
                {
                    "input_role": "reactant",
                    "artifact_id": catalog["inputs/reactant.xyz"]["artifact_id"],
                },
                {
                    "input_role": "product",
                    "artifact_id": catalog["inputs/product.xyz"]["artifact_id"],
                },
            ],
            "parameters": {"images": 3, "interpolation": "linear"},
            "execution_target": {"kind": "local"},
            "dry_run": True,
        },
    )
    prepared = prepare_calculation(workspace, created["intent_ref"])["prepared"]
    assert [Path(ref).name for ref in prepared["prepared_task"]["expected_artifacts"]] == list(
        ASE_NEB_ARTIFACTS
    )
    output_dir = workspace / "nodes" / node_id / "attempts" / created["intent_id"] / "outputs"
    _synthetic_outputs(output_dir, converged=True)

    result = parse_calculation(
        workspace,
        created["intent_id"],
        (output_dir / "neb_summary.json").relative_to(workspace).as_posix(),
    )

    assert result["program_status"] == "completed"
    assert result["task_validation"] == {"status": "completed", "failures": []}
    assert result["provenance"]["parser_contract"] == "ase.neb/1"
    assert len(result["provenance"]["parser_inputs"]) == 6
    assert (output_dir / "parsed/ase_neb_summary.json").is_file()
    assert (output_dir / "parsed/reaction_path.json").is_file()

    product.write_text(reactant.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="different source content"):
        parse_calculation(
            workspace,
            created["intent_id"],
            (output_dir / "neb_summary.json").relative_to(workspace).as_posix(),
        )


def _endpoints(directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    reactant = directory / "reactant.xyz"
    product = directory / "product.xyz"
    reactant.write_text("2\nreactant\nH 0 0 0\nH 0 0 0.7\n", encoding="utf-8")
    product.write_text("2\nproduct\nH 0 0 0\nH 0 0 0.9\n", encoding="utf-8")
    return reactant, product


def _synthetic_outputs(output_dir: Path, *, converged: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    energies = [-10.0, -9.0, -9.5]
    summary = {
        "schema_version": "ase-neb-run/1",
        "backend": "ase_neb",
        "task_type": "neb",
        "execution_completed": True,
        "ase_version": "3.29.0",
        "calculator": "xtb_cli",
        "calculator_version": "6.7.1",
        "method": "gfn2",
        "charge": 0,
        "uhf": 0,
        "accuracy": None,
        "electronic_temperature": None,
        "solvent_model": None,
        "solvent": None,
        "optimizer": "FIRE",
        "interpolation": "linear",
        "climb": False,
        "remove_rotation_and_translation": True,
        "spring_constant_ev_per_angstrom2": 0.1,
        "fmax_ev_per_angstrom": 0.05,
        "max_steps": 500,
        "steps": 42,
        "converged": converged,
        "atom_count": 2,
        "image_count": 3,
        "image_energies_ev": energies,
        "highest_energy_image_index": 1,
        "barrier_forward_ev": 1.0,
        "barrier_reverse_ev": 0.5,
        "max_neb_force_ev_per_angstrom": 0.04,
    }
    (output_dir / "ase_neb.out").write_text(
        'ASE_NEB_RUN_COMPLETED {"converged": true, "images": 3, "steps": 42}\n',
        encoding="utf-8",
    )
    (output_dir / "neb.traj").write_bytes(b"synthetic ASE trajectory")
    frames = []
    distances = [0.7, 0.8, 0.9]
    for index, (energy, distance) in enumerate(zip(energies, distances)):
        frames.append(
            "2\n"
            f"image: {index} energy_ev: {energy:.15g}\n"
            "H 0.000000000000 0.000000000000 0.000000000000\n"
            f"H 0.000000000000 0.000000000000 {distance:.12f}\n"
        )
    (output_dir / "neb_path.xyz").write_text("".join(frames), encoding="utf-8")
    (output_dir / "neb_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
