"""Registered predicates, Gate templates, and acceptance profiles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .digests import sha256_json


Predicate = Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]]
PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATE_ROOT = PACKAGE_ROOT / "templates" / "builtin"
PROFILE_ROOT = PACKAGE_ROOT / "acceptance_profiles"


class RegistryError(ValueError):
    """Raised when a registered validation component is missing or malformed."""


@dataclass(frozen=True)
class PredicateRegistration:
    name: str
    version: str
    evaluate: Predicate


class PredicateRegistry:
    """Closed runtime registry for maintained deterministic predicates."""

    def __init__(self) -> None:
        self._items: dict[str, PredicateRegistration] = {}

    def register(self, name: str, version: str, evaluate: Predicate) -> None:
        if not _component_id(name) or not _version(version) or not callable(evaluate):
            raise RegistryError("predicate registration is invalid")
        if name in self._items:
            raise RegistryError(f"predicate is already registered: {name}")
        self._items[name] = PredicateRegistration(name, version, evaluate)

    def get(self, name: str) -> PredicateRegistration:
        try:
            return self._items[name]
        except KeyError as exc:
            raise RegistryError(f"predicate is not registered: {name}") from exc

    @property
    def digest(self) -> str:
        return sha256_json(
            [
                {"name": item.name, "version": item.version}
                for item in sorted(self._items.values(), key=lambda value: value.name)
            ]
        )

    @property
    def capabilities(self) -> list[dict[str, str]]:
        return [
            {"name": item.name, "version": item.version}
            for item in sorted(self._items.values(), key=lambda value: value.name)
        ]


def builtin_predicate_registry() -> PredicateRegistry:
    from .predicates.core import register_core_predicates

    registry = PredicateRegistry()
    register_core_predicates(registry)
    return registry


def load_gate_template(template_id: str, version: str) -> dict[str, Any]:
    return _load_versioned_document(
        TEMPLATE_ROOT,
        template_id,
        version,
        schema_version="ts-gate-template/1",
        id_field="template_id",
    )


def load_acceptance_profile(profile_id: str, version: str) -> dict[str, Any]:
    value = _load_versioned_document(
        PROFILE_ROOT,
        profile_id,
        version,
        schema_version="ts-acceptance-profile/1",
        id_field="profile_id",
    )
    _validate_acceptance_profile(value)
    return value


def list_gate_templates() -> list[dict[str, str]]:
    return _list_versioned_documents(TEMPLATE_ROOT, "ts-gate-template/1", "template_id")


def list_acceptance_profiles() -> list[dict[str, str]]:
    return _list_versioned_documents(PROFILE_ROOT, "ts-acceptance-profile/1", "profile_id")


def _load_versioned_document(
    root: Path,
    component_id: str,
    version: str,
    *,
    schema_version: str,
    id_field: str,
) -> dict[str, Any]:
    if not _component_id(component_id) or not _version(version):
        raise RegistryError(f"invalid registered component reference: {component_id}@{version}")
    path = root / f"{component_id}__{version}.json"
    if not path.is_file() or path.is_symlink():
        raise RegistryError(f"registered component does not exist: {component_id}@{version}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"cannot read registered component: {component_id}@{version}: {exc}") from exc
    if not isinstance(value, dict):
        raise RegistryError(f"registered component must be an object: {component_id}@{version}")
    if value.get("schema_version") != schema_version:
        raise RegistryError(f"registered component schema mismatch: {component_id}@{version}")
    if value.get(id_field) != component_id or value.get("version") != version:
        raise RegistryError(f"registered component identity mismatch: {component_id}@{version}")
    return value


def _list_versioned_documents(root: Path, schema_version: str, id_field: str) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    for path in sorted(root.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict) or value.get("schema_version") != schema_version:
            continue
        component_id = value.get(id_field)
        version = value.get("version")
        if isinstance(component_id, str) and isinstance(version, str):
            values.append({id_field: component_id, "version": version, "digest": sha256_json(value)})
    return values


def _validate_acceptance_profile(value: dict[str, Any]) -> None:
    expected = {
        "schema_version",
        "profile_id",
        "version",
        "title",
        "required_dimensions",
        "require_all_attached_specs",
        "block_on_open_finding_severity",
    }
    if set(value) != expected:
        raise RegistryError("acceptance profile fields are invalid")
    if not isinstance(value.get("title"), str) or not value["title"].strip():
        raise RegistryError("acceptance profile title is invalid")
    dimensions = value.get("required_dimensions")
    if (
        not isinstance(dimensions, list)
        or any(not _component_id(item) for item in dimensions)
        or len(dimensions) != len(set(dimensions))
    ):
        raise RegistryError("acceptance profile required_dimensions are invalid")
    if not isinstance(value.get("require_all_attached_specs"), bool):
        raise RegistryError("acceptance profile require_all_attached_specs is invalid")
    blocker_severities = value.get("block_on_open_finding_severity")
    if (
        not isinstance(blocker_severities, list)
        or any(item not in {"blocking", "warning", "informational"} for item in blocker_severities)
        or len(blocker_severities) != len(set(blocker_severities))
    ):
        raise RegistryError("acceptance profile blocker severities are invalid")


def _component_id(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and len(value) <= 128 and all(
        char.isalnum() or char in "._-" for char in value
    )


def _version(value: Any) -> bool:
    return _component_id(value)
