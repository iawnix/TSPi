"""Compatibility error type for ASE NEB adapters."""

from __future__ import annotations

from transition_state_workflow.backends.ase_neb import AseNebConfigError

ConfigError = AseNebConfigError

__all__ = ["ConfigError"]
