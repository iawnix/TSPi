"""Deterministic typed-backend capability catalog.

The catalog states what this package can express. It does not choose a
chemistry strategy and does not claim that a local or remote executable is
currently ready.
"""

from __future__ import annotations

from typing import Final


BACKEND_TASK_INPUT_ROLES: Final[dict[str, dict[str, frozenset[str]]]] = {
    "gaussian": {
        "sp": frozenset({"gjf"}),
        "opt": frozenset({"gjf"}),
        "freq": frozenset({"gjf"}),
        "opt_freq": frozenset({"gjf"}),
        "irc": frozenset({"gjf"}),
    },
    "xtb": {
        "sp": frozenset({"xyz"}),
        "opt": frozenset({"xyz"}),
        "freq": frozenset({"xyz"}),
        "opt_freq": frozenset({"xyz"}),
        "scan": frozenset({"xyz", "control"}),
        "md": frozenset({"xyz", "control"}),
    },
    "crest": {"conformer_search": frozenset({"xyz"})},
    "ase_neb": {"neb": frozenset({"reactant", "product"})},
    "qbics_dmecp": {"dmecp": frozenset({"config"})},
}


CANDIDATE_STRATEGIES_BY_TASK: Final[dict[tuple[str, str], tuple[str, ...]]] = {
    ("gaussian", "sp"): ("candidate_ranking",),
    ("gaussian", "opt"): (
        "intermediate_optimization",
        "manual_seed_optimization",
        "qst",
        "relaxed_scan",
        "transition_state_optimization",
    ),
    ("gaussian", "opt_freq"): (
        "manual_seed_optimization",
        "qst",
        "transition_state_optimization",
    ),
    ("xtb", "sp"): ("candidate_ranking",),
    ("xtb", "opt"): (
        "intermediate_optimization",
        "manual_seed_optimization",
    ),
    ("xtb", "opt_freq"): ("manual_seed_optimization",),
    ("xtb", "scan"): ("relaxed_scan",),
    ("xtb", "md"): ("molecular_dynamics_sampling",),
    ("crest", "conformer_search"): ("conformer_search",),
    ("ase_neb", "neb"): ("path_search",),
    ("qbics_dmecp", "dmecp"): ("crossing_point_search",),
}


def calculation_capabilities() -> dict[str, object]:
    """Return stable adapter support separately from environment readiness."""

    backends = []
    for backend, tasks in sorted(BACKEND_TASK_INPUT_ROLES.items()):
        backends.append(
            {
                "backend": backend,
                "tasks": [
                    {
                        "task_type": task_type,
                        "input_roles": sorted(input_roles),
                        "candidate_strategies": list(
                            CANDIDATE_STRATEGIES_BY_TASK.get((backend, task_type), ())
                        ),
                    }
                    for task_type, input_roles in sorted(tasks.items())
                ],
            }
        )
    return {
        "schema_version": "ts-compute-capabilities/1",
        "backends": backends,
        "readiness": {
            "state": "not_probed",
            "meaning": (
                "Adapter support does not prove executable, profile, scheduler, "
                "or transport readiness; establish readiness separately with "
                "local runtime checks or ts_remote diagnostics."
            ),
        },
    }
