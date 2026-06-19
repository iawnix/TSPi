"""Evidence-gate checks shared by reports and validators."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
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


def accepted_ts_supporting_evidence_records(
    records: Sequence[Mapping[str, object]],
    *,
    node_id: str,
    node_payload: Mapping[str, object] | None = None,
    input_refs_by_node: Mapping[str, Sequence[str]] | None = None,
) -> list[Mapping[str, object]]:
    """Return records explicitly bound to one accepted-TS audit decision.

    Direct records on the audit node remain valid, but accepted audit nodes may
    also bind already-validated TS/Freq and connectivity evidence through their
    decision-card evidence refs or explicit input refs. Parent lineage is not
    traversed here: an accepted audit must state which evidence or dependency
    nodes it is using.
    """

    node_payload = node_payload or {}
    input_refs_by_node = input_refs_by_node or {}
    records_by_id: dict[str, Mapping[str, object]] = {}
    selected: list[Mapping[str, object]] = []
    selected_ids: set[str] = set()

    def add(record: Mapping[str, object]) -> None:
        evidence_id = clean_string(record.get("evidence_id"))
        key = evidence_id or f"record:{id(record)}"
        if key in selected_ids:
            return
        selected_ids.add(key)
        selected.append(record)

    for record in records:
        if not isinstance(record, Mapping):
            continue
        evidence_id = clean_string(record.get("evidence_id"))
        if evidence_id:
            records_by_id[evidence_id] = record
        if clean_string(record.get("node_id")) == node_id:
            add(record)

    for evidence_ref in evidence_refs_from_node_payload(node_payload):
        record = records_by_id.get(evidence_ref)
        if record is not None:
            add(record)

    dependency_nodes = accepted_ts_dependency_node_ids(
        node_id=node_id,
        node_payload=node_payload,
        input_refs_by_node=input_refs_by_node,
    )
    for record in records:
        if isinstance(record, Mapping) and clean_string(record.get("node_id")) in dependency_nodes:
            add(record)
    return selected


def accepted_ts_dependency_node_ids(
    *,
    node_id: str,
    node_payload: Mapping[str, object],
    input_refs_by_node: Mapping[str, Sequence[str]],
) -> set[str]:
    """Return explicit dependency nodes for an accepted audit node."""

    out: set[str] = set()
    seen = {node_id}
    stack = [
        *input_refs_from_node_payload(node_payload),
        *[clean_string(item) for item in input_refs_by_node.get(node_id, ()) if clean_string(item)],
    ]
    while stack:
        current = clean_string(stack.pop())
        if not current or current in seen:
            continue
        seen.add(current)
        out.add(current)
        stack.extend(clean_string(item) for item in input_refs_by_node.get(current, ()) if clean_string(item))
    return out


def evidence_refs_from_node_payload(node_payload: Mapping[str, object]) -> set[str]:
    """Collect evidence ids cited by a node's decision or closure records."""

    refs: set[str] = set()
    collect_evidence_refs(node_payload.get("decision_provenance"), refs)
    collect_evidence_refs(node_payload.get("closure_explanation"), refs)
    collect_evidence_refs(node_payload, refs)
    return refs


def collect_evidence_refs(value: object, refs: set[str]) -> None:
    """Collect scalar or list evidence refs from nested JSON-like values."""

    if isinstance(value, Mapping):
        scalar = clean_string(value.get("evidence_ref"))
        if scalar:
            refs.add(scalar)
        raw_refs = value.get("evidence_refs")
        if isinstance(raw_refs, Sequence) and not isinstance(raw_refs, (str, bytes)):
            for item in raw_refs:
                ref = clean_string(item)
                if ref:
                    refs.add(ref)
        for child in value.values():
            collect_evidence_refs(child, refs)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            collect_evidence_refs(child, refs)


def input_refs_from_node_payload(node_payload: Mapping[str, object]) -> list[str]:
    """Return explicit input refs from public node state and decision provenance."""

    refs: list[str] = []
    add_input_refs(node_payload.get("input_refs"), refs)
    provenance = node_payload.get("decision_provenance")
    if isinstance(provenance, Mapping):
        add_input_refs(provenance.get("input_refs"), refs)
    return refs


def add_input_refs(raw_refs: object, refs: list[str]) -> None:
    if not isinstance(raw_refs, Sequence) or isinstance(raw_refs, (str, bytes)):
        return
    for item in raw_refs:
        ref = clean_string(item)
        if ref and ref not in refs:
            refs.append(ref)


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
