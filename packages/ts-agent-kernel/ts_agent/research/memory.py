"""Research Memory service boundaries.

``ResearchMemoryService`` is the stable read facade used by Hosts and context
builders.  It deliberately does not introduce another persistence layer:
``MemoryStore`` owns access to the canonical records and the default adapter is
just a thin wrapper around :class:`ResearchKernel`.

The service returns read models as dictionaries, while ``MemoryStore`` keeps
the canonical ``ResearchMap``/metadata API available for typed callers.  A
context or liveness reader can be injected by a Host, which keeps this module
independent from the prompt/context assembly implementation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from .kernel import ResearchKernel, ResearchKernelError
from .model import ResearchMap


@runtime_checkable
class MemoryStore(Protocol):
    """Minimal persistence boundary for Research Memory.

    Implementations must expose canonical records only.  Context and
    liveness are projections and belong to ``ResearchMemoryService`` (or an
    injected Host-owned reader), not to a second database.
    """

    def load(self) -> ResearchMap:
        """Load the authoritative ResearchMap."""

    def load_read_only(self) -> ResearchMap:
        """Load the authoritative map without acquiring a write lock."""

    def decision_records(self, *, claim_id: str | None = None, limit: int = 128) -> dict[str, Any]:
        """Read bounded Decision Memory records."""

    def evidence_records(
        self,
        *,
        record_type: str | None = None,
        node_id: str | None = None,
        artifact_id: str | None = None,
        subject_id: str | None = None,
        limit: int = 128,
    ) -> dict[str, Any]:
        """Read bounded Evidence Memory metadata."""


class KernelMemoryStore:
    """Adapt the current ResearchKernel to the MemoryStore protocol."""

    def __init__(self, kernel: ResearchKernel):
        if not isinstance(kernel, ResearchKernel):
            raise TypeError("KernelMemoryStore requires a ResearchKernel")
        self.kernel = kernel

    def load(self) -> ResearchMap:
        return self.kernel.load()

    def load_read_only(self) -> ResearchMap:
        return self.kernel.load_read_only()

    def decision_records(self, *, claim_id: str | None = None, limit: int = 128) -> dict[str, Any]:
        return self.kernel.decision_records(claim_id=claim_id, limit=limit)

    def evidence_records(
        self,
        *,
        record_type: str | None = None,
        node_id: str | None = None,
        artifact_id: str | None = None,
        subject_id: str | None = None,
        limit: int = 128,
    ) -> dict[str, Any]:
        return self.kernel.evidence_records(
            record_type=record_type,
            node_id=node_id,
            artifact_id=artifact_id,
            subject_id=subject_id,
            limit=limit,
        )


ContextReader = Callable[[ResearchMap, Path], dict[str, Any]]
LivenessReader = Callable[[ResearchMap, Path], dict[str, Any]]


class ResearchMemoryService:
    """Unified read facade over Scientific, Evidence, and Decision Memory.

    ``ResearchMemoryService`` has no independent state store.  Its ``root``
    and ``store`` identify the source of truth; returned context/liveness
    payloads are ephemeral projections and may be regenerated at any time.
    ``context_reader`` and ``liveness_reader`` are explicit seams for a Host's
    ContextBuilder and lifecycle implementation.  Until those are supplied,
    the service adapts the existing canonical API read models lazily.
    """

    schema_version = "research-memory-service/1"

    def __init__(
        self,
        root: str | Path,
        *,
        store: MemoryStore | None = None,
        context_reader: ContextReader | None = None,
        liveness_reader: LivenessReader | None = None,
    ) -> None:
        self.root = Path(root).expanduser().absolute()
        self.store: MemoryStore = store or KernelMemoryStore(ResearchKernel(self.root))
        if not isinstance(self.store, MemoryStore):
            raise TypeError("store does not implement MemoryStore")
        self._context_reader = context_reader
        self._liveness_reader = liveness_reader

    @property
    def kernel(self) -> ResearchKernel | None:
        """Return the backing Kernel for compatibility adapters, if present."""

        store = self.store
        return store.kernel if isinstance(store, KernelMemoryStore) else None

    def read(self, *, read_only: bool = True) -> ResearchMap:
        """Read the authoritative ResearchMap object.

        The object is intentionally returned as the domain model rather than a
        duplicated serialized snapshot.  Call ``to_dict`` at a transport
        boundary when JSON is required.
        """

        return self.store.load_read_only() if read_only else self.store.load()

    def context(self) -> dict[str, Any]:
        """Build the bounded Agent context projection."""

        research_map = self.read()
        reader = self._context_reader or _default_context_reader
        return reader(research_map, self.root)

    def liveness(self) -> dict[str, Any]:
        """Build the compact Host lifecycle projection."""

        research_map = self.read()
        reader = self._liveness_reader or _default_liveness_reader
        return reader(research_map, self.root)

    def decisions(self, *, claim_id: str | None = None, limit: int = 128) -> dict[str, Any]:
        """Read bounded Decision Memory without exposing the store itself."""

        return self.store.decision_records(claim_id=claim_id, limit=limit)

    def evidence(
        self,
        *,
        record_type: str | None = None,
        node_id: str | None = None,
        artifact_id: str | None = None,
        subject_id: str | None = None,
        limit: int = 128,
    ) -> dict[str, Any]:
        """Read bounded Evidence Memory metadata and provenance references."""

        return self.store.evidence_records(
            record_type=record_type,
            node_id=node_id,
            artifact_id=artifact_id,
            subject_id=subject_id,
            limit=limit,
        )

    def read_projection(self, mode: str, **filters: Any) -> Any:
        """Dispatch the stable read modes used by Host transports.

        ``map``/``summary`` are intentionally small convenience projections;
        callers needing focused object detail should continue using the
        canonical command API rather than making this facade a second query
        language.
        """

        if mode == "map":
            return self.read().to_dict()
        if mode == "summary":
            research_map = self.read()
            return {
                "schema_version": "research-summary/1",
                "map_id": research_map.map_id,
                "title": research_map.title,
                "revision": research_map.revision,
                "progress": research_map.progress(),
                "ready_node_ids": [node.id for node in research_map.ready_nodes()],
                "focus_claim_ids": list(research_map.focus_claim_ids),
                "focus_node_ids": list(research_map.focus_node_ids),
            }
        if mode == "context":
            return self.context()
        if mode == "liveness":
            return self.liveness()
        if mode == "decisions":
            return self.decisions(claim_id=filters.get("claim_id"), limit=filters.get("limit", 128))
        if mode == "evidence":
            return self.evidence(
                record_type=filters.get("record_type"),
                node_id=filters.get("node_id"),
                artifact_id=filters.get("artifact_id"),
                subject_id=filters.get("subject_id"),
                limit=filters.get("limit", 128),
            )
        raise ResearchKernelError(f"unsupported Research Memory read mode: {mode}")


def _default_context_reader(research_map: ResearchMap, root: Path) -> dict[str, Any]:
    """Build with the extracted ContextBuilder during the compatibility period."""

    from .context import ContextBuilder
    from ts_agent.api import _research_liveness, _runtime_status

    runtime = _runtime_status(root)
    return ContextBuilder().build(
        research_map,
        liveness=_research_liveness(research_map, root, runtime=runtime),
        runtime=runtime,
    )


def _default_liveness_reader(research_map: ResearchMap, root: Path) -> dict[str, Any]:
    """Bridge to the current API read model until lifecycle is extracted."""

    from ts_agent.api import _research_liveness

    return _research_liveness(research_map, root)


__all__ = ["ContextReader", "KernelMemoryStore", "LivenessReader", "MemoryStore", "ResearchMemoryService"]
