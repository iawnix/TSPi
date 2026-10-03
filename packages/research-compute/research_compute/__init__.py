"""Typed operational control plane for transition-state calculations.

The package intentionally keeps its public convenience imports lazy. Runtime
status needs the lightweight contract validator, but should not
import optional scientific stacks (NumPy/RDKit) merely to inspect an Attempt.
Keeping the heavy artifact/control modules behind ``__getattr__`` avoids coupling
the runtime state reader to backend dependencies.
"""

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "ComputeContractError": (".errors", "ComputeContractError"),
    "cancel_calculation": (".control", "cancel_calculation"),
    "calculation_status": (".control", "calculation_status"),
    "calculation_tail": (".control", "calculation_tail"),
    "collect_calculation": (".control", "collect_calculation"),
    "create_calculation_intent": (".control", "create_calculation_intent"),
    "discard_calculation_intent": (".control", "discard_calculation_intent"),
    "parse_calculation": (".control", "parse_calculation"),
    "preflight_calculation": (".control", "preflight_calculation"),
    "prepare_calculation": (".control", "prepare_calculation"),
    "submit_calculation": (".control", "submit_calculation"),
    "calculation_capabilities": (".capabilities", "calculation_capabilities"),
    "resolve_capability_result": (".capabilities", "resolve_capability_result"),
    "resolve_capability_registration": (".capabilities", "resolve_capability_registration"),
    "register_capability": (".capabilities", "register_capability"),
    "register_capability_provider": (".capabilities", "register_capability_provider"),
    "CapabilityRegistry": (".registry", "CapabilityRegistry"),
    "CapabilityRegistration": (".registry", "CapabilityRegistration"),
    "CapabilityProvider": (".registry", "CapabilityProvider"),
    "ExecutionCapabilityProvider": (".registry", "ExecutionCapabilityProvider"),
    "BackendTask": (".provider", "BackendTask"),
    "PreparedTask": (".provider", "PreparedTask"),
    "ProviderUnavailable": (".provider", "ProviderUnavailable"),
    "register_compute_provider": (".provider", "register_compute_provider"),
    "resolve_compute_provider": (".provider", "resolve_compute_provider"),
    "compute_provider_catalog": (".provider", "compute_provider_catalog"),
    "ArtifactOperationDescriptor": (".artifact_registry", "ArtifactOperationDescriptor"),
    "ArtifactProvider": (".artifact_registry", "ArtifactProvider"),
    "artifact_operation_catalog": (".artifact_registry", "artifact_operation_catalog"),
    "artifact_operation_digest": (".artifact_registry", "artifact_operation_digest"),
    "register_artifact_operation": (".artifact_registry", "register_artifact_operation"),
    "register_artifact_provider": (".artifact_registry", "register_artifact_provider"),
    "resolve_artifact_operation": (".artifact_registry", "resolve_artifact_operation"),
    "validate_artifact_request": (".artifact_registry", "validate_artifact_request"),
    "validate_artifact_result": (".artifact_registry", "validate_artifact_result"),
    "analysis_capabilities": (".analysis", "analysis_capabilities"),
    "resolve_analysis_capability": (".analysis", "resolve_analysis_capability"),
    "register_analysis_capability": (".analysis", "register_analysis_capability"),
    "register_analysis_provider": (".analysis", "register_analysis_provider"),
    "create_structure_comparison_artifact": (".artifacts", "create_structure_comparison_artifact"),
    "create_reaction_mapping_validation_artifact": (".artifacts", "create_reaction_mapping_validation_artifact"),
    "create_mol_structure_artifact": (".artifacts", "create_mol_structure_artifact"),
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
    "resolve_capability_registration",
    "register_capability",
    "register_capability_provider",
    "CapabilityRegistry",
    "CapabilityRegistration",
    "CapabilityProvider",
    "ExecutionCapabilityProvider",
    "BackendTask",
    "PreparedTask",
    "ProviderUnavailable",
    "register_compute_provider",
    "resolve_compute_provider",
    "compute_provider_catalog",
    "ArtifactOperationDescriptor",
    "ArtifactProvider",
    "artifact_operation_catalog",
    "artifact_operation_digest",
    "register_artifact_operation",
    "register_artifact_provider",
    "resolve_artifact_operation",
    "validate_artifact_request",
    "validate_artifact_result",
    "analysis_capabilities",
    "resolve_analysis_capability",
    "register_analysis_capability",
    "register_analysis_provider",
    "collect_calculation",
    "create_calculation_intent",
    "discard_calculation_intent",
    "create_structure_comparison_artifact",
    "create_reaction_mapping_validation_artifact",
    "create_mol_structure_artifact",
    "import_calculation_artifact",
    "list_calculation_artifacts",
    "resolve_artifact_ref",
    "parse_calculation",
    "preflight_calculation",
    "prepare_calculation",
    "submit_calculation",
]
