"""Lightweight validation for immutable calculation contracts.

This module deliberately lives at the package root.  Workspace, Web, and
Compute readers can validate an Attempt without importing the Compute package
initializer (which exposes optional NumPy/RDKit-backed artifact helpers).
The JSON files under ``compute/contracts`` remain the single schema source;
this module only provides a dependency-neutral loader and the shared intent /
result binding rule.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from ts_agent.io import sha256_json


CONTRACT_DIR = Path(__file__).resolve().parent / "compute" / "contracts"


class CalculationContractError(ValueError):
    """Raised when an immutable calculation document is not trustworthy."""


def validate_calculation_contract(schema_name: str, instance: Any) -> None:
    """Validate one bundled calculation schema and report bounded paths."""

    errors = sorted(
        _validator(schema_name).iter_errors(instance),
        key=lambda error: tuple(str(part) for part in error.path),
    )
    if not errors:
        return
    shown = []
    for error in errors[:3]:
        location = "$" + "".join(f"[{part!r}]" for part in error.path)
        shown.append(f"{location}: {error.message}")
    if len(errors) > 3:
        shown.append(f"... {len(errors) - 3} more schema error(s)")
    raise CalculationContractError(f"{schema_name} validation failed; " + "; ".join(shown))


def validate_calculation_result_binding(
    intent: dict[str, Any],
    result: dict[str, Any],
    *,
    label: str = "calculation result",
) -> None:
    """Validate a result and bind it to its immutable calculation intent."""

    validate_calculation_contract("calculation_result.schema.json", result)
    provenance = result.get("provenance")
    if (
        result.get("intent_id") != intent.get("intent_id")
        or result.get("node_id") != intent.get("node_id")
        or result.get("capability") != intent.get("capability")
        or result.get("capability_version") != intent.get("capability_version")
        or result.get("expected_output_roles") != intent.get("expected_output_roles")
        or not isinstance(provenance, dict)
        or provenance.get("intent_digest") != sha256_json(intent)
        or provenance.get("capability") != intent.get("capability")
        or provenance.get("capability_version") != intent.get("capability_version")
        or provenance.get("capability_descriptor_digest") != intent.get("capability_descriptor_digest")
    ):
        raise CalculationContractError(f"{label} is not bound to the prepared calculation intent")


@lru_cache(maxsize=None)
def _validator(schema_name: str) -> Draft202012Validator:
    schema = _schema(schema_name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=_registry())


@lru_cache(maxsize=None)
def _schema(schema_name: str) -> dict[str, Any]:
    path = CONTRACT_DIR / schema_name
    if not path.exists():
        raise CalculationContractError(f"unknown calculation contract: {schema_name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CalculationContractError(f"cannot read calculation contract: {schema_name}") from exc
    if not isinstance(value, dict):
        raise CalculationContractError(f"calculation contract must be an object: {schema_name}")
    return value


@lru_cache(maxsize=1)
def _registry() -> Registry:
    registry = Registry()
    for path in sorted(CONTRACT_DIR.glob("*.schema.json")):
        registry = registry.with_resource(path.name, Resource.from_contents(_schema(path.name)))
    return registry
