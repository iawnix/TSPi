from __future__ import annotations
import json, hashlib, tempfile, os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
class ProjectionWriter(Protocol):
    def write_projection(self, root: str | Path, state: dict[str, Any], revision: int) -> dict[str, Any]: ...
@dataclass(frozen=True)
class ContextPack:
    revision: int; context: dict[str, Any]; liveness: dict[str, Any]; memory: dict[str, Any]
class ContextBuilder:
    def build(self, root: str | Path) -> ContextPack:
        from research_state import read_context, read_liveness
        state=read_context(root); live=read_liveness(root); return ContextPack(int(state.get("revision",0)),state,live,_read_memory(Path(root)))
class ResearchMemoryService(ContextBuilder):
    def project(self, root: str | Path, state: dict[str, Any], revision: int | None = None) -> dict[str, Any]:
        return FileProjectionWriter().write_projection(root,state,int(state.get("revision",revision or 0)))
class FileProjectionWriter:
    def write_projection(self, root: str | Path, state: dict[str, Any], revision: int) -> dict[str, Any]:
        root=Path(root); payload={"schema_version":"research_memory_index_1","revision":revision,"state_digest":hashlib.sha256(json.dumps(state,sort_keys=True,separators=(",",":")).encode()).hexdigest(),"focus":state.get("focus",{}),"claims":state.get("claims",[]),"nodes":state.get("nodes",[]),"findings":state.get("findings",[]),"gates":state.get("gates",[]),"evidence_links":state.get("evidence_links",[])}
        path=root/"memory"/"index.json"; path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix=".index.",suffix=".tmp",dir=path.parent)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as f: json.dump(payload,f,ensure_ascii=False,indent=2,sort_keys=True); f.write("\n"); f.flush(); os.fsync(f.fileno())
            os.replace(tmp,path)
        finally:
            try: os.unlink(tmp)
            except FileNotFoundError: pass
        return payload
def _read_memory(root: Path)->dict[str,Any]:
    try:return json.loads((root/"memory"/"index.json").read_text(encoding="utf-8"))
    except (FileNotFoundError,json.JSONDecodeError):return {"schema_version":"research_memory_index_1","revision":0}

class StateProjectionWriter:
    def write_projection(self, root, context, liveness):
        root=Path(root); previous=_read_memory(root)
        payload={"schema_version":"research_memory_index_1","workspace_id":context.get("workspace_id"),"scope":"workspace","authority":"research_state","revision":context.get("revision",0),"context_revision":context.get("revision",0),"lifecycle":liveness.get("lifecycle","idle"),"disposition":liveness.get("disposition"),"checkpoint_id":liveness.get("checkpoint_id"),"waiting_external":liveness.get("waiting_external",[]),"decision_needed":liveness.get("decision_needed",[]),"focus":context.get("focus",{}),"entries":previous.get("entries",[]) if isinstance(previous.get("entries",[]),list) else []}
        path=root/"memory"/"index.json"; path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(prefix=".index.",suffix=".tmp",dir=path.parent)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as f: json.dump(payload,f,ensure_ascii=False,indent=2,sort_keys=True); f.write("\n"); f.flush(); os.fsync(f.fileno())
            os.replace(tmp,path)
        finally:
            try: os.unlink(tmp)
            except FileNotFoundError: pass

def install_state_projection_writer():
    from research_state import register_projection_writer
    register_projection_writer(StateProjectionWriter())

class SessionMemory:
    """Append-only per-session memory that is rebuildable from State revisions."""
    def __init__(self, root: str | Path, session_id: str):
        self.root=Path(root); self.session_id=session_id
    @property
    def path(self): return self.root/'memory'/'sessions'/f'{self.session_id}.jsonl'
    def append(self, entry: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(entry,dict): raise TypeError('session memory entry must be an object')
        self.path.parent.mkdir(parents=True,exist_ok=True); value={"session_id":self.session_id,**entry}
        with self.path.open('a',encoding='utf-8') as f: f.write(json.dumps(value,ensure_ascii=False,sort_keys=True)+'\n')
        return value
    def read(self, limit: int = 128) -> list[dict[str, Any]]:
        if limit < 0: raise ValueError('limit must be non-negative')
        try: rows=[json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines() if line.strip()]
        except FileNotFoundError: return []
        return rows[-limit:] if limit else []
