"""Evidence bindings for Claim assessments, including imported research material.

These checks establish provenance and version consistency, not scientific truth.
Only the assessment currently adopted by a Claim participates in live validation.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def _fingerprint(record, fields):
    value = {key: record.get(key) for key in fields}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


FINDING_FIELDS = ("node_id", "claim_ids", "kind", "statement", "status", "source_refs",
                  "value", "datatype", "unit", "provenance", "resolution")
LINK_FIELDS = ("artifact_id", "subject_type", "subject_id", "attempt_ref", "relation", "locator")
ARTIFACT_SOURCE_FIELDS = ("location", "kind", "producer_attempt_id", "input_artifact_ids")


def gate_assessment_version(gate: dict) -> dict:
    """Bind the adopted check, including re-evaluations of unchanged criteria."""
    evaluation = (gate.get("evaluations") or [{}])[-1]
    return {"version": gate.get("version"),
            "evaluation": _fingerprint(evaluation, tuple(sorted(evaluation)))}


def bind_evidence(root: Path, context: dict, refs: list[str], claim_id: str) -> dict:
    """Resolve every cited source; a registered external Artifact needs no Job.

    Runtime outputs must belong to their producer's current collected result.
    Findings and links retain their own version as well as their source bindings.
    No single trusted ancestor can stand in for the other inputs of a derivation.
    """
    artifacts = {row["id"]: row for row in context["artifacts"]}
    findings = {row["id"]: row for row in context["findings"]}
    links = {row["id"]: row for row in context["evidence_links"]}
    attempts = {row["id"]: row for row in context["attempts"]}
    basis = {key: {} for key in ("artifact_versions", "artifact_sources", "finding_versions", "link_versions", "result_versions")}
    visiting, visited = set(), set()

    def visit(ref):
        if ref in visiting:
            raise ValueError("assessment_evidence_cycle: " + ref)
        if ref in visited:
            return
        visiting.add(ref)
        if ref in artifacts:
            artifact = artifacts[ref]
            digest = artifact.get("sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", digest):
                raise ValueError("assessment_artifact_digest_required: register the actual material with artifact_register/create")
            if artifact.get("kind") == "derivation_descriptor":
                raise ValueError("assessment_derivation_not_executed: a description of analysis is not its result")
            location = artifact.get("location")
            if not isinstance(location, str) or not location:
                raise ValueError("assessment_artifact_unavailable: register the actual material: " + ref)
            path = Path(location).expanduser()
            if not path.is_absolute():
                path = root / path
            try:
                if not path.is_file():
                    raise OSError("not a regular file")
                with path.open("rb") as stream:
                    actual_digest = hashlib.file_digest(stream, "sha256").hexdigest()
            except OSError as exc:
                raise ValueError("assessment_artifact_unavailable: register readable material: " + ref) from exc
            if actual_digest != digest.removeprefix("sha256:"):
                raise ValueError("assessment_artifact_digest_mismatch: re-register the changed material: " + ref)
            basis["artifact_versions"][ref] = digest
            basis["artifact_sources"][ref] = _fingerprint(artifact, ARTIFACT_SOURCE_FIELDS)
            producer_id = artifact.get("producer_attempt_id")
            if producer_id:
                producer = attempts.get(producer_id)
                metadata = (producer or {}).get("metadata", {})
                result_id = metadata.get("latest_result_receipt_ref")
                if (not producer or metadata.get("execution_conflict") or not isinstance(result_id, str)
                        or not re.fullmatch(r"result_[0-9a-f]{64}", result_id)):
                    raise ValueError("assessment_result_required: collect or reconcile the producing Attempt")
                receipt = json.loads((root / "operations/results" / (result_id + ".json")).read_text())
                if (receipt.get("attempt_id") != producer_id or receipt.get("job_id") != metadata.get("job_id")
                        or ref not in receipt.get("artifact_refs", [])):
                    raise ValueError("assessment_result_stale: cite material from the current collected result")
                basis["result_versions"][producer_id] = result_id
            for source in artifact.get("input_artifact_ids", []):
                visit(source)
        elif ref in findings:
            finding = findings[ref]
            if finding.get("status") == "superseded":
                raise ValueError("assessment_finding_superseded: " + ref)
            sources = finding.get("source_refs", [])
            if not sources:
                raise ValueError("assessment_finding_sources_required: cite a Finding backed by registered material")
            basis["finding_versions"][ref] = _fingerprint(finding, FINDING_FIELDS)
            for source in sources:
                visit(source)
        elif ref in links:
            link = links[ref]
            if link.get("subject_type") == "claim" and link.get("subject_id") != claim_id:
                raise ValueError("assessment_evidence_scope_mismatch: cite the material directly for a different Claim")
            basis["link_versions"][ref] = _fingerprint(link, LINK_FIELDS)
            visit(link["artifact_id"])
        else:
            raise ValueError("assessment_evidence_unknown: use registered Artifact, Finding or evidence-link IDs: " + ref)
        visiting.remove(ref)
        visited.add(ref)

    for ref in refs:
        visit(ref)
    return basis


def assessment_current(context: dict, assessment: dict) -> bool:
    basis = assessment.get("evidence_basis")
    if not isinstance(basis, dict):
        return False
    for collection, versions, fields in (
        ("artifacts", "artifact_versions", None),
        ("artifacts", "artifact_sources", ARTIFACT_SOURCE_FIELDS),
        ("findings", "finding_versions", FINDING_FIELDS),
        ("evidence_links", "link_versions", LINK_FIELDS),
    ):
        records = {row["id"]: row for row in context[collection]}
        for ref, version in basis.get(versions, {}).items():
            record = records.get(ref)
            if record is None or (record.get("sha256") if fields is None else _fingerprint(record, fields)) != version:
                return False
    attempts = {row["id"]: row for row in context["attempts"]}
    for ref, version in basis.get("result_versions", {}).items():
        metadata = attempts.get(ref, {}).get("metadata", {})
        if metadata.get("execution_conflict") or metadata.get("latest_result_receipt_ref") != version:
            return False
    gates = {row["id"]: row for row in context["gates"]}
    from .invariants import gate_evaluation_current
    bound_gates = basis.get("gate_versions", {})
    if assessment.get("verdict") == "supported":
        current_gates = {ref for ref, gate in gates.items()
                         if gate.get("scope") == "claim" and gate.get("target_id") == assessment.get("claim_id")}
        if current_gates != set(bound_gates):
            return False
    for ref, version in bound_gates.items():
        gate = gates.get(ref)
        if gate is None or gate_assessment_version(gate) != version or not gate_evaluation_current(context, gate):
            return False
    return True


def claim_review_state(context: dict, claim: dict) -> str:
    ref = claim.get("current_assessment_id")
    if not ref:
        return "not_assessed"
    assessment = next((row for row in context.get("claim_assessments", []) if row["id"] == ref), None)
    if (assessment is None or assessment.get("claim_id") != claim["id"]
            or assessment.get("verdict") != claim.get("status")):
        return "needs_review"
    return "current" if assessment_current(context, assessment) else "needs_review"
