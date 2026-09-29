"""Environment selection without commands or installation paths in contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Callable, Iterable


# Keep the Python contract in lockstep with the JS EnvironmentBinding and
# JSON schema. ``unavailable`` is a resolved selector whose required backend
# or environment checks failed; it is distinct from a malformed request.
_READINESS_STATES = frozenset({"configured", "ready", "not_ready", "unknown", "error", "unavailable"})


class EnvironmentError(ValueError):
    """Raised when an environment requirement cannot be bound."""


@dataclass(frozen=True)
class EnvironmentSpec:
    environment_id: str
    environment_kind: str
    provider_ids: tuple[str, ...] = ()
    tool_ids: tuple[str, ...] = ()
    environment_keys: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.environment_id or not self.environment_kind:
            raise EnvironmentError("environment_id and environment_kind are required")
        for name in ("provider_ids", "tool_ids", "environment_keys"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(value, str) or not value for value in values):
                raise EnvironmentError(f"{name} must contain non-empty strings")
            if len(values) != len(set(values)):
                raise EnvironmentError(f"{name} must not contain duplicates")


@dataclass(frozen=True)
class EnvironmentRequirement:
    capability_id: str
    provider_id: str
    environment_kind: str | None = None
    required_tool_ids: tuple[str, ...] = ()
    required_environment_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("capability_id", "provider_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise EnvironmentError(f"{field_name} must be a non-empty string")
        if self.environment_kind is not None and (
            not isinstance(self.environment_kind, str) or not self.environment_kind
        ):
            raise EnvironmentError("environment_kind must be a non-empty string")
        for field_name in ("required_tool_ids", "required_environment_keys"):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or any(not isinstance(value, str) or not value for value in values):
                raise EnvironmentError(f"{field_name} must contain non-empty strings")
            if len(values) != len(set(values)):
                raise EnvironmentError(f"{field_name} must not contain duplicates")


@dataclass(frozen=True)
class EnvironmentReadiness:
    state: str
    checks: tuple[dict[str, Any], ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.state not in _READINESS_STATES:
            raise EnvironmentError(f"unsupported readiness state: {self.state}")
        if not isinstance(self.checks, tuple) or any(not isinstance(item, dict) for item in self.checks):
            raise EnvironmentError("readiness checks must be a tuple of objects")
        if self.reason is not None and (not isinstance(self.reason, str) or not self.reason):
            raise EnvironmentError("readiness reason must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"state": self.state, "checks": [dict(item) for item in self.checks]}
        if self.reason:
            result["reason"] = self.reason
        return result


@dataclass(frozen=True)
class EnvironmentBinding:
    capability_id: str
    provider_id: str
    environment_id: str
    environment_kind: str
    readiness: EnvironmentReadiness
    binding_digest: str

    def __post_init__(self) -> None:
        for field_name in ("capability_id", "provider_id", "environment_id", "environment_kind"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise EnvironmentError(f"{field_name} must be a non-empty string")
        if not isinstance(self.binding_digest, str) or not self.binding_digest.startswith("sha256:"):
            raise EnvironmentError("binding_digest must be a sha256 digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "research-agent-environment-binding/1",
            "capability_id": self.capability_id,
            "provider_id": self.provider_id,
            "environment_id": self.environment_id,
            "environment_kind": self.environment_kind,
            "binding_digest": self.binding_digest,
            "readiness": self.readiness.to_dict(),
        }


class EnvironmentBroker:
    """Select configured environments using declarative requirements."""

    def __init__(
        self,
        environments: Iterable[EnvironmentSpec],
        *,
        readiness_probe: Callable[[EnvironmentSpec, EnvironmentRequirement], EnvironmentReadiness] | None = None,
    ) -> None:
        self._environments = tuple(environments)
        self._readiness_probe = readiness_probe
        if any(not isinstance(item, EnvironmentSpec) for item in self._environments):
            raise EnvironmentError("environments must contain EnvironmentSpec values")
        ids = [item.environment_id for item in self._environments]
        if len(ids) != len(set(ids)):
            raise EnvironmentError("environment_id values must be unique")

    def bind(
        self,
        requirement: EnvironmentRequirement,
        environment_id: str | None = None,
        *,
        probe: bool = False,
    ) -> EnvironmentBinding:
        candidates = [item for item in self._environments if self._matches(item, requirement, environment_id)]
        if not candidates:
            requested = environment_id or requirement.provider_id
            raise EnvironmentError(f"no configured environment satisfies: {requested}")
        selected = candidates[0]
        readiness = (
            self._readiness_probe(selected, requirement)
            if probe and self._readiness_probe is not None
            else EnvironmentReadiness("configured", ({"name": "environment", "state": "configured"},))
        )
        if not isinstance(readiness, EnvironmentReadiness):
            raise EnvironmentError("readiness_probe must return EnvironmentReadiness")
        digest_payload = {
            "capability_id": requirement.capability_id,
            "provider_id": requirement.provider_id,
            "environment_id": selected.environment_id,
            "environment_kind": selected.environment_kind,
            "provider_ids": selected.provider_ids,
            "tool_ids": selected.tool_ids,
            "environment_keys": selected.environment_keys,
        }
        digest = "sha256:" + sha256(json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return EnvironmentBinding(
            capability_id=requirement.capability_id,
            provider_id=requirement.provider_id,
            environment_id=selected.environment_id,
            environment_kind=selected.environment_kind,
            readiness=readiness,
            binding_digest=digest,
        )

    @staticmethod
    def _matches(
        environment: EnvironmentSpec,
        requirement: EnvironmentRequirement,
        environment_id: str | None,
    ) -> bool:
        return (
            (environment_id is None or environment.environment_id == environment_id)
            and (requirement.environment_kind is None or environment.environment_kind == requirement.environment_kind)
            and requirement.provider_id in environment.provider_ids
            and set(requirement.required_tool_ids).issubset(environment.tool_ids)
            and set(requirement.required_environment_keys).issubset(environment.environment_keys)
        )
