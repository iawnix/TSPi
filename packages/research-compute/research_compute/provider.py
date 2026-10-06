"""Provider boundary for compute and domain operations.

``research_compute`` owns the lifecycle, binding and provenance rules.  It
does not own a scientific backend.  An installed extension registers one
object implementing :class:`ComputeProvider` during application bootstrap.
Keeping this protocol in the compute package makes the dependency direction
explicit: extensions depend on the protocol, while the lifecycle never
imports an extension implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Protocol


@dataclass(frozen=True)
class BackendTask:
    node_id: str
    task_type: str
    work_dir: str
    inputs: dict[str, str]
    settings: dict[str, str] = field(default_factory=dict)
    backend: str | None = None


@dataclass(frozen=True)
class PreparedTask:
    backend: str
    node_id: str
    command: list[str]
    input_paths: list[str]
    expected_artifacts: list[str]
    environment: dict[str, str] = field(default_factory=dict)
    activation_script: str | None = None


class ComputeProvider(Protocol):
    """Extension-owned implementation for one or more compute capabilities."""

    provider_id: str

    def supports(self, backend: str) -> bool: ...
    def environment_providers(self, descriptor: Any, environment_kind: str) -> tuple[str, ...]: ...
    def classify_task(self, workspace: Path, intent: dict[str, Any]) -> str: ...
    def validate_inputs(self, workspace: Path, intent: dict[str, Any], inputs: dict[str, str]) -> None: ...
    def prepare(self, task: BackendTask) -> PreparedTask: ...
    def required_artifacts(self, backend: str, task_type: str) -> set[str]: ...
    def parse(self, workspace: Path, intent: dict[str, Any], source: Path,
              parse_inputs: dict[str, tuple[str, Path]], *, parse_context: dict[str, Any]) -> dict[str, Any]: ...
    def parser_name(self, backend: str, *, parse_context: dict[str, Any]) -> str: ...
    def write_parse_artifacts(self, parsed: dict[str, Any], parse_dir: Path, source: Path,
                              *, backend: str, parse_context: dict[str, Any]) -> None: ...

    # Optional artifact naming/validation hooks.  The lifecycle falls back to
    # a single prepared artifact when these are absent, so third-party
    # providers can remain small while domain providers can describe stable
    # parser inputs without adding backend branches to the kernel.
    def parse_artifact_name(self, backend: str, expected_names: list[str]) -> str | None: ...
    def validate_parse_source(self, backend: str, source: Path) -> None: ...
    def remote_stdout_name(self, prepared_task: dict[str, Any]) -> str: ...
    def build_parse_context(self, workspace: Path, intent: dict[str, Any],
                            parse_inputs: dict[str, tuple[str, Path]]) -> tuple[dict[str, Any], list[dict[str, str]]]: ...
    def validate_parse_inputs(self, backend: str, intent: dict[str, Any], context: dict[str, Any]) -> None: ...
    def remote_job_options(self, config: Any) -> dict[str, Any]: ...
    def remote_artifact_name(self, config: Any, name: str) -> str: ...
    def local_job_options(self, prepared_task: dict[str, Any], local_command: list[str],
                          input_names: set[str], run_dir: Path) -> dict[str, Any]: ...
    def artifact_import_formats(self) -> dict[str, Iterable[str]]: ...
    def artifact_input_roles(self, path: str) -> list[str]: ...
    def validate_artifact_import(self, artifact_format: str, content: str,
                                 charge: int | None, multiplicity: int | None) -> dict[str, Any]: ...

    def validate_parsed_task(self, backend: str, task_type: str, facts: dict[str, Any]) -> dict[str, Any]: ...
    def parsed_program_outcome(self, backend: str, facts: dict[str, Any]) -> tuple[str, str | None]: ...

    # Optional installation-owned runtime probe.  The generic readiness and
    # remote doctor code executes the returned shell protocol but never knows
    # which scientific modules it imports.  Extensions own the implementation.
    def readiness_probe(self, backend: str, binding: Any) -> dict[str, Any] | None: ...

    # Domain operations are intentionally optional.  The generic artifact
    # catalog can report an unavailable capability when an extension is absent.
    def structure_operation(self, operation: str, root: Path, request: dict[str, Any]) -> dict[str, Any]: ...
    def run_analysis(self, root: Path, request: dict[str, Any]) -> dict[str, Any]: ...
    def validate_candidate(self, root: Path, artifact: dict[str, Any], node_id: str, candidate_id: str) -> dict[str, Any]: ...


class ProviderUnavailable(RuntimeError):
    """Raised when no installed extension can serve a requested backend."""


_lock = RLock()
_providers: dict[str, ComputeProvider] = {}


def register_compute_provider(provider: ComputeProvider, *, replace: bool = False) -> None:
    identifier = getattr(provider, "provider_id", None)
    if not isinstance(identifier, str) or not identifier:
        raise TypeError("compute provider_id must be a non-empty string")
    supports = getattr(provider, "supports", None)
    if not callable(supports):
        raise TypeError("compute provider must expose supports(backend)")
    backends = tuple(getattr(provider, "backends", ()))
    if not backends:
        raise TypeError("compute provider must declare at least one backend")
    unsupported = sorted(backend for backend in backends if not supports(backend))
    if unsupported:
        raise ValueError(f"compute provider does not support declared backends: {unsupported}")
    keys = (*backends, *((getattr(provider, "domain_id"),) if getattr(provider, "domain_id", None) else ()))
    with _lock:
        for backend in keys:
            if not isinstance(backend, str) or not backend:
                raise TypeError("compute provider backend names must be non-empty strings")
            if backend in _providers and not replace:
                raise ValueError(f"compute backend already registered: {backend}")
        for backend in keys:
            _providers[backend] = provider


def resolve_compute_provider(backend: str) -> ComputeProvider:
    with _lock:
        provider = _providers.get(backend)
    if provider is None:
        raise ProviderUnavailable(f"compute provider unavailable for backend: {backend}")
    return provider


def compute_provider_catalog() -> dict[str, Any]:
    with _lock:
        return {backend: provider.provider_id for backend, provider in sorted(_providers.items())}


__all__ = [
    "BackendTask", "PreparedTask", "ComputeProvider", "ProviderUnavailable",
    "register_compute_provider", "resolve_compute_provider", "compute_provider_catalog",
]
