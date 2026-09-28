"""Generic provider contract for artifact-producing operations.

This module deliberately does not know about chemistry, Gaussian, or a
particular workspace layout.  An extension owns an operation descriptor and
its adapter; the kernel only discovers the descriptor, validates the provider
result envelope, and preserves input/output provenance.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any, Iterable, Protocol

from jsonschema import Draft202012Validator

from ts_agent.io import sha256_json

from .registry import CapabilityRegistration, CapabilityRegistry, CapabilityRegistryError


@dataclass(frozen=True)
class ArtifactOperationDescriptor:
    """Provider-owned contract for one artifact-producing operation."""

    operation: str
    version: str
    input_schema: dict[str, Any]
    parameter_schema: dict[str, Any]
    result_schema: dict[str, Any]
    output_roles: tuple[str, ...]
    provenance_schema: str | dict[str, Any]
    effects: tuple[str, ...] = ("local_prepare", "local_execute", "local_parse")

    def __post_init__(self) -> None:
        if not isinstance(self.operation, str) or not self.operation or len(self.operation) > 128:
            raise ValueError("artifact operation must be a non-empty string of at most 128 characters")
        if not isinstance(self.version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}", self.version):
            raise ValueError("artifact operation version is invalid")
        for field_name in ("input_schema", "parameter_schema", "result_schema"):
            value = getattr(self, field_name)
            if not isinstance(value, dict):
                raise ValueError(f"artifact {field_name} must be an object schema")
        if not isinstance(self.output_roles, tuple) or any(
            not isinstance(role, str) or not role for role in self.output_roles
        ) or len(self.output_roles) != len(set(self.output_roles)):
            raise ValueError("artifact output_roles must contain unique non-empty strings")
        if not isinstance(self.effects, tuple) or any(
            not isinstance(effect, str) or not effect for effect in self.effects
        ) or len(self.effects) != len(set(self.effects)):
            raise ValueError("artifact effects must contain unique non-empty strings")
        if not isinstance(self.provenance_schema, (str, dict)) or (
            isinstance(self.provenance_schema, str) and not self.provenance_schema
        ):
            raise ValueError("artifact provenance_schema must be a non-empty string or object schema")

    def public(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "version": self.version,
            "input_schema": deepcopy(self.input_schema),
            "parameter_schema": deepcopy(self.parameter_schema),
            "result_schema": deepcopy(self.result_schema),
            "output_roles": list(self.output_roles),
            "provenance_schema": deepcopy(self.provenance_schema),
            "effects": list(self.effects),
        }


class ArtifactProvider(Protocol):
    """Structural contract for an extension that owns artifact operations."""

    provider_id: str

    def operations(self) -> Iterable[ArtifactOperationDescriptor]:
        ...

    def prepare(self, operation: str, request: dict[str, Any], context: Any) -> Any:
        """Return a provider-owned execution plan for one operation."""
        ...

    def execute(self, prepared: Any, context: Any) -> dict[str, Any]:
        """Return the generic result envelope validated below."""
        ...


ARTIFACT_RESULT_SCHEMA = {
    "type": "object",
    "required": ["operation", "version", "result", "provenance"],
    "properties": {
        "operation": {"type": "string", "minLength": 1, "maxLength": 128},
        "version": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$"},
        # The provider-owned result_schema below may describe an object,
        # array, scalar, or any other JSON value.
        "result": {},
        "provenance": {
            "type": "object",
            "required": ["provider_id", "descriptor_digest", "inputs", "outputs"],
            "properties": {
                "provider_id": {"type": "string", "minLength": 1, "maxLength": 128},
                "descriptor_digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                "inputs": {"type": "array", "maxItems": 256, "items": {"type": "object"}},
                "outputs": {"type": "array", "maxItems": 256, "items": {"type": "object"}},
            },
            # Providers may add fields and constrain them with their
            # descriptor.provenance_schema.
            "additionalProperties": True,
        },
    },
    "additionalProperties": False,
}


def _operation_key(descriptor: ArtifactOperationDescriptor) -> tuple[str, str]:
    if not isinstance(descriptor, ArtifactOperationDescriptor):
        raise CapabilityRegistryError("artifact providers must return ArtifactOperationDescriptor values")
    return descriptor.operation, descriptor.version


ARTIFACT_OPERATION_REGISTRY: CapabilityRegistry[ArtifactOperationDescriptor] = CapabilityRegistry(
    key=_operation_key,
)


def register_artifact_operation(
    descriptor: ArtifactOperationDescriptor,
    *,
    provider_id: str = "builtin",
    provider: object | None = None,
    replace: bool = False,
) -> CapabilityRegistration[ArtifactOperationDescriptor]:
    """Register one extension-owned operation descriptor."""

    return ARTIFACT_OPERATION_REGISTRY.register(
        descriptor,
        provider_id=provider_id,
        provider=provider,
        replace=replace,
    )


def register_artifact_provider(
    provider: ArtifactProvider,
    *,
    provider_id: str | None = None,
    replace: bool = False,
) -> tuple[CapabilityRegistration[ArtifactOperationDescriptor], ...]:
    """Register all operations exposed by one provider atomically."""

    identifier = provider_id or getattr(provider, "provider_id", None)
    if not isinstance(identifier, str) or not identifier:
        raise CapabilityRegistryError("provider_id is required for an unnamed artifact provider")
    operations = getattr(provider, "operations", None)
    if not callable(operations):
        raise CapabilityRegistryError("artifact provider must expose operations()")
    return ARTIFACT_OPERATION_REGISTRY.register_many(
        tuple(operations()),
        provider_id=identifier,
        provider=provider,
        replace=replace,
    )


def resolve_artifact_operation(
    operation: str,
    version: str = "1",
) -> CapabilityRegistration[ArtifactOperationDescriptor] | None:
    return ARTIFACT_OPERATION_REGISTRY.resolve(operation, version)


def artifact_operation_catalog() -> dict[str, Any]:
    """Return schemas without exposing provider objects or command paths."""

    return {
        "schema_version": "ts-artifact-operation-catalog/1",
        "operations": [item.public() for item in ARTIFACT_OPERATION_REGISTRY.descriptors()],
        "detail_query": "compute.artifact-operation operation=<operation>@<version>",
    }


def artifact_operation_digest(descriptor: ArtifactOperationDescriptor) -> str:
    """Return the stable digest providers must include in result provenance."""

    return sha256_json(descriptor.public())


def validate_artifact_result(
    descriptor: ArtifactOperationDescriptor,
    result: dict[str, Any],
    *,
    provider_id: str,
    descriptor_digest: str,
) -> dict[str, Any]:
    """Validate and return an immutable copy of a provider result envelope."""

    if not isinstance(result, dict):
        raise ValueError("artifact provider result must be an object")
    errors = sorted(Draft202012Validator(ARTIFACT_RESULT_SCHEMA).iter_errors(result), key=lambda item: tuple(item.path))
    if errors:
        raise ValueError(f"invalid artifact result envelope: {errors[0].message}")
    if result["operation"] != descriptor.operation or result["version"] != descriptor.version:
        raise ValueError("artifact result operation/version does not match descriptor")
    provenance = result["provenance"]
    if provenance["provider_id"] != provider_id or provenance["descriptor_digest"] != descriptor_digest:
        raise ValueError("artifact result provenance does not match registered provider descriptor")
    if isinstance(descriptor.provenance_schema, dict):
        errors = sorted(
            Draft202012Validator(descriptor.provenance_schema).iter_errors(provenance),
            key=lambda item: tuple(item.path),
        )
        if errors:
            raise ValueError(f"artifact provider provenance failed provenance_schema: {errors[0].message}")
    errors = sorted(Draft202012Validator(descriptor.result_schema).iter_errors(result["result"]), key=lambda item: tuple(item.path))
    if errors:
        raise ValueError(f"artifact provider result failed result_schema: {errors[0].message}")
    return deepcopy(result)


def validate_artifact_request(
    descriptor: ArtifactOperationDescriptor,
    inputs: Any,
    parameters: Any,
) -> tuple[Any, Any]:
    """Validate provider-owned request schemas before preparing an operation."""

    for label, schema, value in (
        ("inputs", descriptor.input_schema, inputs),
        ("parameters", descriptor.parameter_schema, parameters),
    ):
        errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda item: tuple(item.path))
        if errors:
            raise ValueError(f"artifact provider {label} failed schema: {errors[0].message}")
    return deepcopy(inputs), deepcopy(parameters)


__all__ = [
    "ARTIFACT_OPERATION_REGISTRY",
    "ARTIFACT_RESULT_SCHEMA",
    "ArtifactOperationDescriptor",
    "ArtifactProvider",
    "artifact_operation_catalog",
    "artifact_operation_digest",
    "register_artifact_operation",
    "register_artifact_provider",
    "resolve_artifact_operation",
    "validate_artifact_request",
    "validate_artifact_result",
]
