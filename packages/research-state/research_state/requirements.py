"""Versioned user deliverables, derived coverage, and registered acceptance checks.

Profiles declare a finite set of checks, not a workflow or a model-authored DSL.
Scientific meaning remains with extension validators and the Agent's explanation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re

from .assessments import assessment_current, bind_evidence


SCHEMA_VERSION = "research-requirements/1"
PUBLIC_OPERATIONS = frozenset({"create_requirement", "bind_requirement", "revise_requirement",
                               "assess_requirement", "record_requirement_stop", "resume_requirement",
                               "review_source"})


def _digest(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                                separators=(",", ":")).encode()).hexdigest()


def _source(root, context, source_ref, quote=None):
    if not isinstance(source_ref, str) or not re.fullmatch(r"user_[0-9a-f]{64}", source_ref):
        raise ValueError("requirement_source_invalid: use a Host-recorded source_ref")
    path = root / "operations/user-inputs" / (source_ref + ".json")
    if path.is_symlink():
        raise ValueError("requirement_source_invalid: symbolic source file")
    try:
        from .sources import read_source
        source = read_source(root, source_ref)
    except (OSError, ValueError) as exc:
        raise ValueError("requirement_source_missing: read research sources") from exc
    text = source.get("text")
    if (source.get("schema_version") != "research-user-input/1" or source.get("source_ref") != source_ref
            or source.get("workspace_id") != context["workspace_id"] or source.get("role") != "user"
            or source.get("origin") != "host_user" or source.get("kind") != "user_message"
            or not isinstance(text, str) or not source.get("session_id") or not source.get("message_id")
            or source.get("sha256") != "sha256:" + hashlib.sha256(text.encode()).hexdigest()):
        raise ValueError("requirement_source_invalid: source identity or content digest differs")
    if quote is not None and (not isinstance(quote, str) or not quote.strip() or quote not in text):
        raise ValueError("requirement_source_quote_mismatch: quote the actual user input")
    return source


def acceptance_profiles():
    """Discover installed versioned profiles without importing domain code."""
    package = Path(os.environ.get("TSPI_PACKAGE_ROOT") or os.environ.get("TS_PACKAGE_ROOT")
                   or Path(__file__).resolve().parents[3]).resolve()
    core = json.loads((Path(__file__).parent / "contracts/acceptance_profiles.json").read_text())
    found = {(row["id"], row["version"]): copy.deepcopy(row) for row in core["profiles"]}
    for manifest in sorted((package / "extensions").glob("*/manifest.json")):
        extension = json.loads(manifest.read_text())
        for profile in extension.get("acceptance_profiles", []):
            key = (profile.get("id"), profile.get("version"))
            if not all(isinstance(part, str) and part for part in key) or key in found:
                raise ValueError("acceptance_profile_identity_invalid")
            checks = profile.get("checks")
            if not isinstance(checks, list) or not checks or len({row.get("id") for row in checks}) != len(checks):
                raise ValueError("acceptance_profile_checks_invalid")
            for check in checks:
                if check.get("kind") == "validator_result":
                    if not check.get("validator_id") or not check.get("validator_version"):
                        raise ValueError("acceptance_profile_validator_identity_required")
                elif check.get("kind") != "registered_artifact":
                    raise ValueError("acceptance_profile_check_not_supported")
            found[key] = copy.deepcopy(profile)
    return found


def _profile(reference):
    profile = acceptance_profiles().get((reference.get("id"), reference.get("version")))
    if profile is None:
        raise ValueError("acceptance_profile_not_registered: choose an installed, versioned extension profile")
    return profile


def _lookup(context, requirement_id):
    requirement = next((row for row in context.get("requirements", []) if row["id"] == requirement_id), None)
    if requirement is None:
        raise ValueError("requirement_unknown: " + str(requirement_id))
    return requirement


def _refs(context, collection, refs, label):
    known = {row["id"] for row in context.get(collection, [])}
    if any(ref not in known for ref in refs):
        raise ValueError(label + ": " + ", ".join(ref for ref in refs if ref not in known))


def _receipt(root, context, ref):
    if not isinstance(ref, str) or not re.fullmatch(r"result_[0-9a-f]{64}", ref):
        raise ValueError("requirement_result_reference_invalid")
    try:
        receipt = json.loads((root / "operations/results" / (ref + ".json")).read_text())
    except (OSError, ValueError) as exc:
        raise ValueError("requirement_result_missing: collect the actual Job") from exc
    attempt = next((row for row in context["attempts"] if row["id"] == receipt.get("attempt_id")), None)
    metadata = (attempt or {}).get("metadata", {})
    if (receipt.get("schema_version") != "job-result/1" or receipt.get("receipt_id") != ref
            or receipt.get("workspace_id") != context["workspace_id"] or not attempt
            or receipt.get("job_id") != metadata.get("job_id")
            or metadata.get("latest_result_receipt_ref") != ref or metadata.get("execution_conflict")):
        raise ValueError("requirement_result_stale: collect or reconcile current evidence")
    return receipt, attempt


def _source_review(context, source, requirement_id, reason):
    record = next((row for row in context.setdefault("requirement_sources", [])
                   if row["source_ref"] == source["source_ref"]), None)
    if record is None:
        raise ValueError("requirement_source_not_registered: the Host must register this input")
    if record["sha256"] != source["sha256"]:
        raise ValueError("requirement_source_changed")
    previous = record.get("review") or {}
    ids = list(previous.get("requirement_ids", []))
    if requirement_id not in ids:
        ids.append(requirement_id)
    record["review"] = {"disposition": "requirements_recorded", "requirement_ids": ids, "reason": reason,
                        "source_sha256": source["sha256"]}


def _check_constraints(profile, constraints):
    unknown = set(constraints) - set(profile.get("constraint_keys", [])) - {"platform"}
    if unknown:
        raise ValueError("requirement_constraint_not_supported: " + ", ".join(sorted(unknown)))


def _bump(requirement, reason):
    requirement.setdefault("revisions", []).append({key: copy.deepcopy(requirement.get(key)) for key in
        ("version", "statement", "constraints", "acceptance_profile", "profile_digest", "input_artifact_ids")}
        | {"reason": reason})
    requirement["version"] += 1


def apply_requirement_operation(root, context, operation, created_at):
    """Apply inside the existing State transaction and authenticated write boundary."""
    kind = operation["type"]
    for field in ("reason", "statement"):
        if field in operation and (not isinstance(operation[field], str) or not operation[field].strip()):
            raise ValueError("requirement_text_required: " + field)
    context["requirements_schema_version"] = SCHEMA_VERSION
    if kind == "register_requirement_source":
        from .write_origin import is_runtime_write
        if not is_runtime_write():
            raise ValueError("requirement_source_host_only")
        source = _source(root, context, operation.get("source_ref"))
        records = context.setdefault("requirement_sources", [])
        previous = next((row for row in records if row["source_ref"] == source["source_ref"]), None)
        record = {key: source[key] for key in ("source_ref", "sha256", "session_id", "message_id")}
        if previous is not None:
            if any(previous.get(key) != value for key, value in record.items()):
                raise ValueError("requirement_source_identity_conflict")
            return source["source_ref"]
        records.append({**record, "recorded_at": created_at, "review": None})
        return source["source_ref"]
    if kind == "review_source":
        source = _source(root, context, operation["source_ref"])
        record = next((row for row in context.get("requirement_sources", []) if row["source_ref"] == source["source_ref"]), None)
        if record is None or record["sha256"] != source["sha256"]:
            raise ValueError("requirement_source_not_registered")
        ids = operation.get("requirement_ids", [])
        for requirement_id in ids:
            requirement = _lookup(context, requirement_id)
            if requirement["source_ref"] != source["source_ref"]:
                raise ValueError("requirement_source_scope_mismatch")
        existing = [row["id"] for row in context.get("requirements", []) if row["source_ref"] == source["source_ref"]]
        if operation["disposition"] == "requirements_recorded" and (not ids or set(ids) != set(existing)):
            raise ValueError("requirement_source_coverage_incomplete: include every requirement extracted from this source")
        if operation["disposition"] == "no_new_requirements" and (existing or ids):
            raise ValueError("requirement_source_has_requirements: review cannot cancel existing obligations")
        record["review"] = {"disposition": operation["disposition"], "requirement_ids": ids,
                            "reason": operation["reason"], "source_sha256": source["sha256"]}
        return source["source_ref"]
    if kind == "create_requirement":
        requirements = context.setdefault("requirements", [])
        if any(row["id"] == operation["id"] for row in requirements):
            raise ValueError("requirement_already_exists")
        source = _source(root, context, operation["source_ref"], operation["source_quote"])
        profile = _profile(operation["acceptance_profile"])
        constraints = operation.get("constraints", {})
        _check_constraints(profile, constraints)
        inputs = operation.get("input_artifact_ids", [])
        _refs(context, "artifacts", inputs, "requirement_input_unknown")
        nodes = operation.get("node_ids", [])
        _refs(context, "nodes", nodes, "requirement_node_unknown")
        requirement = {"id": operation["id"], "version": 1, "created_at": created_at,
            "source_ref": source["source_ref"], "source_sha256": source["sha256"],
            "source_quote": operation["source_quote"], "statement": operation["statement"],
            "constraints": copy.deepcopy(constraints), "acceptance_profile": copy.deepcopy(operation["acceptance_profile"]),
            "profile": profile, "profile_digest": _digest(profile), "node_ids": list(nodes),
            "input_artifact_ids": list(inputs), "assessments": [], "stops": [], "revisions": []}
        _source_review(context, source, requirement["id"], "Requirement extracted from the quoted user request.")
        requirements.append(requirement)
        return requirement["id"]
    requirement = _lookup(context, operation["requirement_id"])
    if kind == "bind_requirement":
        nodes, inputs = operation.get("node_ids", []), operation.get("input_artifact_ids", [])
        _refs(context, "nodes", nodes, "requirement_node_unknown")
        _refs(context, "artifacts", inputs, "requirement_input_unknown")
        new_inputs = [ref for ref in inputs if ref not in requirement["input_artifact_ids"]]
        if new_inputs:
            _bump(requirement, operation["reason"])
            requirement["input_artifact_ids"].extend(new_inputs)
        requirement["node_ids"] = list(dict.fromkeys([*requirement["node_ids"], *nodes]))
        return requirement["id"]
    if kind == "revise_requirement":
        # Additive constraint refinement preserves the user's minimum. A changed
        # user request is recorded as an explicit stop and a new sourced requirement.
        additions = operation.get("constraints", {})
        _check_constraints(requirement["profile"], additions)
        if any(key in requirement["constraints"] and requirement["constraints"][key] != value
               for key, value in additions.items()):
            raise ValueError("requirement_minimum_cannot_be_weakened: preserve the original requirement; record an explicitly sourced scope change")
        if not any(key not in requirement["constraints"] for key in additions):
            raise ValueError("requirement_revision_no_change")
        _bump(requirement, operation["reason"])
        requirement["constraints"].update(copy.deepcopy(additions))
        return requirement["id"]
    if kind == "resume_requirement":
        requirement["stop_resumption"] = {"after_stop_count": len(requirement.get("stops", [])),
                                           "reason": operation["reason"], "created_at": created_at}
        return requirement["id"]
    if kind == "record_requirement_stop":
        return _record_stop(root, context, requirement, operation, created_at)
    if kind == "assess_requirement":
        return _assess(root, context, requirement, operation, created_at)
    raise ValueError("requirement_operation_unknown")


def _assess(root, context, requirement, operation, created_at):
    if any(row["id"] == operation["id"] for row in requirement["assessments"]):
        raise ValueError("requirement_assessment_already_exists")
    profile = _profile(requirement["acceptance_profile"])
    if _digest(profile) != requirement["profile_digest"]:
        raise ValueError("acceptance_profile_version_changed: installed standards must use a new version")
    receipts = [_receipt(root, context, ref)[0] for ref in operation.get("result_receipt_refs", [])]
    evidence = list(dict.fromkeys([*operation.get("evidence_refs", []), *requirement["input_artifact_ids"],
                                  *(ref for receipt in receipts for ref in receipt.get("artifact_refs", []))]))
    basis = bind_evidence(root, context, evidence, "")
    for receipt in receipts:
        basis["result_versions"][receipt["attempt_id"]] = receipt["receipt_id"]
    checks = []
    execution_platforms = {}
    required_platform = requirement["constraints"].get("platform")
    subject_key = profile.get("subject_binding")
    subjects = requirement["input_artifact_ids"] if subject_key else [None]
    if subject_key and not subjects:
        checks.append({"id": "input_binding", "satisfied": False, "reason": "Bind the actual research input Artifacts before acceptance"})
    artifacts = {row["id"]: row for row in context["artifacts"]}
    for subject in subjects:
        bound_values = {}
        for check in profile["checks"]:
            if check["kind"] == "registered_artifact":
                candidates = operation.get("evidence_refs", [])
                accepted = bool(candidates) and all(ref in artifacts for ref in candidates)
                checks.append({"id": check["id"], "subject_ref": subject, "satisfied": accepted,
                               "reason": "Registered material inspected" if accepted else "Registered material is required"})
                continue
            matches = []
            for receipt in receipts:
                validation = receipt.get("validator_result") or {}
                if (receipt.get("execution_state") != "succeeded" or receipt.get("collection_state") != "complete"
                        or validation.get("id") != check["validator_id"]
                        or validation.get("version") != check["validator_version"] or validation.get("verdict") != "pass"):
                    continue
                bindings = validation.get("bindings", {})
                if any(key not in bindings for key in profile.get("binding_keys", [])):
                    continue
                if subject is not None and (bindings.get(subject_key) != subject
                        or validation.get("input_versions", {}).get(subject) != artifacts[subject].get("sha256")):
                    continue
                if any(bindings.get(key) != value for key, value in requirement["constraints"].items() if key != "platform"):
                    continue
                if any(key in bound_values and bound_values[key] != bindings[key] for key in profile.get("binding_keys", [])):
                    continue
                # Validator inputs have their own producer/Artifact version bindings.
                if any(next((row for row in context["attempts"] if row["id"] == attempt), {}).get("metadata", {}).get("latest_result_receipt_ref") != version
                       for attempt, version in validation.get("input_result_versions", {}).items()):
                    continue
                if any(artifacts.get(ref, {}).get("sha256") != digest for ref, digest in validation.get("input_versions", {}).items()):
                    continue
                producer_platforms = {attempt: next((row for row in context["attempts"] if row["id"] == attempt), {}).get("environment")
                                      for attempt in validation.get("input_result_versions", {})}
                if required_platform is not None and any(value != required_platform for value in producer_platforms.values()):
                    continue
                matches.append(receipt["receipt_id"])
                basis["artifact_versions"].update(validation.get("input_versions", {}))
                basis["result_versions"].update(validation.get("input_result_versions", {}))
                if required_platform is not None:
                    execution_platforms.update(producer_platforms)
                bound_values.update({key: bindings[key] for key in profile.get("binding_keys", [])})
            checks.append({"id": check["id"], "subject_ref": subject, "satisfied": bool(matches),
                           "result_receipt_refs": matches,
                           "reason": "Current matching validator evidence" if matches else "Missing a passing validator result bound to this input and its constraints"})
    if required_platform is not None:
        checks.append({"id": "execution_platform", "satisfied": bool(execution_platforms),
                       "reason": "Actual scientific producer platforms match" if execution_platforms else "No matching scientific producer platform evidence"})
    requirement["assessments"].append({"id": operation["id"], "requirement_version": requirement["version"],
        "profile_digest": requirement["profile_digest"], "created_at": created_at, "reason": operation["reason"],
        "evidence_refs": operation.get("evidence_refs", []), "result_receipt_refs": operation.get("result_receipt_refs", []),
        "checks": checks, "evidence_basis": basis, "execution_platforms": execution_platforms})
    return operation["id"]


def _record_stop(root, context, requirement, operation, created_at):
    if any(row["id"] == operation["id"] for row in requirement["stops"]):
        raise ValueError("requirement_stop_already_exists")
    active = [row["id"] for row in context["attempts"] if row.get("node_id") in requirement["node_ids"]
              and (row.get("state") not in {"succeeded", "failed", "timed_out", "cancelled"}
                   or row.get("metadata", {}).get("execution_conflict"))]
    if active:
        raise ValueError("requirement_stop_active_attempts: cancel or reconcile the scoped work first")
    category = operation["category"]
    basis = bind_evidence(root, context, operation.get("evidence_refs", []), "")
    source_binding = None
    if category == "user_cancel":
        source = _source(root, context, operation.get("source_ref"), operation.get("source_quote"))
        if not operation.get("source_quote"):
            raise ValueError("requirement_stop_source_quote_required")
        if not any(row["source_ref"] == source["source_ref"] for row in context.get("requirement_sources", [])):
            raise ValueError("requirement_source_not_registered")
        source_binding = {"source_ref": source["source_ref"], "source_sha256": source["sha256"],
                          "source_quote": operation["source_quote"], "interpretation": "agent_assessment"}
    else:
        receipts = [_receipt(root, context, ref) for ref in operation.get("result_receipt_refs", [])]
        if not receipts:
            raise ValueError("requirement_stop_execution_evidence_required: not having started is not a failure")
        for receipt, attempt in receipts:
            if attempt.get("node_id") not in requirement["node_ids"] or receipt.get("execution_state") not in {"failed", "timed_out", "cancelled"}:
                raise ValueError("requirement_stop_scope_mismatch: cite an actual failed execution for this requirement")
            if category == "capability_unavailable" and receipt.get("execution_observation", {}).get("error_class") not in {
                    "executable_not_found", "environment_unavailable", "capability_unavailable"}:
                raise ValueError("requirement_stop_capability_not_proven: an arbitrary failure cannot prove a capability unavailable")
            basis["result_versions"][attempt["id"]] = receipt["receipt_id"]
    requirement["stops"].append({"id": operation["id"], "requirement_version": requirement["version"],
        "category": category, "reason": operation["reason"], "created_at": created_at,
        "scope_node_ids": sorted(requirement["node_ids"]),
        "scope_attempt_ids": sorted(row["id"] for row in context["attempts"] if row.get("node_id") in requirement["node_ids"]),
        "evidence_basis": basis, "source": source_binding, "result_receipt_refs": operation.get("result_receipt_refs", [])})
    return operation["id"]


def requirement_evaluation(context, requirement):
    assessments = requirement.get("assessments", [])
    latest = assessments[-1] if assessments else None
    current = bool(latest and latest.get("requirement_version") == requirement["version"]
                   and latest.get("profile_digest") == requirement["profile_digest"]
                   and assessment_current(context, latest))
    if current and latest.get("execution_platforms"):
        attempts = {row["id"]: row for row in context["attempts"]}
        current = all(attempts.get(ref, {}).get("environment") == platform
                      for ref, platform in latest["execution_platforms"].items())
    satisfied = bool(current and latest["checks"] and all(row["satisfied"] for row in latest["checks"]))
    stops = requirement.get("stops", [])
    stop = stops[-1] if stops else None
    resumed = requirement.get("stop_resumption", {}).get("after_stop_count", 0) >= len(stops)
    scoped_attempts = [row for row in context["attempts"] if row.get("node_id") in requirement["node_ids"]]
    stop_scope_current = bool(stop and stop.get("scope_node_ids") == sorted(requirement["node_ids"])
                              and stop.get("scope_attempt_ids") == sorted(row["id"] for row in scoped_attempts)
                              and all(row.get("state") in {"succeeded", "failed", "timed_out", "cancelled"}
                                      and not row.get("metadata", {}).get("execution_conflict") for row in scoped_attempts))
    stopped = bool(not satisfied and stop and not resumed and stop["requirement_version"] == requirement["version"]
                   and stop_scope_current and assessment_current(context, stop))
    needs_review = (latest and not current) or (stop and not resumed and not stopped)
    state = "satisfied" if satisfied else "stopped" if stopped else "needs_review" if needs_review else "unmet"
    return {"id": requirement["id"], "version": requirement["version"], "statement": requirement["statement"],
            "source_ref": requirement["source_ref"], "source_quote": requirement["source_quote"],
            "constraints": copy.deepcopy(requirement["constraints"]),
            "input_artifact_ids": list(requirement["input_artifact_ids"]),
            "acceptance_profile": requirement["acceptance_profile"],
            "state": state, "satisfied": satisfied, "settled": satisfied or stopped,
            "covered": bool(requirement.get("node_ids")), "node_ids": list(requirement.get("node_ids", [])),
            "checks": copy.deepcopy(latest["checks"]) if latest else [],
            "stop": copy.deepcopy(stop) if stopped else None}


def requirements_evaluation(context):
    requirements = [requirement_evaluation(context, row) for row in context.get("requirements", [])]
    pending = [row["source_ref"] for row in context.get("requirement_sources", []) if not row.get("review")]
    return {"schema_version": SCHEMA_VERSION, "requirements": requirements, "unreviewed_source_refs": pending,
            "satisfied": not pending and all(row["satisfied"] for row in requirements),
            "settled": not pending and all(row["settled"] for row in requirements),
            "tracked": bool(context.get("requirement_sources") or requirements)}


def requirement_obligations(context):
    evaluation = requirements_evaluation(context)
    return ([{"kind": "review_user_source", "source_ref": ref} for ref in evaluation["unreviewed_source_refs"]]
            + [{"kind": "satisfy_requirement" if row["covered"] else "plan_requirement", "requirement_id": row["id"],
                "state": row["state"], "statement": row["statement"]}
               for row in evaluation["requirements"] if not row["settled"]])


def node_requirement_evaluation(context, node):
    """Only explicitly final deliverables consume whole requirements.

    Contributing preparation Nodes can complete before the overall research does.
    """
    consumed = node.get("consumes", {}).get("requirement_ids", [])
    rows = {row["id"]: row for row in requirements_evaluation(context)["requirements"]}
    observed = node.get("consumes", {}).get("condition", "satisfied") == "observed"
    unmet = [ref for ref in consumed if ref not in rows or (not observed and not rows[ref]["satisfied"])]
    return {"satisfied": not unmet, "unmet_requirement_ids": unmet}


def snapshot_node_requirements(context, node, created_at):
    """Record what a completed delivery actually consumed, without freezing research."""
    consumed = node.get("consumes", {}).get("requirement_ids", [])
    rows = {row["id"]: row for row in context.get("requirements", [])}
    return {"condition": node.get("consumes", {}).get("condition", "satisfied"), "created_at": created_at,
            "requirements": [{"id": ref, "version": rows[ref]["version"],
                "assessment_id": rows[ref]["assessments"][-1]["id"] if rows[ref]["assessments"] else None,
                "state": requirement_evaluation(context, rows[ref])["state"]} for ref in consumed]}


def completed_node_requirement_evaluation(context, node):
    """Validate the recorded consumption; later evidence may invalidate current acceptance."""
    snapshot = node.get("requirement_consumption")
    if snapshot is None:
        return node_requirement_evaluation(context, node)
    consumed = set(node.get("consumes", {}).get("requirement_ids", []))
    condition = node.get("consumes", {}).get("condition", "satisfied")
    records = {row["id"]: row for row in snapshot.get("requirements", [])}
    requirements = {row["id"]: row for row in context.get("requirements", [])}
    unmet = set(consumed ^ set(records))
    if snapshot.get("condition") != condition:
        unmet.update(consumed)
    for ref in consumed & set(records):
        record, requirement = records[ref], requirements.get(ref)
        if requirement is None or record.get("version") not in {
                requirement["version"], *(row["version"] for row in requirement.get("revisions", []))}:
            unmet.add(ref)
            continue
        if condition == "observed":
            continue
        assessment = next((row for row in requirement["assessments"] if row["id"] == record.get("assessment_id")), None)
        if (record.get("state") != "satisfied" or not assessment
                or assessment["requirement_version"] != record["version"]
                or not assessment["checks"] or not all(row["satisfied"] for row in assessment["checks"])):
            unmet.add(ref)
    return {"satisfied": not unmet, "unmet_requirement_ids": sorted(unmet)}
