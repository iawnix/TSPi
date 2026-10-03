"""Independent-process JSONL provider protocol and runner."""

from .protocol import (
    PROVIDER_PROTOCOL_VERSION,
    CapabilityDescriptor,
    ProviderError,
    ProviderRequest,
    ProviderResult,
    digest,
    load_descriptor,
    validate_descriptor,
)
from .runner import run_jsonl_provider

__all__ = [
    "PROVIDER_PROTOCOL_VERSION",
    "CapabilityDescriptor",
    "ProviderError",
    "ProviderRequest",
    "ProviderResult",
    "digest",
    "load_descriptor",
    "run_jsonl_provider",
    "validate_descriptor",
]
