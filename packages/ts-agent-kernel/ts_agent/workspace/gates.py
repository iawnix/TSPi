"""Deterministic Gate projections over the current workspace state.

 Gate records are projected from the existing scientific sources.  Explicit
 GateSpec and GateResult records are optional registries, and can only be
 written through the canonical ``ts_change`` mutation boundary.  This module
 gives Kernel, Web, and context a single vocabulary without letting plugins
 own scientific state.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from ts_agent.io import sha256_json


NODE_PROFILE = "node.complete.basic"
CLAIM_PROFILE = "claim.validation.current"
NODE_SUPPORTED_PROFILES = {NODE_PROFILE}
CLAIM_SUPPORTED_PROFILES = {CLAIM_PROFILE}
_ID = re.compile(r"^[a-z]+_([1-9][0-9]*)$")


def project_gates(
    *,
    nodes: Iterable[dict[str, Any]],
    claims: Iterable[dict[str, Any]],
    proof_specs: Iterable[dict[str, Any]],
    validation_results: Iterable[dict[str, Any]],
    findings: Iterable[dict[str, Any]],
    operational: dict[str, Any] | None = None,
    input_revision: str | None = None,
    gate_specs: Iterable[dict[str, Any]] = (),
    gate_results: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Return stable Gate-shaped projections for Nodes and Claims."""

    node_rows = [row for row in nodes if isinstance(row, dict) and isinstance(row.get("node_id"), str)]
    claim_rows = [row for row in claims if isinstance(row, dict) and isinstance(row.get("claim_id"), str)]
    spec_rows = [row for row in proof_specs if isinstance(row, dict)]
    result_rows = [row for row in validation_results if isinstance(row, dict)]
    finding_rows = [row for row in findings if isinstance(row, dict)]
    operational = operational if isinstance(operational, dict) else {}
    revision = input_revision if isinstance(input_revision, str) and input_revision else None

    node_projections = [
        evaluate_node_gate(
            node,
            findings=finding_rows,
            operational=operational,
            input_revision=revision,
        )
        for node in node_rows
    ]
    claim_projections = [
        evaluate_claim_gate(
            claim,
            proof_specs=spec_rows,
            validation_results=result_rows,
            findings=finding_rows,
            input_revision=revision,
        )
        for claim in claim_rows
    ]
    explicit_specs = [row for row in gate_specs if isinstance(row, dict)]
    explicit_results = [row for row in gate_results if isinstance(row, dict)]
    node_projections = _overlay_persisted(
        node_projections, explicit_specs, explicit_results, scope="node", input_revision=revision
    )
    claim_projections = _overlay_persisted(
        claim_projections, explicit_specs, explicit_results, scope="claim", input_revision=revision
    )
    return {
        "schema_version": "ts-gate-projection/1",
        "node_gates": node_projections,
        "claim_gates": claim_projections,
        "summary": {
            "node_count": len(node_projections),
            "claim_count": len(claim_projections),
            "node_pass_count": sum(row["result"]["verdict"] == "pass" for row in node_projections),
            "claim_pass_count": sum(row["result"]["verdict"] == "pass" for row in claim_projections),
            "blocked_count": sum(
                row["result"]["verdict"] == "blocked"
                for row in (*node_projections, *claim_projections)
            ),
        },
    }


