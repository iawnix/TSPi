"""Read facade for canonical Research Agent workspace Memory.

``ResearchMemoryService`` reads the admitted filesystem workspace through the
same boundary used by Host and Agent Runtime.  It never creates or selects a
JSON/SQLite ResearchMap store.  ``KernelMemoryStore`` remains available only
as an explicit typed adapter for isolated domain code; callers must opt into it
directly when working with a non-runtime fixture.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from .kernel import ResearchKernel, ResearchKernelError
from .model import ResearchMap


def _filesystem_map(context: dict[str, Any]) -> ResearchMap:
    """Convert the canonical filesystem context into the typed read model.

    ``context.json`` is the only Research Memory source used by the current
    runtime.  The conversion is read-only and never writes a legacy map or
    opens a SQLite repository.
    """

    focus = context.get("focus") if isinstance(context.get("focus"), dict) else {}
    document = dict(context)
    document.update({
        "schema_version": "research-map/1",
        "map_id": context.get("map_id") or f"map_{context.get('workspace_id', '')}",
        "title": context.get("title") or context.get("workspace_id") or "Research workspace",
        "focus_claim_ids": list(focus.get("claim_ids", [])),
        "focus_node_ids": list(focus.get("node_ids", [])),
    })
    return ResearchMap.from_dict(document)


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


class FilesystemMemoryStore:
    """Read-only MemoryStore adapter for an admitted Agent workspace.

    The adapter deliberately has no ``ResearchKernel`` member.  Context and
    liveness are loaded through the filesystem workspace boundary, keeping
    Memory aligned with Host/Agent Runtime and preventing a silent fallback to
    ``research_map.json`` or ``research.db``.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().absolute()

    def _context(self) -> dict[str, Any]:
        from .agent_workspace import read_context

        return read_context(self.root)

    def _liveness(self) -> dict[str, Any]:
        from .agent_workspace import read_liveness

        return read_liveness(self.root)

    def load(self) -> ResearchMap:
        return _filesystem_map(self._context())

    def load_read_only(self) -> ResearchMap:
        return self.load()

    def decision_records(self, *, claim_id: str | None = None, limit: int = 128) -> dict[str, Any]:
        context = self._context()
        records = [
            {**item, "decision_type": decision_type}
            for key, decision_type in (
                ("strategy_plans", "strategy_plan"),
                ("strategy_reviews", "strategy_review"),
                ("attempt_interpretations", "attempt_interpretation"),
            )
            for item in context.get(key, [])
            if isinstance(item, dict)
        ]
        if claim_id is not None:
            records = [item for item in records if item.get("claim_id") == claim_id]
        return {
            "schema_version": "research-decisions/1",
            "claim_id": claim_id,
            "records": records[:limit],
        }

    def evidence_records(
        self,
        *,
        record_type: str | None = None,
        node_id: str | None = None,
        artifact_id: str | None = None,
        subject_id: str | None = None,
        limit: int = 128,
    ) -> dict[str, Any]:
        context = self._context()
        groups = {"attempt": "attempts", "artifact": "artifacts", "link": "evidence_links"}
        names = [groups[record_type]] if record_type in groups else list(groups.values())
        records = [
            item
            for name in names
            for item in context.get(name, [])
            if isinstance(item, dict)
        ]
        filters = {
            "node_id": node_id,
            "artifact_id": artifact_id,
            "subject_id": subject_id,
        }
        for field, expected in filters.items():
            if expected is None:
                continue
            records = [
                item for item in records
                if item.get(field) == expected
                or (isinstance(item.get("subject"), dict) and item["subject"].get(field) == expected)
                or (isinstance(item.get(f"{field}s"), list) and expected in item[f"{field}s"])
            ]
        return {
            "schema_version": "research-evidence/1",
            "record_type": record_type,
            "records": records[:limit],
        }


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
        # The canonical runtime stores Memory in the admitted filesystem
        # workspace.  A caller that still supplies ``KernelMemoryStore`` is an
        # explicit legacy adapter and is never selected implicitly.
        self.store: MemoryStore = store or FilesystemMemoryStore(self.root)
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
    """Read the Host-owned context projection from the canonical workspace."""

    from .agent_workspace import read_context

    return read_context(root)


def _default_liveness_reader(research_map: ResearchMap, root: Path) -> dict[str, Any]:
    """Read the restart-safe lifecycle projection from the canonical workspace."""

    from .agent_workspace import read_liveness

    return read_liveness(root)


__all__ = [
    "ContextReader",
    "FilesystemMemoryStore",
    "KernelMemoryStore",
    "LivenessReader",
    "MemoryStore",
    "ResearchMemoryService",
]
