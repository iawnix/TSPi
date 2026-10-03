"""Runtime registration for executable and analytical capabilities.

The research and execution kernels only need a small, stable descriptor
registry.  Providers can register descriptors at application startup without
editing a central dispatch table.  Execution adapters remain provider-owned;
the registry stores the provider object only as an association and never
invokes it while answering catalog queries.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable, Generic, Iterable, Protocol, TypeVar


T = TypeVar("T")
Key = tuple[str, str]


class CapabilityRegistryError(ValueError):
    """Base error for invalid capability registrations."""


class DuplicateCapabilityError(CapabilityRegistryError):
    """Raised when a descriptor is registered without an explicit replace."""

    def __init__(self, capability: str, version: str) -> None:
        self.capability = capability
        self.version = version
        super().__init__(f"capability already registered: {capability}@{version}")


@dataclass(frozen=True)
class CapabilityRegistration(Generic[T]):
    """Descriptor plus the provider that owns its implementation."""

    descriptor: T
    provider_id: str
    provider: Any = None


class CapabilityProvider(Protocol[T]):
    """Structural contract for provider packages discovered at startup."""

    provider_id: str

    def descriptors(self) -> Iterable[T]:
        ...


class ExecutionCapabilityProvider(CapabilityProvider[T], Protocol[T]):
    """Provider contract for a calculation adapter.

    ``validate_inputs`` is optional at runtime; when present it receives
    keyword arguments ``workspace``, ``intent`` and ``inputs``.  ``prepare``
    (or the legacy spelling ``prepare_task``) must return a
    :class:`~chemical_runtime.backends.base.PreparedTask`.  This protocol is kept
    structural so third-party packages do not import a framework base class.
    """

    def prepare(self, task: Any) -> Any:
        ...


class CapabilityRegistry(Generic[T]):
    """Thread-safe registry keyed by a descriptor's id and version.

    ``key`` lets this registry serve both the dataclass descriptors used by
    calculations and the mapping descriptors used by analysis capabilities.
    A registration is deliberately process-local: installation discovery and
    environment readiness belong to their respective managers, not here.
    """

    def __init__(
        self,
        *,
        key: Callable[[T], Key] | None = None,
    ) -> None:
        self._key = key or _descriptor_key
        self._entries: dict[Key, CapabilityRegistration[T]] = {}
        self._lock = RLock()

    def register(
        self,
        descriptor: T,
        *,
        provider_id: str = "builtin",
        provider: Any = None,
        replace: bool = False,
    ) -> CapabilityRegistration[T]:
        """Register one descriptor and return its immutable registration."""

        entry = CapabilityRegistration(descriptor, provider_id, provider)
        key = self._validated_key(descriptor)
        with self._lock:
            if key in self._entries and not replace:
                raise DuplicateCapabilityError(*key)
            self._entries[key] = entry
        return entry

    def register_many(
        self,
        descriptors: Iterable[T],
        *,
        provider_id: str = "builtin",
        provider: Any = None,
        replace: bool = False,
    ) -> tuple[CapabilityRegistration[T], ...]:
        """Register a provider's descriptors atomically.

        Validation and duplicate checks happen before mutating the registry,
        so a malformed provider cannot leave a partially installed catalog.
        """

        entries = tuple(CapabilityRegistration(item, provider_id, provider) for item in descriptors)
        keys = tuple(self._validated_key(entry.descriptor) for entry in entries)
        if len(set(keys)) != len(keys):
            duplicate = next(key for key in keys if keys.count(key) > 1)
            raise DuplicateCapabilityError(*duplicate)
        with self._lock:
            if not replace:
                duplicate = next((key for key in keys if key in self._entries), None)
                if duplicate is not None:
                    raise DuplicateCapabilityError(*duplicate)
            self._entries.update(dict(zip(keys, entries)))
        return entries

    def register_provider(
        self,
        provider: Any,
        *,
        provider_id: str | None = None,
        replace: bool = False,
    ) -> tuple[CapabilityRegistration[T], ...]:
        """Register descriptors exposed by a provider object.

        Providers may expose either ``descriptors()`` or ``capabilities()``;
        the latter is accepted so a provider can mirror its public catalog
        terminology.  No provider code is called during catalog reads.
        """

        source = getattr(provider, "descriptors", None)
        if source is None:
            source = getattr(provider, "capabilities", None)
        if not callable(source):
            raise CapabilityRegistryError("provider must expose descriptors() or capabilities()")
        identifier = provider_id or getattr(provider, "provider_id", None) or getattr(provider, "name", None)
        if not isinstance(identifier, str) or not identifier:
            raise CapabilityRegistryError("provider_id is required for an unnamed provider")
        return self.register_many(source(), provider_id=identifier, provider=provider, replace=replace)

    def resolve(self, capability: str, version: str = "1") -> CapabilityRegistration[T] | None:
        with self._lock:
            return self._entries.get((capability, version))

    def registrations(self) -> tuple[CapabilityRegistration[T], ...]:
        with self._lock:
            # Dict insertion order preserves the established built-in catalog
            # order while still making provider additions deterministic.
            return tuple(self._entries.values())

    def descriptors(self) -> tuple[T, ...]:
        return tuple(entry.descriptor for entry in self.registrations())

    def find(self, predicate: Callable[[T], bool]) -> tuple[CapabilityRegistration[T], ...]:
        return tuple(entry for entry in self.registrations() if predicate(entry.descriptor))

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _validated_key(self, descriptor: T) -> Key:
        capability, version = self._key(descriptor)
        if (
            not isinstance(capability, str)
            or not isinstance(version, str)
            or not capability
            or not version
        ):
            raise CapabilityRegistryError("descriptor capability and version must be non-empty strings")
        return capability, version


def _descriptor_key(descriptor: Any) -> Key:
    if isinstance(descriptor, dict):
        capability, version = descriptor.get("capability"), descriptor.get("version")
    else:
        capability, version = getattr(descriptor, "capability", None), getattr(descriptor, "version", None)
    if not isinstance(capability, str) or not isinstance(version, str):
        raise CapabilityRegistryError("descriptor must expose string capability and version")
    return capability, version


__all__ = [
    "CapabilityRegistration",
    "CapabilityProvider",
    "ExecutionCapabilityProvider",
    "CapabilityRegistry",
    "CapabilityRegistryError",
    "DuplicateCapabilityError",
]
