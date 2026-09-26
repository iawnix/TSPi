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
    _validate_run_summary,
    parse_ase_neb_artifacts,
    prepare_ase_neb,
    validate_ase_neb_endpoints,
)
from ts_agent.backends.ase_neb_runner import (
    NebRunConfig,
    GaussianCliCalculator,
    XtbCliCalculator,
    _configured_xtb_executable,
    _validate_config,
    main as ase_neb_runner_main,
    run_ase_neb,
)
from ts_agent.backends.base import BackendTask
from ts_agent.compute.control import _apply_compute_environment
from ts_agent.compute import (
    ComputeContractError,
    create_calculation_intent,
    list_calculation_artifacts,
    parse_calculation,
    prepare_calculation,
)
from ts_agent.compute.task_validation import validate_parsed_task
from ts_agent.platforms import BackendBinding


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
                "neb_method": "improvedtangent",
                "optimizer": "BFGS",
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
    neb_method_index = prepared.command.index("--neb-method")
    assert prepared.command[neb_method_index : neb_method_index + 4] == [
        "--neb-method",
        "improvedtangent",
        "--optimizer",
        "BFGS",
    ]
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
    ci_index = prepared.command.index("--ci-neb")
    assert prepared.command[ci_index : ci_index + 2] == [
        "--ci-neb",
        "false",
    ]
    assert "--ci-fmax" not in prepared.command
    assert prepared.input_paths == ["reactant.xyz", "product.xyz"]
    assert prepared.expected_artifacts == list(ASE_NEB_ARTIFACTS)


def test_ase_neb_preparer_expands_ci_fmax_default_from_fmax() -> None:
    prepared = prepare_ase_neb(
        BackendTask(
            node_id="node_1",
            task_type="neb",
            work_dir="nodes/node_1",
            inputs={"reactant": "reactant.xyz", "product": "product.xyz"},
            settings={"fmax": "0.03", "ci_neb": "true"},
        )
    )
    ci_index = prepared.command.index("--ci-fmax")
    assert prepared.command[ci_index : ci_index + 2] == ["--ci-fmax", "0.03"]


def test_ase_neb_preparer_exposes_gaussian_calculator_settings() -> None:
    prepared = prepare_ase_neb(
        BackendTask(
            node_id="node_1",
            task_type="neb",
            work_dir="nodes/node_1",
            inputs={"reactant": "reactant.xyz", "product": "product.xyz"},
            settings={
                "calculator": "gaussian_cli",
                "gaussian_route": "#p B3LYP/6-31G(d) Force",
                "gaussian_multiplicity": "1",
                "gaussian_nproc": "4",
                "gaussian_mem": "2GB",
            },
        )
    )
    assert prepared.command[prepared.command.index("--calculator") + 1] == "gaussian_cli"
    assert prepared.command[prepared.command.index("--gaussian-route") + 1] == "#p B3LYP/6-31G(d) Force"
    assert prepared.command[prepared.command.index("--gaussian-mem") + 1] == "2GB"


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"images": "2"}, "images must be between"),
        ({"method": "gfnff"}, "method"),
        ({"solvent": "water"}, "provided together"),
        ({"ci_neb": "true", "climb": "true"}, "mutually exclusive"),
        ({"ci_fmax": "0.02"}, "requires ci_neb"),
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


def test_ase_neb_runner_rejects_ci_fmax_without_ci_neb(tmp_path: Path) -> None:
    config = NebRunConfig(
        reactant=tmp_path / "reactant.xyz",
        product=tmp_path / "product.xyz",
        images=3,
        fmax=0.05,
        max_steps=1,
        spring_constant=0.1,
        interpolation="linear",
        method="gfn2",
        charge=0,
        uhf=0,
        climb=False,
        remove_rotation_and_translation=True,
        ci_fmax=0.02,
    )
    with pytest.raises(ValueError, match="ci_fmax requires ci_neb"):
        _validate_config(config)


def test_ase_neb_runner_cli_rejects_ci_fmax_without_ci_neb(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="ci_fmax requires ci_neb"):
        ase_neb_runner_main(
            [
                "--reactant",
                str(tmp_path / "reactant.xyz"),
                "--product",
                str(tmp_path / "product.xyz"),
                "--images",
                "3",
                "--fmax",
                "0.05",
                "--max-steps",
                "1",
                "--spring-constant",
                "0.1",
                "--interpolation",
                "linear",
                "--neb-method",
                "aseneb",
                "--optimizer",
                "FIRE",
                "--method",
                "gfn2",
                "--charge",
                "0",
                "--uhf",
                "0",
                "--climb",
                "false",
                "--ci-neb",
                "false",
                "--ci-fmax",
                "0.02",
                "--remove-rotation-and-translation",
                "true",
            ]
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


def test_gaussian_cli_calculator_parses_energy_and_forces(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "fake-g16"
    executable.write_text(
        f"""#!{sys.executable}
import sys
sys.stdin.read()
print(' Gaussian 16: Rev. C.01')
print(' SCF Done:  E(RHF) =  -1.2500000000     A.U. after 5 cycles')
print(' Forces (Hartrees/Bohr)')
print(' -------------------------------------------------------------------')
print('     1  1    0.100000  0.000000  0.000000')
print('     2  1   -0.100000  0.000000  0.000000')
print(' Normal termination of Gaussian 16')
""",
        encoding="utf-8",
    )
    executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    calculator = GaussianCliCalculator(
        executable=str(executable),
        route="#p HF/3-21G Force",
        charge=0,
        multiplicity=1,
        nproc=1,
        mem="1GB",
    )
    atoms = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.74, 0.0, 0.0]])
    atoms.calc = calculator

    assert atoms.get_potential_energy() == pytest.approx(-1.25 * Hartree)
    assert atoms.get_forces() == pytest.approx(
        np.asarray([[0.1, 0.0, 0.0], [-0.1, 0.0, 0.0]]) * Hartree / Bohr
    )
    assert calculator.program_version == "C.01"


