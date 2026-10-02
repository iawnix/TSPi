"""Generic isolated Provider contracts and JSONL dispatcher."""
from .protocol import CapabilityDescriptor, ProviderError, ProviderRequest, ProviderResult, load_descriptor, validate_descriptor
from .runner import run_jsonl_provider
from .dispatcher import ProviderDispatcher
__all__=["CapabilityDescriptor","ProviderError","ProviderRequest","ProviderResult","load_descriptor","validate_descriptor","run_jsonl_provider","ProviderDispatcher"]
