"""Compatibility exports for evidence-gate checks."""

from __future__ import annotations

from transition_state_workflow.base.evidence_gates import (
    ACCEPTED_TS_REQUIRED_EVIDENCE_GATES,
    CONNECTIVITY_KINDS,
    TSFREQ_KINDS,
    accepted_ts_evidence_gate_hits,
    accepted_ts_missing_evidence_gates,
    accepted_ts_supporting_evidence_records,
    record_supports_tsfreq_reframe,
    supports_connectivity_gate,
    supports_tsfreq_gate,
)

__all__ = [
    "ACCEPTED_TS_REQUIRED_EVIDENCE_GATES",
    "CONNECTIVITY_KINDS",
    "TSFREQ_KINDS",
    "accepted_ts_evidence_gate_hits",
    "accepted_ts_missing_evidence_gates",
    "accepted_ts_supporting_evidence_records",
    "record_supports_tsfreq_reframe",
    "supports_connectivity_gate",
    "supports_tsfreq_gate",
]
