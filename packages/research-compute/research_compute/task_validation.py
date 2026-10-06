"""Provider-dispatched calculation result validation.

The compute kernel owns the result envelope, while each provider owns the
meaning of parser facts and completion rules for its task types.
"""

from __future__ import annotations

from typing import Any

from .provider import ProviderUnavailable, resolve_compute_provider


def _provider_validator(backend: str, method: str):
    try:
        provider = resolve_compute_provider(backend)
    except ProviderUnavailable as exc:
        raise ValueError(str(exc)) from exc
    validator = getattr(provider, method, None)
    if not callable(validator):
        raise ValueError(f"provider {backend!r} does not expose {method}()")
    return validator


def validate_parsed_task(backend: str, task_type: str, facts: dict[str, Any]) -> dict[str, Any]:
    return _provider_validator(backend, "validate_parsed_task")(backend, task_type, facts)


def parsed_program_outcome(backend: str, facts: dict[str, Any]) -> tuple[str, str | None]:
    return _provider_validator(backend, "parsed_program_outcome")(backend, facts)
