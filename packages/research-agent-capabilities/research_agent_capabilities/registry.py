"""Provider registry independent of any execution backend."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Iterable, Protocol

from .descriptors import CapabilityDescriptor


class RegistryError(ValueError):
    """Base error for provider registry failures."""


class DuplicateCapabilityError(RegistryError):
    """Raised when a capability version is registered twice."""


class CapabilityNotFoundError(RegistryError):
    """Raised when a capability version cannot be resolved."""


class CapabilityModeNotSupportedError(RegistryError):
    """Raised when a capability is not admitted in a workspace mode."""


class CapabilityProvider(Protocol):
    provider_id: str

    def descriptors(self) -> Iterable[CapabilityDescriptor]:
        """Return declarative descriptors owned by this provider."""


@dataclass(frozen=True)
class ProviderRegistration:
    descriptor: CapabilityDescriptor
    provider_id: str
    provider: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "descriptor": self.descriptor.to_dict(),
        }


class ProviderRegistry:
    """Thread-safe registry keyed by ``(capability_id, version)``."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], ProviderRegistration] = {}
        self._providers: dict[str, Any] = {}
        self._lock = RLock()

    def register_provider(self, provider: CapabilityProvider, *, replace: bool = False) -> tuple[ProviderRegistration, ...]:
        """Discover and register one provider atomically.

        Discovery is intentionally limited to the provider object's
        ``descriptors()`` method. Loading modules, selecting environments, and
        invoking an implementation remain Host responsibilities.
        """
        provider_id, entries = self._prepare_provider(provider)
        with self._lock:
            self._commit(provider, provider_id, entries, replace=replace)
        return entries

    def register_providers(
        self,
        providers: Iterable[CapabilityProvider],
        *,
        replace: bool = False,
    ) -> tuple[ProviderRegistration, ...]:
        """Discover and register several providers as one catalog update."""
        prepared = tuple((provider, *self._prepare_provider(provider)) for provider in providers)
        flattened = tuple(entry for _, _, entries in prepared for entry in entries)
        keys = tuple(entry.descriptor.key for entry in flattened)
        if len(keys) != len(set(keys)):
            raise DuplicateCapabilityError("providers returned duplicate capability versions")
        provider_ids = tuple(provider_id for _, provider_id, _ in prepared)
        if len(provider_ids) != len(set(provider_ids)):
            raise RegistryError("providers returned duplicate provider IDs")
        with self._lock:
            if not replace:
                duplicate = next((key for key in keys if key in self._entries), None)
                if duplicate is not None:
                    raise DuplicateCapabilityError(f"capability already registered: {duplicate[0]}@{duplicate[1]}")
            for provider, provider_id, entries in prepared:
                self._commit(provider, provider_id, entries, replace=replace)
        return flattened

    def _prepare_provider(self, provider: CapabilityProvider) -> tuple[str, tuple[ProviderRegistration, ...]]:
        provider_id = getattr(provider, "provider_id", None)
        descriptors_method = getattr(provider, "descriptors", None)
        if not isinstance(provider_id, str) or not provider_id:
            raise RegistryError("provider_id is required")
        if not callable(descriptors_method):
            raise RegistryError("provider must expose descriptors()")
        descriptors = tuple(descriptors_method())
        entries = tuple(self._entry(provider, provider_id, descriptor) for descriptor in descriptors)
        keys = tuple(entry.descriptor.key for entry in entries)
        if len(keys) != len(set(keys)):
            raise DuplicateCapabilityError("provider returned duplicate capability versions")
        return provider_id, entries

    def _commit(
        self,
        provider: CapabilityProvider,
        provider_id: str,
        entries: tuple[ProviderRegistration, ...],
        *,
        replace: bool,
    ) -> None:
        keys = tuple(entry.descriptor.key for entry in entries)
        existing_entries = tuple(
            (key, self._entries[key]) for key in keys if key in self._entries
        )
        if existing_entries and not replace:
            key, _ = existing_entries[0]
            raise DuplicateCapabilityError(f"capability already registered: {key[0]}@{key[1]}")
        if replace:
            displaced = next(
                ((key, entry) for key, entry in existing_entries if entry.provider_id != provider_id),
                None,
            )
            if displaced is not None:
                key, entry = displaced
                raise DuplicateCapabilityError(
                    f"capability {key[0]}@{key[1]} belongs to provider {entry.provider_id}"
                )
            # Replacing a provider is a complete catalog update for that
            # provider. Remove descriptors it no longer advertises so stale
            # provider implementations cannot survive a hot reload.
            for key, entry in tuple(self._entries.items()):
                if entry.provider_id == provider_id:
                    del self._entries[key]
        self._entries.update({entry.descriptor.key: entry for entry in entries})
        self._providers[provider_id] = provider

    def register_descriptor(
        self,
        descriptor: CapabilityDescriptor,
        provider: Any,
        *,
        replace: bool = False,
    ) -> ProviderRegistration:
        provider_id = getattr(provider, "provider_id", None)
        if not isinstance(provider_id, str) or provider_id != descriptor.provider_id:
            raise RegistryError("descriptor provider_id does not match provider")
        entry = self._entry(provider, provider_id, descriptor)
        with self._lock:
            existing = self._entries.get(entry.descriptor.key)
            if existing is not None and not replace:
                raise DuplicateCapabilityError(
                    f"capability already registered: {descriptor.capability_id}@{descriptor.version}"
                )
            if existing is not None and existing.provider_id != provider_id:
                raise DuplicateCapabilityError(
                    f"capability {descriptor.capability_id}@{descriptor.version} belongs to provider {existing.provider_id}"
                )
            self._entries[entry.descriptor.key] = entry
            self._providers[provider_id] = provider
        return entry

    def unregister_provider(self, provider_id: str) -> bool:
        """Remove all descriptors owned by a provider, if present."""
        if not isinstance(provider_id, str) or not provider_id:
            raise RegistryError("provider_id is required")
        with self._lock:
            if provider_id not in self._providers:
                return False
            for key, entry in tuple(self._entries.items()):
                if entry.provider_id == provider_id:
                    del self._entries[key]
            del self._providers[provider_id]
            return True

    def provider_ids(self) -> tuple[str, ...]:
        """Return registered provider IDs without exposing implementation data."""
        with self._lock:
            return tuple(self._providers)

    def registered_providers(self) -> tuple[tuple[str, Any], ...]:
        """Return Host-owned provider objects for inspection or lifecycle control."""
        with self._lock:
            return tuple(self._providers.items())

    def resolve(self, capability_id: str, version: str = "1") -> ProviderRegistration | None:
        with self._lock:
            return self._entries.get((capability_id, version))

    def require(self, capability_id: str, version: str = "1") -> ProviderRegistration:
        entry = self.resolve(capability_id, version)
        if entry is None:
            raise CapabilityNotFoundError(f"capability is not registered: {capability_id}@{version}")
        return entry

    def resolve_for_workspace_mode(
        self, capability_id: str, workspace_mode: str, version: str = "1"
    ) -> ProviderRegistration | None:
        entry = self.resolve(capability_id, version)
        if entry is None:
            return None
        if workspace_mode not in entry.descriptor.supported_workspace_modes:
            raise CapabilityModeNotSupportedError(
                f"capability is not supported in workspace mode: {capability_id}@{version} ({workspace_mode})"
            )
        return entry

    def require_for_workspace_mode(
        self, capability_id: str, workspace_mode: str, version: str = "1"
    ) -> ProviderRegistration:
        entry = self.resolve_for_workspace_mode(capability_id, workspace_mode, version)
        if entry is None:
            raise CapabilityNotFoundError(f"capability is not registered: {capability_id}@{version}")
        return entry

    def registrations(self) -> tuple[ProviderRegistration, ...]:
        with self._lock:
            return tuple(self._entries.values())

    def descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        return tuple(entry.descriptor for entry in self.registrations())

    @staticmethod
    def _entry(provider: Any, provider_id: str, descriptor: Any) -> ProviderRegistration:
        if not isinstance(descriptor, CapabilityDescriptor):
            raise RegistryError("provider descriptors must be CapabilityDescriptor values")
        if descriptor.provider_id != provider_id:
            raise RegistryError("descriptor provider_id does not match provider")
        return ProviderRegistration(descriptor, provider_id, provider)
