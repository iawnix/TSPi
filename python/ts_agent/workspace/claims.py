"""Immutable Claim pre-registration helpers."""

from __future__ import annotations

from typing import Any

from ts_agent.io import sha256_json


PREREGISTRATION_FIELDS = (
    "question",
    "claim_type",
    "statement",
    "scope",
    "uncertainty",
    "assumptions",
    "predictions",
    "falsifiers",
)


def claim_preregistration_snapshot(claim: dict[str, Any]) -> dict[str, Any]:
    """Return the immutable scientific standard fixed when a Claim is created."""

    return {field: claim.get(field) for field in PREREGISTRATION_FIELDS}


def claim_preregistration_digest(claim: dict[str, Any]) -> str:
    return sha256_json(claim_preregistration_snapshot(claim))


def claim_is_testable(claim: dict[str, Any]) -> bool:
    predictions = claim.get("predictions")
    falsifiers = claim.get("falsifiers")
    return (
        isinstance(predictions, list)
        and bool(predictions)
        and all(isinstance(item, str) and bool(item.strip()) for item in predictions)
        and isinstance(falsifiers, list)
        and bool(falsifiers)
        and all(isinstance(item, str) and bool(item.strip()) for item in falsifiers)
    )
