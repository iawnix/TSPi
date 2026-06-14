"""Evidence-gate checks for TS workflow claim promotion."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from transition_state_workflow.util.path_utils import clean_string


ACCEPTED_TS_REQUIRED_EVIDENCE_GATES = ("tsfreq", "connectivity")

TSFREQ_KINDS = {
    "gaussian_tsfreq_validation",
    "gaussian_tsfreq_parse",
    "gaussian_ts_freq_validation",
    "gaussian_ts_freq_parse",
    "tsfreq_validation",
    "tsfreq_summary",
}

CONNECTIVITY_KINDS = {
    "connectivity_check",
    "rmsd_connectivity_check",
    "rmsd_connectivity",
    "irc_connectivity_check",
    "mode_endpoint_connectivity",
    "endpoint_connectivity_check",
}


def accepted_ts_missing_evidence_gates(
    root: Path,
    records: list[Mapping[str, object]] | tuple[Mapping[str, object], ...],
) -> list[str]:
    """Return accepted-TS gates not supported by structured evidence records."""

    hits = accepted_ts_evidence_gate_hits(root, records)
    return [gate for gate in ACCEPTED_TS_REQUIRED_EVIDENCE_GATES if gate not in hits]


def accepted_ts_evidence_gate_hits(
    root: Path,
    records: list[Mapping[str, object]] | tuple[Mapping[str, object], ...],
) -> set[str]:
    """Return accepted-TS evidence gates supported by parsed validation payloads."""

    hits: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            continue
        if clean_string(record.get("evidence_state")) != "supports":
            continue
        payload = load_record_payload(root, record)
        if supports_tsfreq_gate(record, payload):
            hits.add("tsfreq")
        if supports_connectivity_gate(record, payload):
            hits.add("connectivity")
    return hits


def record_supports_tsfreq_reframe(root: Path, record: Mapping[str, object]) -> bool:
    """Return true when an evidence record can support TS/Freq reuse planning."""

    if clean_string(record.get("evidence_state")) != "supports":
        return False
    payload = load_record_payload(root, record)
    if supports_tsfreq_gate(record, payload):
        return True
    kind = normalized_token(record.get("kind"))
    return kind in TSFREQ_KINDS


def load_record_payload(root: Path, record: Mapping[str, object]) -> dict[str, Any]:
    """Load a JSON evidence payload when the registry path points to one."""

    path_text = clean_string(record.get("path"))
    if not path_text:
        return {}
    path = Path(path_text)
    target = path if path.is_absolute() else root / path
    if target.suffix.lower() != ".json" or not target.exists():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def supports_tsfreq_gate(record: Mapping[str, object], payload: Mapping[str, Any]) -> bool:
    """Return true only for a structured Gaussian TS/Freq validation pass."""

    kind = normalized_token(record.get("kind"))
    gate = normalized_token(record.get("validation_gate") or record.get("gate"))
    if gate and gate not in {"tsfreq", "ts_freq", "gaussian_tsfreq", "gaussian_ts_freq"}:
        return False
    if not gate and kind not in TSFREQ_KINDS:
        return False

    status = normalized_token(payload.get("status"))
    if status == "validated_ts":
        return True

    normal = bool_value(first_present(payload, "normal_termination"))
    stationary = bool_value(first_present(payload, "stationary_point_found", "stationary_point"))
    convergence = bool_value(
        first_present(
            payload,
            "final_convergence_satisfied",
            "optimization_converged",
            "converged",
        )
    )
    imaginary_count = int_value(first_present(payload, "imaginary_frequency_count", "imaginary_frequencies"))
    return normal and stationary and convergence and imaginary_count == 1


def supports_connectivity_gate(record: Mapping[str, object], payload: Mapping[str, Any]) -> bool:
    """Return true only for a structured endpoint or IRC connectivity pass."""

    kind = normalized_token(record.get("kind"))
    gate = normalized_token(record.get("validation_gate") or record.get("gate"))
    if gate and gate not in {"connectivity", "endpoint_connectivity", "irc_connectivity", "mode_endpoint_connectivity"}:
        return False
    if not gate and kind not in CONNECTIVITY_KINDS:
        return False

    decision = normalized_token(payload.get("decision"))
    supported = bool_value(first_present(payload, "connectivity_supported", "connected", "passed"))
    selected = payload.get("selected_assignment")
    if isinstance(selected, Mapping):
        supported = supported or bool_value(selected.get("passed"))
    return decision in {"connected", "endpoint_connected", "irc_connected"} or supported


def first_present(payload: Mapping[str, Any], *keys: str) -> Any:
    """Return the first present value from payload, preserving false-like values."""

    for key in keys:
        if key in payload:
            return payload[key]
    return None


def bool_value(value: Any) -> bool:
    """Interpret simple validation booleans without treating arbitrary text as true."""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "pass", "passed", "connected", "validated_ts"}
    return False


def int_value(value: Any) -> int | None:
    """Interpret an integer or list count for validation summaries."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def normalized_token(value: object) -> str:
    """Normalize registry text for exact-kind comparisons."""

    return clean_string(value).lower().replace("-", "_").replace("/", "_")
