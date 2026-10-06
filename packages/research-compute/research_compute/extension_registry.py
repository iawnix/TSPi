"""Single bootstrap entry point for extension owned capability providers."""

from __future__ import annotations

from typing import Any


def register_extension_provider(
    provider: Any,
    *,
    provider_id: str | None = None,
    replace: bool = False,
) -> dict[str, tuple[Any, ...] | None]:
    """Register every capability kind exposed by one extension provider.

    The provider remains the sole owner of descriptors and execution hooks;
    this coordinator only installs the corresponding kind-specific indexes.
    Keeping this at the bootstrap boundary prevents applications from
    accidentally registering a compute provider while forgetting its analysis
    or artifact capabilities.
    """

    from .provider import register_compute_provider
    from .capabilities import register_capability_provider
    from .analysis import register_analysis_provider
    from .artifact_registry import register_artifact_provider

    identifier = provider_id or getattr(provider, "provider_id", None)
    result: dict[str, tuple[Any, ...] | None] = {
        "compute": None,
        "capability": None,
        "analysis": None,
        "artifact": None,
    }
    if callable(getattr(provider, "supports", None)) and getattr(provider, "backends", ()):
        register_compute_provider(provider, replace=replace)
        result["compute"] = (provider,)
    if callable(getattr(provider, "descriptors", None)) or callable(getattr(provider, "capabilities", None)):
        result["capability"] = register_capability_provider(
            provider, provider_id=identifier, replace=replace,
        )
    if callable(getattr(provider, "analysis_descriptors", None)):
        result["analysis"] = register_analysis_provider(
            provider, provider_id=identifier, replace=replace,
        )
    if callable(getattr(provider, "operations", None)):
        result["artifact"] = register_artifact_provider(
            provider, provider_id=identifier, replace=replace,
        )
    if all(value is None for value in result.values()):
        raise ValueError("extension provider exposes no registered capability kind")
    return result


__all__ = ["register_extension_provider"]
