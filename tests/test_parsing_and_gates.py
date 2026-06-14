"""Regression tests for Gaussian frequency parsing and NEB candidate gating.

These lock in three fixes:
  * ``freq=hpmodes`` logs (three-dash ``Frequencies ---`` lines) must not crash
    the parsers or double-count modes.
  * ``****`` convergence overflow tokens must be tolerated, not raise.
  * ``continue-gaussian-neb-from-images`` must honor declared endpoint readiness,
    and the candidate gate must report the highest-priority failure, not the last.
"""

from __future__ import annotations

import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "src"))

from transition_state_workflow.chem.gaussian_log import (  # noqa: E402
    frequency_summary,
    standard_frequency_values,
)
from transition_state_workflow.backends.ase_neb import (  # noqa: E402
    evaluate_neb_candidate_quality,
)
from transition_state_workflow.cli.parse_gaussian_ts_result import (  # noqa: E402
    parse_convergence,
    parse_frequencies,
)
from transition_state_workflow.tools.descriptors import (  # noqa: E402
    parse_freq_metadata,
    parse_imaginary_vectors,
)


# A hpmodes frequency block: a high-precision ``---`` triple followed by the
# standard ``--`` block for the same three modes (one imaginary).
HPMODES_BLOCK = [
    " Frequencies ---  -1969.5123    45.1234    90.5678",
    " Reduced masses ---     1.0890      5.1234      6.7890",
    " Frequencies --   -1969.51     45.12     90.57",
    " Red. masses --     1.0890      5.1234      6.7890",
    " Frc consts  --     2.4567      0.0123      0.0456",
    " IR Inten    --   123.4567     0.1234     0.5678",
]


def test_standard_frequency_values_skips_hpmodes_line() -> None:
    assert standard_frequency_values(" Frequencies ---  -1969.5  45.1") is None
    assert standard_frequency_values(" Frequencies --   -1969.5  45.1") == [-1969.5, 45.1]


def test_parse_frequencies_does_not_double_count_hpmodes() -> None:
    freqs = parse_frequencies(HPMODES_BLOCK)
    assert freqs == [-1969.51, 45.12, 90.57]
    assert len([f for f in freqs if f < 0.0]) == 1


def test_frequency_summary_counts_hpmodes_once() -> None:
    summary = frequency_summary(HPMODES_BLOCK)
    assert summary["frequency_count"] == 3
    assert summary["imaginary_frequency_count"] == 1


def test_descriptor_metadata_counts_hpmodes_once() -> None:
    meta = parse_freq_metadata(HPMODES_BLOCK)
    assert meta["frequency_count"] == 3
    assert meta["imaginary_frequency_count"] == 1


def test_descriptor_imaginary_vectors_skip_hpmodes_frequency_line() -> None:
    vectors = parse_imaginary_vectors(
        [
            " Frequencies ---  -1969.5123    45.1234    90.5678",
            " Frequencies --   -1969.51     45.12     90.57",
            " Atom  AN      X      Y      Z        X      Y      Z        X      Y      Z",
            "    1   6   0.100  0.200  0.300   0.0  0.0  0.0   0.0  0.0  0.0",
            "    2   1  -0.100 -0.200 -0.300   0.0  0.0  0.0   0.0  0.0  0.0",
        ],
        natoms=2,
    )

    assert vectors == [(0.1, 0.2, 0.3), (-0.1, -0.2, -0.3)]


def test_parse_convergence_tolerates_overflow() -> None:
    rows, source = parse_convergence(
        [
            " Maximum Force            ********     0.000450     NO",
            " RMS     Force            0.000123     0.000300     YES",
        ]
    )
    assert source == "last_section_rows"
    overflow = rows["Maximum Force"]
    assert overflow["value"] == "********"
    assert overflow["converged"] == "NO"


def _summary(*, images: int = 7, ts_index: int = 3, barrier: float = 0.5) -> dict[str, object]:
    return {
        "images": images,
        "ts_candidate_index": ts_index,
        "barrier_ev_relative_to_reactant": barrier,
    }


def test_candidate_gate_rejects_undeclared_endpoints() -> None:
    result = evaluate_neb_candidate_quality(
        _summary(), {"candidate_selection": {}}, optimizer_converged=True
    )
    assert result["accepted_for_promotion"] is False
    assert result["outcome_code"] == "endpoint_minima_missing"
    assert result["gates"]["endpoint_minima_ready"] is False


def test_candidate_gate_accepts_declared_ready_endpoints() -> None:
    cfg = {
        "candidate_selection": {},
        "endpoint_validation": {
            "reactant_state": "validated_minimum",
            "product_state": "validated_minimum",
        },
    }
    result = evaluate_neb_candidate_quality(_summary(), cfg, optimizer_converged=True)
    assert result["accepted_for_promotion"] is True
    assert result["outcome_code"] is None


def test_candidate_gate_failure_priority_prefers_convergence_over_barrier() -> None:
    # A non-converged path with a near-flat barrier: the numerical failure must win
    # over the chemical "no barrier" verdict so the path is not rejected on chemistry.
    cfg = {
        "candidate_selection": {},
        "endpoint_validation": {
            "reactant_state": "validated_minimum",
            "product_state": "validated_minimum",
        },
    }
    result = evaluate_neb_candidate_quality(
        _summary(barrier=0.0), cfg, optimizer_converged=False
    )
    assert result["outcome_code"] == "neb_not_converged"
    assert result["failure_codes"] == ["neb_not_converged", "neb_no_barrier"]
