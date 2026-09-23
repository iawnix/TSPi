from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path

import pytest

from ts_agent.backends.base import BackendTask
from ts_agent.backends import pyscf as pyscf_backend
from ts_agent.backends.pyscf import (
    PYSCF_ARTIFACTS,
    normalize_pyscf_settings,
    parse_pyscf_artifacts,
    prepare_pyscf,
)
from ts_agent.pyscf import runner as pyscf_runner


def test_pyscf_preparer_emits_explicit_runner_and_fixed_artifacts() -> None:
    prepared = prepare_pyscf(
        BackendTask(
            node_id="node_1",
            task_type="ts_freq",
            work_dir="nodes/node_1",
            inputs={"xyz": "nodes/node_1/inputs/start.xyz"},
            settings={"charge": "-1", "spin": "1", "threads": "4", "use_initial_hessian": "true"},
        )
    )

    assert prepared.backend == "pyscf"
    assert prepared.command[1:7] == [
        "-m",
        "ts_agent.backends.pyscf_runner",
        "--xyz",
        "nodes/node_1/inputs/start.xyz",
        "--task",
        "ts_freq",
    ]
    assert "--use-initial-hessian" in prepared.command
    assert prepared.input_paths == ["nodes/node_1/inputs/start.xyz"]
    assert prepared.expected_artifacts == list(PYSCF_ARTIFACTS["ts_freq"])


def test_pyscf_settings_are_cf22d_bound_and_bounded() -> None:
    normalized = normalize_pyscf_settings({"basis": "def2-svp", "xc": "cf22d"}, "sp")
    assert normalized["xc"] == "CF22D"
    assert normalized["basis"] == "def2-svp"
    assert normalized["grid_level"] == 6
    with pytest.raises(ValueError, match="only permits xc=CF22D"):
        normalize_pyscf_settings({"xc": "B3LYP"}, "sp")
    with pytest.raises(ValueError, match="must be negative"):
        normalize_pyscf_settings({"imaginary_threshold_cm": "0"}, "freq")


def test_pyscf_ts_keeps_source_initial_hessian_default_but_allows_override() -> None:
    assert normalize_pyscf_settings({}, "ts")["use_initial_hessian"] is True
    assert normalize_pyscf_settings({}, "ts_freq")["use_initial_hessian"] is True
    assert normalize_pyscf_settings({"use_initial_hessian": "false"}, "ts")[
        "use_initial_hessian"
    ] is False
    direct = pyscf_runner.PyscfRunConfig(
        xyz=Path("input.xyz"), task_type="ts", output_dir=Path("output")
    )
    assert pyscf_runner._apply_task_defaults(direct).use_initial_hessian is True


def test_pyscf_thermo_payload_preserves_source_energy_and_corrections() -> None:
    config = pyscf_runner.PyscfRunConfig(
        xyz=Path("input.xyz"), task_type="thermo", output_dir=Path("output")
    )
    payload = pyscf_runner._thermo_payload(
        {"ZPE": [0.1], "E_0K": [0.2], "E_tot": [0.3], "H_tot": [0.4], "S_tot": [0.5], "G_tot": [0.6]},
        config,
        electronic_energy=-1.0,
    )
    assert payload["electronic_energy_hartree"] == -1.0
    assert payload["thermal_energy_hartree"] == 0.3
    assert payload["thermal_energy_correction_hartree"] == 1.3
    assert payload["enthalpy_correction_hartree"] == 1.4
    assert payload["gibbs_correction_hartree"] == 1.6
    pyscf_backend._validate_thermo_payload(payload)


def test_pyscf_parser_validates_fixed_manifest_and_settings(tmp_path: Path) -> None:
    result = {
        "schema_version": "pyscf-run/1",
        "backend": "pyscf",
        "task_type": "sp",
        "execution_completed": True,
        "pyscf_version": "2.8.0",
        "settings": normalize_pyscf_settings({}, "sp"),
        "summary": {
            "electronic_energy_hartree": -1.1,
            "scf_converged": True,
        },
    }
    result_path = tmp_path / "pyscf_result.json"
    output_path = tmp_path / "pyscf.out"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    output_path.write_text("PYSCF_RUN_COMPLETED {}\n", encoding="utf-8")

    parsed = parse_pyscf_artifacts(
        "sp",
        {"pyscf_result.json": result_path, "pyscf.out": output_path},
        expected_settings={},
    )
    assert parsed["summary"]["execution_completed"] is True
    assert parsed["summary"]["settings_match"] is True
    assert parsed["summary"]["missing_artifacts"] == []


