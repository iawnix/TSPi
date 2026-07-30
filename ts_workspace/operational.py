"""Read-only indexing for noncanonical calculation and agent-run state."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .io import read_json, sha256_json


def operational_snapshot(root: str | Path) -> dict[str, Any]:
    root_path = Path(root)
    files = _operational_files(root_path)
    agent_runs = agent_run_index(root_path)
    return {
        "operational_revision": sha256_json(
            {
                "files": [
                    {"path": path.relative_to(root_path).as_posix(), "sha256": _sha256_file(path)}
                    for path in files
                ]
            }
        ),
        "agent_runs": agent_runs,
        "operational_summary": {
            "tracked_file_count": len(files),
            "calculation_file_count": sum(1 for path in files if "agent-runs" not in path.parts),
            "agent_run_count": len(agent_runs),
            "agent_run_failed_count": sum(1 for row in agent_runs if row.get("status") == "failed"),
            "agent_run_pending_count": sum(1 for row in agent_runs if row.get("status") == "pending"),
        },
    }


def agent_run_index(root: str | Path) -> list[dict[str, Any]]:
    root_path = Path(root)
    run_dirs = [
        *root_path.glob("nodes/*/agent-runs/*"),
        *root_path.glob("operations/agent-runs/*"),
    ]
    rows: list[dict[str, Any]] = []
    for run_dir in sorted(run_dirs, key=lambda path: path.relative_to(root_path).as_posix()):
        if not run_dir.is_dir() or run_dir.is_symlink():
            continue
        task = _read_or_empty(run_dir / "task.json")
        run = _read_or_empty(run_dir / "run.json")
        result = _read_or_empty(run_dir / "result.json")
        error = run.get("error") if isinstance(run.get("error"), dict) else {}
        scope = task.get("scope") if isinstance(task.get("scope"), dict) else {}
        rows.append(
            {
                "task_id": task.get("task_id") or run_dir.name,
                "role": task.get("role"),
                "authority": task.get("authority"),
                "operation": task.get("operation"),
                "status": run.get("status") or "pending",
                "node_ids": scope.get("node_ids", []),
                "run_ref": run_dir.relative_to(root_path).as_posix(),
                "started_at": run.get("started_at"),
                "finished_at": run.get("finished_at"),
                "summary": result.get("summary"),
                "error_code": error.get("code"),
                "error_message": error.get("message"),
            }
        )
    return rows


def _operational_files(root: Path) -> list[Path]:
    patterns = (
        "nodes/*/attempts/*/status.json",
        "nodes/*/attempts/*/outputs/calculation_result.json",
        "nodes/*/remote/calculations/*/status.json",
        "nodes/*/outputs/calculations/*/calculation_result.json",
        "nodes/*/agent-runs/*/*.json",
        "operations/agent-runs/*/*.json",
    )
    files = {
        path
        for pattern in patterns
        for path in root.glob(pattern)
        if path.is_file() and not path.is_symlink()
    }
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _read_or_empty(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        value = read_json(path)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}
