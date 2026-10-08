"""Durable user-input provenance supplied by the Host, separate from model text."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from .transactions import read_json, state_transaction, write_json


def read_source(root, source_ref):
    if not isinstance(source_ref, str) or not re.fullmatch(r"user_[0-9a-f]{64}", source_ref):
        raise ValueError("requirement_source_invalid")
    value = read_json(Path(root) / "operations/user-inputs" / (source_ref + ".json"))
    text = value.get("text")
    if (value.get("schema_version") != "research-user-input/1" or value.get("source_ref") != source_ref
            or value.get("origin") != "host_user" or value.get("role") != "user" or not isinstance(text, str)
            or value.get("sha256") != "sha256:" + hashlib.sha256(text.encode()).hexdigest()):
        raise ValueError("requirement_source_corrupt")
    return value


@state_transaction("research.source")
def record_source(root, request):
    from .agent_workspace import apply_change, read_context
    from .write_origin import runtime_write
    root = Path(root).resolve()
    for field in ("session_id", "message_id", "text"):
        if not isinstance(request.get(field), str) or not request[field].strip():
            raise ValueError("user_input_invalid: " + field)
    if len(request["text"].encode()) > 1_000_000:
        raise ValueError("user_input_too_large")
    state = read_context(root)
    identity = "\0".join((state["workspace_id"], request["session_id"], request["message_id"]))
    source_ref = "user_" + hashlib.sha256(identity.encode()).hexdigest()
    path = root / "operations/user-inputs" / (source_ref + ".json")
    try:
        previous = read_source(root, source_ref)
    except FileNotFoundError:
        previous = None
    if previous is not None:
        if any(previous.get(field) != request[field] for field in ("session_id", "message_id", "text")):
            raise ValueError("user_input_identity_reused")
        return {"source_ref": source_ref, "recorded": True}
    value = {"schema_version": "research-user-input/1", "source_ref": source_ref,
             "workspace_id": state["workspace_id"], "session_id": request["session_id"],
             "message_id": request["message_id"], "role": "user", "origin": "host_user", "kind": "user_message",
             "text": request["text"], "sha256": "sha256:" + hashlib.sha256(request["text"].encode()).hexdigest(),
             "received_at": datetime.now(timezone.utc).isoformat()}
    write_json(path, value)
    with runtime_write():
        apply_change(root, {"principal": "root_agent", "authority": "kernel_write",
                           "operations": [{"type": "register_requirement_source", "source_ref": source_ref}]})
    return {"source_ref": source_ref, "recorded": True}


def source_records(root, *, source_ref=None, offset=0, limit=10):
    from .agent_workspace import read_context
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 32:
        raise ValueError("source_pagination_invalid")
    if source_ref:
        return {"schema_version": "research-sources/1", "records": [read_source(root, source_ref)], "next_offset": None}
    rows = read_context(root).get("requirement_sources", [])
    selected = list(reversed(rows))[offset:offset + limit]
    records = [{**read_source(root, item["source_ref"]), "coverage": item} for item in selected]
    return {"schema_version": "research-sources/1", "records": records, "total": len(rows),
            "next_offset": offset + limit if offset + limit < len(rows) else None}
