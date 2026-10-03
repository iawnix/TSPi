"""Registry for deterministic scientific analysis capabilities.

Analysis capabilities operate on existing Node/artifact inputs.  They are
kept separate from the external-program calculation catalog so adding one does
not imply a scheduler task or a scientific successor workflow.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Final

from jsonschema import Draft202012Validator

from .errors import ComputeContractError
from .registry import CapabilityRegistration, CapabilityRegistry


def _analysis_key(descriptor: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(descriptor, dict) or not isinstance(descriptor.get("capability"), str) or not isinstance(descriptor.get("version"), str):
        raise ValueError("analysis descriptor must expose capability and version")
    return descriptor["capability"], descriptor["version"]


ANALYSIS_CAPABILITY_REGISTRY: CapabilityRegistry[dict[str, Any]] = CapabilityRegistry(key=_analysis_key)


def register_analysis_capability(
    descriptor: dict[str, Any],
    *,
    provider_id: str = "builtin",
    provider: object | None = None,
    replace: bool = False,
) -> CapabilityRegistration[dict[str, Any]]:
    """Register one analysis descriptor with the runtime provider catalog."""

    return ANALYSIS_CAPABILITY_REGISTRY.register(
        descriptor, provider_id=provider_id, provider=provider, replace=replace,
    )


def register_analysis_provider(
    provider: object,
    *,
    provider_id: str | None = None,
    replace: bool = False,
) -> tuple[CapabilityRegistration[dict[str, Any]], ...]:
    """Register all analysis descriptors exposed by a provider object."""

    return ANALYSIS_CAPABILITY_REGISTRY.register_provider(provider, provider_id=provider_id, replace=replace)


def analysis_capabilities() -> dict[str, Any]:
    """Return the analysis catalog without asserting scientific readiness."""

    return {
        "schema_version": "ts-analysis-capability-catalog/1",
        "capability_kind": "analysis",
        "capabilities": [
            {key: deepcopy(item[key]) for key in (
                "capability", "version", "capability_kind", "summary", "input_roles", "output_roles"
            )}
            for item in ANALYSIS_CAPABILITY_REGISTRY.descriptors()
        ],
        "detail_query": "research_read mode=capabilities capabilityKind=analysis query=<capability>@<version>",
    }


def resolve_analysis_capability(capability: str, version: str = "1") -> dict[str, Any]:
    registration = ANALYSIS_CAPABILITY_REGISTRY.resolve(capability, version)
    if registration is None:
        return {
            "schema_version": "ts-capability-gap/1",
            "ok": False,
            "status": "rejected",
            "reason": "capability_unavailable",
            "requested": f"{capability}@{version}",
            "missing_capability": capability,
            "requested_version": version,
            "retryable": False,
        }
    return {"schema_version": "ts-analysis-capability-resolution/1", "ok": True, **deepcopy(registration.descriptor)}


def run_analysis(root: str, request: dict[str, Any]) -> dict[str, Any]:
    """Dispatch an exact registered capability with validated, bounded inputs."""

    required = {"schema_version", "node_id", "capability", "capability_version", "input_artifacts", "parameters"}
    if not isinstance(request, dict) or set(request) != required:
        raise ComputeContractError("analysis request fields must be " + ", ".join(sorted(required)))
    if request["schema_version"] != "ts-analysis-request/1":
        raise ComputeContractError("analysis schema_version must be ts-analysis-request/1")
    capability, version = request["capability"], request["capability_version"]
    if not isinstance(capability, str) or not isinstance(version, str):
        raise ComputeContractError("analysis capability and capability_version must be strings")
    descriptor = resolve_analysis_capability(capability, version)
    if not descriptor["ok"]:
        return descriptor
    for field, schema in (("input_artifacts", "input_schema"), ("parameters", "parameter_schema")):
        error = next(Draft202012Validator(descriptor[schema]).iter_errors(request[field]), None)
        if error is not None:
            location = ".".join([field, *(str(part) for part in error.absolute_path)])
            raise ComputeContractError(f"analysis {location}: {error.message}")
    registration = ANALYSIS_CAPABILITY_REGISTRY.resolve(capability, version)
    provider = registration.provider if registration is not None else None
    runner = getattr(provider, "run_analysis", None)
    if not callable(runner):
        return {
            "schema_version": "ts-capability-gap/1", "ok": False, "status": "rejected",
            "reason": "capability_provider_unavailable", "requested": f"{capability}@{version}",
            "retryable": False,
        }
    try:
        return runner(root, request)
    except ComputeContractError:
        raise
    except Exception as exc:
        raise ComputeContractError(f"analysis provider failed: {exc}") from exc
