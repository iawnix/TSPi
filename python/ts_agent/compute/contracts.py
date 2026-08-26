"""JSON contracts for calculation intents and operational results."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


CONTRACT_DIR = Path(__file__).resolve().parent / "contracts"


class ComputeContractError(ValueError):
    """Raised when a compute request crosses the operational contract."""


def validate_compute_contract(schema_name: str, instance: Any) -> None:
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
    raise ComputeContractError(f"{schema_name} validation failed; " + "; ".join(shown))


@lru_cache(maxsize=None)
def _validator(schema_name: str) -> Draft202012Validator:
    schema = _schema(schema_name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=_registry())


@lru_cache(maxsize=None)
def _schema(schema_name: str) -> dict[str, Any]:
    path = CONTRACT_DIR / schema_name
    if not path.exists():
        raise ComputeContractError(f"unknown compute contract: {schema_name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ComputeContractError(f"compute contract must be an object: {schema_name}")
    return value


@lru_cache(maxsize=1)
def _registry() -> Registry:
    registry = Registry()
    for path in sorted(CONTRACT_DIR.glob("*.schema.json")):
        registry = registry.with_resource(path.name, Resource.from_contents(_schema(path.name)))
    return registry
