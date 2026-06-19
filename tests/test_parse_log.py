"""End-to-end tests for ``parse_log`` over minimal synthetic Gaussian logs.

``parse_log`` is the core TS/Freq validation judge. It used to have zero direct
tests; this module locks the behavior of the full pipeline (section splitting,
convergence quirks, hpmodes safety) against small in-memory log fixtures.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "src"))

from transition_state_workflow.chem.gaussian_log import (  # noqa: E402
    final_job_lines,
    split_job_sections,
    terminated_normally,
)
from transition_state_workflow.backends.gaussian import (  # noqa: E402
    GaussianBackendAdapter,
    GaussianInputRequest,
    gaussian_refinement_defaults,
    render_gaussian_input,
    write_gaussian_refinement_input,
    parse_charge_table,
    parse_gaussian_energy_hartree,
    parse_gaussian_forces_hartree_per_bohr,
    parse_gaussian_opt_cycle_diagnostics,
    parse_gaussian_tsfreq_log,
    parse_last_scf_energy,
)
from transition_state_workflow.cli.parse_gaussian_ts_result import main as parse_cli_main  # noqa: E402
from transition_state_workflow.cli.parse_gaussian_ts_result import parse_log  # noqa: E402


# --- multi-job termination semantics ---------------------------------------

def test_terminated_normally_scopes_to_final_job_on_concatenated_log() -> None:
    # opt succeeds, then a Link1 freq job fails: the log must NOT be judged as
    # normally terminated just because an earlier job printed it.
    lines = [
        "opt step",
        "Normal termination of Gaussian 16",
        " --Link1--",
        "freq step",
        "Error termination via Lnk1e",
    ]
    assert terminated_normally(lines) is False


def test_terminated_normally_true_when_all_jobs_succeed() -> None:
    lines = [
        "opt",
        "Normal termination of Gaussian 16",
        " --Link1--",
        "freq",
        "Normal termination of Gaussian 16",
    ]
    assert terminated_normally(lines) is True


def test_terminated_normally_true_for_single_job() -> None:
    assert terminated_normally(["x", "Normal termination of Gaussian 16"]) is True


def test_split_job_sections_single_job_returns_one_block() -> None:
    lines = ["a", "Normal termination of Gaussian 16"]
    assert split_job_sections(lines) == [lines]
    assert final_job_lines(lines) == lines


# --- Minimal log fragments --------------------------------------------------

_GEOMETRY_BLOCK = """\
 Standard orientation:
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates (Angstroms)
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
      1          1           0        0.000000    0.000000    0.000000
      2          1           0        0.000000    0.000000    0.740000
 ---------------------------------------------------------------------
"""

_CONVERGENCE_OK = """\
         Item               Value     Threshold  Converged?
 Maximum Force            0.000123     0.000450     YES
 RMS     Force            0.000034     0.000300     YES
 Maximum Displacement     0.000567     0.001800     YES
 RMS     Displacement     0.000211     0.001200     YES
 Stationary point found.
"""

_STD_FREQ_ONE_IMAG = """\
 Frequencies --   -1969.51     45.12     90.57
 Red. masses --     1.0890      5.1234      6.7890
 Frc consts  --     2.4567      0.0123      0.0456
 IR Inten    --   123.4567     0.1234     0.5678
"""

_HPMODES_FREQ_ONE_IMAG = """\
 Frequencies ---  -1969.5123    45.1234    90.5678
 Reduced masses ---     1.0890      5.1234      6.7890
 Frequencies --   -1969.51     45.12     90.57
 Red. masses --     1.0890      5.1234      6.7890
 Frc consts  --     2.4567      0.0123      0.0456
 IR Inten    --   123.4567     0.1234     0.5678
