"""Configuration profiles plus a Python entry-point hook for future adapters."""

from __future__ import annotations

from importlib import metadata
from typing import Any, Protocol

from .config import SoftwareProfile
from .errors import ConfigurationError


class SoftwareAdapter(Protocol):
    """Optional extension API loaded from the ``cluster_mcp.software`` entry-point group."""

    name: str
    description: str

    def build_body(self, parameters: dict[str, Any]) -> tuple[str, ...]: ...


class SoftwareRegistry:
    def __init__(self, profiles: dict[str, SoftwareProfile]) -> None:
        self.profiles = dict(profiles)
        self.adapters: dict[str, SoftwareAdapter] = {}
        self.load_errors: dict[str, str] = {}

    def load_entry_points(self) -> None:
        entry_points = metadata.entry_points()
        selected = entry_points.select(group="cluster_mcp.software")
        for entry_point in selected:
            try:
                adapter = entry_point.load()()
                name = getattr(adapter, "name", entry_point.name)
                if not isinstance(name, str) or not name:
                    raise ConfigurationError("adapter name must be a non-empty string")
                if name in self.profiles or name in self.adapters:
                    raise ConfigurationError(f"duplicate software adapter name: {name}")
                self.adapters[name] = adapter
            except Exception as exc:  # noqa: BLE001 - extension failures are isolated and reported.
                self.load_errors[entry_point.name] = f"{type(exc).__name__}: {exc}"

    def describe(self) -> dict[str, Any]:
        profiles = [
            {
                "name": profile.name,
                "kind": "profile",
                "description": profile.description,
                "command": list(profile.command),
                "activation_script": str(profile.activation_script)
                if profile.activation_script
                else None,
                "activation_script_exists": profile.activation_script.is_file()
                if profile.activation_script
                else None,
                "default_queue": profile.default_queue,
                "allowed_queues": list(profile.allowed_queues),
                "requires_gpu": profile.requires_gpu,
            }
            for profile in self.profiles.values()
        ]
        adapters = [
            {
                "name": name,
                "kind": "python_adapter",
                "description": getattr(adapter, "description", ""),
            }
            for name, adapter in self.adapters.items()
        ]
        return {
            "software": sorted([*profiles, *adapters], key=lambda item: item["name"]),
            "load_errors": self.load_errors,
        }
