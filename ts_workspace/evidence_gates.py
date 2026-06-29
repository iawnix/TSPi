"""Evidence-gate checks shared by finalizers and validators."""

from __future__ import annotations

from typing import Any


class EvidenceGateError(ValueError):
    """Raised when evidence cannot satisfy a workflow gate."""


BASE_ACCEPTED_GATE_ROLES = {"connectivity_gate", "tsfreq_gate"}
STEREOCHEMICAL_GATE_ROLE = "stereochemical_connectivity_gate"


def accepted_gate_evidence(
    evidence_records: list[Any],
    evidence_refs: list[str],
    *,
    require_stereochemical_gate: bool = False,
) -> dict[str, Any]:
    """Return required accepted-TS gate evidence records.

    The accepted-TS gate is intentionally stricter than evidence-role presence:
    TS/Freq and connectivity records must both exist and must share one
    hypothesis id. Strict IRC completeness is checked separately so callers can
    report hypothesis mismatches first.
    """

    allowed_refs = set(evidence_refs)
    recognized_roles = set(BASE_ACCEPTED_GATE_ROLES)
    recognized_roles.add(STEREOCHEMICAL_GATE_ROLE)
    gate_evidence: dict[str, Any] = {}
    gate_hypothesis_ids: set[str] = set()
    for entry in evidence_records:
        if not isinstance(entry, dict):
            continue
        evidence_id = entry.get("evidence_id")
        role = entry.get("role")
        if evidence_id in allowed_refs and role in recognized_roles:
            gate_evidence[role] = entry
            quality = entry.get("quality") if isinstance(entry.get("quality"), dict) else {}
            hypothesis_id = quality.get("hypothesis_id")
            if not hypothesis_id:
                raise EvidenceGateError(f"accepted audit gate evidence missing quality.hypothesis_id: {evidence_id}")
            gate_hypothesis_ids.add(str(hypothesis_id))
    required_roles = set(BASE_ACCEPTED_GATE_ROLES)
    if require_stereochemical_gate:
        required_roles.add(STEREOCHEMICAL_GATE_ROLE)
    missing_gates = sorted(required_roles - set(gate_evidence))
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


def hypothesis_requires_stereochemical_gate(hypothesis: dict[str, Any] | None) -> bool:
    """Return whether accepted TS audit needs an explicit stereochemical gate."""

    if not isinstance(hypothesis, dict):
        return False
    required = hypothesis.get("required_evidence")
    if isinstance(required, list) and STEREOCHEMICAL_GATE_ROLE in {str(item) for item in required}:
        return True
    for prediction in hypothesis.get("testable_predictions", []):
        if not isinstance(prediction, dict):
            continue
        roles = prediction.get("required_evidence_roles")
        if isinstance(roles, list) and STEREOCHEMICAL_GATE_ROLE in {str(item) for item in roles}:
            return True
    claim = hypothesis.get("structured_claim")
    if not isinstance(claim, dict):
        return False
    for key in (
        "stereochemical_policy",
        "stereochemical_requirements",
        "stereochemical_checks",
        "stereochemistry",
        "stereo",
    ):
        if _meaningful_stereo_value(claim.get(key)):
            return True
    return False


def validate_stereochemical_connectivity_gate(stereo_gate: dict[str, Any]) -> None:
    evidence_id = str(stereo_gate.get("evidence_id") or "<unknown>")
    quality = stereo_gate.get("quality") if isinstance(stereo_gate.get("quality"), dict) else {}
    diagnostics = stereo_gate.get("diagnostics")
    if diagnostics:
        raise EvidenceGateError(f"accepted audit stereochemical gate has diagnostics: {evidence_id}")
    verdict = str(quality.get("stereochemical_verdict") or "").strip().lower()
    matched = quality.get("stereochemistry_matched")
    if matched is not True and verdict not in {"matched", "supported"}:
        raise EvidenceGateError(
            "accepted audit stereochemical_connectivity_gate requires "
            f"quality.stereochemistry_matched=true or quality.stereochemical_verdict=matched: {evidence_id}"
        )
    mismatches = quality.get("stereochemical_mismatches", [])
    if mismatches:
        raise EvidenceGateError(f"accepted audit stereochemical gate has mismatches: {evidence_id}")
    checks = quality.get("stereochemical_checks", [])
    if isinstance(checks, list):
        for index, check in enumerate(checks):
            if not isinstance(check, dict):
                continue
            if str(check.get("verdict") or "").strip().lower() not in {"", "matched", "supported"}:
                raise EvidenceGateError(
                    f"accepted audit stereochemical gate failed check {index}: {evidence_id}"
                )


def stereochemical_gate_diagnostic(stereo_gate: dict[str, Any]) -> str | None:
    try:
        validate_stereochemical_connectivity_gate(stereo_gate)
    except EvidenceGateError as exc:
        return str(exc)
    return None


def _meaningful_stereo_value(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {
            "",
            "none",
            "not_applicable",
            "not applicable",
            "n/a",
            "na",
            "unspecified",
            "not_required",
            "not required",
            "unknown",
        }
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True
