"""Acceptance history and currentness for the research kernel."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from ts_agent.validation.registry import load_acceptance_profile

from ts_agent.io import read_json, sha256_json
from .refs import finding_sort_key, validation_spec_sort_key
from .state import (
    CLAIMS_FILE,
    FINDINGS_FILE,
    VALIDATION_RESULTS_FILE,
    VALIDATION_SPECS_FILE,
)


class AcceptanceError(ValueError):
    """Raised when an acceptance record cannot be resolved safely."""


def acceptance_policy_violations(
    *,
    claim_snapshot: dict[str, Any],
    profile: dict[str, Any],
    specs: Iterable[dict[str, Any]],
    results: Iterable[dict[str, Any]],
    findings: Iterable[dict[str, Any]],
) -> list[tuple[str, str]]:
    """Evaluate profile policy without conflating it with record currentness."""

    selected_specs = list(specs)
    selected_results = list(results)
    snapshot_findings = list(findings)
    violations: list[tuple[str, str]] = []
    if claim_snapshot.get("status") != "supported":
        violations.append(("acceptance_claim_not_supported", "acceptance requires a supported Claim snapshot"))
    if not selected_specs:
        violations.append(("acceptance_missing_spec", "acceptance requires at least one attached GateSpec"))

    spec_refs = {str(spec.get("spec_id")) for spec in selected_specs}
    result_by_spec: dict[str, list[dict[str, Any]]] = {}
    for result in selected_results:
        result_by_spec.setdefault(str(result.get("spec_ref")), []).append(result)
    if set(result_by_spec) != spec_refs or any(len(values) != 1 for values in result_by_spec.values()):
        violations.append(("acceptance_result_coverage", "acceptance requires exactly one result per GateSpec"))
    if any(result.get("verdict") != "pass" for result in selected_results):
        violations.append(("acceptance_nonpassing_result", "acceptance contains a non-passing ValidationResult"))

    dimensions = {str(spec.get("dimension")) for spec in selected_specs}
    missing_dimensions = sorted(set(profile.get("required_dimensions", [])) - dimensions)
    if missing_dimensions:
        violations.append(
            (
                "acceptance_missing_dimension",
                "acceptance is missing required dimensions: " + ", ".join(missing_dimensions),
            )
        )

    blocked_severities = set(profile.get("block_on_open_finding_severity", []))
    blockers = sorted(
        (
            str(finding.get("finding_id"))
            for finding in snapshot_findings
            if finding.get("status") == "open" and finding.get("severity") in blocked_severities
        ),
        key=finding_sort_key,
    )
    if blockers:
        violations.append(
            (
                "acceptance_blocking_finding",
                "acceptance has unresolved blocking Findings: " + ", ".join(blockers),
            )
        )
    return violations


def latest_results_for_specs(
    spec_refs: Iterable[str],
    results: Mapping[str, dict[str, Any]] | Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the last registered ValidationResult for every requested GateSpec."""

    ordered_results = list(results.values()) if isinstance(results, Mapping) else list(results)
    latest: dict[str, dict[str, Any]] = {}
    requested = list(spec_refs)
    requested_set = set(requested)
    for result in ordered_results:
        spec_ref = result.get("spec_ref") if isinstance(result, dict) else None
        if spec_ref in requested_set:
            latest[str(spec_ref)] = result
    missing = [spec_ref for spec_ref in requested if spec_ref not in latest]
    if missing:
        raise AcceptanceError("no ValidationResult for GateSpec: " + ", ".join(missing))
    return [latest[spec_ref] for spec_ref in requested]


