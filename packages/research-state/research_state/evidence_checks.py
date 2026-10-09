"""Receipt and criterion evidence shared by Requirements and Gates.

These checks establish what ran, which material it used, and whether a registered
validator passed. Scientific interpretation remains an explicit Agent assessment.
"""
from __future__ import annotations

import json
import re

from .assessments import assessment_current, bind_evidence


def read_result(root, context, ref, *, label="evidence"):
    if not isinstance(ref, str) or not re.fullmatch(r"result_[0-9a-f]{64}", ref):
        raise ValueError(label + "_result_receipt_required")
    path = root / "operations/results" / (ref + ".json")
    try:
        if path.is_symlink():
            raise ValueError("symbolic result receipt")
        receipt = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(label + "_result_missing: collect the actual Job") from exc
    attempt = next((row for row in context["attempts"] if row["id"] == receipt.get("attempt_id")), None)
    metadata = (attempt or {}).get("metadata", {})
    if (receipt.get("schema_version") != "job-result/1" or receipt.get("receipt_id") != ref
            or receipt.get("workspace_id") != context["workspace_id"] or not attempt
            or receipt.get("job_id") != metadata.get("job_id")
            or metadata.get("latest_result_receipt_ref") != ref or metadata.get("execution_conflict")):
        raise ValueError(label + "_result_receipt_stale: collect or reconcile current evidence")
    return receipt, attempt


def machine_check(root, context, criterion, ref=None, *, label="evidence", evidence_refs=()):
    """Derive the machine verdict and bind every validator input, including files.

    Callers select the scope and candidate receipts. They cannot replace this
    verdict with a model-supplied value or accept a failed validator execution.
    """
    if criterion["source_type"] == "runtime_fact" and criterion.get("fact") == "artifacts_registered":
        artifacts = {row["id"] for row in context["artifacts"]}
        passed = bool(evidence_refs) and all(ref in artifacts for ref in evidence_refs)
        basis = bind_evidence(root, context, list(evidence_refs), "")
        return {"verdict": "pass" if passed else "inconclusive", "receipt": None, "attempt": None,
                "bindings": {}, "evidence_basis": basis, "execution_platforms": {}}
    receipt, attempt = read_result(root, context, ref, label=label)
    basis = bind_evidence(root, context, receipt.get("artifact_refs", []), "")
    basis["result_versions"][attempt["id"]] = ref
    metadata = attempt.get("metadata", {}).get("job_metadata", {})
    input_basis = metadata.get("input_evidence_basis")
    if input_basis is not None:
        if not assessment_current(context, {"evidence_basis": input_basis}):
            raise ValueError(label + "_input_evidence_stale")
        # Check physical content too; a changed input cannot retain an earlier
        # acceptance merely because its registered digest was not updated.
        bind_evidence(root, context, metadata.get("input_artifact_ids", []), "")
        for field, values in input_basis.items():
            basis[field].update(values)
    bindings, producer_platforms = {}, {}
    if criterion["source_type"] == "runtime_fact":
        if criterion.get("fact") == "execution_succeeded":
            verdict = "pass" if receipt.get("execution_state") == "succeeded" else "fail"
        elif criterion.get("fact") == "outputs_collected":
            verdict = "pass" if receipt.get("collection_state") == "complete" else "inconclusive"
        else:
            raise ValueError(label + "_runtime_fact_invalid")
        producer_platforms[attempt["id"]] = attempt.get("environment")
    elif criterion["source_type"] == "validator_result":
        validation = receipt.get("validator_result")
        if not validation or validation.get("id") != criterion.get("validator_id"):
            raise ValueError(label + "_validator_receipt_required")
        if validation.get("version") != criterion.get("validator_version"):
            raise ValueError(label + "_validator_version_mismatch")
        artifacts = {row["id"]: row for row in context["artifacts"]}
        for artifact_id, digest in validation.get("input_versions", {}).items():
            if artifacts.get(artifact_id, {}).get("sha256") != digest:
                raise ValueError(label + "_validator_input_stale")
        input_basis = bind_evidence(root, context, list(validation.get("input_versions", {})), "")
        for field, values in input_basis.items():
            basis[field].update(values)
        for producer_id, version in validation.get("input_result_versions", {}).items():
            producer_result, producer = read_result(root, context, version, label=label)
            if producer["id"] != producer_id:
                raise ValueError(label + "_validator_input_stale")
            if (producer_result.get("execution_state") != "succeeded"
                    or producer_result.get("collection_state") != "complete"):
                raise ValueError(label + "_validator_input_execution_incomplete")
            basis["result_versions"][producer_id] = version
            producer_platforms[producer_id] = producer.get("environment")
        bindings = validation.get("bindings", {})
        verdict = validation.get("verdict", "inconclusive")
        if receipt.get("execution_state") != "succeeded":
            verdict = "fail"
        elif receipt.get("collection_state") != "complete":
            verdict = "inconclusive"
    else:
        raise ValueError(label + "_machine_criterion_required")
    if any(bindings.get(key) != value for key, value in criterion.get("bindings", {}).items()):
        verdict = "fail"
    return {"verdict": verdict, "receipt": receipt, "attempt": attempt,
            "bindings": bindings, "evidence_basis": basis, "execution_platforms": producer_platforms}


def aggregate_verdict(verdicts):
    return ("pass" if verdicts and all(value == "pass" for value in verdicts)
            else next((value for value in ("fail", "blocked", "inconclusive") if value in verdicts), "inconclusive"))
