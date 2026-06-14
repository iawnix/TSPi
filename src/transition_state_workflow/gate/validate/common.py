"""Shared read-only primitives for ChemGate validation."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from transition_state_workflow.util.path_utils import clean_string, list_or_empty

from .contracts import Finding


def clean_string_list(values: Iterable[Any]) -> list[str]:
    """Return cleaned, non-empty string values in input order."""

    out: list[str] = []
    for value in values:
        text = clean_string(value)
        if text:
            out.append(text)
    return out


def clean_string_set(values: Iterable[Any]) -> set[str]:
    """Return cleaned, non-empty string values as a set."""

    return set(clean_string_list(values))


def require_list_field(
    payload: dict[str, Any],
    field: str,
    findings: list[Finding],
    *,
    code: str,
    message: str,
    path: str,
) -> list[Any]:
    """Return a list field or append a validation finding and return an empty list."""

    raw_value = payload.get(field)
    if not isinstance(raw_value, list):
        findings.append(Finding("error", code, message, path=path))
        return []
    return list_or_empty(raw_value)


def iter_object_records(
    records: Iterable[Any],
    findings: list[Finding],
    *,
    code: str,
    message_template: str,
    path: str,
) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield object records while reporting non-object entries consistently."""

    for index, item in enumerate(records):
        if not isinstance(item, dict):
            findings.append(Finding("error", code, message_template.format(index=index), path=path))
            continue
        yield index, item


def register_unique_id(
    raw_value: Any,
    seen: set[str],
    findings: list[Finding],
    *,
    duplicate_code: str,
    duplicate_message_template: str,
    path: str,
    missing_code: str = "",
    missing_message: str = "",
    node_id: str = "",
) -> str:
    """Clean one id and append missing/duplicate findings without hiding policy."""

    value = clean_string(raw_value)
    if not value:
        if missing_code:
            findings.append(Finding("error", missing_code, missing_message, path=path, node_id=node_id))
        return ""
    if value in seen:
        findings.append(
            Finding(
                "error",
                duplicate_code,
                duplicate_message_template.format(value=value),
                path=path,
                node_id=node_id,
            )
        )
    else:
        seen.add(value)
    return value


def validate_known_node_ref(
    raw_value: Any,
    known_nodes: set[str],
    findings: list[Finding],
    *,
    code: str,
    message: str,
    path: str = "",
    node_id: str = "",
    allow_empty: bool = True,
) -> str:
    """Clean one node reference and append a finding when it is absent."""

    value = clean_string(raw_value)
    finding_node_id = node_id or value
    if not value:
        if not allow_empty:
            findings.append(Finding("error", code, message, path=path, node_id=finding_node_id))
        return ""
    if value not in known_nodes:
        findings.append(Finding("error", code, message, path=path, node_id=finding_node_id))
    return value


def evidence_ids_from_records(evidence: dict[str, Any]) -> set[str]:
    """Return cleaned evidence ids from an evidence registry-like object."""

    return {
        evidence_id
        for item in list_or_empty(evidence.get("records"))
        if isinstance(item, dict)
        for evidence_id in [clean_string(item.get("evidence_id"))]
        if evidence_id
    }


def validate_evidence_refs(
    payload: dict[str, Any],
    evidence_ids: set[str],
    findings: list[Finding],
    *,
    code: str,
    message_template: str,
    path: str = "",
    node_id: str = "",
    field: str = "evidence_refs",
) -> None:
    """Validate evidence id references from a record field."""

    for ref in list_or_empty(payload.get(field)):
        ref_id = clean_string(ref)
        if ref_id and ref_id not in evidence_ids:
            findings.append(
                Finding(
                    "warning",
                    code,
                    message_template.format(ref_id=ref_id),
                    path=path,
                    node_id=node_id,
                )
            )


__all__ = [
    "clean_string_list",
    "clean_string_set",
    "require_list_field",
    "iter_object_records",
    "register_unique_id",
    "validate_known_node_ref",
    "evidence_ids_from_records",
    "validate_evidence_refs",
]