def relevant_findings(
    claim_ref: str,
    findings: Mapping[str, dict[str, Any]] | Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the canonical, deterministically ordered Finding snapshot for a Claim."""

    rows = findings.values() if isinstance(findings, Mapping) else findings
    return sorted(
        (
            deepcopy(finding)
            for finding in rows
            if isinstance(finding, dict) and claim_ref in finding.get("claim_refs", [])
        ),
        key=lambda item: finding_sort_key(str(item["finding_id"])),
    )


def acceptance_currentness(
    record: dict[str, Any],
    *,
    claims: Mapping[str, dict[str, Any]],
    specs: Mapping[str, dict[str, Any]],
    results: Mapping[str, dict[str, Any]] | Iterable[dict[str, Any]],
    findings: Mapping[str, dict[str, Any]] | Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Compare one immutable acceptance snapshot with current canonical science."""

    reasons: list[str] = []
    digest_input = dict(record)
    acceptance_digest = digest_input.pop("acceptance_digest", None)
    if acceptance_digest != sha256_json(digest_input):
        reasons.append("acceptance_record_changed")
    claim_ref = str(record.get("claim_ref") or "")
    claim = claims.get(claim_ref)
    if claim is None:
        reasons.append("claim_missing")
    elif record.get("claim_digest") != sha256_json(claim):
        reasons.append("claim_snapshot_changed")

    profile = None
    profile_ref = record.get("profile_ref")
    if not isinstance(profile_ref, dict):
        reasons.append("profile_unavailable")
    else:
        try:
            profile = load_acceptance_profile(str(profile_ref.get("profile_id")), str(profile_ref.get("version")))
        except Exception:
            reasons.append("profile_unavailable")
        else:
            if record.get("profile_digest") != sha256_json(profile):
                reasons.append("profile_digest_changed")

    selected_spec_refs = _string_list(record.get("validation_spec_refs"))
    attached_spec_refs = sorted(
        (spec_id for spec_id, spec in specs.items() if spec.get("target_claim_ref") == claim_ref),
        key=validation_spec_sort_key,
    )
    if profile is not None and profile.get("require_all_attached_specs") is True:
        if selected_spec_refs != attached_spec_refs:
            reasons.append("attached_specs_changed")
    elif any(spec_ref not in attached_spec_refs for spec_ref in selected_spec_refs):
        reasons.append("attached_specs_changed")

    spec_digests = record.get("validation_spec_digests")
    if not isinstance(spec_digests, dict) or any(
        spec_ref not in specs or spec_digests.get(spec_ref) != sha256_json(specs[spec_ref])
        for spec_ref in selected_spec_refs
    ):
        reasons.append("validation_spec_changed")

    try:
        latest_results = latest_results_for_specs(selected_spec_refs, results)
    except AcceptanceError:
        latest_results = []
        reasons.append("latest_results_changed")
    else:
        latest_refs = [str(result["result_id"]) for result in latest_results]
        if latest_refs != _string_list(record.get("validation_result_refs")):
            reasons.append("latest_results_changed")
        result_digests = record.get("validation_result_digests")
        if not isinstance(result_digests, dict) or any(
            result_digests.get(str(result["result_id"])) != sha256_json(result)
            for result in latest_results
        ):
            reasons.append("validation_result_changed")

    current_findings = relevant_findings(claim_ref, findings)
    if record.get("finding_snapshot_digest") != sha256_json(current_findings):
        reasons.append("finding_snapshot_changed")

    canonical_reasons = list(dict.fromkeys(reasons))
    return {"current": not canonical_reasons, "stale_reasons": canonical_reasons}


def project_acceptances(
    root: str | Path,
    refs: Iterable[str],
    documents: Mapping[str, dict[str, Any]],
    *,
    include_snapshots: bool = False,
) -> list[dict[str, Any]]:
    """Read acceptance history and attach derived currentness without mutating it."""

    root_path = Path(root).expanduser().resolve()
    claims = _record_map(documents[CLAIMS_FILE].get("claims"), "claim_id")
    specs = _record_map(documents[VALIDATION_SPECS_FILE].get("specs"), "spec_id")
    result_rows = _records(documents[VALIDATION_RESULTS_FILE].get("results"))
    results = _record_map(result_rows, "result_id")
    findings = _record_map(documents[FINDINGS_FILE].get("findings"), "finding_id")
    projections: list[dict[str, Any]] = []
    for ref in refs:
        path = acceptance_path(root_path, ref)
        record = read_json(path)
        if not isinstance(record, dict):
            raise AcceptanceError(f"acceptance record is not an object: {ref}")
        currentness = acceptance_currentness(
            record,
            claims=claims,
            specs=specs,
            results=result_rows,
            findings=findings,
        )
        if include_snapshots:
            projection = deepcopy(record)
        else:
            projection = {
                key: deepcopy(record.get(key))
                for key in (
                    "schema_version",
                    "acceptance_id",
                    "claim_ref",
                    "profile_ref",
                    "validation_spec_refs",
                    "validation_result_refs",
                    "summary",
                    "decision_id",
                    "accepted_at",
                    "acceptance_digest",
                )
            }
            projection["finding_refs"] = [
                str(item.get("finding_id"))
                for item in record.get("finding_snapshot", [])
                if isinstance(item, dict) and isinstance(item.get("finding_id"), str)
            ]
        projections.append({**projection, "ref": ref, **currentness})
    return projections


def acceptance_path(root: Path, ref: Any) -> Path:
    """Resolve one canonical acceptance ref without accepting traversal or symlinks."""

    if not isinstance(ref, str) or re.fullmatch(r"acceptances/acc_[1-9][0-9]*\.json", ref) is None:
        raise AcceptanceError(f"invalid acceptance ref: {ref!r}")
    expected_parent = root / "acceptances"
    candidate = root / ref
    if expected_parent.is_symlink() or candidate.is_symlink() or not candidate.is_file():
        raise AcceptanceError(f"invalid acceptance artifact: {ref}")
    path = candidate.resolve()
    if path.parent != expected_parent.resolve():
        raise AcceptanceError(f"invalid acceptance artifact: {ref}")
    return path


def _record_map(value: Any, key: str) -> dict[str, dict[str, Any]]:
    return {
        str(item[key]): item
        for item in _records(value)
        if isinstance(item.get(key), str)
    }


def _records(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []
