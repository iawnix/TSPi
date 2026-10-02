"""Generic isolated Provider contracts and JSONL dispatcher."""
from .protocol import PROVIDER_PROTOCOL_VERSION, CapabilityDescriptor, ProviderError, ProviderRequest, ProviderResult, load_descriptor, validate_descriptor
from .runner import run_jsonl_provider
__all__=["PROVIDER_PROTOCOL_VERSION","CapabilityDescriptor","ProviderError","ProviderRequest","ProviderResult","load_descriptor","validate_descriptor","run_jsonl_provider"]
