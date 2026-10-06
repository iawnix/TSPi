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
    if operation == "create":
        value = params.get("content", "")
        payload = value.encode("utf-8") if isinstance(value, str) else bytes(value)
        artifact_id = _id(payload, supplied)
        return {**store.put_bytes(artifact_id, payload, media_type=params.get("mediaType", "application/octet-stream")).as_dict(), "provenance": {"name": params.get("name"), "node_id": params.get("node_id") or params.get("nodeId"), "producer_attempt_id": params.get("producer_attempt_id") or params.get("job_id") or params.get("jobId")}}
    if operation == "register":
        value = params.get("path")
        if not isinstance(value, str) or not value:
            raise ValueError("artifact path is required")
        path = Path(value).expanduser()
        if not path.is_absolute(): path = root / path
        path = path.resolve()
        try: path.relative_to(root)
        except ValueError as exc: raise ValueError("artifact path escapes workspace") from exc
        payload = path.read_bytes()
        producer = params.get("producer_attempt_id") or params.get("job_id") or params.get("jobId")
        artifact_id = _id(payload, supplied, str(producer) if producer else None)
        return {**store.put_file(artifact_id, path, media_type=params.get("mediaType"), expected_sha256=params.get("sha256")).as_dict(), "provenance": {"source_path": str(path.relative_to(root)), "node_id": params.get("node_id") or params.get("nodeId"), "producer_attempt_id": params.get("producer_attempt_id") or params.get("job_id") or params.get("jobId")}}
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
        return {**store.put_bytes(artifact_id, payload, media_type="application/json").as_dict(), "derivation": descriptor, "provenance": {"input_artifact_ids": descriptor["inputs"]}}
    if operation == "link":
        return {"artifact_id": supplied, "subject_id": params.get("subject_id") or params.get("subjectId"), "relation": params.get("relation") or "evidence"}
    raise ValueError("unsupported artifact operation: " + operation)
