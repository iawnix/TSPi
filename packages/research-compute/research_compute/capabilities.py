"""Self-describing calculation capability catalog.

The catalog is deliberately declarative.  A capability says what an executor
can accept and produce; it never says which capability should be selected for a
Claim.  Scientific strategy remains in the Root Agent and in the rationale of
an action request.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Any

from .registry import CapabilityRegistration, CapabilityRegistry
from tspi_foundation.io import sha256_json


@dataclass(frozen=True)
class CapabilityDescriptor:
    """The stable, machine-readable envelope for one executor capability."""

    capability: str
    version: str
    backend: str
    task_type: str
    input_roles: frozenset[str]
    output_roles: tuple[str, ...]
    effects: tuple[str, ...]
    parameter_schema: dict[str, Any]
    limits: dict[str, Any]
    parsers: tuple[str, ...]

    def public(self) -> dict[str, Any]:
        # ``capability_id``/``capability_version`` are the cross-runtime
        # catalog protocol.  The calculation intent still uses the shorter
        # ``capability``/``capability_version`` fields internally because it
        # is the semantic request accepted by the Native lifecycle; those
        # internal names must not leak into the public catalog.
        canonical = {
            "protocol": "capability_descriptor",
            "version": 1,
            "capability_id": self.capability,
            "capability_version": self.version,
            "kind": "compute",
            "summary": f"Run a bounded {self.backend} {self.task_type} calculation.",
            "input_schema": {
                "type": "object",
                "required": sorted(self.input_roles),
                "additionalProperties": False,
            },
            "output_schema": {
                "type": "object",
                "additionalProperties": True,
            },
            "provider": {
                "provider_id": "unbound",
                "provider_version": "1",
                "descriptor_digest": "sha256:" + "0" * 64,
            },
            "limits": deepcopy(self.limits),
            "effects": list(self.effects),
            "extensions": {
                "input_roles": sorted(self.input_roles),
                "output_roles": list(self.output_roles),
                "parameter_schema": deepcopy(self.parameter_schema),
                "parsers": list(self.parsers),
                "execution_routes": ["native_lifecycle"],
                "backend": self.backend,
                "task_type": self.task_type,
            },
        }
        digest_payload = deepcopy(canonical)
        digest_payload["provider"]["descriptor_digest"] = ""
        canonical["provider"]["descriptor_digest"] = sha256_json(digest_payload)
        # Generated aliases keep existing Native lifecycle adapters stable;
        # they are projections of the canonical extensions above.
        canonical.update({
            "input_roles": sorted(self.input_roles),
            "output_roles": list(self.output_roles),
            "parameter_schema": deepcopy(self.parameter_schema),
            "parsers": list(self.parsers),
            "execution_routes": ["native_lifecycle"],
        })
        return canonical


class CapabilityGapError(ValueError):
    """A requested capability is not present in this package."""

    def __init__(self, requested: str, version: str | None = None) -> None:
        self.requested = requested
        self.version = version
        suffix = f"@{version}" if version else ""
        self.payload = {
            "status": "rejected",
            "reason": "capability_unavailable",
            "requested": f"{requested}{suffix}",
            "missing_capability": requested,
            "requested_version": version,
            "retryable": False,
        }
        super().__init__(f"capability unavailable: {requested}{suffix}")


CAPABILITY_REGISTRY: CapabilityRegistry[CapabilityDescriptor] = CapabilityRegistry()

# These maps remain as compatibility views for the existing executor boundary.
# Resolution and catalog output use CAPABILITY_REGISTRY so a registered
# provider does not require edits to this module's built-in tuple.
def register_capability(
    descriptor: CapabilityDescriptor,
    *,
    provider_id: str = "builtin",
    provider: object | None = None,
    replace: bool = False,
) -> CapabilityRegistration[CapabilityDescriptor]:
    """Register one calculation descriptor with the runtime provider catalog.

    The descriptor remains declarative.  A provider adapter may be associated
    for discovery, but it is not imported or executed by catalog queries.
    Duplicate ``capability@version`` registrations are rejected unless
    ``replace=True`` is explicit.
    """

    if not isinstance(descriptor, CapabilityDescriptor):
        raise TypeError("calculation capability providers must return CapabilityDescriptor values")
    return CAPABILITY_REGISTRY.register(
        descriptor,
        provider_id=provider_id,
        provider=provider,
        replace=replace,
    )


def register_capability_provider(
    provider: object,
    *,
    provider_id: str | None = None,
    replace: bool = False,
) -> tuple[CapabilityRegistration[CapabilityDescriptor], ...]:
    """Register all descriptors exposed by a provider object."""

    source = getattr(provider, "descriptors", None) or getattr(provider, "capabilities", None)
    if not callable(source):
        raise ValueError("provider must expose descriptors() or capabilities()")
    identifier = provider_id or getattr(provider, "provider_id", None) or getattr(provider, "name", None)
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("provider_id is required for an unnamed provider")
    descriptors = tuple(source())
    if not all(isinstance(item, CapabilityDescriptor) for item in descriptors):
        raise TypeError("calculation capability providers must return CapabilityDescriptor values")
    supports = getattr(provider, "supports", None)
    if callable(supports):
        unsupported = sorted({item.backend for item in descriptors if not supports(item.backend)})
        if unsupported:
            raise ValueError(
                f"provider {identifier!r} does not support registered backends: {unsupported}"
            )
    return CAPABILITY_REGISTRY.register_many(
        descriptors,
        provider_id=identifier,
        provider=provider,
        replace=replace,
    )


def resolve_capability(capability: str, version: str = "1") -> CapabilityDescriptor:
    registration = resolve_capability_registration(capability, version)
    return registration.descriptor


def resolve_capability_registration(
    capability: str,
    version: str = "1",
) -> CapabilityRegistration[CapabilityDescriptor]:
    """Resolve the descriptor and its trusted provider association.

    Catalog consumers normally need only :func:`resolve_capability`.  The
    execution boundary uses this richer lookup so an installed provider can
    supply its own adapter without adding a backend-specific branch to the
    kernel.  Provider objects are never exposed by the public catalog.
    """

    registration = CAPABILITY_REGISTRY.resolve(capability, version)
    if registration is None:
        raise CapabilityGapError(capability, version)
    return registration


def validate_capability_parameters(
    descriptor: CapabilityDescriptor,
    parameters: Any,
) -> dict[str, Any]:
    """Validate a Root-authored parameter object against one descriptor."""

    # Catalog/readiness discovery may run in the Host bridge interpreter where
    # the optional validator dependency is absent. Execution still fails
    # explicitly at this boundary when validation cannot be performed.
    from jsonschema import Draft202012Validator

    if not isinstance(parameters, dict):
        raise ValueError("capability parameters must be an object")
    errors = sorted(
        Draft202012Validator(descriptor.parameter_schema).iter_errors(parameters),
        key=lambda error: tuple(str(part) for part in error.path),
    )
    if errors:
        details = []
        for error in errors[:3]:
            location = "$" + "".join(f"[{part!r}]" for part in error.path)
            details.append(f"{location}: {error.message}")
        raise ValueError(
            f"invalid parameters for capability {descriptor.capability}@{descriptor.version}; "
            + "; ".join(details)
        )
    return deepcopy(parameters)


def adapter_settings(parameters: dict[str, Any]) -> dict[str, str]:
    """Convert validated JSON values to the backend adapter string boundary.

    Arrays and objects use canonical JSON so extension providers can recover
    structured parameters without depending on Python's representation.
    """

    settings: dict[str, str] = {}
    for name, value in parameters.items():
        if isinstance(value, (list, dict)):
            settings[name] = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        elif isinstance(value, bool):
            settings[name] = "true" if value else "false"
        else:
            settings[name] = str(value)
    return settings


def calculation_capabilities() -> dict[str, object]:
    """Return descriptors separately from environment readiness."""

    capabilities = []
    for registration in CAPABILITY_REGISTRY.registrations():
        item = registration.descriptor.public()
        item["provider"] = {
            "provider_id": registration.provider_id,
            "provider_version": str(getattr(registration.provider, "provider_version", "1")),
            "descriptor_digest": "",
        }
        digest_payload = deepcopy(item)
        digest_payload["provider"]["descriptor_digest"] = ""
        item["provider"]["descriptor_digest"] = sha256_json(digest_payload)
        capabilities.append(item)
    return {
        "schema_version": "ts-capability-catalog/1",
        "protocol": "capability_catalog",
        "version": 1,
        "kind": "compute",
        "capabilities": capabilities,
        "readiness": {
            "state": "not_probed",
            "meaning": (
                "Descriptor presence does not prove executable, environment, scheduler, "
                "or transport readiness; establish readiness separately with "
                "runtime checks or the installation remote readiness check."
            ),
        },
    }


def resolve_capability_result(capability: str, version: str = "1") -> dict[str, Any]:
    """Return one descriptor or a structured, side-effect-free capability gap."""

    try:
        registration = resolve_capability_registration(capability, version)
        descriptor = registration.descriptor
    except CapabilityGapError as exc:
        return {"schema_version": "ts-capability-gap/1", "ok": False, **exc.payload}
    public = descriptor.public()
    public["provider"] = {
        "provider_id": registration.provider_id,
        "provider_version": str(getattr(registration.provider, "provider_version", "1")),
        "descriptor_digest": "",
    }
    digest_payload = deepcopy(public)
    digest_payload["provider"]["descriptor_digest"] = ""
    public["provider"]["descriptor_digest"] = sha256_json(digest_payload)
    return {
        "schema_version": "ts-capability-resolution/1",
        "protocol": "capability_resolution",
        "version": 1,
        "ok": True,
        "descriptor": public,
    }