"""


def _build_log(*, frequencies: str, convergence: str = _CONVERGENCE_OK, terminated: bool = True) -> str:
    parts = [
        " Charge = 0 Multiplicity = 1\n",
        _GEOMETRY_BLOCK,
        convergence,
        frequencies,
    ]
    if terminated:
        parts.append(" Normal termination of Gaussian 16\n")
    return "".join(parts)


def _write_log(tmp_path: Path, text: str, name: str = "freq.out") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# --- Happy path -------------------------------------------------------------

def test_parse_log_validates_ts_with_one_imaginary_frequency(tmp_path: Path) -> None:
    log = _write_log(tmp_path, _build_log(frequencies=_STD_FREQ_ONE_IMAG))
    out = parse_log(log)
    summary = out["summary"]
    assert summary["status"] == "validated_ts"
    assert summary["imaginary_frequency_count"] == 1
    assert summary["frequency_count"] == 3
    assert summary["normal_termination"] is True
    assert summary["stationary_point_found"] is True
    assert summary["final_convergence_satisfied"] is True
    assert summary["validation_failures"] == []


def test_backend_gaussian_parser_matches_legacy_parse_log(tmp_path: Path) -> None:
    log = _write_log(tmp_path, _build_log(frequencies=_STD_FREQ_ONE_IMAG))

    legacy = parse_log(log)
    backend = parse_gaussian_tsfreq_log(log)

    assert backend["summary"] == legacy["summary"]
    assert backend["frequencies"] == legacy["frequencies"]
    assert backend["atoms"] == legacy["atoms"]


def test_parse_log_warns_when_opt_maxcycle_request_does_not_change_printed_limit(tmp_path: Path) -> None:
    text = """\
 #P M062X/def2SVP SCF=XQC Opt=(Cartesian,MaxCycles=300) NoSymm

 Step number   1 out of a maximum of 100
 Step number 100 out of a maximum of 100
 Number of steps exceeded,  NStep=100
 Error termination request processed by link 9999.
