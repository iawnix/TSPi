"""Backend adapter registry."""

from __future__ import annotations

from dataclasses import dataclass, field

from transition_state_workflow.backends.contracts import BackendAdapter
from transition_state_workflow.backends.gaussian import GaussianBackendAdapter
from transition_state_workflow.backends.xtb import XtbBackendAdapter
from transition_state_workflow.backends.ase import AseBackendAdapter
from transition_state_workflow.backends.qbics import QbicsBackendAdapter


@dataclass
class BackendRegistry:
    """Lookup table for backend adapters."""

    _adapters_by_name: dict[str, BackendAdapter] = field(default_factory=dict)

    def register(self, adapter: BackendAdapter) -> None:
        """Register one adapter by its stable backend name."""

        if not adapter.name:
            raise ValueError("backend adapter name must be nonempty")
        self._adapters_by_name[adapter.name] = adapter

    def get(self, name: str) -> BackendAdapter:
        """Return one adapter by name."""

        try:
            return self._adapters_by_name[name]
        except KeyError as exc:
            raise KeyError(f"unknown backend adapter: {name}") from exc

    def names(self) -> tuple[str, ...]:
        """Return registered backend names in stable order."""

        return tuple(sorted(self._adapters_by_name))


def default_backend_registry() -> BackendRegistry:
    """Return the built-in backend registry."""

    registry = BackendRegistry()
    registry.register(GaussianBackendAdapter())
    registry.register(XtbBackendAdapter())
    registry.register(AseBackendAdapter())
    registry.register(QbicsBackendAdapter())
    return registry
