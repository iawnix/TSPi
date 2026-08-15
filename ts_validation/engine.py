"""Execute frozen GateSpecs against an explicit Observation snapshot."""

from __future__ import annotations

from typing import Any

from .digests import now_iso, sha256_json
from .registry import PredicateRegistry, RegistryError


class ValidationEngineError(ValueError):
    """Raised when a frozen GateSpec or Observation snapshot is inconsistent."""


def evaluate_gate_spec(
    spec: dict[str, Any],
    observations: list[dict[str, Any]],
    *,
    result_id: str,
    evaluated_by_act: str,
    evaluated_by_decision: str,
    registry: PredicateRegistry,
    evaluated_at: str | None = None,
) -> dict[str, Any]:
    _validate_spec_binding(spec, registry)
    selected = _validate_observations(observations)
    selected_refs = {str(item["observation_id"]) for item in selected}
    check_results: list[dict[str, Any]] = []
    for check in spec["checks"]:
        registration = registry.get(str(check["predicate"]))
        try:
            outcome = registration.evaluate(dict(check["parameters"]), selected)
            outcome = _normalize_outcome(outcome, selected_refs)
        except Exception as exc:
            outcome = {"verdict": "error", "observation_refs": [], "message": str(exc)[:2000]}
        check_results.append(
            {
                "check_id": check["check_id"],
                "predicate": check["predicate"],
                "predicate_version": registration.version,
                "blocking": check["blocking"],
                **outcome,
            }
        )

    verdict = _aggregate(spec["success_policy"], check_results)
    observation_digests = {
        str(item["observation_id"]): sha256_json(item)
        for item in selected
    }
    result = {
        "schema_version": "ts-validation-result/1",
        "result_id": result_id,
        "spec_ref": spec["spec_id"],
        "spec_digest": spec["spec_digest"],
        "target_claim_ref": spec["target_claim_ref"],
        "dimension": spec["dimension"],
        "verdict": verdict,
        "observation_refs": sorted(observation_digests),
        "observation_digests": observation_digests,
        "check_results": check_results,
        "evaluated_by_act": evaluated_by_act,
        "evaluated_by_decision": evaluated_by_decision,
        "evaluated_at": evaluated_at or now_iso(),
    }
    result["result_digest"] = sha256_json(result)
    return result


def _validate_spec_binding(spec: dict[str, Any], registry: PredicateRegistry) -> None:
    if not isinstance(spec, dict) or spec.get("schema_version") != "ts-gate-spec/1":
        raise ValidationEngineError("unsupported or malformed GateSpec")
    expected = dict(spec)
    digest = expected.pop("spec_digest", None)
    if not isinstance(digest, str) or digest != sha256_json(expected):
        raise ValidationEngineError("GateSpec digest does not match its content")
    if spec.get("predicate_registry_digest") != registry.digest:
        raise ValidationEngineError("GateSpec predicate registry digest is not active")
    checks = spec.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValidationEngineError("GateSpec contains no checks")
    for check in checks:
        if not isinstance(check, dict):
            raise ValidationEngineError("GateSpec check is malformed")
        try:
            registration = registry.get(str(check.get("predicate") or ""))
        except RegistryError as exc:
            raise ValidationEngineError(str(exc)) from exc
        if check.get("predicate_version") != registration.version:
            raise ValidationEngineError(f"GateSpec predicate version is not active: {registration.name}")


def _validate_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(observations, list):
        raise ValidationEngineError("observations must be an array")
    seen: set[str] = set()
    values = []
    for item in observations:
        if not isinstance(item, dict) or item.get("schema_version") != "ts-observation/1":
            raise ValidationEngineError("observation snapshot contains an unsupported record")
        observation_id = item.get("observation_id")
        if not isinstance(observation_id, str) or not observation_id or observation_id in seen:
            raise ValidationEngineError(f"duplicate or invalid observation_id: {observation_id}")
        seen.add(observation_id)
        values.append(item)
    return sorted(values, key=lambda value: value["observation_id"])


def _normalize_outcome(value: Any, selected_refs: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationEngineError("predicate returned a non-object result")
    verdict = value.get("verdict")
    refs = value.get("observation_refs")
    message = value.get("message")
    if verdict not in {"pass", "fail", "inconclusive", "error"}:
        raise ValidationEngineError("predicate returned an invalid verdict")
    if not isinstance(refs, list) or any(not isinstance(item, str) for item in refs):
        raise ValidationEngineError("predicate returned invalid observation refs")
    unknown_refs = sorted(set(refs) - selected_refs)
    if unknown_refs:
        raise ValidationEngineError(
            "predicate referenced observations outside the selected snapshot: " + ", ".join(unknown_refs)
        )
    if not isinstance(message, str) or len(message) > 2000:
        raise ValidationEngineError("predicate returned an invalid message")
    return {"verdict": verdict, "observation_refs": sorted(set(refs)), "message": message}


def _aggregate(policy: dict[str, Any], results: list[dict[str, Any]]) -> str:
    mode = policy.get("mode") if isinstance(policy, dict) else None
    selected = results if mode == "all" else [item for item in results if item["blocking"] is True]
    if not selected:
        return "error"
    verdicts = {str(item["verdict"]) for item in selected}
    if "error" in verdicts:
        return "error"
    if "fail" in verdicts:
        return "fail"
    if "inconclusive" in verdicts:
        return "inconclusive"
    return "pass"