"""
    log = _write_log(tmp_path, text, name="endpoint_continuation.out")

    summary = parse_log(log)["summary"]
    diagnostics = summary["opt_cycle_diagnostics"]

    assert diagnostics["requested_opt_max_cycles"] == 300
    assert diagnostics["printed_opt_maximum_steps"] == 100
    assert diagnostics["nstep_termination"] == 100
    assert diagnostics["max_cycle_request_mismatch"] is True
    assert diagnostics["step_limit_reached"] is True
    assert diagnostics["warnings"] == ["opt_maxcycle_request_mismatch", "opt_step_limit_reached"]


def test_opt_cycle_diagnostics_use_printed_step_limit_not_nstep_proxy() -> None:
    diagnostics = parse_gaussian_opt_cycle_diagnostics(
        [
            " #P Opt=(MaxCycle=300)",
            " Step number  80 out of a maximum of 100",
            " Number of steps exceeded,  NStep=120",
        ]
    )

    assert diagnostics["printed_opt_step"] == 80
    assert diagnostics["printed_opt_maximum_steps"] == 100
    assert diagnostics["nstep_termination"] == 120
    assert diagnostics["step_limit_reached"] is False
    assert diagnostics["warnings"] == ["opt_maxcycle_request_mismatch"]


def test_opt_cycle_diagnostics_ignore_scf_maxcycle_request() -> None:
    diagnostics = parse_gaussian_opt_cycle_diagnostics(
        [
            " #P M062X/def2SVP Opt=(MaxCycle=100) SCF=(XQC,Tight,MaxCycle=512)",
            "",
            " Step number   1 out of a maximum of 100",
            " Normal termination of Gaussian 16",
        ]
    )

    assert diagnostics["requested_opt_max_cycles"] == 100
    assert diagnostics["printed_opt_maximum_steps"] == 100
    assert diagnostics["max_cycle_request_mismatch"] is False
    assert diagnostics["warnings"] == []


def test_gaussian_scf_energy_parsers_accept_fortran_d_exponents(tmp_path: Path) -> None:
    lines = [
        " SCF Done:  E(RB3LYP) =  -1.234567890123D+02     A.U. after 10 cycles",
        " SCF Done:  E(UB3LYP) =  -1.234567890124d+02     A.U. after 11 cycles",
    ]
    log = tmp_path / "energy.out"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert parse_last_scf_energy(lines) == pytest.approx(-123.4567890124)
    assert parse_gaussian_energy_hartree(log) == pytest.approx(-123.4567890124)


def test_parse_tsfreq_summary_accepts_exponent_energy_fields(tmp_path: Path) -> None:
    text = _build_log(
        frequencies=_STD_FREQ_ONE_IMAG,
        convergence=(
            " SCF Done:  E(RB3LYP) =  -1.234567890123D+02     A.U. after 10 cycles\n"
            " Zero-point correction=                           1.234567D-02 (Hartree/Particle)\n"
            " Thermal correction to Gibbs Free Energy=         2.345678d-02\n"
            " Sum of electronic and zero-point Energies=      -1.234444433423D+02\n"
            " Sum of electronic and thermal Free Energies=    -1.234333322323d+02\n"
            + _CONVERGENCE_OK
        ),
    )
    log = _write_log(tmp_path, text)

    summary = parse_gaussian_tsfreq_log(log)["summary"]

    assert summary["electronic_energy_hartree"] == pytest.approx(-123.4567890123)
    assert summary["zero_point_correction_hartree"] == pytest.approx(0.01234567)
    assert summary["thermal_gibbs_correction_hartree"] == pytest.approx(0.02345678)
    assert summary["electronic_plus_zpe_hartree"] == pytest.approx(-123.4444433423)
    assert summary["electronic_plus_thermal_free_energy_hartree"] == pytest.approx(-123.4333322323)


def test_parse_charge_table_keeps_charge_column_when_spin_density_is_present() -> None:
    lines = [
        " Mulliken charges:",
        "              1",
        "     1  C   -0.123456    0.777777",
        "     2  H    0.123456   -0.777777",
        " Sum of Mulliken charges = 0.00000",
    ]

    assert parse_charge_table(lines, "Mulliken charges:", "Sum of Mulliken charges") == {
        1: pytest.approx(-0.123456),
        2: pytest.approx(0.123456),
    }


def test_gaussian_backend_adapter_extracts_tsfreq_summary(tmp_path: Path) -> None:
    log = _write_log(tmp_path, _build_log(frequencies=_STD_FREQ_ONE_IMAG))

    output = GaussianBackendAdapter().parse((log,))

    assert output.properties["artifact_count"] == 1
    assert output.properties["existing_artifacts"] == 1
    assert output.properties["parser"] == "gaussian_tsfreq"
    assert output.properties["status"] == "validated_ts"
    assert output.properties["imaginary_frequency_count"] == 1
    assert output.properties["summary"]["frequency_count"] == 3


def test_gaussian_backend_renders_tsfreq_input() -> None:
    text = render_gaussian_input(
        GaussianInputRequest(
            title="candidate",
            coords=[("H", 0.0, 0.0, 0.0), ("H", 0.0, 0.0, 0.74)],
            route="M062X/6-31G(d) opt=(ts,calcfc) freq",
            charge=0,
            multiplicity=1,
            nproc=8,
            mem="16GB",
            chk="candidate.chk",
            extra_sections=("H 0\n6-31G(d)\n****",),
        )
    )

    assert text.startswith("%chk=candidate.chk\n%nprocshared=8\n%mem=16GB\n#P M062X/6-31G(d)")
    assert "candidate\n\n0 1\n" in text
    assert "H         0.00000000       0.00000000       0.74000000" in text
    assert "H 0\n6-31G(d)\n****\n\n" in text


def test_gaussian_backend_prepare_writes_input_from_xyz(tmp_path: Path) -> None:
    xyz = tmp_path / "candidate.xyz"
    output = tmp_path / "candidate.gjf"
    xyz.write_text(
        "2\n"
        "from xyz\n"
        "H 0 0 0\n"
        "H 0 0 0.74\n",
        encoding="utf-8",
    )

    prepared = GaussianBackendAdapter().prepare(
        {
            "xyz": xyz,
            "output": output,
            "route": "M062X/6-31G(d) opt=(ts,calcfc) freq",
            "charge": 0,
            "multiplicity": 1,
            "nproc": 4,
            "mem": "8GB",
            "chk": "candidate.chk",
            "command_argv": ["g16", str(output)],
        }
    )

    text = output.read_text(encoding="utf-8")
    assert prepared.backend == "gaussian"
    assert prepared.files == (output,)
    assert prepared.command_argv == ("g16", str(output))
    assert prepared.metadata["frame"] == 0
    assert prepared.metadata["atoms"] == 2
    assert prepared.metadata["chk"] == "candidate.chk"
    assert text.startswith("%chk=candidate.chk\n%nprocshared=4\n%mem=8GB\n#P M062X/6-31G(d)")


def test_gaussian_backend_writes_ase_neb_refinement_input(tmp_path: Path) -> None:
    xyz = tmp_path / "candidate.xyz"
    output = tmp_path / "candidate.gjf"
    xyz.write_text(
        "2\n"
        "neb candidate\n"
        "H 0 0 0\n"
        "H 0 0 0.74\n",
        encoding="utf-8",
    )
    cfg = gaussian_refinement_defaults()
    cfg.update(
        {
            "route": "M062X/6-31G(d) opt=(ts,calcfc) freq",
            "nprocshared": 8,
            "mem": "16GB",
            "extra_sections": ["H 0\n6-31G(d)\n****"],
        }
    )

    written = write_gaussian_refinement_input(xyz, output, cfg)
    text = output.read_text(encoding="utf-8")

    assert written == output
    assert text.startswith("%chk=ts_candidate.chk\n%nprocshared=8\n%mem=16GB\nM062X/6-31G(d)")
    assert "TS candidate from ASE NEB\n\n0 1\n" in text
    assert "H         0.00000000       0.00000000       0.74000000" in text
    assert "H 0\n6-31G(d)\n****\n\n\n" in text


def test_parse_gaussian_ts_result_cli_writes_artifacts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    log = _write_log(tmp_path, _build_log(frequencies=_STD_FREQ_ONE_IMAG))
    output_dir = tmp_path / "parsed"

    rc = parse_cli_main([str(log), "-o", str(output_dir), "--strict"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert rc == 0
    assert payload["output_dir"] == str(output_dir)
    assert payload["summary"]["status"] == "validated_ts"
    assert (output_dir / "validation_summary.json").exists()
    assert (output_dir / "frequencies_cm-1.txt").exists()
    assert (output_dir / "freq_final.xyz").exists()


def test_gaussian_backend_parses_external_force_energy_output(tmp_path: Path) -> None:
    output = _write_log(
        tmp_path,
        "\n".join(
            [
                " SCF Done:  E(RB3LYP) =  -7.612300D+01 A.U. after 1 cycles",
                " Center     Atomic                   Forces (Hartrees/Bohr)",
                " Number     Number              X              Y              Z",
                " -------------------------------------------------------------------",
                "      1        6       1.000000D-03  -2.000000D-03   3.000000D-03",
                "      2        1      -4.000000D-03   5.000000D-03  -6.000000D-03",
                "",
            ]
        ),
    )

    forces = parse_gaussian_forces_hartree_per_bohr(output, natoms=2)

    assert parse_gaussian_energy_hartree(output) == pytest.approx(-76.123)
    assert forces.shape == (2, 3)
    assert forces[0, 0] == pytest.approx(0.001)
    assert forces[1, 2] == pytest.approx(-0.006)


def test_parse_log_handles_hpmodes_block_without_double_counting(tmp_path: Path) -> None:
    log = _write_log(tmp_path, _build_log(frequencies=_HPMODES_FREQ_ONE_IMAG))
    out = parse_log(log)
    summary = out["summary"]
    # The high-precision ``Frequencies ---`` lines must not be parsed again.
    assert summary["frequency_count"] == 3
    assert summary["imaginary_frequency_count"] == 1
    assert summary["status"] == "validated_ts"


# --- Rejection cases --------------------------------------------------------

def test_parse_log_rejects_log_without_normal_termination(tmp_path: Path) -> None:
    log = _write_log(tmp_path, _build_log(frequencies=_STD_FREQ_ONE_IMAG, terminated=False))
    summary = parse_log(log)["summary"]
    assert summary["status"] == "not_validated_ts"
    assert "missing_normal_termination" in summary["validation_failures"]


def test_parse_log_rejects_when_imaginary_count_is_zero(tmp_path: Path) -> None:
    freqs = _STD_FREQ_ONE_IMAG.replace("-1969.51", "1969.51")  # flip the sign
    log = _write_log(tmp_path, _build_log(frequencies=freqs))
    summary = parse_log(log)["summary"]
    assert summary["status"] == "not_validated_ts"
    assert "imaginary_frequency_count_not_one" in summary["validation_failures"]


def test_parse_log_rejects_when_imaginary_count_is_two(tmp_path: Path) -> None:
    freqs = _STD_FREQ_ONE_IMAG.replace("45.12", "-45.12")
    log = _write_log(tmp_path, _build_log(frequencies=freqs))
    summary = parse_log(log)["summary"]
    assert summary["imaginary_frequency_count"] == 2
    assert "imaginary_frequency_count_not_one" in summary["validation_failures"]


def test_parse_log_marks_overflow_convergence_as_not_satisfied(tmp_path: Path) -> None:
    # Replace one converged value with the Gaussian overflow token.
    bad_conv = _CONVERGENCE_OK.replace(
        " Maximum Force            0.000123     0.000450     YES",
        " Maximum Force            ********     0.000450     NO ",
    )
    log = _write_log(
        tmp_path,
        _build_log(frequencies=_STD_FREQ_ONE_IMAG, convergence=bad_conv),
    )
    summary = parse_log(log)["summary"]
    assert summary["final_convergence_satisfied"] is False
    assert "final_convergence_not_satisfied" in summary["validation_failures"]
    assert summary["status"] == "not_validated_ts"


def test_parse_log_extracts_final_geometry_atoms(tmp_path: Path) -> None:
    log = _write_log(tmp_path, _build_log(frequencies=_STD_FREQ_ONE_IMAG))
    out = parse_log(log)
    assert out["summary"]["final_geometry_atoms"] == 2
    assert out["atoms"][0][0] == "H"
    assert out["atoms"][1][3] == pytest.approx(0.74)
