"""Evidence-gate checks shared by finalizers and validators."""

from __future__ import annotations

from typing import Any


class EvidenceGateError(ValueError):
    """Raised when evidence cannot satisfy a workflow gate."""


def accepted_gate_evidence(evidence_records: list[Any], evidence_refs: list[str]) -> dict[str, Any]:
    """Return required accepted-TS gate evidence records.

    The accepted-TS gate is intentionally stricter than evidence-role presence:
    TS/Freq and connectivity records must both exist and must share one
    hypothesis id. Strict IRC completeness is checked separately so callers can
    report hypothesis mismatches first.
    """

    allowed_refs = set(evidence_refs)
    gate_evidence: dict[str, Any] = {}
    gate_hypothesis_ids: set[str] = set()
    for entry in evidence_records:
        if not isinstance(entry, dict):
            continue
        evidence_id = entry.get("evidence_id")
        role = entry.get("role")
        if evidence_id in allowed_refs and role in {"connectivity_gate", "tsfreq_gate"}:
            gate_evidence[role] = entry
            quality = entry.get("quality") if isinstance(entry.get("quality"), dict) else {}
            hypothesis_id = quality.get("hypothesis_id")
            if not hypothesis_id:
                raise EvidenceGateError(f"accepted audit gate evidence missing quality.hypothesis_id: {evidence_id}")
            gate_hypothesis_ids.add(str(hypothesis_id))
    missing_gates = sorted({"connectivity_gate", "tsfreq_gate"} - set(gate_evidence))
    if missing_gates:
        raise EvidenceGateError(f"accepted audit missing required evidence gates: {', '.join(missing_gates)}")
    if len(gate_hypothesis_ids) != 1:
        raise EvidenceGateError("accepted audit gate evidence must share one hypothesis_id")
    gate_evidence["__hypothesis_id"] = next(iter(gate_hypothesis_ids))
    return gate_evidence


def validate_strict_connectivity_gate(connectivity_gate: dict[str, Any]) -> None:
    """Require normal-terminated bidirectional IRC evidence for acceptance.

    Endpoint optimization after an IRC program failure is useful diagnostic
    evidence, but it must not satisfy accepted-TS or accepted-pathway gates.
    """

    evidence_id = str(connectivity_gate.get("evidence_id") or "<unknown>")
    quality = connectivity_gate.get("quality") if isinstance(connectivity_gate.get("quality"), dict) else {}
    if quality.get("strict_irc_complete") is not True:
        raise EvidenceGateError(
            f"accepted audit connectivity_gate requires quality.strict_irc_complete=true: {evidence_id}"
        )

    failures = quality.get("irc_program_failures", [])
    if failures:
        raise EvidenceGateError(f"accepted audit connectivity_gate has unresolved IRC program failures: {evidence_id}")

    directions = quality.get("irc_directions")
    if not isinstance(directions, dict):
        raise EvidenceGateError(f"accepted audit connectivity_gate requires quality.irc_directions: {evidence_id}")

    for direction in ("forward", "reverse"):
        status = directions.get(direction)
        if not isinstance(status, dict):
            raise EvidenceGateError(
                f"accepted audit connectivity_gate requires {direction} IRC direction status: {evidence_id}"
            )
        if status.get("normal_termination") is not True:
            raise EvidenceGateError(
                f"accepted audit connectivity_gate requires normal-terminated {direction} IRC: {evidence_id}"
            )
        if str(status.get("assignment") or "").strip() == "":
            raise EvidenceGateError(
                f"accepted audit connectivity_gate requires {direction} endpoint assignment: {evidence_id}"
            )


def strict_connectivity_diagnostic(connectivity_gate: dict[str, Any]) -> str | None:
    try:
        validate_strict_connectivity_gate(connectivity_gate)
    except EvidenceGateError as exc:
        return str(exc)
    return None