def evaluate_frozen_gate(
    spec: dict[str, Any],
    *,
    node: dict[str, Any] | None = None,
    claim: dict[str, Any] | None = None,
    proof_specs: Iterable[dict[str, Any]] = (),
    validation_results: Iterable[dict[str, Any]] = (),
    findings: Iterable[dict[str, Any]] = (),
    operational: dict[str, Any] | None = None,
    input_revision: str | None = None,
    result_id: str | None = None,
    evaluated_by_node: str | None = None,
    evaluated_by_decision: str | None = None,
    evaluated_at: str | None = None,
) -> dict[str, Any]:
    """Evaluate a frozen GateSpec without changing its criteria or digest."""

    scope = spec.get("scope")
    if scope == "node" and isinstance(node, dict):
        projection = evaluate_node_gate(
            node,
            findings=findings,
            operational=operational,
            input_revision=input_revision,
        )
    elif scope == "claim" and isinstance(claim, dict):
        projection = evaluate_claim_gate(
            claim,
            proof_specs=proof_specs,
            validation_results=validation_results,
            findings=findings,
            input_revision=input_revision,
        )
    else:
        return _blocked_result(
            spec,
            input_revision=input_revision,
            result_id=result_id,
            evaluated_by_decision=evaluated_by_decision,
            evaluated_at=evaluated_at,
            message="Gate target is not available in the current workspace.",
        )
    generated = projection["spec"]
    expected_checks = {(row.get("check_id"), row.get("predicate"), row.get("predicate_version"), row.get("blocking")) for row in spec.get("checks", [])}
    actual_checks = {(row.get("check_id"), row.get("predicate"), row.get("predicate_version"), row.get("blocking")) for row in generated.get("checks", [])}
    if expected_checks != actual_checks or spec.get("profile_ref") != generated.get("profile_ref"):
        return _blocked_result(
            spec,
            input_revision=input_revision,
            result_id=result_id,
            evaluated_by_node=evaluated_by_node or spec.get("created_by_node") or (node or claim or {}).get("created_by_node"),
            evaluated_by_decision=evaluated_by_decision,
            evaluated_at=evaluated_at,
            message="Frozen GateSpec no longer matches the installed evaluator profile.",
        )
    return _result(
        spec,
        projection["result"]["check_results"],
        input_revision=input_revision,
        evaluated_by_node=evaluated_by_node or spec.get("created_by_node") or (node or claim or {}).get("created_by_node"),
        evaluated_by_decision=evaluated_by_decision,
        evaluated_at=evaluated_at,
        result_id=result_id,
    )


def gate_profile_catalog() -> list[dict[str, Any]]:
    """Return a machine-readable profile and predicate contract."""

    return [
        {
            "profile_id": NODE_PROFILE,
            "version": "1",
            "scope": "node",
            "title": "Node completion",
            "evaluator": "builtin",
            "evaluator_version": "1",
            "predicates": ["node.deliverable_declared", "node.execution_settled", "node.blocking_findings_resolved"],
            "predicate_contracts": [
                {"id": "node.deliverable_declared", "input_schema": {"type": "node"}, "output_schema": {"verdict": ["pass", "fail"]}},
                {"id": "node.execution_settled", "input_schema": {"type": "operational.node"}, "output_schema": {"verdict": ["pass", "blocked"]}},
                {"id": "node.blocking_findings_resolved", "input_schema": {"type": "finding[]"}, "output_schema": {"verdict": ["pass", "fail"]}},
            ],
        },
        {
            "profile_id": CLAIM_PROFILE,
            "version": "1",
            "scope": "claim",
            "title": "Current Claim validation",
            "evaluator": "builtin",
            "evaluator_version": "1",
            "predicates": ["claim.preregistered", "claim.validation_coverage", "claim.proof_result", "claim.blocking_findings_resolved"],
            "predicate_contracts": [
                {"id": "claim.preregistered", "input_schema": {"type": "claim"}, "output_schema": {"verdict": ["pass", "blocked"]}},
                {"id": "claim.validation_coverage", "input_schema": {"type": "proof[]", "result": "validation_result[]"}, "output_schema": {"verdict": ["pass", "blocked", "inconclusive"]}},
                {"id": "claim.proof_result", "input_schema": {"type": "validation_result"}, "output_schema": {"verdict": ["pass", "fail", "blocked", "inconclusive"]}},
                {"id": "claim.blocking_findings_resolved", "input_schema": {"type": "finding[]"}, "output_schema": {"verdict": ["pass", "blocked"]}},
            ],
        },
    ]


