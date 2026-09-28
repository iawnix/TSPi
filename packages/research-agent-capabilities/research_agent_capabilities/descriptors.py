"""Versioned capability descriptors for the framework-neutral API."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_VERSION = re.compile(r"^[1-9][0-9]*$")
WorkspaceMode = Literal["light", "research"]
WORKSPACE_MODES: tuple[WorkspaceMode, ...] = ("light", "research")
_WORKSPACE_MODE_SET = frozenset(WORKSPACE_MODES)


class DescriptorError(ValueError):
    """Raised when a capability descriptor violates the protocol."""


@dataclass(frozen=True)
class CapabilityDescriptor:
    """Declarative description of one versioned capability.

    A descriptor contains no executable command or environment path. Provider
    implementations are associated by :class:`ProviderRegistry` separately.
    """

    capability_id: str
    version: str
    provider_id: str
    input_kinds: tuple[str, ...] = ()
    output_kinds: tuple[str, ...] = ()
    parameter_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})
    environment_requirements: tuple[str, ...] = ()
    supported_workspace_modes: tuple[WorkspaceMode, ...] = WORKSPACE_MODES
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "research-agent-capability/1"

    def __post_init__(self) -> None:
        for field_name, value in (
            ("capability_id", self.capability_id),
            ("provider_id", self.provider_id),
        ):
            if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
                raise DescriptorError(f"{field_name} must be a lowercase identifier")
        if not isinstance(self.version, str) or not _VERSION.fullmatch(self.version):
            raise DescriptorError("version must be a positive integer string")
        if self.schema_version != "research-agent-capability/1":
            raise DescriptorError("unsupported capability descriptor schema_version")
        for field_name in ("input_kinds", "output_kinds", "environment_requirements"):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or any(
                not isinstance(item, str) or not _IDENTIFIER.fullmatch(item) for item in values
            ):
                raise DescriptorError(f"{field_name} must contain lowercase identifiers")
            if len(values) != len(set(values)):
                raise DescriptorError(f"{field_name} must not contain duplicates")
        if (
            not isinstance(self.supported_workspace_modes, tuple)
            or not self.supported_workspace_modes
            or any(
                not isinstance(value, str) or value not in _WORKSPACE_MODE_SET
                for value in self.supported_workspace_modes
            )
            or len(self.supported_workspace_modes) != len(set(self.supported_workspace_modes))
        ):
            raise DescriptorError("supported_workspace_modes must contain unique light/research values")
        if not isinstance(self.parameter_schema, dict) or self.parameter_schema.get("type") != "object":
            raise DescriptorError("parameter_schema must be an object schema")
        if not isinstance(self.metadata, dict):
            raise DescriptorError("metadata must be an object")

    @property
    def key(self) -> tuple[str, str]:
        return self.capability_id, self.version

    def to_dict(self) -> dict[str, Any]:
        """Return a detached, JSON-compatible descriptor document."""

        return {
            "schema_version": self.schema_version,
            "capability_id": self.capability_id,
            "version": self.version,
            "provider_id": self.provider_id,
            "input_kinds": list(self.input_kinds),
            "output_kinds": list(self.output_kinds),
            "parameter_schema": copy.deepcopy(self.parameter_schema),
            "environment_requirements": list(self.environment_requirements),
            "supported_workspace_modes": list(self.supported_workspace_modes),
            "metadata": copy.deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CapabilityDescriptor":
        """Parse a serialized descriptor at the capability boundary.

        JSON arrays are converted to the immutable tuples expected by the
        dataclass before the same constructor validation is applied. Missing
        or unknown fields are rejected so admission cannot silently broaden a
        capability's supported workspace modes.
        """

        if not isinstance(value, Mapping):
            raise DescriptorError("capability descriptor must be an object")
        fields = {
            "schema_version",
            "capability_id",
            "version",
            "provider_id",
            "input_kinds",
            "output_kinds",
            "parameter_schema",
            "environment_requirements",
            "supported_workspace_modes",
            "metadata",
        }
        unknown = set(value) - fields
        missing = fields - set(value)
        if unknown:
            raise DescriptorError(f"unknown capability descriptor fields: {', '.join(sorted(unknown))}")
        if missing:
            raise DescriptorError(f"missing capability descriptor fields: {', '.join(sorted(missing))}")

        def tuple_field(name: str) -> tuple[str, ...]:
            raw = value[name]
            if not isinstance(raw, (list, tuple)):
                raise DescriptorError(f"{name} must be an array")
            return tuple(raw)

        parameter_schema = value["parameter_schema"]
        metadata = value["metadata"]
        if not isinstance(parameter_schema, Mapping):
            raise DescriptorError("parameter_schema must be an object schema")
        if not isinstance(metadata, Mapping):
            raise DescriptorError("metadata must be an object")
        return cls(
            schema_version=value["schema_version"],
            capability_id=value["capability_id"],
            version=value["version"],
            provider_id=value["provider_id"],
            input_kinds=tuple_field("input_kinds"),
            output_kinds=tuple_field("output_kinds"),
            parameter_schema=copy.deepcopy(dict(parameter_schema)),
            environment_requirements=tuple_field("environment_requirements"),
            supported_workspace_modes=tuple_field("supported_workspace_modes"),
            metadata=copy.deepcopy(dict(metadata)),
        )
