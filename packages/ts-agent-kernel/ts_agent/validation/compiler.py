"""Compile template or inline definitions into immutable expanded ProofSpecs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .digests import now_iso, sha256_json
from .registry import PredicateRegistry, RegistryError, load_proof_template


class ProofSpecCompileError(ValueError):
    """Raised when a declarative ProofSpec cannot be frozen."""


def compile_proof_spec(
    request: dict[str, Any],
    *,
    proof_id: str,
    target_claim_ref: str,
    claim_preregistration_digest: str,
    registry: PredicateRegistry,
    created_by_node: str,
    created_by_decision: str,
    frozen_at: str | None = None,
) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ProofSpecCompileError("ProofSpec request must be an object")
    allowed = {"dimension", "title", "template", "definition"}
    if set(request) - allowed:
        raise ProofSpecCompileError("ProofSpec request contains unsupported fields")
    if ("template" in request) == ("definition" in request):
        raise ProofSpecCompileError("ProofSpec request requires exactly one of template or definition")
    dimension = _nonempty_string(request.get("dimension"), "dimension", 128)

    template_ref = None
    template_digest = None
    if "template" in request:
        binding = request["template"]
        if not isinstance(binding, dict) or set(binding) != {"template_id", "version", "parameters"}:
            raise ProofSpecCompileError("template binding requires template_id, version, and parameters")
        template_id = _nonempty_string(binding.get("template_id"), "template_id", 128)
        version = _nonempty_string(binding.get("version"), "template version", 64)
        parameters = binding.get("parameters")
        if not isinstance(parameters, dict):
            raise ProofSpecCompileError("template parameters must be an object")
        try:
            template = load_proof_template(template_id, version)
        except RegistryError as exc:
            raise ProofSpecCompileError(str(exc)) from exc
        _validate_template_parameters(template, parameters)
        definition = _substitute(deepcopy(template.get("definition")), parameters)
        template_ref = {"template_id": template_id, "version": version}
        template_digest = sha256_json(template)
    else:
        definition = deepcopy(request["definition"])

    title = _nonempty_string(request.get("title", template.get("title") if template_ref else None), "title", 300)

    normalized = _normalize_definition(definition, registry)
    spec = {
        "schema_version": "ts-proof-spec/1",
        "proof_id": proof_id,
        "target_claim_ref": target_claim_ref,
        "claim_preregistration_digest": claim_preregistration_digest,
        "dimension": dimension,
        "title": title,
        "template_ref": template_ref,
        "template_digest": template_digest,
        "predicate_registry_digest": registry.digest,
        "checks": normalized["checks"],
        "success_policy": normalized["success_policy"],
        "created_by_node": created_by_node,
        "created_by_decision": created_by_decision,
        "frozen_at": frozen_at or now_iso(),
    }
    spec["proof_digest"] = sha256_json(spec)
    return spec


def _validate_template_parameters(template: dict[str, Any], parameters: dict[str, Any]) -> None:
    definitions = template.get("parameters", {})
    if not isinstance(definitions, dict):
        raise ProofSpecCompileError("template parameter definitions are invalid")
    unknown = sorted(set(parameters) - set(definitions))
    missing = sorted(
        name
        for name, definition in definitions.items()
        if isinstance(definition, dict) and definition.get("required") is True and name not in parameters
    )
    if unknown:
        raise ProofSpecCompileError("unknown template parameters: " + ", ".join(unknown))
    if missing:
        raise ProofSpecCompileError("missing template parameters: " + ", ".join(missing))
    for name, definition in definitions.items():
        if name not in parameters or not isinstance(definition, dict):
            continue
        expected = definition.get("type")
        value = parameters[name]
        if expected == "string" and not isinstance(value, str):
            raise ProofSpecCompileError(f"template parameter {name} must be a string")
        if expected == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ProofSpecCompileError(f"template parameter {name} must be a number")
        if expected == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            raise ProofSpecCompileError(f"template parameter {name} must be an integer")
        if expected == "boolean" and not isinstance(value, bool):
            raise ProofSpecCompileError(f"template parameter {name} must be a boolean")


def _substitute(value: Any, parameters: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        name = value[2:-1]
        if name not in parameters:
            raise ProofSpecCompileError(f"template references missing parameter: {name}")
        return deepcopy(parameters[name])
    if isinstance(value, list):
        return [_substitute(item, parameters) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, parameters) for key, item in value.items()}
    return value


def _normalize_definition(value: Any, registry: PredicateRegistry) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"checks", "success_policy"}:
        raise ProofSpecCompileError("ProofSpec definition requires checks and success_policy")
    checks = value.get("checks")
    if not isinstance(checks, list) or not checks or len(checks) > 64:
        raise ProofSpecCompileError("ProofSpec checks must contain 1 to 64 entries")
    normalized_checks = []
    seen: set[str] = set()
    for raw in checks:
        if not isinstance(raw, dict) or set(raw) != {"check_id", "predicate", "parameters", "blocking"}:
            raise ProofSpecCompileError("each ProofSpec check requires check_id, predicate, parameters, and blocking")
        check_id = _nonempty_string(raw.get("check_id"), "check_id", 128)
        if check_id in seen:
            raise ProofSpecCompileError(f"duplicate ProofSpec check_id: {check_id}")
        seen.add(check_id)
        predicate = _nonempty_string(raw.get("predicate"), "predicate", 128)
        try:
            registration = registry.get(predicate)
        except RegistryError as exc:
            raise ProofSpecCompileError(str(exc)) from exc
        parameters = raw.get("parameters")
        if not isinstance(parameters, dict):
            raise ProofSpecCompileError(f"ProofSpec check parameters must be an object: {check_id}")
        if not isinstance(raw.get("blocking"), bool):
            raise ProofSpecCompileError(f"ProofSpec check blocking must be boolean: {check_id}")
        normalized_checks.append(
            {
                "check_id": check_id,
                "predicate": predicate,
                "predicate_version": registration.version,
                "parameters": parameters,
                "blocking": raw["blocking"],
            }
        )
    success_policy = value.get("success_policy")
    if not isinstance(success_policy, dict) or set(success_policy) != {"mode"}:
        raise ProofSpecCompileError("success_policy requires only mode")
    if success_policy.get("mode") not in {"all_blocking", "all"}:
        raise ProofSpecCompileError("success_policy.mode must be all_blocking or all")
    return {"checks": normalized_checks, "success_policy": dict(success_policy)}


def _nonempty_string(value: Any, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ProofSpecCompileError(f"{name} must be a non-empty string up to {maximum} characters")
    return value.strip()