def evaluate_node_gate(
    node: dict[str, Any],
    *,
    findings: Iterable[dict[str, Any]] = (),
    operational: dict[str, Any] | None = None,
    input_revision: str | None = None,
) -> dict[str, Any]:
    """Evaluate whether one bounded Node is ready for a terminal outcome."""

    node_ref = str(node.get("node_id") or "")
    profile = _profile(node.get("gate_profile"), NODE_PROFILE)
    blockers = _operational_blockers(operational or {}, node_ref)
    node_findings = [
        row for row in findings
        if node_ref in _strings(row.get("node_refs")) and row.get("status") == "open"
    ]
    blocking_findings = [
        row for row in node_findings if row.get("severity") == "blocking"
    ]
    checks = [
        _check(
            "profile.available",
            "gate.profile_available",
            "pass" if profile["profile_id"] in NODE_SUPPORTED_PROFILES else "blocked",
            True,
            (
                f"Gate profile {profile['profile_id']} is available."
                if profile["profile_id"] in NODE_SUPPORTED_PROFILES
                else f"Gate profile {profile['profile_id']} is not installed."
            ),
        ),
        _check(
            "deliverable.declared",
            "node.deliverable_declared",
            "pass" if isinstance(node.get("deliverable"), str) and node["deliverable"].strip() else "fail",
            bool(not isinstance(node.get("deliverable"), str) or not node["deliverable"].strip()),
            message=("The Node has a declared deliverable." if node.get("deliverable") else "The Node has no deliverable."),
        ),
        _check(
            "execution.settled",
            "node.execution_settled",
            "blocked" if blockers else "pass",
            True,
            message=(blockers[0]["message"] if blockers else "Owned execution records are settled."),
        ),
        _check(
            "findings.resolved",
            "node.blocking_findings_resolved",
            "fail" if blocking_findings else "pass",
            True,
            message=(
                f"{len(blocking_findings)} open blocking Finding(s) remain."
                if blocking_findings else "No open blocking Findings remain."
            ),
            finding_refs=[str(row["finding_id"]) for row in blocking_findings if isinstance(row.get("finding_id"), str)],
        ),
    ]
    spec = _spec(
        gate_id=_gate_id("node", node_ref),
        scope="node",
        target_node_ref=node_ref,
        target_claim_ref=None,
        title="Node completion",
        purpose="Determine whether this bounded ResearchNode can close.",
        profile_id=profile["profile_id"],
        profile_version=profile["version"],
        checks=[
            {"check_id": row["check_id"], "predicate": row["predicate"], "predicate_version": row["predicate_version"], "parameters": {}, "blocking": row["blocking"]}
            for row in checks
        ],
        created_by_node=node_ref,
        created_by_decision=node.get("created_by_decision"),
        frozen_at=_event_time(node),
    )
    result = _result(
        spec,
        checks,
        input_revision=input_revision,
        evaluated_by_node=node_ref,
        evaluated_by_decision=_event_decision(node),
        evaluated_at=_event_time(node),
    )
    return {"spec": spec, "result": result}


