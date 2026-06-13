"""Tiny config-value coercers shared across the NEB toolkit.

These validate-or-raise helpers are layer-zero (they depend only on
:class:`ConfigError`), so both ``config`` and ``mechanism`` can use them without
``mechanism`` having to depend on ``config``.
"""

from __future__ import annotations

from typing import Any

from transition_state_workflow.tool.ase_neb.errors import ConfigError


def as_mapping(value: Any, name: str) -> dict[str, Any]:
    """Return a shallow copy of a mapping, or ``{}`` for None; raise otherwise."""

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a mapping")
    return dict(value)


def as_positive_int(value: Any, name: str) -> int:
    """Return ``value`` if it is a positive int, else raise :class:`ConfigError`."""

    if not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{name} must be a positive integer")
    return value


__all__ = ["as_mapping", "as_positive_int"]
