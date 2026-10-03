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


class ContextBuilder:
    """Read State and its projection to construct a bounded context pack."""

    def build(self, root: str | Path) -> ContextPack:
        from research_state import read_context, read_liveness
        state = read_context(root)
        liveness = read_liveness(root)
        memory = _read_memory(Path(root))
        memory.setdefault("schema_version", "research_memory_index_1")
        memory.setdefault("authority", "research_memory")
        memory.setdefault("scope", "workspace")
        memory["projection_stale"] = memory.get("revision", 0) != int(state.get("revision", 0))
        return ContextPack(int(state.get("revision", 0)), state, liveness, memory)


class ResearchMemoryService(ContextBuilder):
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
        "focus": context.get("focus", {}), "entries": previous.get("entries", []) if isinstance(previous.get("entries", []), list) else [],
    }


class FileProjectionWriter:
    """Atomically rebuild ``memory/index.json`` from a committed State view."""

    def write_projection(self, root: str | Path, context: dict[str, Any], liveness: dict[str, Any] | None = None, *, revision: int | None = None) -> dict[str, Any]:
        root = Path(root)
        payload = _projection_payload(context, liveness or {}, revision=revision, previous=_read_memory(root))
        path = root / "memory" / "index.json"
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


class AgentSessionMemory:
    """Session notes, separate from persistent scientific Research Memory."""

    def __init__(self, root: str | Path, session_id: str):
        self.root = Path(root); self.session_id = session_id

    @property
    def path(self) -> Path:
        return self.root / "memory" / "sessions" / f"{self.session_id}.jsonl"

    def append(self, entry: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(entry, dict): raise TypeError("session memory entry must be an object")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        value = {"session_id": self.session_id, "authority": "agent_session", **entry}
        with self.path.open("a", encoding="utf-8") as handle: handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        return value

    def read(self, limit: int = 128) -> list[dict[str, Any]]:
        if limit < 0: raise ValueError("limit must be non-negative")
        try: rows = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except FileNotFoundError: return []
        return rows[-limit:] if limit else []


__all__ = ["ProjectionWriter", "ContextPack", "ContextBuilder", "ResearchMemoryService", "FileProjectionWriter", "AgentSessionMemory", "install_state_projection_writer"]