def test_ase_neb_prefers_injected_xtb_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TS_ASE_NEB_XTB", "/managed/xtb/bin/xtb")
    monkeypatch.setattr(
        "ts_agent.backends.ase_neb_runner.configured_backend_command",
        lambda _backend: pytest.fail("local compute config should not be consulted"),
    )
    assert _configured_xtb_executable() == "/managed/xtb/bin/xtb"


def test_ase_neb_remote_binding_requires_explicit_xtb_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "ts_agent.compute.control._backend_binding",
        lambda *_args: BackendBinding(command=("/managed/ase/bin/python",)),
    )
    task = prepare_ase_neb(
        BackendTask(
            node_id="node_1",
            task_type="neb",
            work_dir="nodes/node_1",
            inputs={"reactant": "reactant.xyz", "product": "product.xyz"},
        )
    )
    with pytest.raises(ComputeContractError, match="requires environment.TS_ASE_NEB_XTB"):
        _apply_compute_environment(
            tmp_path, {"execution_target": {"kind": "remote"}}, task
        )


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
    assert summary["ci_neb"] is False
    assert summary["ci_fmax_ev_per_angstrom"] is None
    assert summary["settings"]["ci_fmax"] is None
    assert summary["image_count"] == 3
    assert (output_dir / "neb.traj").is_file()
    assert (output_dir / "neb_path.xyz").is_file()
    assert json.loads((output_dir / "neb_summary.json").read_text(encoding="utf-8")) == summary
    (output_dir / "ase_neb.out").write_text("ASE_NEB_RUN_COMPLETED {}\n", encoding="utf-8")
    parsed = parse_ase_neb_artifacts(
        {path.name: path for path in output_dir.iterdir()},
        reactant=reactant,
        product=product,
        expected_settings={
            "images": "3",
            "fmax": "10",
            "max_steps": "2",
            "spring_constant": "0.1",
            "interpolation": "linear",
        },
    )
    assert parsed["summary"]["endpoint_match"] is True
    assert parsed["summary"]["settings_match"] is True