def evaluate_claim_gate(
    claim: dict[str, Any],
    *,
    proof_specs: Iterable[dict[str, Any]] = (),
    validation_results: Iterable[dict[str, Any]] = (),
    findings: Iterable[dict[str, Any]] = (),
    input_revision: str | None = None,
) -> dict[str, Any]:
    """Evaluate the currently available deterministic coverage for a Claim."""

    claim_ref = str(claim.get("claim_id") or "")
    profile = _profile(claim.get("gate_profile"), CLAIM_PROFILE)
    specs = sorted(
        [row for row in proof_specs if row.get("target_claim_ref") == claim_ref],
        key=lambda row: str(row.get("proof_id") or ""),
    )
    results = [row for row in validation_results if row.get("target_claim_ref") == claim_ref]
    latest = _latest_results(results)
    claim_findings = [
        row for row in findings
        if claim_ref in _strings(row.get("claim_refs")) and row.get("status") == "open"
    ]
    blocking_findings = [row for row in claim_findings if row.get("severity") == "blocking"]
    checks: list[dict[str, Any]] = [
        _check(
            "profile.available",
            "gate.profile_available",
            "pass" if profile["profile_id"] in CLAIM_SUPPORTED_PROFILES else "blocked",
            True,
            (
                f"Gate profile {profile['profile_id']} is available."
                if profile["profile_id"] in CLAIM_SUPPORTED_PROFILES
                else f"Gate profile {profile['profile_id']} is not installed."
            ),
        )
    ]
    if claim.get("predictions") and claim.get("falsifiers"):
        checks.append(_check("claim.preregistered", "claim.preregistered", "pass", True, "Claim predictions and falsifiers are pre-registered."))
    else:
        checks.append(_check("claim.preregistered", "claim.preregistered", "blocked", True, "Claim predictions and falsifiers are incomplete."))

    if not specs:
        checks.append(_check("validation.coverage", "claim.validation_coverage", "inconclusive", True, "No ProofSpec is attached to the Claim."))
    else:
        missing = [str(row.get("proof_id")) for row in specs if str(row.get("proof_id")) not in latest]
        checks.append(_check(
            "validation.coverage",
            "claim.validation_coverage",
            "blocked" if missing else "pass",
            True,
            ("Missing latest ValidationResult for: " + ", ".join(missing)) if missing else "Every attached ProofSpec has a latest ValidationResult.",
            validation_result_refs=[str(latest[ref].get("result_id")) for ref in latest if ref in {str(row.get("proof_id")) for row in specs}],
        ))
        for spec in specs:
            proof_ref = str(spec.get("proof_id") or "")
            result = latest.get(proof_ref)
            if result is None:
                continue
            verdict = str(result.get("verdict") or "inconclusive")
            if verdict == "error":
                verdict = "blocked"
            checks.append(_check(
                f"proof.{proof_ref}",
                "claim.proof_result",
                verdict if verdict in {"pass", "fail", "inconclusive", "blocked"} else "blocked",
                True,
                f"ProofSpec {proof_ref} has ValidationResult {result.get('result_id')}: {result.get('verdict')}",
                observation_refs=_strings(result.get("observation_refs")),
                validation_result_refs=[str(result.get("result_id"))] if result.get("result_id") else [],
            ))
    checks.append(_check(
        "findings.clear",
        "claim.blocking_findings_resolved",
        "blocked" if blocking_findings else "pass",
        True,
        (f"{len(blocking_findings)} open blocking Finding(s) remain." if blocking_findings else "No open blocking Findings remain."),
        finding_refs=[str(row["finding_id"]) for row in blocking_findings if isinstance(row.get("finding_id"), str)],
    ))
    spec = _spec(
        gate_id=_gate_id("claim", claim_ref),
        scope="claim",
        target_node_ref=None,
        target_claim_ref=claim_ref,
        title="Current Claim validation",
        purpose="Determine whether current declared evidence is sufficient to interpret the Claim.",
        profile_id=profile["profile_id"],
        profile_version=profile["version"],
        checks=[
            {"check_id": row["check_id"], "predicate": row["predicate"], "predicate_version": row["predicate_version"], "parameters": {}, "blocking": row["blocking"]}
            for row in checks
        ],
        created_by_node=claim.get("created_by_node"),
        created_by_decision=claim.get("created_by_decision"),
        frozen_at=_event_time(claim),
    )
    result = _result(
        spec,
        checks,
        input_revision=input_revision,
        evaluated_by_node=claim.get("created_by_node"),
        evaluated_by_decision=_event_decision(claim),
        evaluated_at=_event_time(claim),
    )
    return {"spec": spec, "result": result}


def _spec(**values: Any) -> dict[str, Any]:
    record = {
        "schema_version": "ts-gate-spec/1",
        "gate_id": values["gate_id"],
        "scope": values["scope"],
        "target_node_ref": values["target_node_ref"],
        "target_claim_ref": values["target_claim_ref"],
        "title": values["title"],
        "purpose": values["purpose"],
        "profile_ref": {"profile_id": values["profile_id"], "version": values.get("profile_version", "1")},
        "checks": values["checks"],
        "success_policy": {"mode": "all_blocking"},
        "created_by_node": values.get("created_by_node"),
        "created_by_decision": values.get("created_by_decision"),
        "created_at": values.get("frozen_at"),
        "frozen_at": values.get("frozen_at"),
    }
    record["gate_digest"] = sha256_json(record)
    return record


