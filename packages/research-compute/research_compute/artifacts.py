"""Deterministic discovery and binding of workspace calculation artifacts.

Public callers use logical ``art_*`` identifiers. Physical paths remain an
implementation detail of this module and are frozen with a digest whenever a
calculation intent is created.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from tspi_foundation.io import read_json
from research_compute.workspace.artifacts import (
    WorkspaceArtifactError,
    artifact_for_path as workspace_artifact_for_path,
    artifact_for_ref as workspace_artifact_for_ref,
    artifact_id as workspace_artifact_id,
    list_workspace_artifacts,
    sha256_file as workspace_sha256_file,
    workspace_node_ids,
    workspace_node_records,
    workspace_root,
)
from research_compute.workspace.refs import NODE_ID
from tspi_foundation.path_safety import has_symlink_component
from research_compute.workspace.transactions import workspace_lock
from .provider import ProviderUnavailable, resolve_compute_provider
from .capabilities import CAPABILITY_REGISTRY
from .artifact_registry import (
    resolve_artifact_operation,
    artifact_operation_digest,
    validate_artifact_request,
    validate_artifact_result,
)

from .errors import ComputeContractError


CATALOG_SCHEMA_VERSION = "ts-artifact-catalog/3"
IMPORT_REQUEST_SCHEMA_VERSION = "ts-artifact-import-request/2"
IMPORT_RESULT_SCHEMA_VERSION = "ts-artifact-import-result/1"
STRUCTURE_SEED_REQUEST_SCHEMA_VERSION = "ts-create-mol-structure-request/1"
STRUCTURE_SEED_RESULT_SCHEMA_VERSION = "ts-create-mol-structure-result/1"
STRUCTURE_COMPARE_REQUEST_SCHEMA_VERSION = "ts-structure-compare-request/1"
STRUCTURE_COMPARE_RESULT_SCHEMA_VERSION = "ts-structure-compare-result/1"
STRUCTURE_COMPARISON_SCHEMA_VERSION = "ts-structure-comparison/1"
REACTION_MAPPING_VALIDATE_REQUEST_SCHEMA_VERSION = "ts-reaction-mapping-validate-request/1"
REACTION_MAPPING_VALIDATE_RESULT_SCHEMA_VERSION = "ts-reaction-mapping-validate-result/1"
REACTION_MAPPING_VALIDATE_ARTIFACT_SCHEMA_VERSION = "ts-reaction-mapping-validation/1"
MAX_IMPORT_BYTES = 128 * 1024
# Import formats are contributed by registered providers. These empty values
# remain as compatibility names for callers that imported the old constants.
IMPORT_FORMATS = frozenset()
IMPORT_FORMAT_SUFFIXES: dict[str, frozenset[str]] = {}
IMPORT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ROLE_SUFFIXES: dict[str, frozenset[str]] = {}
def list_calculation_artifacts(
    root: str | Path,
    *,
    node_id: str | None = None,
) -> dict[str, Any]:
    """Return a bounded catalog of files eligible as calculation inputs."""

    workspace = _workspace_root(root)
    known_nodes = _node_ids(workspace)
    if node_id is not None and node_id not in known_nodes:
        raise ComputeContractError(f"unknown ResearchNode: {node_id}")
    artifacts = [
        item
        for item in _catalog_items(workspace, known_nodes)
        if node_id is None or item["owner_node"] == node_id
    ]
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "workspace_root": str(workspace),
        "node_id": node_id,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


def resolve_artifact_ids(
    root: str | Path,
    artifact_ids: Iterable[str],
) -> list[dict[str, Any]]:
    """Resolve exact logical IDs to current path/digest records."""

    workspace = _workspace_root(root)
    requested = list(artifact_ids)
    if not requested or len(set(requested)) != len(requested):
        raise ComputeContractError("artifact_ids must be a non-empty unique list")
    catalog = {item["artifact_id"]: item for item in _catalog_items(workspace, _node_ids(workspace))}
    missing = [artifact_id for artifact_id in requested if artifact_id not in catalog]
    if missing:
        raise ComputeContractError("unknown artifact_id: " + ", ".join(missing))
    return [catalog[artifact_id] for artifact_id in requested]


def resolve_artifact_ref(root: str | Path, artifact_ref: str) -> dict[str, Any]:
    """Resolve one logical workspace path to its current catalog binding."""

    workspace = _workspace_root(root)
    return _artifact_for_ref(workspace, artifact_ref, _node_ids(workspace))


def import_calculation_artifact(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    """Ingest one provider-validated input through the generic artifact boundary.

    The kernel owns path safety, persistence and Research State registration;
    the registered provider owns format discovery and content semantics.
    """
    workspace = _workspace_root(root)
    normalized = _validate_import_request(request)
    with workspace_lock(workspace):
        node = _node_record(workspace, normalized["node_id"])
        if node.get("state") == "closed":
            raise ComputeContractError(
                f"artifact import requires an open ResearchNode: {normalized['node_id']}"
            )
        content = _normalize_import_content(normalized["content"])
        payload = content.encode("utf-8")
        if len(payload) > MAX_IMPORT_BYTES:
            raise ComputeContractError(f"artifact import exceeds {MAX_IMPORT_BYTES} UTF-8 bytes")
        import_provider = _registered_import_provider(normalized["format"])
        metadata = _validate_import_content(
            normalized["format"], content, normalized.get("charge"), normalized.get("multiplicity")
        )
        inputs = _node_inputs_directory(workspace, normalized["node_id"])
        path = inputs / normalized["input_name"]
        created = _write_artifact_payload(path, payload)
        artifact = _artifact_for_path(workspace, path, _node_ids(workspace))
        try:
            workspace_revision = register_artifacts_in_state(workspace, normalized["node_id"], [{
                "artifact": artifact,
                "kind": "calculation_input",
                "format": normalized["format"],
                "metadata": {
                    "input_roles": artifact.get("input_roles", []),
                    f"{getattr(import_provider, 'domain_id', 'provider')}_metadata": metadata,
                },
            }])
        except Exception:
            if created:
                path.unlink(missing_ok=True)
            raise
    return {
        "schema_version": IMPORT_RESULT_SCHEMA_VERSION,
        "operation": "import",
        "node_id": normalized["node_id"],
        "format": normalized["format"],
        "created": created,
        "workspace_revision": workspace_revision,
        f"{getattr(import_provider, 'domain_id', 'provider')}_metadata": metadata,
        "artifact": artifact,
    }


def register_artifacts_in_state(workspace: Path, node_id: str, records: list[dict[str, Any]]) -> int:
    """Atomically register generated files and return the committed revision."""
    from research_state.agent_workspace import (
        AgentWorkspaceError,
        apply_change as apply_agent_workspace_change,
        read_context as read_agent_workspace_context,
    )
    if not records:
        raise ComputeContractError("at least one artifact is required for registration")
    operations = []
    for record in records:
        artifact = record.get("artifact")
        if not isinstance(artifact, dict):
            raise ComputeContractError("artifact registration record is invalid")
        operations.append({
            "type": "register_artifact",
            "id": artifact["artifact_id"],
            "node_id": node_id,
            "kind": record.get("kind", "calculation_artifact"),
            "format": record.get("format") or artifact.get("format", "binary"),
            "location": artifact["path"],
            "sha256": artifact["sha256"],
            "size_bytes": artifact["size_bytes"],
            "input_artifact_ids": list(record.get("input_artifact_ids", [])),
            "metadata": dict(record.get("metadata") or {}),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    for attempt in range(2):
        context = read_agent_workspace_context(workspace)
        existing_by_id = {
            row.get("id"): row for row in context.get("artifacts", [])
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }
        pending = []
        for operation in operations:
            existing = existing_by_id.get(operation["id"])
            if existing is None:
                pending.append(operation)
            elif (
                existing.get("node_id") != node_id
                or existing.get("location") != operation["location"]
                or existing.get("sha256") != operation["sha256"]
            ):
                raise ComputeContractError(
                    f"Research State artifact binding conflicts with generated file: {operation['id']}"
                )
        if not pending:
            return context["revision"]
        try:
            result = apply_agent_workspace_change(workspace, {
                "principal": "root_agent", "authority": "kernel_write",
                "expected_revision": context["revision"], "operations": pending,
            })
            return result["revision"]
        except AgentWorkspaceError as exc:
            if "research_revision_mismatch" not in str(exc) or attempt:
                raise ComputeContractError(f"cannot register artifacts in canonical workspace: {exc}") from exc
    raise ComputeContractError("cannot register artifacts in canonical workspace")


def create_mol_structure_artifact(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    return _run_structure_operation("create_mol_structure", root, request)


def create_structure_comparison_artifact(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    return _run_structure_operation("structure_compare", root, request)


def create_reaction_mapping_validation_artifact(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    return _run_structure_operation("mapping_validate", root, request)


def _run_structure_operation(operation: str, root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    registration = resolve_artifact_operation(operation, "1")
    if registration is None:
        raise ComputeContractError(f"artifact operation provider unavailable: {operation}@1")
    descriptor = registration.descriptor
    provider = registration.provider
    if provider is None:
        raise ComputeContractError(f"artifact operation provider unavailable: {operation}@1")
    inputs, parameters = validate_artifact_request(descriptor, request, {})
    execute = getattr(provider, "execute_operation", None)
    if not callable(execute):
        # This fallback is intentionally provider-owned and is only used by
        # older extensions while they migrate to execute_operation().  The
        # registry lookup above remains the sole dispatch decision.
        execute = getattr(provider, "structure_operation", None)
    if not callable(execute):
        raise ComputeContractError(f"artifact provider cannot execute: {operation}@1")
    try:
        raw = execute(operation, Path(root), inputs)
    except ComputeContractError:
        raise
    except Exception as exc:
        raise ComputeContractError(f"artifact provider failed for {operation}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ComputeContractError("artifact provider result must be an object")
    envelope = {
        "operation": descriptor.operation,
        "version": descriptor.version,
        "result": raw,
        "provenance": {
            "provider_id": registration.provider_id,
            "descriptor_digest": artifact_operation_digest(
                descriptor,
                provider_id=registration.provider_id,
                provider_version=str(getattr(provider, "provider_version", "1")),
            ),
            "inputs": [{"request": inputs}],
            "outputs": _artifact_result_outputs(raw),
        },
    }
    try:
        validate_artifact_result(
            descriptor,
            envelope,
            provider_id=registration.provider_id,
            descriptor_digest=artifact_operation_digest(
                descriptor,
                provider_id=registration.provider_id,
                provider_version=str(getattr(provider, "provider_version", "1")),
            ),
        )
    except ValueError as exc:
        raise ComputeContractError(f"artifact provider result failed contract: {exc}") from exc
    return raw


def _artifact_result_outputs(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract bounded artifact references for the generic result envelope."""

    outputs: list[dict[str, Any]] = []
    for key, value in result.items():
        if not isinstance(value, dict) or "artifact_id" not in value:
            continue
        outputs.append({
            "role": key,
            "artifact_id": value.get("artifact_id"),
            "sha256": value.get("sha256", "sha256:" + "0" * 64),
        })
    return outputs[:256]


