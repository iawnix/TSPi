"""JSON Schema validation for workspace contract files."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry, Resource


CONTRACT_DIR = Path(__file__).resolve().parent / "contracts"


class SchemaValidationError(ValueError):
    """Raised when a JSON instance does not match a local contract schema."""


def validate_contract(schema_name: str, instance: Any) -> None:
    """Validate one JSON-like value against a local contract schema."""

    errors = _sorted_errors(schema_name, instance)
    if errors:
        raise SchemaValidationError(_summarize_errors(schema_name, errors))


def schema_findings(schema_name: str, instance: Any, source: str) -> list[dict[str, str]]:
    """Return validator-compatible findings for one contract schema."""

    return [
        {
            "severity": "error",
            "code": "schema_validation_failed",
            "message": f"{schema_name}: {error.message}",
            "path": _source_path(source, error.absolute_path),
        }
        for error in _sorted_errors(schema_name, instance)
    ]


def check_all_contract_schemas() -> None:
    """Validate every bundled contract schema against Draft 2020-12."""

    for name in _schema_names():
        _validator(name)


@lru_cache(maxsize=None)
def _schema_names() -> tuple[str, ...]:
    return tuple(sorted(path.name for path in CONTRACT_DIR.glob("*.schema.json")))


@lru_cache(maxsize=None)
def _schema(name: str) -> dict[str, Any]:
    path = CONTRACT_DIR / name
    if not path.exists():
        raise SchemaValidationError(f"unknown contract schema: {name}")
    with path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    if not isinstance(schema, dict):
        raise SchemaValidationError(f"contract schema must be an object: {name}")
    return schema


@lru_cache(maxsize=1)
def _registry() -> Registry:
    registry = Registry()
    for name in _schema_names():
        registry = registry.with_resource(name, Resource.from_contents(_schema(name)))
    return registry


@lru_cache(maxsize=None)
def _validator(schema_name: str) -> Draft202012Validator:
    schema = _schema(schema_name)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise SchemaValidationError(f"invalid contract schema {schema_name}: {exc.message}") from exc
    return Draft202012Validator(schema, registry=_registry())


def _sorted_errors(schema_name: str, instance: Any) -> list[ValidationError]:
    expanded = [
        leaf
        for error in _validator(schema_name).iter_errors(instance)
        for leaf in _leaf_errors(error)
    ]
    unique = {
        (
            tuple(error.absolute_path),
            tuple(error.absolute_schema_path),
            error.message,
        ): error
        for error in expanded
    }
    return sorted(
        unique.values(),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            tuple(str(part) for part in error.absolute_schema_path),
        ),
    )


def _leaf_errors(error: ValidationError) -> list[ValidationError]:
    if not error.context:
        return [error]
    leaves = [leaf for child in error.context for leaf in _leaf_errors(child)]
    if error.validator not in {"oneOf", "anyOf"}:
        return leaves
    parent_path = tuple(error.absolute_path)
    relevant = [
        leaf
        for leaf in leaves
        if not (leaf.validator == "type" and tuple(leaf.absolute_path) == parent_path)
    ]
    if relevant:
        return relevant
    return leaves


def _summarize_errors(schema_name: str, errors: list[ValidationError]) -> str:
    shown = [f"{_source_path('$', error.absolute_path)}: {error.message}" for error in errors[:3]]
    if len(errors) > 3:
        shown.append(f"... {len(errors) - 3} more schema error(s)")
    return f"{schema_name} validation failed; " + "; ".join(shown)


def _source_path(source: str, parts: Iterable[Any]) -> str:
    path = source
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        elif _simple_key(str(part)):
            path += f".{part}"
        else:
            path += f"[{part!r}]"
    return path


def _simple_key(value: str) -> bool:
    return value.replace("_", "").isalnum() and bool(value)