def test_pyscf_parser_records_missing_required_artifact(tmp_path: Path) -> None:
    result_path = tmp_path / "pyscf_result.json"
    result_path.write_text(
        json.dumps(
            {
                "schema_version": "pyscf-run/1",
                "backend": "pyscf",
                "task_type": "freq",
                "execution_completed": True,
                "settings": normalize_pyscf_settings({}, "freq"),
                "summary": {"frequency_count": 3, "scf_converged": True},
            }
        ),
        encoding="utf-8",
    )
    parsed = parse_pyscf_artifacts("freq", {"pyscf_result.json": result_path}, expected_settings={})
    assert "pyscf.out" in parsed["summary"]["missing_artifacts"]
    assert parsed["summary"]["settings_match"] is True


def test_pyscf_runner_records_runtime_failure_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    xyz = tmp_path / "input.xyz"
    xyz.write_text("1\nH\nH 0 0 0\n", encoding="utf-8")
    output_dir = tmp_path / "output"

    def unavailable_runtime() -> object:
        raise RuntimeError("synthetic missing PySCF runtime")

    monkeypatch.setattr(pyscf_runner, "_load_runtime", unavailable_runtime)
    with pytest.raises(RuntimeError, match="synthetic missing PySCF runtime"):
        pyscf_runner.run_pyscf(
            pyscf_runner.PyscfRunConfig(
                xyz=xyz,
                task_type="sp",
                output_dir=output_dir,
            )
        )

    manifest = json.loads((output_dir / "pyscf_result.json").read_text(encoding="utf-8"))
    assert manifest["execution_completed"] is False
    assert manifest["summary"]["atom_count"] == 1
    assert manifest["error"]["message"] == "synthetic missing PySCF runtime"


def test_pyscf_runtime_loads_namespace_dispersion() -> None:
    pytest.importorskip("pyscf")
    pytest.importorskip("pyscf.dispersion")
    pytest.importorskip("geometric")
    try:
        expected_version = importlib.metadata.version("pyscf-dispersion")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("pyscf-dispersion distribution is not installed")

    _runtime, _pyscf_version, _geometric_version, dispersion_version = pyscf_runner._load_runtime()

    assert dispersion_version == expected_version


def test_geometric_convergence_evidence_is_explicit() -> None:
    assert pyscf_runner._parse_optimization_evidence("Converged! = YES") == {
        "optimization_convergence_evidence_present": True,
        "optimization_convergence_satisfied": True,
    }
    assert pyscf_runner._parse_optimization_evidence("Converged! = NO") == {
        "optimization_convergence_evidence_present": True,
        "optimization_convergence_satisfied": False,
    }
    assert pyscf_runner._parse_optimization_evidence("optimizer returned a geometry") == {
        "optimization_convergence_evidence_present": False,
        "optimization_convergence_satisfied": None,
    }
    molecule = object()
    assert pyscf_runner._unwrap_optimization_result((molecule, True))[1] == {
        "optimization_convergence_evidence_present": True,
        "optimization_convergence_satisfied": True,
    }


def test_pyscf_parser_does_not_trust_optimization_success_without_evidence(tmp_path: Path) -> None:
    result_path = tmp_path / "pyscf_result.json"
    result_path.write_text(
        json.dumps(
            {
                "schema_version": "pyscf-run/1",
                "backend": "pyscf",
                "task_type": "opt",
                "execution_completed": True,
                "settings": normalize_pyscf_settings({}, "opt"),
                "summary": {
                    "electronic_energy_hartree": -1.1,
                    "scf_converged": True,
                    "optimization_converged": True,
                    "stationary_point_found": True,
                    "optimized_geometry_atom_count": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    parsed = parse_pyscf_artifacts(
        "opt",
        {"pyscf_result.json": result_path},
        expected_settings={},
    )
    assert parsed["summary"]["optimization_converged"] is None