def test_ase_neb_parser_accepts_legacy_ci_summary_without_ci_fmax(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "outputs"
    _synthetic_outputs(output_dir, converged=True)
    summary_path = output_dir / "neb_summary.json"
    run = json.loads(summary_path.read_text(encoding="utf-8"))
    energies = run["image_energies_ev"]
    run.update(
        {
            "ci_neb": True,
            "stages": [
                {
                    "stage": "neb",
                    "climb": False,
                    "fmax_ev_per_angstrom": run["fmax_ev_per_angstrom"],
                    "max_steps": run["max_steps"],
                    "steps": run["steps"],
                    "converged": True,
                    "image_energies_ev": energies,
                    "max_neb_force_ev_per_angstrom": run["max_neb_force_ev_per_angstrom"],
                },
                {
                    "stage": "ci_neb",
                    "climb": True,
                    "fmax_ev_per_angstrom": run["fmax_ev_per_angstrom"],
                    "max_steps": run["max_steps"],
                    "steps": run["steps"],
                    "converged": True,
                    "image_energies_ev": energies,
                    "max_neb_force_ev_per_angstrom": run["max_neb_force_ev_per_angstrom"],
                },
            ],
        }
    )
    summary_path.write_text(json.dumps(run), encoding="utf-8")

    parsed = parse_ase_neb_artifacts(
        {path.name: path for path in output_dir.iterdir()},
        expected_settings={
            "images": "3",
            "fmax": "0.05",
            "max_steps": "500",
            "spring_constant": "0.1",
            "interpolation": "linear",
            "ci_neb": "true",
        },
    )
    assert parsed["summary"]["settings_match"] is True


def test_ase_neb_two_stage_ci_records_stages_and_history(tmp_path: Path) -> None:
    reactant = tmp_path / "reactant.xyz"
    product = tmp_path / "product.xyz"
    reactant.write_text("2\nreactant\nAr 0 0 0\nAr 1.2 0 0\n", encoding="utf-8")
    product.write_text("2\nproduct\nAr 0 0 0\nAr 1.4 0 0\n", encoding="utf-8")
    output_dir = tmp_path / "outputs"
    summary = run_ase_neb(
        NebRunConfig(
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
            ci_neb=True,
            ci_fmax=5.0,
            neb_method="improvedtangent",
            optimizer="BFGS",
        ),
        output_dir=output_dir,
        calculator_factory=lambda _index: LennardJones(),
    )

    assert summary["ci_neb"] is True
    assert summary["ci_fmax_ev_per_angstrom"] == pytest.approx(5.0)
    assert summary["settings"]["ci_fmax"] == pytest.approx(5.0)
    assert [stage["stage"] for stage in summary["stages"]] == ["neb", "ci_neb"]
    assert all(stage["converged"] for stage in summary["stages"])
    history = summary["history"]
    assert history["schema_version"] == "ase-neb-history/1"
    assert history["image_count"] == 3
    assert {record["stage"] for record in history["records"]} == {"neb", "ci_neb"}

    (output_dir / "ase_neb.out").write_text(
        "ASE_NEB_RUN_COMPLETED {}\n",
        encoding="utf-8",
    )
    parsed = parse_ase_neb_artifacts(
        {path.name: path for path in output_dir.iterdir()},
        reactant=reactant,
        product=product,
        expected_settings={
            "images": "3",
            "fmax": "10",
            "max_steps": "2",
            "spring_constant": "0.1",
            "interpolation": "linear",
            "ci_neb": "true",
            "ci_fmax": "5",
            "neb_method": "improvedtangent",
            "optimizer": "BFGS",
        },
    )
    assert parsed["summary"]["settings_match"] is True
    assert parsed["summary"]["history_complete"] is True
    assert parsed["summary"]["history_stages"] == ["neb", "ci_neb"]


def test_ase_neb_summary_keeps_two_stage_state_consistent(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    _synthetic_outputs(output_dir, converged=True)
    summary_path = output_dir / "neb_summary.json"
    run = json.loads(summary_path.read_text(encoding="utf-8"))
    energies = run["image_energies_ev"]
    run.update(
        {
            "ci_neb": True,
            "ci_fmax_ev_per_angstrom": 0.025,
            "steps": 7,
            "max_neb_force_ev_per_angstrom": 0.02,
            "stages": [
                {
                    "stage": "neb",
                    "climb": False,
                    "fmax_ev_per_angstrom": 0.05,
                    "max_steps": 500,
                    "steps": 42,
                    "converged": True,
                    "image_energies_ev": energies,
                    "max_neb_force_ev_per_angstrom": 0.04,
                },
                {
                    "stage": "ci_neb",
                    "climb": True,
                    "fmax_ev_per_angstrom": 0.025,
                    "max_steps": 500,
                    "steps": 7,
                    "converged": True,
                    "image_energies_ev": energies,
                    "max_neb_force_ev_per_angstrom": 0.02,
                },
            ],
            "history": {
                "schema_version": "ase-neb-history/1",
                "image_count": 3,
                "records": [
                    {
                        "stage": "neb",
                        "step": 0,
                        "max_neb_force_ev_per_angstrom": 1.0,
                        "image_energies_ev": energies,
                    },
                    {
                        "stage": "neb",
                        "step": 42,
                        "max_neb_force_ev_per_angstrom": 0.04,
                        "image_energies_ev": energies,
                    },
                    {
                        "stage": "ci_neb",
                        "step": 0,
                        "max_neb_force_ev_per_angstrom": 0.04,
                        "image_energies_ev": energies,
                    },
                    {
                        "stage": "ci_neb",
                        "step": 7,
                        "max_neb_force_ev_per_angstrom": 0.02,
                        "image_energies_ev": energies,
                    },
                ],
            },
        }
    )
    _validate_run_summary(run)

    invalid = json.loads(json.dumps(run))
    invalid["converged"] = False
    with pytest.raises(ValueError, match="convergence disagrees"):
        _validate_run_summary(invalid)

    invalid = json.loads(json.dumps(run))
    invalid["stages"][0]["converged"] = False
    with pytest.raises(ValueError, match="ran before"):
        _validate_run_summary(invalid)

    invalid = json.loads(json.dumps(run))
    invalid["history"]["records"][-1]["stage"] = "neb"
    with pytest.raises(ValueError, match="history stage order"):
        _validate_run_summary(invalid)

    invalid = json.loads(json.dumps(run))
    invalid["stages"][1]["fmax_ev_per_angstrom"] = 0.5
    with pytest.raises(ValueError, match="stage fmax"):
        _validate_run_summary(invalid)

    invalid = json.loads(json.dumps(run))
    invalid["climb"] = True
    with pytest.raises(ValueError, match="mutually exclusive"):
        _validate_run_summary(invalid)

    invalid = json.loads(json.dumps(run))
    invalid["history"]["records"][-1]["step"] = 99
    with pytest.raises(ValueError, match="history steps"):
        _validate_run_summary(invalid)


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
        """default_environment = \"local\"\n\n[environments.local]\nkind = \"local\"\n\n[environments.local.backends.ase_neb_xtb]\ncommand = \"/bin/true\"\n""",
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
