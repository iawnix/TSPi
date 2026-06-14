"""Compatibility wrapper for ChemKernel planning packets.

Use :mod:`transition_state_workflow.core.plan_next` for new imports. This
legacy module injects the current ChemGate validator and evidence predicate so
the public CLI behavior stays unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.core.plan_next import *  # noqa: F401,F403
from transition_state_workflow.core.plan_next import build_plan_next_packet as _core_build_plan_next_packet
from transition_state_workflow.gate.evidence import record_supports_tsfreq_reframe
from transition_state_workflow.gate.validate import validate_ts_workspace_contract


def build_plan_next_packet(
    root: Path,
    *,
    max_suggestions: int = 4,
    alternative_mechanism: bool = False,
) -> dict[str, Any]:
    """Return the historical plan-next packet with ChemGate validation enabled."""

    return _core_build_plan_next_packet(
        root,
        max_suggestions=max_suggestions,
        alternative_mechanism=alternative_mechanism,
        validate_workspace=validate_ts_workspace_contract,
        supports_tsfreq_evidence=record_supports_tsfreq_reframe,
    )
