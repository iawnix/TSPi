"""Artifact-path policy checks for ChemGate workspace validation."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import re
from typing import Any

from transition_state_workflow.util.path_utils import clean_string, list_or_empty, relative_path_or_absolute

from .contracts import (
    ENGINE_ROOT_ARTIFACT_NAMES,
    ENGINE_ROOT_ARTIFACT_STEM_SUFFIXES,
    ENGINE_ROOT_ARTIFACT_SUFFIXES,
    GAUSSIAN_INPUT_SUFFIXES,
    Finding,
)
from .io import walk_values


def validate_paths_are_portable(
    source: Path,
    node_json_by_id: dict[str, dict[str, Any]],
    evidence: dict[str, Any],
    findings: list[Finding],
) -> None:
    """Warn when workspace metadata stores non-portable absolute paths."""

    for node_id, node_json in node_json_by_id.items():
        for key_path, value in walk_values(node_json):
            if isinstance(value, str) and value.startswith("/") and not value.startswith(str(source)):
                if any(part in key_path for part in ("changed_variables", "evidence", "display")):
                    findings.append(
                        Finding(
                            "warning",
                            "absolute_nested_path",
                            f"absolute path in node field {'.'.join(key_path)} may not be portable",
                            path=relative_path_or_absolute(source, source / "nodes" / node_id / "node.json"),
                            node_id=node_id,
                        )
                    )
    for index, item in enumerate(list_or_empty(evidence.get("records"))):
        if isinstance(item, dict):
            path_text = clean_string(item.get("path"))
            if path_text.startswith("/") and not bool(item.get("external_path")):
                findings.append(Finding("warning", "absolute_registry_path", f"absolute registry path at records[{index}] is not marked external_path", path="evidence_registry.json", node_id=clean_string(item.get("node_id"))))


def validate_engine_artifact_policy(
    source: Path,
    node_json_by_id: dict[str, dict[str, Any]],
    findings: list[Finding],
) -> None:
    """Detect engine artifacts outside node-scoped run/output directories."""

    validate_workspace_root_has_no_engine_artifacts(source, findings)
    for node_id, node_json in node_json_by_id.items():
        if not node_json:
            continue
        validate_node_artifact_policy(source, node_id, node_json, findings)
        validate_gaussian_checkpoint_paths(source, node_id, findings)


def validate_workspace_root_has_no_engine_artifacts(source: Path, findings: list[Finding]) -> None:
    """Warn when known engine output files are written at workspace root."""

    if not source.exists():
        return
    for path in sorted(source.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        lower_name = name.lower()
        if (
            lower_name in ENGINE_ROOT_ARTIFACT_NAMES
            or any(lower_name.endswith(suffix) for suffix in ENGINE_ROOT_ARTIFACT_STEM_SUFFIXES)
            or path.suffix.lower() in ENGINE_ROOT_ARTIFACT_SUFFIXES
            or lower_name.startswith("qbics")
            or lower_name.startswith("xtb_")
        ):
            findings.append(
                Finding(
                    "warning",
                    "engine_artifact_at_workspace_root",
                    "engine artifact is at workspace root; run Gaussian/xTB/QBICS from nodes/<node_id>/outputs or scratch",
                    path=relative_path_or_absolute(source, path),
                )
            )


def validate_node_artifact_policy(
    source: Path,
    node_id: str,
    node_json: dict[str, Any],
    findings: list[Finding],
) -> None:
    """Validate optional node artifact policy written by new decision cards."""

    policy = node_json.get("artifact_policy")
    if policy is None:
        return
    node_path = relative_path_or_absolute(source, source / "nodes" / node_id / "node.json")
    if not isinstance(policy, dict):
        findings.append(Finding("warning", "artifact_policy_not_object", "artifact_policy must be an object", path=node_path, node_id=node_id))
        return
    expected = {
        "input_dir": f"nodes/{node_id}/inputs",
        "output_dir": f"nodes/{node_id}/outputs",
        "run_cwd": f"nodes/{node_id}/outputs",
        "scratch_dir": f"nodes/{node_id}/scratch",
    }
    for key, expected_value in expected.items():
        value = clean_string(policy.get(key))
        if not value:
            findings.append(Finding("warning", "artifact_policy_missing_field", f"artifact_policy missing {key}", path=node_path, node_id=node_id))
            continue
        if Path(value).is_absolute() or path_escapes_workspace(value):
            findings.append(Finding("warning", "artifact_policy_nonportable_path", f"artifact_policy {key} should be workspace-relative", path=node_path, node_id=node_id))
        if value != expected_value:
            findings.append(
                Finding(
                    "warning",
                    "artifact_policy_not_node_scoped",
                    f"artifact_policy {key} should be {expected_value!r}, got {value!r}",
                    path=node_path,
                    node_id=node_id,
                )
            )


def validate_gaussian_checkpoint_paths(source: Path, node_id: str, findings: list[Finding]) -> None:
    """Warn on Gaussian checkpoint paths that contradict outputs/ as run cwd."""

    inputs_dir = source / "nodes" / node_id / "inputs"
    if not inputs_dir.exists():
        return
    for input_path in sorted(inputs_dir.iterdir()):
        if not input_path.is_file() or input_path.suffix.lower() not in GAUSSIAN_INPUT_SUFFIXES:
            continue
        for key, raw_value in iter_gaussian_checkpoint_directives(input_path):
            value = raw_value.strip()
            if not value:
                continue
            if Path(value).is_absolute():
                findings.append(
                    Finding(
                        "warning",
                        "gaussian_checkpoint_absolute_path",
                        f"{key} uses an absolute checkpoint path; prefer a path relative to the node outputs/ run directory",
                        path=relative_path_or_absolute(source, input_path),
                        node_id=node_id,
                    )
                )
                continue
            parts = [part for part in PurePosixPath(value).parts if part not in {"", "."}]
            if key.lower() == "%chk" and any(part == ".." for part in parts):
                findings.append(
                    Finding(
                        "warning",
                        "gaussian_checkpoint_escapes_run_cwd",
                        f"{key}={value} would write the checkpoint outside nodes/{node_id}/outputs; use a bare checkpoint name for %chk",
                        path=relative_path_or_absolute(source, input_path),
                        node_id=node_id,
                    )
                )
                continue
            if parts and parts[0] in {"nodes", "inputs", "outputs"}:
                findings.append(
                    Finding(
                        "warning",
                        "gaussian_checkpoint_not_run_cwd_relative",
                        f"{key}={value} looks workspace- or node-root-relative; Gaussian should run from nodes/{node_id}/outputs, so use a bare checkpoint name or a path relative to outputs/",
                        path=relative_path_or_absolute(source, input_path),
                        node_id=node_id,
                    )
                )


def iter_gaussian_checkpoint_directives(input_path: Path) -> list[tuple[str, str]]:
    """Return %chk/%oldchk directives from one Gaussian input."""

    directives: list[tuple[str, str]] = []
    for line in input_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"\s*(%oldchk|%chk)\s*=\s*(.+?)\s*$", line, re.IGNORECASE)
        if match:
            directives.append((match.group(1), match.group(2)))
    return directives


def path_escapes_workspace(raw_path: str) -> bool:
    """Return true when a workspace-relative path starts with '..'."""

    return any(part == ".." for part in PurePosixPath(raw_path).parts)


__all__ = [
    "validate_paths_are_portable",
    "validate_engine_artifact_policy",
    "validate_workspace_root_has_no_engine_artifacts",
    "validate_node_artifact_policy",
    "validate_gaussian_checkpoint_paths",
    "iter_gaussian_checkpoint_directives",
    "path_escapes_workspace",
]
