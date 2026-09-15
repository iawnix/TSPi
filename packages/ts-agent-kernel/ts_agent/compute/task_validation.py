"""Task completion checks over backend-owned parser facts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


TaskValidator = Callable[[dict[str, Any]], list[str]]


def validate_parsed_task(
    backend: str,
    task_type: str,
    facts: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate one requested task without assigning scientific meaning to it."""

    validator = _TASK_VALIDATORS.get((backend, task_type))
    if validator is None:
        raise ValueError(f"no task validator is registered for {backend}.{task_type}")
    failures = _common_failures(backend, facts)
    failures.extend(validator(facts))
    failures = list(dict.fromkeys(failures))
    return {
        "status": "completed" if not failures else "incomplete",
        "failures": failures,
    }


def parsed_program_outcome(backend: str, facts: dict[str, Any]) -> tuple[str, str | None]:
    """Report only whether the underlying program reached its normal terminus."""

    if backend == "gaussian":
        completed = facts.get("normal_termination") is True
    elif backend in {"xtb", "crest"}:
        completed = facts.get("execution_completed") is True
    else:
        raise ValueError(f"no program outcome rule is registered for backend: {backend}")
    return ("completed", None) if completed else ("failed", f"{backend}_error_termination")


def _common_failures(backend: str, facts: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if backend == "gaussian":
        if facts.get("normal_termination") is not True:
            failures.append("program_did_not_terminate_normally")
        route = facts.get("route_expectation")
        if isinstance(route, dict) and route.get("checked") is True and route.get("matched") is not True:
            failures.append("route_does_not_match_intent")
    else:
        if facts.get("execution_completed") is not True:
            failures.append("program_did_not_complete")
        if backend == "xtb" and (
            facts.get("scc_convergence_applicable") is True
            and facts.get("scc_converged") is not True
        ):
            failures.append("electronic_structure_not_converged")
    missing = facts.get("missing_artifacts")
    if isinstance(missing, list) and missing:
        failures.append("required_artifacts_missing")
    return failures


def _require_truthy(*requirements: tuple[str, str]) -> TaskValidator:
    def validate(facts: dict[str, Any]) -> list[str]:
        return [failure for field, failure in requirements if not facts.get(field)]

    return validate


def _require_present(*requirements: tuple[str, str]) -> TaskValidator:
    def validate(facts: dict[str, Any]) -> list[str]:
        return [failure for field, failure in requirements if facts.get(field) is None]

    return validate


def _optimization_failures(facts: dict[str, Any]) -> list[str]:
    failures = _require_truthy(
        ("stationary_point_found", "stationary_point_missing"),
        ("final_geometry_atoms", "final_geometry_missing"),
    )(facts)
    if facts.get("final_convergence_evidence_present") is not True:
        failures.append("optimization_convergence_evidence_missing")
    elif facts.get("final_convergence_satisfied") is not True:
        failures.append("optimization_not_converged")
    return failures


def _combine(*validators: TaskValidator) -> TaskValidator:
    def validate(facts: dict[str, Any]) -> list[str]:
        return [failure for validator in validators for failure in validator(facts)]

    return validate


_TASK_VALIDATORS: dict[tuple[str, str], TaskValidator] = {
    ("gaussian", "sp"): _require_present(
        ("electronic_energy_hartree", "electronic_energy_missing"),
    ),
    ("gaussian", "opt"): _optimization_failures,
    ("gaussian", "freq"): _require_truthy(
        ("frequency_count", "frequencies_missing"),
    ),
    ("gaussian", "opt_freq"): _combine(
        _optimization_failures,
        _require_truthy(
            ("frequency_count", "frequencies_missing"),
        ),
    ),
    ("gaussian", "irc"): _require_truthy(
        ("path_complete_marker", "irc_path_not_complete"),
        ("point_count", "irc_points_missing"),
        ("endpoint_geometry_atoms", "irc_endpoint_geometry_missing"),
    ),
    ("xtb", "sp"): _require_present(
        ("total_energy_hartree", "total_energy_missing"),
    ),
    ("xtb", "opt"): _require_truthy(
        ("optimization_converged", "optimization_not_converged"),
        ("optimized_geometry_atom_count", "optimized_geometry_missing"),
    ),
    ("xtb", "freq"): _require_truthy(
        ("frequency_count", "frequencies_missing"),
    ),
    ("xtb", "opt_freq"): _require_truthy(
        ("optimization_converged", "optimization_not_converged"),
        ("optimized_geometry_atom_count", "optimized_geometry_missing"),
        ("frequency_count", "frequencies_missing"),
    ),
    ("xtb", "scan"): _require_truthy(
        ("scan_detected", "scan_not_detected"),
        ("scan_complete", "scan_not_complete"),
    ),
    ("xtb", "md"): _require_truthy(
        ("md_completed", "molecular_dynamics_not_complete"),
        ("trajectory_frame_count", "trajectory_missing"),
    ),
    ("crest", "conformer_search"): _require_truthy(
        ("conformer_count", "conformers_missing"),
        ("ensemble_counts_match", "ensemble_energy_counts_differ"),
    ),
}
