"""Registry for deterministic scientific analysis capabilities.

Analysis capabilities operate on existing Node/artifact inputs.  They are
kept separate from the external-program calculation catalog so adding one does
not imply a scheduler task or a scientific successor workflow.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Final

from jsonschema import Draft202012Validator
from tspi_foundation.io import sha256_json

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

    # A compute provider may expose separate calculation and analysis
    # descriptor catalogs. Domain extensions should not overload one method
    # with two incompatible descriptor shapes.
    source = getattr(provider, "analysis_descriptors", None)
    if callable(source):
        identifier = provider_id or getattr(provider, "provider_id", None) or getattr(provider, "name", None)
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("provider_id is required for an unnamed provider")
        return ANALYSIS_CAPABILITY_REGISTRY.register_many(
            source(), provider_id=identifier, provider=provider, replace=replace,
        )
    return ANALYSIS_CAPABILITY_REGISTRY.register_provider(provider, provider_id=provider_id, replace=replace)


def analysis_capabilities() -> dict[str, Any]:
    """Return the analysis catalog without asserting scientific readiness."""
    capabilities = []
    for registration in ANALYSIS_CAPABILITY_REGISTRY.registrations():
        capabilities.append(_public_descriptor(registration.descriptor, registration.provider_id, compact=True))
    return {
        "schema_version": "ts-capability-catalog/1",
        "protocol": "capability_catalog",
        "version": 1,
        "kind": "analysis",
        "capabilities": capabilities,
        "detail_query": "capability <capability_id>@<capability_version>",
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
    return {
        "protocol": "capability_resolution",
        "version": 1,
        "ok": True,
        **_public_descriptor(registration.descriptor, registration.provider_id, compact=False),
    }


def _public_descriptor(
    descriptor: dict[str, Any], provider_id: str, *, compact: bool,
) -> dict[str, Any]:
    """Project every analysis descriptor into the shared capability protocol.

    The legacy names are retained only in the returned compatibility view for
    old Native clients.  Execution and registry lookup continue to use the
    canonical ``capability_id``/``capability_version`` pair.
    """
    capability_id = str(descriptor["capability"])
    capability_version = str(descriptor["version"])
    canonical = {
        "protocol": "capability_descriptor",
        "version": 1,
        "capability_id": capability_id,
        "capability_version": capability_version,
        "kind": "analysis",
        "summary": str(descriptor.get("summary", capability_id)),
        "input_schema": deepcopy(descriptor.get("input_schema", {"type": "object"})),
        "output_schema": deepcopy(descriptor.get("output_schema", {"type": "object"})),
        "provider": {
            "provider_id": provider_id,
            "provider_version": str(getattr(_provider_for_id(provider_id), "provider_version", "1")),
            "descriptor_digest": "sha256:" + "0" * 64,
        },
        "limits": deepcopy(descriptor.get("limits", {})),
        "effects": list(descriptor.get("effects", [])),
        "extensions": {
            "input_roles": list(descriptor.get("input_roles", [])),
            "output_roles": list(descriptor.get("output_roles", [])),
            "parsers": list(descriptor.get("parsers", [])),
            "parameter_schema": deepcopy(descriptor.get("parameter_schema", {"type": "object"})),
        },
    }
    # Compatibility aliases are deliberately generated from canonical values,
    # so there is one source of truth rather than two independently maintained
    # descriptor protocols.
    canonical.update({
        "capability": capability_id,
        "capability_kind": "analysis",
        "summary": canonical["summary"],
        "input_roles": list(descriptor.get("input_roles", [])),
        "output_roles": list(descriptor.get("output_roles", [])),
    })
    for key in ("scientific_scope", "limitations"):
        if key in descriptor:
            canonical["extensions"][key] = deepcopy(descriptor[key])
    if not compact:
        canonical["parameter_schema"] = deepcopy(descriptor.get("parameter_schema", {"type": "object"}))
    digest_payload = deepcopy(canonical)
    for key in ("capability", "capability_kind", "input_roles", "output_roles", "parameter_schema"):
        digest_payload.pop(key, None)
    digest_payload["provider"]["descriptor_digest"] = ""
    canonical["provider"]["descriptor_digest"] = sha256_json(digest_payload)
    return canonical


def _provider_for_id(provider_id: str) -> Any:
    for registration in ANALYSIS_CAPABILITY_REGISTRY.registrations():
        if registration.provider_id == provider_id:
            return registration.provider
    return None


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
