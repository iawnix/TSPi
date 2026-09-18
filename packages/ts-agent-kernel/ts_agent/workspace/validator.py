"""Validation for the canonical ResearchMap workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ts_agent.io import read_json
from ts_agent.research import ResearchKernel, ResearchKernelError

from .identity import read_workspace_identity
from .path_safety import has_symlink_component, lexical_path, path_has_symlink


WORKSPACE_SCHEMA = "research-workspace/1"
VALIDATION_SCHEMA = "research-map-validation/1"


def validate_workspace(root: str | Path) -> dict[str, Any]:
    root_path = lexical_path(root)
    findings: list[dict[str, str]] = []
    if path_has_symlink(root_path):
        _finding(findings, "workspace_path_symlink", "workspace root contains a symbolic link", ".")
        return _result(findings)
    if not root_path.is_dir():
        _finding(findings, "missing_workspace", "workspace root does not exist", ".")
        return _result(findings)

    legacy = (
        "research_state.json", "phases.json", "claims.json", "claim_relations.json",
        "research_nodes.json", "observations.json", "proof_specs.json",
        "validation_results.json", "findings.json", "gate_specs.json", "gate_results.json",
    )
    for name in legacy:
        if (root_path / name).exists():
            _finding(findings, "legacy_state_present", f"legacy research file is not supported: {name}", name)

    for name in ("workspace.json", "research_map.json", "transactions.jsonl"):
        path = root_path / name
        if has_symlink_component(root_path, path) or path.is_symlink():
            _finding(findings, "symlinked_canonical_file", f"canonical file is a symbolic link: {name}", name)
        elif not path.is_file():
            _finding(findings, "missing_canonical_file", f"canonical file is missing: {name}", name)
    for name in ("nodes", "operations", "scratch"):
        path = root_path / name
        if has_symlink_component(root_path, path) or path.is_symlink():
            _finding(findings, "symlinked_canonical_directory", f"canonical directory is a symbolic link: {name}", name)
        elif not path.is_dir():
            _finding(findings, "missing_canonical_directory", f"canonical directory is missing: {name}", name)
    if findings:
        return _result(findings)

    try:
        workspace = read_json(root_path / "workspace.json")
    except (OSError, ValueError) as exc:
        _finding(findings, "invalid_workspace_json", str(exc), "workspace.json")
        return _result(findings)
    if not isinstance(workspace, dict):
        _finding(findings, "invalid_workspace_document", "workspace.json must contain an object", "workspace.json")
    else:
        if workspace.get("schema_version") != WORKSPACE_SCHEMA:
            _finding(findings, "unsupported_workspace_schema", "workspace.json uses an unsupported schema", "workspace.json")
        if workspace.get("kernel_protocol") != "research-map/1":
            _finding(findings, "unsupported_kernel_protocol", "workspace does not use research-map/1", "workspace.json")
        _validate_identity(root_path, workspace, findings)

    try:
        ResearchKernel(root_path).load()
    except ResearchKernelError as exc:
        _finding(findings, "invalid_research_map", str(exc), "research_map.json")
    return _result(findings)


def _validate_identity(root: Path, workspace: dict[str, Any], findings: list[dict[str, str]]) -> None:
    try:
        identity = read_workspace_identity(root)
    except (OSError, ValueError) as exc:
        _finding(findings, "invalid_workspace_identity", str(exc), ".agents/workspace-identity.json")
        return
    if identity.get("workspace_id") != workspace.get("workspace_id"):
        _finding(findings, "workspace_identity_mismatch", "workspace.json does not match immutable identity", "workspace.json")


def _finding(target: list[dict[str, str]], code: str, message: str, path: str) -> None:
    target.append({"severity": "error", "code": code, "message": message, "path": path})


def _result(findings: list[dict[str, str]]) -> dict[str, Any]:
    return {"schema_version": VALIDATION_SCHEMA, "valid": not findings, "findings": findings}
