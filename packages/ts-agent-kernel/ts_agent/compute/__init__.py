"""Typed operational control plane for transition-state calculations.

The package intentionally keeps its public convenience imports lazy.  Read-only
workspace projections need the lightweight contract validator, but should not
import optional scientific stacks (NumPy/RDKit) merely to inspect an Attempt.
Keeping the heavy artifact/control modules behind ``__getattr__`` preserves the
historic ``from ts_agent.compute import ...`` API without coupling the kernel's
state reader to backend dependencies.
"""

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "ComputeContractError": (".contracts", "ComputeContractError"),
    "cancel_calculation": (".control", "cancel_calculation"),
    "calculation_status": (".control", "calculation_status"),
    "calculation_tail": (".control", "calculation_tail"),
    "collect_calculation": (".control", "collect_calculation"),
    "create_calculation_intent": (".control", "create_calculation_intent"),
    "parse_calculation": (".control", "parse_calculation"),
    "preflight_calculation": (".control", "preflight_calculation"),
    "prepare_calculation": (".control", "prepare_calculation"),
    "submit_calculation": (".control", "submit_calculation"),
    "calculation_capabilities": (".capabilities", "calculation_capabilities"),
    "resolve_capability_result": (".capabilities", "resolve_capability_result"),
    "analysis_capabilities": (".analysis", "analysis_capabilities"),
    "resolve_analysis_capability": (".analysis", "resolve_analysis_capability"),
    "create_structure_comparison_artifact": (".artifacts", "create_structure_comparison_artifact"),
    "create_reaction_mapping_validation_artifact": (".artifacts", "create_reaction_mapping_validation_artifact"),
    "create_structure_seed_artifact": (".artifacts", "create_structure_seed_artifact"),
    "import_calculation_artifact": (".artifacts", "import_calculation_artifact"),
    "list_calculation_artifacts": (".artifacts", "list_calculation_artifacts"),
    "resolve_artifact_ref": (".artifacts", "resolve_artifact_ref"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value

__all__ = [
    "ComputeContractError",
    "cancel_calculation",
    "calculation_status",
    "calculation_tail",
    "calculation_capabilities",
    "resolve_capability_result",
    "analysis_capabilities",
    "resolve_analysis_capability",
    "collect_calculation",
    "create_calculation_intent",
    "create_structure_comparison_artifact",
    "create_reaction_mapping_validation_artifact",
    "create_structure_seed_artifact",
    "import_calculation_artifact",
    "list_calculation_artifacts",
    "resolve_artifact_ref",
    "parse_calculation",
    "preflight_calculation",
    "prepare_calculation",
    "submit_calculation",
]
