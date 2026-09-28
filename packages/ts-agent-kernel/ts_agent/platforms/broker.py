"""Capability-to-environment binding without exposing runtime details.

The compute kernel needs executable commands, activation scripts, and
environment variables to run a provider.  Those are installation-owned
details and must not be part of the contract returned to an Agent.  This
module is the small boundary between a capability/provider and a configured
execution environment.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ts_agent.io import sha256_json

from .config import (
    BackendBinding,
    ComputeEnvironment,
    EnvironmentConfig,
    EnvironmentConfigurationError,
    load_config,
)


@dataclass(frozen=True)
class EnvironmentRequirement:
    """Provider requirements used to select one execution environment.

    ``providers`` are provider/backend identifiers supplied by a capability
    adapter.  They are intentionally not shell commands.  A provider may
    list aliases to support legacy bindings such as ``ase_neb_xtb``.
    """

    providers: tuple[str, ...]
    kind: str | None = None
    required_environment: tuple[str, ...] = ()
    requires_gpu: bool | None = None

    def __post_init__(self) -> None:
        provider_values: Any = (self.providers,) if isinstance(self.providers, str) else self.providers
        if not isinstance(provider_values, (tuple, list)):
            raise ValueError("environment requirement providers must be strings")
        providers = tuple(item.strip() for item in provider_values if isinstance(item, str) and item.strip())
        if not providers:
            raise ValueError("environment requirement must name at least one provider")
        if self.kind is not None and self.kind not in {"local", "remote"}:
            raise ValueError("environment requirement kind must be local or remote")
        if self.requires_gpu is not None and not isinstance(self.requires_gpu, bool):
            raise ValueError("environment requirement requires_gpu must be boolean or null")
        object.__setattr__(self, "providers", providers)
        environment_values: Any = (
            (self.required_environment,)
            if isinstance(self.required_environment, str)
            else self.required_environment
        )
        if not isinstance(environment_values, (tuple, list)):
            raise ValueError("environment requirement required_environment must be strings")
        object.__setattr__(
            self,
            "required_environment",
            tuple(item.strip() for item in environment_values if isinstance(item, str) and item.strip()),
        )


@dataclass(frozen=True)
class EnvironmentReadiness:
    """A bounded readiness result suitable for the Agent-facing catalog."""

    state: str
    checks: tuple[dict[str, Any], ...] = ()
    reason: str | None = None

    def public(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "state": self.state,
            "checks": [dict(check) for check in self.checks],
        }
        if self.reason:
            result["reason"] = self.reason
        return result


@dataclass(frozen=True)
class EnvironmentBinding:
    """A resolved provider/environment pair.

    ``_backend`` is deliberately private to this module boundary.  Execution
    code can call :meth:`to_backend_binding`, while the public representation
    contains only stable identifiers and readiness information.
    """

    environment: str
    kind: str
    provider: str
    readiness: EnvironmentReadiness
    _backend: BackendBinding

    @property
    def binding_digest(self) -> str:
        """Return a stable opaque identity for this installation binding."""

        return sha256_json(
            {
                "environment": self.environment,
                "kind": self.kind,
                "provider": self.provider,
                "command": list(self._backend.command),
                "activation_script": self._backend.activation_script,
                "scratch_root": self._backend.scratch_root,
                "environment_keys": sorted(self._backend.environment),
                "environment_values": self._backend.environment,
            }
        )

    def public(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "kind": self.kind,
            "provider": self.provider,
            "binding_digest": self.binding_digest,
            "readiness": self.readiness.public(),
        }

    def to_backend_binding(self) -> BackendBinding:
        """Return the installation-owned binding for trusted execution code."""

        return self._backend


class EnvironmentBroker:
    """Resolve provider requirements against configured environments.

    The broker has no knowledge of Agent prompts or capability strategy.  It
    only selects a configured environment and reports whether its binding is
    configured (or, when requested, locally probeable).
    """

    def __init__(self, config: EnvironmentConfig | None = None) -> None:
        self.config = config if config is not None else load_config()

    def bind(
        self,
        requirement: EnvironmentRequirement,
        environment: str | None = None,
        *,
        probe: bool = False,
    ) -> EnvironmentBinding:
        """Bind a provider requirement to one environment.

        An explicitly named environment is always honored and validated.  If
        it is omitted, the existing ``EnvironmentConfig.environment`` rules
        select the default or the only environment of the requested kind.
        """

        selected = self.config.environment(environment, kind=requirement.kind)
        if requirement.requires_gpu is True and selected.kind == "local":
            # Local GPU availability is provider-owned and cannot be inferred
            # from a command path.  Keep the binding explicit and defer the
            # probe rather than pretending a GPU is available.
            gpu_deferred = True
        else:
            gpu_deferred = False
        provider, backend = self._provider_binding(selected, requirement.providers)
        readiness = self._readiness(
            selected,
            provider,
            backend,
            requirement,
            probe=probe,
            gpu_deferred=gpu_deferred,
        )
        return EnvironmentBinding(
            environment=selected.name,
            kind=selected.kind,
            provider=provider,
            readiness=readiness,
            _backend=backend,
        )

    def readiness(
        self,
        requirement: EnvironmentRequirement,
        environment: str | None = None,
    ) -> EnvironmentBinding:
        """Resolve and probe a binding for an explicit readiness check."""

        return self.bind(requirement, environment, probe=True)

    @staticmethod
    def _provider_binding(
        environment: ComputeEnvironment,
        providers: tuple[str, ...],
    ) -> tuple[str, BackendBinding]:
        for provider in providers:
            binding = environment.backends.get(provider)
            if binding is not None:
                return provider, binding
        if len(providers) == 1:
            raise EnvironmentConfigurationError(
                f"compute environment {environment.name!r} does not configure backend.{providers[0]}"
            )
        requested = ", ".join(providers)
        raise EnvironmentConfigurationError(
            f"compute environment {environment.name!r} does not configure a requested provider: {requested}"
        )

    @staticmethod
    def _readiness(
        environment: ComputeEnvironment,
        provider: str,
        binding: BackendBinding,
        requirement: EnvironmentRequirement,
        *,
        probe: bool,
        gpu_deferred: bool,
    ) -> EnvironmentReadiness:
        checks: list[dict[str, Any]] = [
            {"name": "provider_binding", "state": "configured"},
        ]
        missing = [name for name in requirement.required_environment if name not in binding.environment]
        if missing:
            return EnvironmentReadiness(
                "unavailable",
                tuple(checks + [{"name": "required_environment", "state": "failed", "missing": missing}]),
                f"provider {provider!r} is missing required environment bindings",
            )
        if not probe:
            if gpu_deferred:
                checks.append({"name": "gpu", "state": "deferred"})
            return EnvironmentReadiness("configured", tuple(checks))
        if environment.kind == "remote":
            # The scheduler/SSH doctor owns remote probing.  This check is
            # intentionally non-destructive and does not run a remote command.
            checks.append({"name": "remote_transport", "state": "deferred"})
            if gpu_deferred:
                checks.append({"name": "gpu", "state": "deferred"})
            return EnvironmentReadiness("configured", tuple(checks))
        executable = binding.command[0] if binding.command else ""
        available = _executable_available(executable)
        checks.append({"name": "executable", "state": "ready" if available else "failed"})
        if not available:
            return EnvironmentReadiness(
                "unavailable",
                tuple(checks),
                f"provider {provider!r} executable is not available",
            )
        if gpu_deferred:
            checks.append({"name": "gpu", "state": "deferred"})
        return EnvironmentReadiness("ready", tuple(checks))


EnvironmentManager = EnvironmentBroker


def _executable_available(value: str) -> bool:
    if not value or "\x00" in value:
        return False
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.is_file() and os.access(path, os.X_OK)
    return shutil.which(value) is not None


__all__ = [
    "EnvironmentBinding",
    "EnvironmentBroker",
    "EnvironmentManager",
    "EnvironmentReadiness",
    "EnvironmentRequirement",
]
