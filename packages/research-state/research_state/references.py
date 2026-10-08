"""Workspace-owned exact references to immutable preparation and evidence.

The index allocates names only. Scientific Artifact identity and provenance
remain in Research State; preparing a request creates no Attempt or finding.
All registry writes share the workspace transaction and recovery boundary.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re

from .transactions import TransactionCoordinator, _safe_path, read_json, state_transaction, write_json

_REFERENCE = re.compile(r"^([ap])([1-9][0-9]*)$")
_INDEX = "operations/references/index.json"
_REQUEST_FIELDS = {"request_id", "work_id", "command", "platform", "environment", "inputs", "outputs", "metadata", "timeout_seconds"}
_REFERENCE_FIELDS = {"artifact_id", "artifact_ref", "source_ref", "source_refs", "evidence_refs", "basis_refs",
                     "direct_evidence_refs", "comparison_evidence_refs", "background_evidence_refs",
                     "input_artifact_ids", "output_artifact_ids", "artifact_refs"}


class ReferenceError(ValueError):
    def __init__(self, code, message, candidates=()):
        self.code = code
        self.candidates = list(candidates)
        suffix = f"; available references: {', '.join(self.candidates)}" if self.candidates else ""
        super().__init__(f"{code}: {message}{suffix}")


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _index(root):
    path = _safe_path(root, _INDEX)
    try:
        value = read_json(path)
    except FileNotFoundError:
        return {"schema_version": "research-references/1", "next_id": 1, "identities": {}}
    if (value.get("schema_version") != "research-references/1" or type(value.get("next_id")) is not int
            or value["next_id"] < 1 or not isinstance(value.get("identities"), dict)):
        raise ReferenceError("reference_registry_invalid", "invalid workspace reference index")
    return value


def _record_path(root, ref):
    if not isinstance(ref, str) or not _REFERENCE.fullmatch(ref):
        raise ReferenceError("reference_invalid", "use an exact prepared_ref (pN) or artifact_ref (aN)")
    return _safe_path(root, f"operations/references/records/{ref}.json")


def _record(root, ref, kind):
    prefix = {"artifact": "a", "prepared_job": "p"}[kind]
    path = _record_path(root, ref)
    if not ref.startswith(prefix):
        raise ReferenceError("reference_type_mismatch", f"{ref} is not a {kind} reference")
    index = _index(root)
    candidates = [value for value in index["identities"].values() if value.startswith(prefix)][-8:]
    try:
        value = read_json(path)
    except FileNotFoundError as exc:
        raise ReferenceError("reference_not_found", f"unknown exact reference {ref}; select a returned reference", candidates) from exc
    if (value.get("schema_version") != "research-reference/1" or value.get("ref") != ref
            or value.get("kind") != kind or index["identities"].get(f"{kind}:{value.get('identity')}") != ref):
        raise ReferenceError("reference_registry_invalid", f"reference {ref} disagrees with its registry")
    return value


def _register(root, kind, identity, payload):
    index = _index(root)
    key = f"{kind}:{identity}"
    existing = index["identities"].get(key)
    if existing is not None:
        record = _record(root, existing, kind)
        if record["payload"] != payload:
            raise ReferenceError("reference_rebinding_forbidden", f"immutable reference {existing} has different content")
        return existing
    prefix = {"artifact": "a", "prepared_job": "p"}[kind]
    ref = prefix + str(index["next_id"])
    path = _record_path(root, ref)
    if path.exists():
        raise ReferenceError("reference_registry_invalid", f"allocated reference {ref} already exists")
    index["next_id"] += 1
    index["identities"][key] = ref
    write_json(path, {"schema_version": "research-reference/1", "ref": ref, "kind": kind,
                      "identity": identity, "payload": payload})
    write_json(_safe_path(root, _INDEX), index)
    return ref


def _workspace(root):
    # Reuse canonical workspace validation and the read-your-writes context.
    from .agent_workspace import read_context
    path = TransactionCoordinator(root).root
    read_context(path)
    return path


@state_transaction("job.prepare")
def prepare_job(root, params=None):
    """Capture a reviewed file and pin every input before handing back a name."""
    params = params or {}
    root = _workspace(root)
    request_file = params.get("request_file")
    if not isinstance(request_file, str) or not request_file:
        raise ReferenceError("prepared_request_required", "request_file is required")
    path = Path(request_file).expanduser()
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ReferenceError("prepared_request_invalid", "request_file must be a file inside the workspace")
    encoded = path.read_bytes()
    if len(encoded) > 1_000_000:
        raise ReferenceError("prepared_request_invalid", "request_file exceeds 1 MB")
    request = json.loads(encoded)
    if (not isinstance(request, dict) or set(request) - _REQUEST_FIELDS
            or not isinstance(request.get("request_id"), str) or not request["request_id"]
            or not isinstance(request.get("command"), list) or not request["command"]
            or any(not isinstance(arg, str) or not arg for arg in request["command"])):
        raise ReferenceError("prepared_request_invalid", "request must have a stable request_id and argv command")
    request.setdefault("work_id", "work_" + _digest(request)[:48])
    if not isinstance(request["work_id"], str) or not request["work_id"]:
        raise ReferenceError("prepared_request_invalid", "work_id must be a nonempty string")
    from job_runtime.inputs import content_digest
    inputs = request.get("inputs", [])
    if not isinstance(inputs, list):
        raise ReferenceError("prepared_request_invalid", "inputs must be an array")
    pinned = []
    for item in inputs:
        item = {"source": item} if isinstance(item, str) else copy.deepcopy(item)
        if not isinstance(item, dict) or not isinstance(item.get("source"), str):
            raise ReferenceError("prepared_request_invalid", "each input needs a source path")
        source = Path(item["source"]).expanduser()
        source = (source if source.is_absolute() else root / source).resolve()
        if not source.exists():
            raise ReferenceError("prepared_input_missing", str(source))
        digest = content_digest(source)
        if item.get("sha256") not in {None, digest}:
            raise ReferenceError("prepared_input_changed", "an input changed; re-prepare its request")
        item.update(source=str(source), sha256=digest)
        pinned.append(item)
    request["inputs"] = pinned
    payload = {"source_path": str(path.relative_to(root)), "source_sha256": hashlib.sha256(encoded).hexdigest(),
               "request_sha256": _digest(request), "request": request}
    ref = _register(root, "prepared_job", _digest(payload), payload)
    return {"prepared_ref": ref, "request_id": request["request_id"], "work_id": request["work_id"],
            "request_sha256": payload["request_sha256"]}


def resolve_prepared_job(root, params):
    """Resolve the immutable snapshot; mutable input content must still match."""
    allowed = {"prepared_ref", "node_id", "timeout_seconds", "repeat", "root", "workspace_root"}
    if set(params) - allowed:
        raise ReferenceError("prepared_override_forbidden", "edit and re-prepare to change a captured request")
    with TransactionCoordinator(root).locked():
        root = _workspace(root)
        record = _record(root, params.get("prepared_ref"), "prepared_job")
        payload = record["payload"]
        request = copy.deepcopy(payload["request"])
        if _digest(payload) != record["identity"] or _digest(request) != payload["request_sha256"]:
            raise ReferenceError("prepared_snapshot_changed", "the registered request snapshot is corrupt")
        from job_runtime.inputs import content_digest
        for item in request.get("inputs", []):
            source = Path(item["source"])
            if not source.exists() or content_digest(source) != item["sha256"]:
                raise ReferenceError("prepared_input_changed", "an input changed; prepare a new reference before submission")
        for key in ("node_id", "timeout_seconds", "repeat"):
            if key in params:
                request[key] = copy.deepcopy(params[key])
        return request


@state_transaction("reference.artifact")
def _artifact_reference(root, params):
    root = _workspace(root)
    from .agent_workspace import read_context
    artifact = next((row for row in read_context(root)["artifacts"] if row["id"] == params["artifact_id"]), None)
    if artifact is None:
        raise ReferenceError("artifact_not_registered", "register the Artifact before requesting its reference")
    return _register(root, "artifact", artifact["id"], {"artifact_id": artifact["id"], "sha256": artifact.get("sha256")})


def artifact_reference(root, artifact_id):
    return _artifact_reference(root, {"artifact_id": artifact_id})


def resolve_artifact_reference(root, value):
    if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
        return value  # Canonical identity validation belongs to its consumer.
    with TransactionCoordinator(root).locked():
        root = TransactionCoordinator(root).root
        record = _record(root, value, "artifact")
        from .agent_workspace import read_context
        artifact = next((row for row in read_context(root)["artifacts"] if row["id"] == record["identity"]), None)
        if artifact is None or artifact.get("sha256") != record["payload"].get("sha256"):
            raise ReferenceError("artifact_reference_stale", f"{value} no longer identifies its registered Artifact version")
        return artifact["id"]


def resolve_operation_references(root, operations):
    """Expand reference-valued fields only; prose and object identities stay verbatim."""
    def visit(value, reference=False):
        if isinstance(value, str):
            return resolve_artifact_reference(root, value) if reference else value
        if isinstance(value, list):
            return [visit(item, reference) for item in value]
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                target = "artifact_id" if key == "artifact_ref" else key
                expanded = visit(item, key in _REFERENCE_FIELDS)
                if target in result and result[target] != expanded:
                    raise ReferenceError("artifact_selector_conflict", "artifact_id and artifact_ref disagree")
                result[target] = expanded
            return result
        return value
    return visit(operations)


def annotate_artifact_references(root, value):
    """Read-only projection: expose existing names without allocating on reads."""
    with TransactionCoordinator(root).locked():
        index = _index(TransactionCoordinator(root).root)
        def visit(item):
            if isinstance(item, list):
                return [visit(row) for row in item]
            if isinstance(item, dict):
                result = {key: visit(row) for key, row in item.items()}
                identity = item.get("artifact_id", item.get("id"))
                ref = index["identities"].get(f"artifact:{identity}")
                if ref:
                    result["artifact_ref"] = ref
                return result
            return item
        return visit(value)
