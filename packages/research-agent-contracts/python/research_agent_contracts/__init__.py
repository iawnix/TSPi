"""Schema reader and validator for the language-neutral research contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from jsonschema import Draft202012Validator


CONTRACT_NAMES: Final[tuple[str, ...]] = (
    "agent_turn_request",
    "agent_turn_result",
    "research_turn_request",
    "research_turn_result",
    "tool_result",
    "tool_error",
    "capability_descriptor",
    "notification_request",
    "notification_result",
    "artifact_manifest",
)
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_DIR = _PACKAGE_ROOT / "schemas"


class ContractError(ValueError):
    """Raised when a contract name or document is invalid."""


def schema_names() -> tuple[str, ...]:
    return CONTRACT_NAMES


def read_schema(name: str) -> dict[str, Any]:
    if name not in CONTRACT_NAMES:
        raise ContractError(f"unknown research agent contract: {name}")
    path = _SCHEMA_DIR / f"{name}.schema.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read research agent contract: {name}") from exc
    if not isinstance(value, dict) or value.get("$id") != name:
        raise ContractError(f"invalid research agent contract schema: {name}")
    return value


def validate(name: str, document: Any) -> None:
    """Validate one document against the canonical schema, raising ContractError."""

    schema = read_schema(name)
    error = next(Draft202012Validator(schema).iter_errors(document), None)
    if error is not None:
        location = ".".join(str(part) for part in error.absolute_path)
        suffix = f" at {location}" if location else ""
        raise ContractError(f"{name} contract validation failed{suffix}: {error.message}")


def validate_protocol(document: Any, name: str) -> dict[str, Any]:
    validate(name, document)
    return document


__all__ = ["CONTRACT_NAMES", "ContractError", "read_schema", "schema_names", "validate", "validate_protocol"]
