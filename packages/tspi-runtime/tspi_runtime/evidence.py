"""Canonical evidence payload adapter backed by ``artifact-store``."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from artifact_store import PayloadStore


def _root(params: dict[str, Any]) -> Path:
    value = params.get("workspace_root") or params.get("root")
    if not isinstance(value, str) or not value:
        raise ValueError("workspace root is required")
    return Path(value).expanduser().resolve()


def _id(payload: bytes, supplied: str | None = None, provenance_key: str | None = None) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    # Attempt outputs retain producer identity: two attempts producing equal
    # bytes are distinct evidence records even though their payloads match.
    generated = "art_" + hashlib.sha256(f"{provenance_key}\0{digest}".encode()).hexdigest() if provenance_key else "art_" + digest
    if supplied is not None and supplied != generated:
        raise ValueError("artifact_id does not match payload/provenance identity")
    return supplied or generated


def _store(root: Path) -> PayloadStore:
    return PayloadStore(root / "artifacts")


def dispatch(operation: str, params: dict[str, Any]) -> dict[str, Any]:
    root = _root(params); store = _store(root)
    supplied = params.get("artifact_id") or params.get("artifactId")
    if operation in {"create", "register"}:
        producer = params.get("producer_attempt_id")
        job_id = params.get("job_id") or params.get("jobId")
        node_id = params.get("node_id") or params.get("nodeId")
        if job_id:
            from .execution import _receipt
            job = _receipt(root, {"jobId":job_id})
            if producer and producer != job.attempt_id: raise ValueError("Artifact producer disagrees with Job")
            producer = job.attempt_id
            if node_id and job.node_id and node_id != job.node_id: raise ValueError("Artifact node disagrees with Job")
            node_id = node_id or job.node_id
        provenance = {"node_id":node_id, "producer_attempt_id":producer, "job_id":job_id}
        if operation == "register":
            path = Path(params["path"]).expanduser()
            if not path.is_absolute(): path = root / path
            path = path.resolve()
            if not path.is_relative_to(root): raise ValueError("artifact path escapes workspace")
            payload = path.read_bytes()
            provenance["source_path"] = str(path.relative_to(root))
        else:
            value = params.get("content", "")
            payload = value.encode("utf-8") if isinstance(value,str) else bytes(value)
            provenance["name"] = params.get("name")
        expected = params.get("sha256")
        if expected and expected.removeprefix("sha256:") != hashlib.sha256(payload).hexdigest():
            raise ValueError("artifact digest does not match expected sha256")
        artifact_id = _id(payload, supplied, str(producer or job_id) if (producer or job_id) else None)
        result = {**store.put_bytes(artifact_id,payload,media_type=params.get("mediaType","application/octet-stream")).as_dict(),
                  "provenance":provenance}
        from research_state.agent_workspace import has_state_files
        if has_state_files(root):
            from .job_state import change, context
            old = next((a for a in context(root)["artifacts"] if a["id"]==artifact_id), None)
            if old is None:
                change(root,"artifact:"+artifact_id,[{"type":"register_artifact","id":artifact_id,
                    "node_id":node_id,"producer_attempt_id":producer,"location":result["location"],
                    "sha256":result["sha256"],"size_bytes":result["size_bytes"],"metadata":provenance}])
        return result
    if operation == "read":
        artifact_id = supplied
        payload = store.read_bytes(artifact_id)
        offset = params.get("offset", 0); limit = params.get("limit")
        if not isinstance(offset, int) or offset < 0: raise ValueError("offset must be non-negative")
        view = payload[offset:] if limit is None else payload[offset:offset + int(limit)]
        return {**store.receipt(artifact_id).as_dict(), "content": view.decode("utf-8", errors="replace")}
    if operation == "derive":
        descriptor = {"operation": params.get("operation"), "inputs": params.get("input_artifact_ids") or params.get("inputArtifactIds") or [], "parameters": params.get("parameters") or {}}
        payload = json.dumps(descriptor, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        artifact_id = _id(payload, supplied)
        return {**store.put_bytes(artifact_id, payload, media_type="application/json").as_dict(), "derivation": descriptor, "executed": False, "kind": "derivation_descriptor", "provenance": {"input_artifact_ids": descriptor["inputs"]}}
    if operation == "link":
        from .job_state import change, context
        subject = params.get("subject_id") or params.get("subjectId")
        ctx = context(root)
        subject_type = next((kind for kind in ("claim","finding","gate") if any(x["id"]==subject for x in ctx[kind+"s"])), None)
        if not subject_type: raise ValueError("unknown evidence subject")
        relation = params.get("relation") or "documents"
        identity = hashlib.sha256(f"{supplied}:{subject}:{relation}".encode()).hexdigest()
        link = {"type":"link_evidence","id":"evidence_"+identity,"artifact_id":supplied,
                "subject_type":subject_type,"subject_id":subject,"relation":relation}
        change(root,"artifact-link:"+identity,[link])
        return link
    raise ValueError("unsupported artifact operation: " + operation)
