"""Compile template or inline definitions into immutable expanded GateSpecs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .digests import now_iso, sha256_json
from .registry import PredicateRegistry, RegistryError, load_gate_template


class GateSpecCompileError(ValueError):
    """Raised when a declarative GateSpec cannot be frozen."""


def compile_gate_spec(
    request: dict[str, Any],
    *,
    spec_id: str,
    target_claim_ref: str,
    registry: PredicateRegistry,
    created_by_act: str,
    created_by_decision: str,
    frozen_at: str | None = None,
) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise GateSpecCompileError("GateSpec request must be an object")
    allowed = {"dimension", "title", "template", "definition"}
    if set(request) - allowed:
        raise GateSpecCompileError("GateSpec request contains unsupported fields")
    if ("template" in request) == ("definition" in request):
        raise GateSpecCompileError("GateSpec request requires exactly one of template or definition")
    dimension = _nonempty_string(request.get("dimension"), "dimension", 128)
    title = _nonempty_string(request.get("title"), "title", 300)

    template_ref = None
    template_digest = None
    if "template" in request:
        binding = request["template"]
        if not isinstance(binding, dict) or set(binding) != {"template_id", "version", "parameters"}:
            raise GateSpecCompileError("template binding requires template_id, version, and parameters")
        template_id = _nonempty_string(binding.get("template_id"), "template_id", 128)
        version = _nonempty_string(binding.get("version"), "template version", 64)
        parameters = binding.get("parameters")
        if not isinstance(parameters, dict):
            raise GateSpecCompileError("template parameters must be an object")
        try:
            template = load_gate_template(template_id, version)
        except RegistryError as exc:
            raise GateSpecCompileError(str(exc)) from exc
        _validate_template_parameters(template, parameters)
        definition = _substitute(deepcopy(template.get("definition")), parameters)
        template_ref = {"template_id": template_id, "version": version}
        template_digest = sha256_json(template)
    else:
        definition = deepcopy(request["definition"])

    normalized = _normalize_definition(definition, registry)
    spec = {
        "schema_version": "ts-gate-spec/1",
        "spec_id": spec_id,
        "target_claim_ref": target_claim_ref,
        "dimension": dimension,
        "title": title,
        "template_ref": template_ref,
        "template_digest": template_digest,
        "predicate_registry_digest": registry.digest,
        "checks": normalized["checks"],
        "success_policy": normalized["success_policy"],
        "created_by_act": created_by_act,
        "created_by_decision": created_by_decision,
        "frozen_at": frozen_at or now_iso(),
    }
    spec["spec_digest"] = sha256_json(spec)
    return spec


def _validate_template_parameters(template: dict[str, Any], parameters: dict[str, Any]) -> None:
    definitions = template.get("parameters", {})
    if not isinstance(definitions, dict):
        raise GateSpecCompileError("template parameter definitions are invalid")
    unknown = sorted(set(parameters) - set(definitions))
    missing = sorted(
        name
        for name, definition in definitions.items()
        if isinstance(definition, dict) and definition.get("required") is True and name not in parameters
    )
    if unknown:
        raise GateSpecCompileError("unknown template parameters: " + ", ".join(unknown))
    if missing:
        raise GateSpecCompileError("missing template parameters: " + ", ".join(missing))
    for name, definition in definitions.items():
        if name not in parameters or not isinstance(definition, dict):
            continue
        expected = definition.get("type")
        value = parameters[name]
        if expected == "string" and not isinstance(value, str):
            raise GateSpecCompileError(f"template parameter {name} must be a string")
        if expected == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise GateSpecCompileError(f"template parameter {name} must be a number")
        if expected == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            raise GateSpecCompileError(f"template parameter {name} must be an integer")
        if expected == "boolean" and not isinstance(value, bool):
            raise GateSpecCompileError(f"template parameter {name} must be a boolean")


def _substitute(value: Any, parameters: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        name = value[2:-1]
        if name not in parameters:
            raise GateSpecCompileError(f"template references missing parameter: {name}")
        return deepcopy(parameters[name])
    if isinstance(value, list):
        return [_substitute(item, parameters) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, parameters) for key, item in value.items()}
    return value


def _normalize_definition(value: Any, registry: PredicateRegistry) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"checks", "success_policy"}:
        raise GateSpecCompileError("GateSpec definition requires checks and success_policy")
    checks = value.get("checks")
    if not isinstance(checks, list) or not checks or len(checks) > 64:
        raise GateSpecCompileError("GateSpec checks must contain 1 to 64 entries")
    normalized_checks = []
    seen: set[str] = set()
    for raw in checks:
        if not isinstance(raw, dict) or set(raw) != {"check_id", "predicate", "parameters", "blocking"}:
            raise GateSpecCompileError("each GateSpec check requires check_id, predicate, parameters, and blocking")
        check_id = _nonempty_string(raw.get("check_id"), "check_id", 128)
        if check_id in seen:
            raise GateSpecCompileError(f"duplicate GateSpec check_id: {check_id}")
        seen.add(check_id)
        predicate = _nonempty_string(raw.get("predicate"), "predicate", 128)
        try:
            registration = registry.get(predicate)
        except RegistryError as exc:
            raise GateSpecCompileError(str(exc)) from exc
        parameters = raw.get("parameters")
        if not isinstance(parameters, dict):
            raise GateSpecCompileError(f"GateSpec check parameters must be an object: {check_id}")
        if not isinstance(raw.get("blocking"), bool):
            raise GateSpecCompileError(f"GateSpec check blocking must be boolean: {check_id}")
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
        raise GateSpecCompileError("success_policy requires only mode")
    if success_policy.get("mode") not in {"all_blocking", "all"}:
        raise GateSpecCompileError("success_policy.mode must be all_blocking or all")
    return {"checks": normalized_checks, "success_policy": dict(success_policy)}


def _nonempty_string(value: Any, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise GateSpecCompileError(f"{name} must be a non-empty string up to {maximum} characters")
    return value.strip()
