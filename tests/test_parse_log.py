"""End-to-end tests for ``parse_log`` over minimal synthetic Gaussian logs.

``parse_log`` is the core TS/Freq validation judge. It used to have zero direct
tests; this module locks the behavior of the full pipeline (section splitting,
convergence quirks, hpmodes safety) against small in-memory log fixtures.
"""

from __future__ import annotations

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
    parse_gaussian_tsfreq_log,
)
from transition_state_workflow.tool.parse_gaussian_ts_result import parse_log  # noqa: E402


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


def test_gaussian_backend_adapter_extracts_tsfreq_summary(tmp_path: Path) -> None:
    log = _write_log(tmp_path, _build_log(frequencies=_STD_FREQ_ONE_IMAG))

    output = GaussianBackendAdapter().parse((log,))

    assert output.properties["artifact_count"] == 1
    assert output.properties["existing_artifacts"] == 1
    assert output.properties["parser"] == "gaussian_tsfreq"
    assert output.properties["status"] == "validated_ts"
    assert output.properties["imaginary_frequency_count"] == 1
    assert output.properties["summary"]["frequency_count"] == 3


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