def _result(
    spec: dict[str, Any],
    checks: list[dict[str, Any]],
    *,
    input_revision: str | None,
    evaluated_by_node: Any,
    evaluated_by_decision: Any,
    evaluated_at: str | None,
    result_id: str | None = None,
) -> dict[str, Any]:
    verdicts = [str(row["verdict"]) for row in checks]
    verdict = "blocked" if "blocked" in verdicts else "fail" if "fail" in verdicts else "inconclusive" if "inconclusive" in verdicts else "pass"
    observation_refs = sorted({ref for row in checks for ref in _strings(row.get("observation_refs"))})
    finding_refs = sorted({ref for row in checks for ref in _strings(row.get("finding_refs"))})
    validation_refs = sorted({ref for row in checks for ref in _strings(row.get("validation_result_refs"))})
    record = {
        "schema_version": "ts-gate-result/1",
        "gate_result_id": result_id or _result_id(spec["gate_id"]),
        "gate_ref": spec["gate_id"],
        "gate_digest": spec["gate_digest"],
        "scope": spec["scope"],
        "target_node_ref": spec["target_node_ref"],
        "target_claim_ref": spec["target_claim_ref"],
        "verdict": verdict,
        "observation_refs": observation_refs,
        "validation_result_refs": validation_refs,
        "finding_refs": finding_refs,
        "artifact_refs": [],
        "check_results": checks,
        "input_revision": input_revision or "sha256:" + "0" * 64,
        "evaluated_by_node": evaluated_by_node,
        "evaluated_by_decision": evaluated_by_decision,
        "evaluated_at": evaluated_at,
    }
    record["result_digest"] = sha256_json(record)
    return record


def _blocked_result(
    spec: dict[str, Any],
    *,
    input_revision: str | None,
    result_id: str | None,
    evaluated_by_node: Any = None,
    evaluated_by_decision: Any = None,
    evaluated_at: str | None = None,
    message: str,
) -> dict[str, Any]:
    check = _check(
        "gate.evaluator_available",
        "gate.evaluator_available",
        "blocked",
        True,
        message,
    )
    return _result(
        spec,
        [check],
        input_revision=input_revision,
        evaluated_by_node=evaluated_by_node,
        evaluated_by_decision=evaluated_by_decision,
        evaluated_at=evaluated_at,
        result_id=result_id,
    )


def _overlay_persisted(
    projections: list[dict[str, Any]],
    specs: list[dict[str, Any]],
    results: list[dict[str, Any]],
    *,
    scope: str,
    input_revision: str | None,
) -> list[dict[str, Any]]:
    by_target: dict[str, list[dict[str, Any]]] = {}
    for spec in specs:
        if spec.get("scope") != scope:
            continue
        target = spec.get("target_node_ref") if scope == "node" else spec.get("target_claim_ref")
        if isinstance(target, str):
            by_target.setdefault(target, []).append(spec)
    latest_results: dict[str, dict[str, Any]] = {}
    result_history: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        gate_ref = result.get("gate_ref")
        if not isinstance(gate_ref, str):
            continue
        result_history.setdefault(gate_ref, []).append(result)
        prior = latest_results.get(gate_ref)
        if prior is None or (str(result.get("evaluated_at") or ""), str(result.get("gate_result_id") or "")) > (
            str(prior.get("evaluated_at") or ""), str(prior.get("gate_result_id") or "")
        ):
            latest_results[gate_ref] = result
    output: list[dict[str, Any]] = []
    for projection in projections:
        target = projection["result"].get("target_node_ref") if scope == "node" else projection["result"].get("target_claim_ref")
        candidates = by_target.get(target, [])
        if not candidates:
            output.append(projection)
            continue
        spec = max(candidates, key=lambda row: (str(row.get("frozen_at") or ""), str(row.get("gate_id") or "")))
        result = latest_results.get(str(spec.get("gate_id")))
        if result is None:
            output.append({"spec": spec, "result": _blocked_result(
                spec,
                input_revision=input_revision,
                result_id=None,
                evaluated_by_node=spec.get("created_by_node"),
                evaluated_by_decision=spec.get("created_by_decision"),
                evaluated_at=spec.get("frozen_at"),
                message="GateSpec is frozen but has not been evaluated.",
            ), "stale": False, "result_history": []})
        else:
            stale = bool(input_revision and result.get("input_revision") != input_revision)
            output.append({
                "spec": spec,
                "result": {**result, "stale": stale},
                "stale": stale,
                "result_history": sorted(
                    result_history.get(str(spec.get("gate_id")), []),
                    key=lambda row: (str(row.get("evaluated_at") or ""), str(row.get("gate_result_id") or "")),
                ),
            })
    return output


