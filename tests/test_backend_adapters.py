"""Behavior tests for concrete backend adapters."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from transition_state_workflow.backends import default_backend_registry
from transition_state_workflow.backends.ase import AseBackendAdapter
from transition_state_workflow.backends.base import FilesystemBackendAdapter
from transition_state_workflow.backends.qbics import (
    QbicsBackendAdapter,
    build_qbics_cli_argv,
    normalize_qbics_atom_indices,
    parse_qbics_output_text,
)
from transition_state_workflow.backends.xtb import (
    XtbBackendAdapter,
    build_xtb_cli_argv,
    parse_xtb_output_text,
    xtb_ase_calculator_params,
)


def test_gaussian_runtime_type_aliases_are_python38_compatible() -> None:
    source = Path("src/transition_state_workflow/backends/gaussian.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    aliases = {
        target.id: node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    assert isinstance(aliases["GaussianCoord"], ast.Subscript)
    assert isinstance(aliases["GaussianCoord"].value, ast.Name)
    assert aliases["GaussianCoord"].value.id == "Tuple"
    assert isinstance(aliases["GaussianFrame"], ast.Subscript)
    assert isinstance(aliases["GaussianFrame"].value, ast.Name)
    assert aliases["GaussianFrame"].value.id == "Tuple"


def test_xtb_backend_prepares_normalized_candidate_command(tmp_path: Path) -> None:
    xyz = tmp_path / "candidate.xyz"
    xyz.write_text("1\nH\nH 0 0 0\n", encoding="utf-8")
    prepared = XtbBackendAdapter().prepare(
        {
            "input_file": xyz,
            "task": "opt",
            "method": "gfn2",
            "charge": "-1",
            "multiplicity": "2",
            "accuracy": "0.2",
            "iterations": "150",
            "electronic_temperature": "300",
            "solvent": "water",
        }
    )

    assert prepared.backend == "xtb"
    assert prepared.files == (xyz,)
    assert prepared.command_argv == (
        "xtb",
        str(xyz),
        "--gfn",
        "2",
        "--opt",
        "--chrg",
        "-1",
        "--uhf",
        "1",
        "--acc",
        "0.2",
        "--iterations",
        "150",
        "--etemp",
        "300",
        "--alpb",
        "water",
    )
    assert prepared.metadata == {
        "task": "optimization",
        "method": "GFN2-xTB",
        "charge": -1,
        "uhf": 1,
        "candidate_only": True,
    }
    assert build_xtb_cli_argv.__module__.endswith(".xtb")


def test_xtb_backend_discovers_artifacts_and_parses_log(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "xtbopt.xyz").write_text("1\nopt\nH 0 0 0\n", encoding="utf-8")
    (outputs / "xtb.trj").write_text("trajectory\n", encoding="utf-8")
    (outputs / "charges").write_text("1 0.0\n", encoding="utf-8")
    (outputs / "wbo").write_text("1 2 0.5\n", encoding="utf-8")
    (outputs / "xtb.out").write_text(
        "TOTAL ENERGY      -5.250000 Eh\n"
        "SCF converged\n"
        "GEOMETRY OPTIMIZATION CONVERGED\n"
        "normal termination\n",
        encoding="utf-8",
    )

    parsed = XtbBackendAdapter().parse((outputs,))

    assert parsed.properties["candidate_geometry"] == str(outputs / "xtbopt.xyz")
    assert parsed.properties["trajectory"] == str(outputs / "xtb.trj")
    assert parsed.properties["charges"] == str(outputs / "charges")
    assert parsed.properties["wbo"] == str(outputs / "wbo")
    log_properties = parsed.properties["parsed_logs"][str(outputs / "xtb.out")]
    assert log_properties["electronic_energy_hartree"] == pytest.approx(-5.25)
    assert log_properties["scf_converged"] is True
    assert log_properties["optimization_converged"] is True
    assert parsed.diagnostics == ()


def test_xtb_ase_calculator_params_reuses_backend_normalization() -> None:
    params = xtb_ase_calculator_params(
        {
            "method": "gfn1",
            "charge": "1",
            "multiplicity": "3",
            "solvent": "water",
            "params": {"accuracy": 0.1},
        }
    )

    assert params == {
        "accuracy": 0.1,
        "method": "GFN1-xTB",
        "charge": 1,
        "uhf": 2,
        "solvent": "water",
    }


def test_xtb_log_parser_flags_failed_scf() -> None:
    parsed = parse_xtb_output_text("TOTAL ENERGY -1.0 Eh\nSCF NOT CONVERGED\n")

    assert parsed["electronic_energy_hartree"] == pytest.approx(-1.0)
    assert parsed["scf_converged"] is False
    assert parsed["optimization_converged"] is None


def test_qbics_backend_prepares_dmecp_command(tmp_path: Path) -> None:
    inp = tmp_path / "qbics_input.inp"
    inp.write_text("task\n dmecp b3lyp\nend\n", encoding="utf-8")
    prepared = QbicsBackendAdapter().prepare(
        {
            "input_file": inp,
            "method": "b3lyp",
            "mpi_ranks": "4",
            "threads": "8",
            "memory_gb": "2",
        }
    )

    assert prepared.backend == "qbics"
    assert prepared.files == (inp,)
    assert prepared.command_argv == (
        "mpirun",
        "-np",
        "4",
        "qbics-linux-cpu-mpi",
        str(inp),
        "-n",
        "8",
        "-m",
        "2",
    )
    assert prepared.metadata == {
        "task": "dmecp",
        "method": "b3lyp",
        "candidate_only": True,
        "mpi_ranks": 4,
        "threads": 8,
        "memory_gb": 2,
    }
    assert build_qbics_cli_argv.__module__.endswith(".qbics")


def test_qbics_backend_normalizes_fragment_state_metadata(tmp_path: Path) -> None:
    inp = tmp_path / "qbics_input.inp"
    inp.write_text("task\n dmecp b3lyp\nend\n", encoding="utf-8")
    prepared = QbicsBackendAdapter().prepare(
        {
            "input_file": inp,
            "charge": "0",
            "spin2p1": "2",
            "atom_count": "4",
            "fragments": {
                "frag1": [
                    {"charge": "-1", "spin": "1", "atoms": "1-2"},
                    {"charge": "1", "spin": "2", "atoms": [3, 4]},
                ],
                "frag2": [
                    {"charge": "0", "spin": "2", "atoms": "1,3"},
                    {"charge": "0", "spin": "1", "atoms": "2 4"},
                ],
            },
        }
    )

    assert normalize_qbics_atom_indices("1-2,4") == (1, 2, 4)
    assert prepared.metadata["charge"] == 0
    assert prepared.metadata["spin2p1"] == 2
    assert prepared.metadata["atom_count"] == 4
    assert prepared.metadata["state_definition_priority"] == "fragment"
    assert prepared.metadata["fragment_state_charges"] == {"frag1": 0, "frag2": 0}
    assert prepared.metadata["fragment_states"] == {
        "frag1": (
            {"state": "frag1", "charge": -1, "spin": 1, "atoms": (1, 2), "atom_range": "1-2"},
            {"state": "frag1", "charge": 1, "spin": 2, "atoms": (3, 4), "atom_range": "3-4"},
        ),
        "frag2": (
            {"state": "frag2", "charge": 0, "spin": 2, "atoms": (1, 3), "atom_range": "1,3"},
            {"state": "frag2", "charge": 0, "spin": 1, "atoms": (2, 4), "atom_range": "2,4"},
        ),
    }


def test_qbics_backend_rejects_fragment_charge_mismatch(tmp_path: Path) -> None:
    inp = tmp_path / "qbics_input.inp"
    inp.write_text("task\n dmecp b3lyp\nend\n", encoding="utf-8")

    with pytest.raises(ValueError, match="fragment charges sum"):
        QbicsBackendAdapter().prepare(
            {
                "input_file": inp,
                "charge": 0,
                "frag1": [{"charge": 1, "spin": 1, "atoms": "1"}],
                "frag2": [{"charge": 0, "spin": 1, "atoms": "1"}],
            }
        )


def test_qbics_backend_rejects_fragment_atom_coverage_errors(tmp_path: Path) -> None:
    inp = tmp_path / "qbics_input.inp"
    inp.write_text("task\n dmecp b3lyp\nend\n", encoding="utf-8")

    with pytest.raises(ValueError, match="cover 1..3 exactly once"):
        QbicsBackendAdapter().prepare(
            {
                "input_file": inp,
                "charge": 0,
                "atom_count": 3,
                "frag1": [{"charge": 0, "spin": 1, "atoms": "1-2"}],
                "frag2": [{"charge": 0, "spin": 1, "atoms": "1-3"}],
            }
        )


def test_qbics_backend_rejects_accidental_mixed_frag_and_orb_states(tmp_path: Path) -> None:
    inp = tmp_path / "qbics_input.inp"
    inp.write_text("task\n dmecp b3lyp\nend\n", encoding="utf-8")
    request = {
        "input_file": inp,
        "charge": 0,
        "atom_count": 1,
        "frag1": [{"charge": 0, "spin": 1, "atoms": "1"}],
        "frag2": [{"charge": 0, "spin": 1, "atoms": "1"}],
        "orb1": "state_a",
        "orb2": "state_b",
    }

    with pytest.raises(ValueError, match="mixed QBICS frag/orb"):
        QbicsBackendAdapter().prepare(request)

    prepared = QbicsBackendAdapter().prepare({**request, "allow_mixed_state_definitions": True})

    assert prepared.metadata["state_definition_priority"] == "orbital"
    assert prepared.metadata["orbital_states"] == {"orb1": "state_a", "orb2": "state_b"}


def test_qbics_backend_discovers_candidate_and_scf_failure(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "demo-mecp.xyz").write_text("1\nmecp\nH 0 0 0\n", encoding="utf-8")
    (outputs / "demo-mecp-traj.xyz").write_text("trajectory\n", encoding="utf-8")
    (outputs / "demo.mwfn").write_text("mwfn\n", encoding="utf-8")
    (outputs / "qbics.log").write_text(
        "energy_cov  1.E-5\n"
        "grad_cov    1.E-3\n"
        "SCF does NOT converge\n"
        "final energy = -123.456\n"
        "<S^2> = 0.750\n",
        encoding="utf-8",
    )

    parsed = QbicsBackendAdapter().parse((outputs,))

    assert parsed.properties["candidate_geometries"] == (str(outputs / "demo-mecp.xyz"),)
    assert parsed.properties["trajectory"] == str(outputs / "demo-mecp-traj.xyz")
    assert parsed.properties["mwfn_files"] == (str(outputs / "demo.mwfn"),)
    log_properties = parsed.properties["parsed_logs"][str(outputs / "qbics.log")]
    assert log_properties["thresholds"]["energy_cov"] == pytest.approx(1e-5)
    assert log_properties["scf_converged"] is False
    assert log_properties["final_energy_hartree"] == pytest.approx(-123.456)
    assert log_properties["spin_squared"] == pytest.approx(0.75)
    assert parsed.diagnostics == ("qbics_scf_nonconverged_but_candidate_written",)


def test_qbics_parser_detects_dmecp_nonconvergence() -> None:
    parsed = parse_qbics_output_text("dMECP does not converge\n")

    assert parsed["dmecp_converged"] is False


def test_ase_registry_adapter_is_environment_boundary(tmp_path: Path) -> None:
    endpoint = tmp_path / "reactant.xyz"
    endpoint.write_text("1\nr\nH 0 0 0\n", encoding="utf-8")
    adapter = default_backend_registry().get("ase")

    prepared = adapter.prepare(
        {
            "workflow": "ase-neb",
            "files": [endpoint],
            "calculator": {"type": "xtb"},
        }
    )
    parsed = adapter.parse((endpoint, tmp_path / "missing.traj"))

    assert isinstance(adapter, AseBackendAdapter)
    assert prepared.backend == "ase"
    assert prepared.command_argv == ()
    assert prepared.metadata["adapter_role"] == "ase_runtime_environment"
    assert prepared.metadata["workflow"] == "ase-neb"
    assert prepared.metadata["calculator_type"] == "xtb"
    assert prepared.metadata["execution_backend"] == "ase_neb"
    assert parsed.properties["adapter_role"] == "ase_runtime_environment"
    assert parsed.properties["supported_workflows"] == ("ase-neb",)
    assert AseBackendAdapter.prepare is not FilesystemBackendAdapter.prepare
    assert AseBackendAdapter.parse is not FilesystemBackendAdapter.parse
