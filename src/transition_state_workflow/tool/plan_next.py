"""Compatibility wrapper for ChemKernel planning packets.

Use :mod:`transition_state_workflow.core.plan_next` for new imports. This
legacy module injects the current ChemGate validator and evidence predicate so
the public CLI behavior stays unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from transition_state_workflow.core.plan_next import *  # noqa: F401,F403
from transition_state_workflow.core.plan_next import build_plan_next_packet as _core_build_plan_next_packet
from transition_state_workflow.gate.evidence import (
    TSFREQ_KINDS,
    load_record_payload,
    normalized_token,
    supports_tsfreq_gate,
)
from transition_state_workflow.gate.validate import validate_ts_workspace_contract
from transition_state_workflow.util.path_utils import clean_string


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


def record_supports_tsfreq_reframe(root: Path, record: Mapping[str, object]) -> bool:
    """Return true when an evidence record can support TS/Freq reuse planning."""

    if clean_string(record.get("evidence_state")) != "supports":
        return False
    payload = load_record_payload(root, record)
    if supports_tsfreq_gate(record, payload):
        return True
    kind = normalized_token(record.get("kind"))
    return kind in TSFREQ_KINDS