def resolve_input_artifacts(
    workspace: Path,
    supplied: list[dict[str, str]],
    required_roles: set[str],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Resolve role/ID pairs into immutable path and digest bindings."""

    by_role: dict[str, str] = {}
    for item in supplied:
        role = str(item["input_role"])
        if role in by_role:
            raise ComputeContractError(f"duplicate calculation input role: {role}")
        by_role[role] = str(item["artifact_id"])
    missing = sorted(required_roles - set(by_role))
    unexpected = sorted(set(by_role) - required_roles)
    if missing or unexpected:
        raise ComputeContractError(
            f"calculation input roles must be exactly {sorted(required_roles)}; "
            f"missing={missing}; unexpected={unexpected}"
        )

    resolved = {
        item["artifact_id"]: item
        for item in resolve_artifact_ids(workspace, by_role.values())
    }
    refs: dict[str, str] = {}
    bindings: list[dict[str, Any]] = []
    for role in sorted(required_roles):
        artifact = resolved[by_role[role]]
        if role not in artifact["input_roles"]:
            raise ComputeContractError(
                f"artifact {artifact['artifact_id']} is not compatible with input role {role}; "
                f"compatible_roles={artifact['input_roles']}"
            )
        path = str(artifact["path"])
        refs[role] = path
        bindings.append(
            {
                "input_role": role,
                "artifact_id": artifact["artifact_id"],
                "path": path,
                "sha256": artifact["sha256"],
                "owner_node": artifact["owner_node"],
                "source_intent_id": artifact["source_intent_id"],
            }
        )
    if len(set(refs.values())) != len(refs):
        raise ComputeContractError("distinct calculation input roles must bind distinct artifacts")
    return refs, bindings


def verify_input_bindings(workspace: Path, intent: dict[str, Any]) -> None:
    """Verify that a frozen input binding still identifies identical bytes."""

    refs = intent.get("input_refs")
    bindings = intent.get("input_bindings")
    if not isinstance(refs, dict) or not isinstance(bindings, list):
        raise ComputeContractError("calculation intent requires input_refs and input_bindings")
    by_role: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        if not isinstance(binding, dict):
            raise ComputeContractError("calculation input binding must be an object")
        role = binding.get("input_role")
        if not isinstance(role, str) or role in by_role:
            raise ComputeContractError(f"duplicate or invalid calculation input binding role: {role}")
        by_role[role] = binding
    if set(by_role) != set(refs):
        raise ComputeContractError("calculation input_bindings roles must match input_refs")
    known_nodes = _node_ids(workspace)
    for role, ref in sorted(refs.items()):
        binding = by_role[role]
        if binding.get("path") != ref:
            raise ComputeContractError(f"calculation input binding path mismatch for role {role}")
        current = _artifact_for_ref(workspace, str(ref), known_nodes)
        for key in ("artifact_id", "sha256", "owner_node", "source_intent_id"):
            if binding.get(key) != current.get(key):
                raise ComputeContractError(
                    f"calculation input binding changed for role {role}: {key} mismatch"
                )


def _catalog_items(workspace: Path, known_nodes: set[str]) -> list[dict[str, Any]]:
    del known_nodes
    return [_with_input_roles(item) for item in list_workspace_artifacts(workspace)]


def _registered_import_formats() -> dict[str, frozenset[str]]:
    formats: dict[str, frozenset[str]] = {}
    for registration in CAPABILITY_REGISTRY.registrations():
        provider = registration.provider
        getter = getattr(provider, "artifact_import_formats", None)
        if not callable(getter):
            continue
        values = getter()
        if not isinstance(values, dict):
            continue
        for name, suffixes in values.items():
            if isinstance(name, str) and isinstance(suffixes, (set, frozenset, tuple, list)):
                formats[name] = frozenset(str(suffix).lower() for suffix in suffixes)
    return formats


def _registered_import_provider(artifact_format: str) -> Any:
    for registration in CAPABILITY_REGISTRY.registrations():
        provider = registration.provider
        getter = getattr(provider, "artifact_import_formats", None)
        if callable(getter) and artifact_format in getter():
            return provider
    raise ComputeContractError(f"artifact import provider unavailable for format: {artifact_format}")


def _validate_import_request(request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ComputeContractError("artifact import request must be an object")
    required = {"schema_version", "node_id", "format", "input_name", "content"}
    optional = {"charge", "multiplicity"}
    missing = sorted(required - set(request))
    unexpected = sorted(set(request) - required - optional)
    if missing or unexpected:
        raise ComputeContractError(
            f"artifact import fields are invalid: missing={missing}; unexpected={unexpected}"
        )
    if request.get("schema_version") != IMPORT_REQUEST_SCHEMA_VERSION:
        raise ComputeContractError(
            f"artifact import schema_version must be {IMPORT_REQUEST_SCHEMA_VERSION}"
        )
    node_id = request.get("node_id")
    if not isinstance(node_id, str) or NODE_ID.fullmatch(node_id) is None:
        raise ComputeContractError("artifact import node_id is invalid")
    artifact_format = request.get("format")
    format_suffixes = _registered_import_formats()
    if artifact_format not in format_suffixes:
        raise ComputeContractError(
            "artifact import format must be one of: " + ", ".join(sorted(format_suffixes))
        )
    input_name = request.get("input_name")
    if not isinstance(input_name, str) or IMPORT_NAME.fullmatch(input_name) is None:
        raise ComputeContractError("artifact import input_name must be a safe filename")
    suffixes = format_suffixes[artifact_format]
    if PurePosixPath(input_name).suffix.lower() not in suffixes:
        raise ComputeContractError(
            f"artifact import input_name for {artifact_format} must end with "
            + " or ".join(sorted(suffixes))
        )
    content = request.get("content")
    if not isinstance(content, str) or not content:
        raise ComputeContractError("artifact import content must be a non-empty string")
    return dict(request)

def _normalize_import_content(content: str) -> str:
    if "\x00" in content:
        raise ComputeContractError("artifact import content cannot contain NUL bytes")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        raise ComputeContractError("artifact import content cannot be blank")
    return normalized if normalized.endswith("\n") else normalized + "\n"

def _validate_import_content(
    artifact_format: str,
    content: str,
    charge: int | None,
    multiplicity: int | None,
) -> dict[str, Any]:
    provider = _registered_import_provider(artifact_format)
    validator = getattr(provider, "validate_artifact_import", None)
    if not callable(validator):
        raise ComputeContractError(f"registered artifact provider cannot validate format: {artifact_format}")
    try:
        return validator(artifact_format, content, charge, multiplicity)
    except ComputeContractError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise ComputeContractError(str(exc)) from exc

def _artifact_for_path(workspace: Path, path: Path, known_nodes: set[str]) -> dict[str, Any]:
    try:
        return _with_input_roles(
            workspace_artifact_for_path(workspace, path, known_nodes=known_nodes)
        )
    except WorkspaceArtifactError as exc:
        raise ComputeContractError(str(exc)) from exc


def _artifact_for_ref(workspace: Path, ref: str, known_nodes: set[str]) -> dict[str, Any]:
    try:
        return _with_input_roles(
            workspace_artifact_for_ref(workspace, ref, known_nodes=known_nodes)
        )
    except WorkspaceArtifactError as exc:
        raise ComputeContractError(str(exc)) from exc


def _artifact_id(path: str, digest: str) -> str:
    return workspace_artifact_id(path, digest)


def _with_input_roles(record: dict[str, Any]) -> dict[str, Any]:
    path = str(record["path"])
    suffix = Path(path).suffix.lower()
    roles: list[str] = []
    for registration in CAPABILITY_REGISTRY.registrations():
        provider = registration.provider
        resolver = getattr(provider, "artifact_input_roles", None)
        if callable(resolver):
            try:
                values = resolver(path)
            except (OSError, TypeError, ValueError):
                continue
            if isinstance(values, (list, tuple, set, frozenset)):
                roles.extend(str(value) for value in values)
    if not roles:
        roles = [role for role, suffixes in ROLE_SUFFIXES.items() if suffix in suffixes]
    return {
        **record,
        "input_roles": sorted(set(roles)),
    }


def _node_inputs_directory(workspace: Path, node_id: str) -> Path:
    nodes_root = workspace / "nodes"
    if has_symlink_component(workspace, nodes_root) or not nodes_root.is_dir() or nodes_root.is_symlink():
        raise ComputeContractError("workspace nodes root must be a physical directory")
    node_root = nodes_root / node_id
    if has_symlink_component(workspace, node_root):
        raise ComputeContractError(f"ResearchNode artifact root is unsafe: {node_id}")
    if node_root.exists():
        if not node_root.is_dir() or node_root.is_symlink():
            raise ComputeContractError(f"ResearchNode artifact root is unsafe: {node_id}")
    else:
        node_root.mkdir(mode=0o700)
    inputs = node_root / "inputs"
    if has_symlink_component(workspace, inputs):
        raise ComputeContractError(f"ResearchNode input root is unsafe: {node_id}")
    if inputs.exists():
        if not inputs.is_dir() or inputs.is_symlink():
            raise ComputeContractError(f"ResearchNode input root is unsafe: {node_id}")
    else:
        inputs.mkdir(mode=0o700)
    expected = workspace / "nodes" / node_id / "inputs"
    if inputs != expected:
        raise ComputeContractError(f"ResearchNode input root escapes the workspace: {node_id}")
    return inputs


def _node_analysis_directory(workspace: Path, node_id: str) -> Path:
    nodes_root = workspace / "nodes"
    if has_symlink_component(workspace, nodes_root) or not nodes_root.is_dir() or nodes_root.is_symlink():
        raise ComputeContractError("workspace nodes root must be a physical directory")
    node_root = nodes_root / node_id
    if has_symlink_component(workspace, node_root):
        raise ComputeContractError(f"ResearchNode artifact root is unsafe: {node_id}")
    if node_root.exists():
        if not node_root.is_dir() or node_root.is_symlink():
            raise ComputeContractError(f"ResearchNode artifact root is unsafe: {node_id}")
    else:
        node_root.mkdir(mode=0o700)
    outputs = node_root / "outputs"
    analysis = outputs / "analysis"
    if has_symlink_component(workspace, outputs) or has_symlink_component(workspace, analysis):
        raise ComputeContractError(f"ResearchNode output root is unsafe: {node_id}")
    for path, label in ((outputs, "output"), (analysis, "analysis")):
        if path.exists():
            if not path.is_dir() or path.is_symlink():
                raise ComputeContractError(f"ResearchNode {label} root is unsafe: {node_id}")
        else:
            path.mkdir(mode=0o700)
    expected = workspace / "nodes" / node_id / "outputs" / "analysis"
    if analysis != expected:
        raise ComputeContractError(f"ResearchNode analysis root escapes the workspace: {node_id}")
    return analysis


def _write_artifact_payload(path: Path, payload: bytes) -> bool:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise ComputeContractError("artifact target is not a regular file")
        if path.read_bytes() != payload:
            raise ComputeContractError("artifact target already contains different content")
        if path.stat().st_mode & 0o077:
            raise ComputeContractError("existing artifact is not private")
        return False
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return True


def _comparison_input_binding(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": artifact["artifact_id"],
        "artifact_ref": artifact["path"],
        "sha256": artifact["sha256"],
        "size_bytes": artifact["size_bytes"],
        "owner_node": artifact["owner_node"],
        "source_intent_id": artifact["source_intent_id"],
    }


def _node_record(workspace: Path, node_id: str) -> dict[str, Any]:
    try:
        records = workspace_node_records(workspace)
    except WorkspaceArtifactError as exc:
        raise ComputeContractError(str(exc)) from exc
    matches = [item for item in records if item.get("id") == node_id]
    if len(matches) != 1:
        raise ComputeContractError(f"unknown ResearchNode: {node_id}")
    return matches[0]


def _workspace_root(root: str | Path) -> Path:
    try:
        return workspace_root(root)
    except WorkspaceArtifactError as exc:
        raise ComputeContractError(str(exc)) from exc


def _node_ids(workspace: Path) -> set[str]:
    try:
        return workspace_node_ids(workspace)
    except WorkspaceArtifactError as exc:
        raise ComputeContractError(str(exc)) from exc


def _sha256_file(path: Path) -> str:
    return workspace_sha256_file(path)
