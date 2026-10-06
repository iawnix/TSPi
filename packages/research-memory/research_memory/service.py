"""Persistent Research Memory projections and bounded context construction."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class ProjectionWriter(Protocol):
    def write_projection(self, root: str | Path, context: dict[str, Any], liveness: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ContextPack:
    revision: int
    context: dict[str, Any]
    liveness: dict[str, Any]
    memory: dict[str, Any]
    schema_version: str = "research_context_pack_1"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "revision": self.revision,
            "context": self.context,
            "liveness": self.liveness,
            "memory": self.memory,
            "provenance": {"source": "research_memory", "authority": "research_state", "memory_revision": self.memory.get("revision", 0)},
        }


class ResearchContextBuilder:
    """Read State and its projection to construct a bounded context pack."""

    def build(self, root: str | Path) -> ContextPack:
        from research_state import read_context, read_liveness
        state = read_context(root)
        liveness = read_liveness(root)
        memory = _read_memory(Path(root))
        memory.setdefault("schema_version", "research_memory_index_1")
        memory.setdefault("authority", "research_memory")
        memory.setdefault("scope", "workspace")
        memory.setdefault("research_obligations", state.get("research_obligations", []))
        memory["projection_stale"] = memory.get("revision", 0) != int(state.get("revision", 0))
        return ContextPack(int(state.get("revision", 0)), state, liveness, memory)


class ResearchMemoryService(ResearchContextBuilder):
    def project(self, root: str | Path, state: dict[str, Any], revision: int | None = None) -> dict[str, Any]:
        liveness = {"lifecycle": state.get("lifecycle", "idle"), "disposition": state.get("disposition"), "checkpoint_id": state.get("checkpoint_id")}
        return FileProjectionWriter().write_projection(root, state, liveness, revision=revision)


def _projection_payload(context: dict[str, Any], liveness: dict[str, Any], revision: int | None = None, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    revision_value = int(context.get("revision", revision or 0))
    previous = previous if isinstance(previous, dict) else {}
    return {
        "schema_version": "research_memory_index_1", "workspace_id": context.get("workspace_id"),
        "scope": "workspace", "authority": "research_memory", "state_authority": "research_state",
        "revision": revision_value, "context_revision": revision_value,
        "lifecycle": liveness.get("lifecycle", context.get("lifecycle", "idle")),
        "disposition": liveness.get("disposition", context.get("disposition")),
        "checkpoint_id": liveness.get("checkpoint_id", context.get("checkpoint_id")),
        "waiting_external": liveness.get("waiting_external", []), "decision_needed": liveness.get("decision_needed", []),
        "focus": context.get("focus", {}),
        "research_obligations": context.get("research_obligations", []),
        "entries": previous.get("entries", []) if isinstance(previous.get("entries", []), list) else [],
    }


class FileProjectionWriter:
    """Atomically rebuild ``memory/index.json`` from a committed State view."""

    def write_projection(self, root: str | Path, context: dict[str, Any], liveness: dict[str, Any] | None = None, *, revision: int | None = None) -> dict[str, Any]:
        root = Path(root)
        payload = _projection_payload(context, liveness or {}, revision=revision, previous=_read_memory(root))
        path = root / "memory" / "index.json"
        # Research State's TransactionCoordinator captures this projection in
        # the same redo record as context/liveness/manifest.  Outside a state
        # transaction, write_json retains the existing atomic writer behavior.
        try:
            from research_state.transactions import write_json
        except ImportError:
            write_json = None
        if write_json is not None:
            write_json(path, payload)
            return payload
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".index.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try: os.unlink(temporary)
            except FileNotFoundError: pass
        return payload


def _read_memory(root: Path) -> dict[str, Any]:
    try:
        value = json.loads((root / "memory" / "index.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"schema_version": "research_memory_index_1", "revision": 0, "entries": []}
    return value if isinstance(value, dict) else {"schema_version": "research_memory_index_1", "revision": 0, "entries": []}


def install_state_projection_writer() -> None:
    from research_state import register_projection_writer
    register_projection_writer(FileProjectionWriter())


__all__ = ["ProjectionWriter", "ContextPack", "ResearchContextBuilder", "ResearchMemoryService", "FileProjectionWriter", "install_state_projection_writer"]
