"""NEB driver primitives: build the NEB object and score candidates.

These functions only need ASE images and a candidate-selection cfg. Result
artifact writing is provided by ``tools.ase_neb.results`` and workspace state
mutation remains with the orchestrating CLI/core boundary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.backends.ase import import_ase_bits
from transition_state_workflow.tools.ase_neb.errors import ConfigError
from transition_state_workflow.tools.ase_neb.results import (
    collect_path_data,
    force_max,
    write_forces_table,
    write_path_summary,
)
from transition_state_workflow.tool.ase_neb.gaussian_calc import create_calculator
from transition_state_workflow.tools.ase_neb.mechanism import endpoint_validation_summary


def make_neb_object(cfg: dict[str, Any], images: list[Any]) -> Any:
    bits = import_ase_bits()
    neb_cfg = cfg["neb"]
    kwargs = {
        "climb": bool(neb_cfg.get("climb", False)),
        "k": neb_cfg.get("k", 0.1),
        "method": neb_cfg.get("method", "improvedtangent"),
        "remove_rotation_and_translation": bool(
            neb_cfg.get("remove_rotation_and_translation", False)
        ),
    }
    if neb_cfg.get("dynamic", False):
        dyneb = bits["DyNEB"]
        if dyneb is None:
            raise ConfigError("DyNEB requested but this ASE version does not provide it")
        return dyneb(images, **kwargs)
    return bits["NEB"](images, **kwargs)


def attach_calculators(cfg: dict[str, Any], images: list[Any], output: Path) -> None:
    calc_cfg = cfg["calculator"]
    calc_root = output / "calculators"
    for index, image in enumerate(images):
        image.calc = create_calculator(calc_cfg, index, calc_root)


def evaluate_neb_candidate_quality(
    summary: dict[str, Any],
    cfg: dict[str, Any],
    *,
    optimizer_converged: bool,
) -> dict[str, Any]:
    candidate_selection = cfg.get("candidate_selection", {})
    min_barrier = float(candidate_selection.get("min_barrier_ev", 0.03))
    allow_endpoint = bool(candidate_selection.get("allow_endpoint_candidate", False))
    image_count = int(summary["images"])
    ts_index = int(summary["ts_candidate_index"])
    barrier = float(summary["barrier_ev_relative_to_reactant"])
    reasons: list[str] = []
    # Collected in priority order: a prerequisite or numerical failure invalidates
    # the path before any chemical interpretation of its barrier/endpoint geometry,
    # so the primary outcome_code is the highest-priority code present rather than
    # whichever check happened to run last.
    failure_codes: list[str] = []
    endpoint_validation = endpoint_validation_summary(cfg)
    if not endpoint_validation["endpoint_minima_ready"]:
        reasons.append(
            "reactant/product endpoints are not declared as validated_minimum, lower_level_minimum, or constrained_reference"
        )
        failure_codes.append("endpoint_minima_missing")
    if not optimizer_converged:
        reasons.append("NEB optimizer did not report convergence within the configured step limit")
        failure_codes.append("neb_not_converged")
    if ts_index in {0, image_count - 1} and not allow_endpoint:
        reasons.append("maximum-energy image is an endpoint")
        failure_codes.append("neb_endpoint_candidate")
    if barrier < min_barrier:
        reasons.append(f"barrier {barrier:.6f} eV is below min_barrier_ev {min_barrier:.6f}")
        failure_codes.append("neb_no_barrier")
    accepted = not reasons
    failure_type = failure_codes[0] if failure_codes else None
    return {
        "accepted_for_promotion": accepted,
        "outcome_code": failure_type,
        "failure_codes": failure_codes,
        "reasons": reasons or ["internal non-endpoint maximum passed candidate gates"],
        "gates": {
            "optimizer_converged": optimizer_converged,
            "ts_candidate_not_endpoint": ts_index not in {0, image_count - 1} or allow_endpoint,
            "barrier_at_least_minimum": barrier >= min_barrier,
            "min_barrier_ev": min_barrier,
            "allow_endpoint_candidate": allow_endpoint,
            "endpoint_minima_ready": endpoint_validation["endpoint_minima_ready"],
            "endpoint_states": {
                "reactant": endpoint_validation["reactant_state"],
                "product": endpoint_validation["product_state"],
            },
        },
    }


__all__ = [
    "make_neb_object",
    "attach_calculators",
    "force_max",
    "collect_path_data",
    "write_forces_table",
    "write_path_summary",
    "evaluate_neb_candidate_quality",
]