def _check(
    check_id: str,
    predicate: str,
    verdict: str,
    blocking: bool,
    message: str,
    *,
    observation_refs: Iterable[str] = (),
    validation_result_refs: Iterable[str] = (),
    finding_refs: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "predicate": predicate,
        "predicate_version": "1",
        "blocking": blocking,
        "verdict": verdict,
        "observation_refs": sorted(set(_strings(observation_refs))),
        "validation_result_refs": sorted(set(_strings(validation_result_refs))),
        "finding_refs": sorted(set(_strings(finding_refs))),
        "artifact_refs": [],
        "message": message,
    }


def _latest_results(results: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in results:
        proof_ref = row.get("proof_ref")
        if not isinstance(proof_ref, str):
            continue
        previous = latest.get(proof_ref)
        if previous is None or (str(row.get("evaluated_at") or ""), str(row.get("result_id") or "")) > (
            str(previous.get("evaluated_at") or ""), str(previous.get("result_id") or "")
        ):
            latest[proof_ref] = row
    return latest


def _operational_blockers(operational: dict[str, Any], node_ref: str) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for item in (
        *operational.get("activity_integrity_findings", []),
        *operational.get("calculation_attempt_integrity_findings", []),
    ):
        if isinstance(item, dict) and node_ref in _strings(item.get("node_refs")):
            blockers.append({"ref": item.get("path") or node_ref, "message": item.get("message") or "Node execution integrity failed."})
    for key in ("deterministic_activities", "calculation_attempts"):
        for item in operational.get(key, []):
            if not isinstance(item, dict) or node_ref not in _strings(item.get("node_refs", [item.get("node_id")])):
                continue
            state = str(item.get("status") or item.get("display_state") or item.get("state") or "")
            if state in {"running", "pending", "queued", "submitted", "collected", "parsing", "prepared"}:
                blockers.append({"ref": item.get("activity_ref") or item.get("intent_id") or node_ref, "message": f"Owned execution is still {state}."})
    return blockers


def _gate_id(scope: str, ref: str) -> str:
    match = _ID.match(ref)
    ordinal = int(match.group(1)) if match else 0
    base = 1_000_000 if scope == "node" else 2_000_000
    return f"gate_{base + ordinal}"


def _result_id(gate_id: str) -> str:
    suffix = gate_id.removeprefix("gate_")
    return f"gate_result_{suffix}"


def _event_time(record: dict[str, Any]) -> str:
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    history = record.get("history") if isinstance(record.get("history"), list) else []
    candidates = [record.get("created_at"), result.get("completed_at")]
    candidates.extend(row.get("created_at") for row in history if isinstance(row, dict))
    return next((str(value) for value in reversed(candidates) if isinstance(value, str) and value), "")


def _event_decision(record: dict[str, Any]) -> str | None:
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    history = record.get("history") if isinstance(record.get("history"), list) else []
    candidates = [result.get("decision_id"), record.get("created_by_decision")]
    candidates.extend(row.get("decision_id") for row in history if isinstance(row, dict))
    return next((str(value) for value in reversed(candidates) if isinstance(value, str) and value), None)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [item for item in value if isinstance(item, str)] if isinstance(value, (list, tuple, set)) else []


def _profile(value: Any, default_id: str) -> dict[str, str]:
    if not isinstance(value, dict):
        return {"profile_id": default_id, "version": "1"}
    profile_id = value.get("profile_id")
    version = value.get("version")
    return {
        "profile_id": str(profile_id) if isinstance(profile_id, str) and profile_id else default_id,
        "version": str(version) if isinstance(version, str) and version else "1",
    }
