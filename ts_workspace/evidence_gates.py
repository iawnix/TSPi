"""Evidence-gate checks shared by finalizers and validators."""

from __future__ import annotations

from typing import Any


class EvidenceGateError(ValueError):
    """Raised when evidence cannot satisfy a workflow gate."""


BASE_ACCEPTED_GATE_ROLES = {"connectivity_gate", "tsfreq_gate"}
STEREOCHEMICAL_GATE_ROLE = "stereochemical_connectivity_gate"
PATHWAY_AUDIT_GATE_ROLE = "pathway_audit_summary"
MECHANISM_REFLECTION_GATE_ROLES = {
    "endpoint_identity_gate",
    "intermediate_identity_gate",
    "electronic_structure_gate",
    "state_character_gate",
    "shared_basin_consistency_gate",
}
MACHINE_GATE_ROLES = (
    BASE_ACCEPTED_GATE_ROLES
    | {STEREOCHEMICAL_GATE_ROLE, PATHWAY_AUDIT_GATE_ROLE}
    | MECHANISM_REFLECTION_GATE_ROLES
)


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


def mechanism_reflection_required_roles(
    hypothesis: dict[str, Any] | None,
    *,
    include_shared_basin: bool = True,
) -> set[str]:
    """Return declared mechanism-reflection gates for a hypothesis.

    The validator only enforces claims the agent declared. It does not infer
    that a chemical label such as "carbene" is true; it checks that declared
    electronic/identity/state/shared-basin claims have corresponding evidence
    gates before accepted/pathway audit language is allowed.
    """

    if not isinstance(hypothesis, dict):
        return set()
    roles: set[str] = set()
    roles.update(_mechanism_roles_from_values(hypothesis.get("required_evidence")))
    for prediction in hypothesis.get("testable_predictions", []):
        if not isinstance(prediction, dict):
            continue
        roles.update(_mechanism_roles_from_values(prediction.get("required_evidence_roles")))

    for claim in _mechanism_claims(hypothesis):
        roles.update(_mechanism_roles_from_values(claim.get("required_evidence_roles")))
        claim_type = _normalized(claim.get("claim_type") or claim.get("type") or claim.get("kind"))
        subject_type = _normalized(claim.get("subject_type") or claim.get("subject_kind"))
        if claim_type in {"endpoint_identity", "endpoint_identity_claim"} or subject_type == "endpoint":
            roles.add("endpoint_identity_gate")
        if claim_type in {"intermediate_identity", "intermediate_identity_claim"} or subject_type == "intermediate":
            roles.add("intermediate_identity_gate")
        if claim_type in {
            "electronic_structure",
            "electron_transfer",
            "charge_transfer",
            "radical",
            "diradical",
            "open_shell",
            "oxidation_state",
            "non_innocent_ligand",
            "carbene",
            "nitrene",
            "oxene",
            "zwitterion",
            "ion_pair",
        }:
            roles.add("electronic_structure_gate")
        if claim_type in {"state_character", "excited_state", "spin_state", "spin_surface", "broken_symmetry"}:
            roles.add("state_character_gate")
        if claim.get("shared_basin_required") is True or claim_type == "shared_basin_consistency":
            roles.add("shared_basin_consistency_gate")

    if not include_shared_basin:
        roles.discard("shared_basin_consistency_gate")
    return roles


def mechanism_reflection_gate_evidence(
    evidence_records: list[Any],
    evidence_refs: list[str],
    required_roles: set[str],
) -> dict[str, Any]:
    """Return evidence records satisfying declared mechanism-reflection roles."""

    allowed_refs = set(evidence_refs)
    required = set(required_roles) & MECHANISM_REFLECTION_GATE_ROLES
    gate_evidence: dict[str, Any] = {}
    gate_hypothesis_ids: set[str] = set()
    for role in sorted(required):
        for entry in evidence_records:
            if not isinstance(entry, dict):
                continue
            if entry.get("evidence_id") not in allowed_refs:
                continue
            if not _record_satisfies_mechanism_role(entry, role):
                continue
            gate_evidence[role] = entry
            quality = entry.get("quality") if isinstance(entry.get("quality"), dict) else {}
            hypothesis_id = quality.get("hypothesis_id")
            if not hypothesis_id:
                raise EvidenceGateError(
                    f"mechanism reflection gate evidence missing quality.hypothesis_id: {entry.get('evidence_id')}"
                )
            gate_hypothesis_ids.add(str(hypothesis_id))
            break

    missing = sorted(required - set(gate_evidence))
    if missing:
        raise EvidenceGateError(f"missing required mechanism reflection gates: {', '.join(missing)}")
    if required and len(gate_hypothesis_ids) != 1:
        raise EvidenceGateError("mechanism reflection gate evidence must share one hypothesis_id")
    if gate_hypothesis_ids:
        gate_evidence["__hypothesis_id"] = next(iter(gate_hypothesis_ids))
    return gate_evidence


def validate_mechanism_reflection_gate(record: dict[str, Any], role: str) -> None:
    """Require a completed current-node diagnostic for a mechanism claim gate."""

    evidence_id = str(record.get("evidence_id") or "<unknown>")
    if record.get("normal_termination") is not True:
        raise EvidenceGateError(f"{role} requires normal_termination=true: {evidence_id}")
    quality = record.get("quality") if isinstance(record.get("quality"), dict) else {}
    pending_key = role.replace("_gate", "_gate_pending")
    if quality.get(pending_key) is True:
        raise EvidenceGateError(f"{role} is still pending: {evidence_id}")


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


def gate_artifact_metadata_diagnostic(record: dict[str, Any]) -> str | None:
    role = record.get("role")
    if role not in MACHINE_GATE_ROLES:
        return None
    evidence_id = str(record.get("evidence_id") or "<unknown>")
    source_files = record.get("source_files")
    if not isinstance(source_files, list) or not source_files or not all(_nonempty_string(item) for item in source_files):
        return f"gate evidence requires non-empty source_files: {evidence_id}"
    source_sha256 = record.get("source_sha256")
    if not _nonempty_string(source_sha256):
        return f"gate evidence requires source_sha256: {evidence_id}"
    for field in ("parser_name", "parser_version"):
        if not _nonempty_string(record.get(field)):
            return f"gate evidence requires {field}: {evidence_id}"
    if not isinstance(record.get("normal_termination"), bool):
        return f"gate evidence requires boolean normal_termination: {evidence_id}"
    diagnostics = record.get("diagnostics")
    if diagnostics is not None and not isinstance(diagnostics, list):
        return f"gate evidence diagnostics must be a list: {evidence_id}"
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


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _mechanism_roles_from_values(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if str(item) in MECHANISM_REFLECTION_GATE_ROLES}


def _mechanism_claims(hypothesis: dict[str, Any]) -> list[dict[str, Any]]:
    claims = hypothesis.get("mechanism_claims")
    if not isinstance(claims, list):
        structured = hypothesis.get("structured_claim") if isinstance(hypothesis.get("structured_claim"), dict) else {}
        claims = structured.get("mechanism_claims") if isinstance(structured.get("mechanism_claims"), list) else []
    return [claim for claim in claims if isinstance(claim, dict)]


def _record_satisfies_mechanism_role(record: dict[str, Any], role: str) -> bool:
    if record.get("role") == role:
        return True
    quality = record.get("quality") if isinstance(record.get("quality"), dict) else {}
    completed_key = role.replace("_gate", "_gate_completed")
    supported_key = role.replace("_gate", "_gate_supported")
    return quality.get(completed_key) is True or quality.get(supported_key) is True


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
