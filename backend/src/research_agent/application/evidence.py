"""Canonical evidence payload adapter backed by ``artifact-store``."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from research_agent.artifacts import PayloadStore


def _root(params: dict[str, Any]) -> Path:
    value = params.get("workspace_root") or params.get("root")
    if not isinstance(value, str) or not value:
        raise ValueError("workspace root is required")
    root = Path(value).expanduser().resolve()
    manifest = root / "workspace_manifest.json"
    if manifest.exists():
        from research_agent.research.workspace import validate_workspace_manifest
        from research_agent.foundation.transactions import TransactionCoordinator, read_json
        with TransactionCoordinator(root).locked():
            validate_workspace_manifest(read_json(manifest), root, require_ready=True, validate_documents=False)
    return root


def _id(payload: bytes, supplied: str | None = None, provenance_key: str | None = None) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    # Job outputs retain producer identity: two Jobs producing equal
    # bytes are distinct evidence records even though their payloads match.
    generated = "art_" + hashlib.sha256(f"{provenance_key}\0{digest}".encode()).hexdigest() if provenance_key else "art_" + digest
    if supplied is not None and supplied != generated:
        raise ValueError("artifact_id does not match payload/provenance identity")
    return supplied or generated


def _store(root: Path) -> PayloadStore:
    return PayloadStore(root / "artifacts")


def dispatch(operation: str, params: dict[str, Any]) -> dict[str, Any]:
    from research_agent.foundation.transactions import workspace_transaction
    return workspace_transaction("material." + operation)(_dispatch)(params.get("workspace_root") or params.get("root"), {"operation": operation, "params": params})


def _dispatch(root, request):
    operation, params = request["operation"], request["params"]
    from .api import validate_command_params
    validate_command_params("artifact." + operation, params, transport_fields=("root", "workspace_root"))
    root = _root(params); store = _store(root)
    from research_agent.application.references import artifact_reference, resolve_artifact_reference
    supplied = params.get("artifact_id")
    if supplied is not None:
        supplied = resolve_artifact_reference(root, supplied)
    if params.get("artifact_ref") is not None:
        selected = resolve_artifact_reference(root, params["artifact_ref"])
        if supplied is not None and selected != supplied:
            raise ValueError("artifact_selector_conflict: artifact_id and artifact_ref disagree")
        supplied = selected
    if operation == "read" and (not isinstance(supplied, str) or not supplied):
        raise ValueError("artifact_selector_required: provide artifact_ref or artifact_id")
    if operation in {"create", "register"}:
        job_id = params.get("job_id")
        if job_id:
            from .execution import _receipt
            job = _receipt(root, {"job_id": job_id})
        provenance = {"job_id": job_id, **(job.metadata.get("research_binding", {}) if job_id else {})}
        input_artifact_ids = []
        if job_id:
            spec = json.loads((Path(job.cwd) / "spec.json").read_text())
            if spec.get("metadata", {}).get("input_evidence_basis"):
                input_artifact_ids = list(spec["metadata"]["input_artifact_ids"])
                provenance["derivation_executed"] = True
        if operation == "register":
            path = Path(params["path"]).expanduser()
            if not path.is_absolute(): path = root / path
            path = path.resolve()
            if not path.is_relative_to(root): raise ValueError("artifact path escapes workspace")
            if job_id:
                job_root = Path(job.cwd).resolve()
                if not path.is_relative_to(job_root):
                    raise ValueError("artifact_source_mismatch: raw Job output must be collected from its own directory")
                from research_agent.jobs.outputs import collect_outputs
                spec = json.loads((job_root / 'spec.json').read_text())
                outputs, _ = collect_outputs(job_root, spec.get('outputs', []))
                allowed = {(job_root / item['path']).resolve() for item in outputs if item.get('exists')}
                allowed.update((job_root / 'logs' / name).resolve() for name in ('stdout.log', 'stderr.log'))
                if path not in allowed:
                    raise ValueError("artifact_source_mismatch: path is not a declared collected Job output")
            payload = path.read_bytes()
            provenance["source_path"] = str(path.relative_to(root))
        else:
            if job_id:
                raise ValueError("artifact_source_mismatch: agent-created text is not raw Job output")
            value = params.get("content", "")
            payload = value.encode("utf-8") if isinstance(value,str) else bytes(value)
            provenance["name"] = params.get("name")
        expected = params.get("sha256")
        if expected and expected.removeprefix("sha256:") != hashlib.sha256(payload).hexdigest():
            raise ValueError("artifact digest does not match expected sha256")
        artifact_id = _id(payload, supplied, json.dumps(provenance, sort_keys=True))
        result = {**store.put_bytes(artifact_id,payload,media_type=params.get("media_type","application/octet-stream")).as_dict(),
                  "provenance":provenance}
        from research_agent.artifacts.registry import register_manifest
        from .job_state import persist_event
        register_manifest(root, {**result, "input_artifact_ids": input_artifact_ids})
        result["artifact_ref"] = artifact_reference(root, artifact_id)
        binding = job.metadata.get("research_binding", {}) if job_id else {}
        persist_event(root, kind="material", title=provenance.get("name") or provenance.get("source_path", "Research material"),
            content=f"Material {result['artifact_ref']} registered" + (f" from Job {job_id}." if job_id else "."),
            data=result, references=[artifact_id], identity=["material", artifact_id], **binding)
        return result
    if operation == "read":
        artifact_id = supplied
        payload = store.read_bytes(artifact_id)
        offset = params.get("offset", 0); limit = params.get("limit", 16000)
        if not isinstance(offset, int) or offset < 0: raise ValueError("offset must be non-negative")
        if type(limit) is not int or not 1 <= limit <= 1_000_000: raise ValueError("limit must be 1..1000000")
        view = payload[offset:offset + limit]
        from research_agent.application.references import annotate_artifact_references
        return annotate_artifact_references(root, {**store.receipt(artifact_id).as_dict(), "content": view.decode("utf-8", errors="replace"), "next_offset": offset + len(view) if offset + len(view) < len(payload) else None})
    raise ValueError("unsupported artifact operation: " + operation)
