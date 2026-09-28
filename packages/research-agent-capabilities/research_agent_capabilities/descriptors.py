"""Versioned capability descriptors for the framework-neutral API."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_CAPABILITY_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_VERSION = re.compile(r"^[1-9][0-9]*$")
WorkspaceMode = Literal["light", "research"]
WORKSPACE_MODES: tuple[WorkspaceMode, ...] = ("light", "research")
_WORKSPACE_MODE_SET = frozenset(WORKSPACE_MODES)


def _canonical_json(value: Any) -> Any:
    if isinstance(value, list):
        return [_canonical_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical_json(value[key]) for key in sorted(value)}
    return value


def _descriptor_digest(value: dict[str, Any]) -> str:
    """Hash the canonical descriptor without its self-referential digest."""

    base = copy.deepcopy(value)
    provider = base.get("provider")
    if isinstance(provider, dict):
        provider.pop("descriptor_digest", None)
    encoded = json.dumps(
        _canonical_json(base),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


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
        if not isinstance(self.capability_id, str) or not _CAPABILITY_IDENTIFIER.fullmatch(self.capability_id):
            raise DescriptorError("capability_id must be a lowercase identifier")
        if not isinstance(self.provider_id, str) or not _IDENTIFIER.fullmatch(self.provider_id):
            raise DescriptorError("provider_id must be a lowercase identifier")
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

    def to_canonical_dict(self) -> dict[str, Any]:
        """Expose the shared ``capability_descriptor/1`` wire shape.

        The kernel keeps its richer role-oriented descriptor internally.  This
        adapter is the only translation needed at the JS/contract boundary;
        callers must not maintain a second provider-specific descriptor schema.
        """
        metadata = copy.deepcopy(self.metadata)
        kind = metadata.pop("kind", "compute")
        summary = metadata.pop("summary", f"{self.provider_id} capability {self.capability_id}")
        output_schema = metadata.pop("output_schema", {
            "type": "object",
            "properties": {role: {"type": "string"} for role in self.output_kinds},
        })
        input_schema = copy.deepcopy(self.parameter_schema)
        input_schema.setdefault("x-ts-input-kinds", list(self.input_kinds))
        input_schema.setdefault("x-ts-environment-requirements", list(self.environment_requirements))
        input_schema.setdefault("x-ts-metadata", copy.deepcopy(self.metadata))
        output_schema = copy.deepcopy(output_schema)
        output_schema.setdefault("x-ts-output-kinds", list(self.output_kinds))
        limits = metadata.pop("limits", None)
        effects = metadata.pop("effects", None)
        document = {
            "protocol": "capability_descriptor",
            "version": 1,
            "capability_id": self.capability_id,
            "capability_version": self.version,
            "kind": kind,
            "summary": summary,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "supported_workspace_modes": list(self.supported_workspace_modes),
            "provider": {"provider_id": self.provider_id, "provider_version": "1"},
            **({"limits": limits} if isinstance(limits, dict) else {}),
            **({"effects": list(effects)} if isinstance(effects, (list, tuple)) else {}),
        }
        document["provider"]["descriptor_digest"] = _descriptor_digest(document)
        return document

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
        if value.get("protocol") == "capability_descriptor":
            return cls.from_canonical_dict(value)
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

    @classmethod
    def from_canonical_dict(cls, value: Mapping[str, Any]) -> "CapabilityDescriptor":
        """Adapt one canonical contract descriptor to the kernel descriptor."""
        if not isinstance(value, Mapping) or value.get("protocol") != "capability_descriptor" or value.get("version") != 1:
            raise DescriptorError("canonical capability descriptor requires protocol=capability_descriptor and version=1")
        required = {"capability_id", "capability_version", "kind", "summary", "input_schema", "output_schema", "supported_workspace_modes", "provider"}
        missing = required - set(value)
        if missing:
            raise DescriptorError(f"missing canonical capability descriptor fields: {', '.join(sorted(missing))}")
        provider = value["provider"]
        if not isinstance(provider, Mapping):
            raise DescriptorError("canonical descriptor provider must be an object")
        provider_required = {"provider_id", "provider_version", "descriptor_digest"}
        if provider_required - set(provider):
            raise DescriptorError("canonical descriptor provider must include provider_id, provider_version, and descriptor_digest")
        digest = provider["descriptor_digest"]
        if not isinstance(digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
            raise DescriptorError("canonical descriptor provider descriptor_digest is invalid")
        if digest != _descriptor_digest(dict(value)):
            raise DescriptorError("canonical descriptor provider descriptor_digest does not match descriptor")
        input_schema = value["input_schema"]
        output_schema = value["output_schema"]
        if not isinstance(input_schema, Mapping) or not isinstance(output_schema, Mapping):
            raise DescriptorError("canonical descriptor schemas must be objects")
        properties = output_schema.get("properties", {})
        output_kinds = tuple(output_schema.get("x-ts-output-kinds", tuple(properties))) if isinstance(properties, Mapping) else ()
        metadata = copy.deepcopy(input_schema.get("x-ts-metadata", {}))
        if not isinstance(metadata, dict):
            metadata = {"kind": value["kind"], "summary": value["summary"]}
        parameter_schema = {
            key: copy.deepcopy(item)
            for key, item in input_schema.items()
            if not key.startswith("x-ts-")
        }
        if "effects" in value: metadata["effects"] = copy.deepcopy(value["effects"])
        if "limits" in value: metadata["limits"] = copy.deepcopy(value["limits"])
        return cls(
            schema_version="research-agent-capability/1",
            capability_id=value["capability_id"],
            version=value["capability_version"],
            provider_id=provider.get("provider_id"),
            input_kinds=tuple(input_schema.get("x-ts-input-kinds", input_schema.get("required", ()))),
            output_kinds=output_kinds,
            parameter_schema=parameter_schema,
            environment_requirements=tuple(input_schema.get("x-ts-environment-requirements", ())),
            supported_workspace_modes=tuple(value["supported_workspace_modes"]),
            metadata=metadata,
        )
