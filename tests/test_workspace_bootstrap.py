from __future__ import annotations

import json
from pathlib import Path

import pytest

from ts_workspace import (
    WorkspaceBootstrapError,
    WorkspaceBootstrapState,
    bootstrap_workspace,
    classify_workspace,
    init_workspace,
)
from ts_workspace.state import REQUIRED_FILES


def test_bootstrap_initializes_fresh_workspace_and_preserves_inputs(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    input_path = workspace / "reactant.xyz"
    input_path.write_text("1\nreactant\nH 0 0 0\n", encoding="utf-8")

    result = bootstrap_workspace(workspace)

    assert result["schema_version"] == "ts-workspace-bootstrap/3"
    assert result["state"] == "initialized"
    assert result["created"] is True
    assert result["validation"]["valid"] is True
    assert input_path.read_text(encoding="utf-8") == "1\nreactant\nH 0 0 0\n"
    assert classify_workspace(workspace).state is WorkspaceBootstrapState.VALID


def test_bootstrap_existing_workspace_is_read_only_and_idempotent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    before = {
        path.relative_to(workspace): (path.stat().st_mtime_ns, path.read_bytes())
        for path in workspace.rglob("*")
        if path.is_file()
    }
    first = bootstrap_workspace(workspace)
    second = bootstrap_workspace(workspace)
    after = {
        path.relative_to(workspace): (path.stat().st_mtime_ns, path.read_bytes())
        for path in workspace.rglob("*")
        if path.is_file()
    }
    assert first["state"] == second["state"] == "existing"
    assert first["workspace_id"] == second["workspace_id"]
    assert before == after


def test_bootstrap_rejects_partial_workspace_without_filling_missing_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    partial = workspace / "research_state.json"
    partial.write_text('{"schema_version":"ts-research-state/5"}\n', encoding="utf-8")

    with pytest.raises(WorkspaceBootstrapError, match="partial workspace") as caught:
        bootstrap_workspace(workspace)

    assert caught.value.state is WorkspaceBootstrapState.PARTIAL
    assert partial.is_file()
    assert not any((workspace / name).exists() for name in REQUIRED_FILES if name != partial.name)


def test_bootstrap_rejects_unsupported_layout_without_side_effects(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "research_state.json").write_text(
        json.dumps({"schema_version": "ts-research-state/unsupported"}),
        encoding="utf-8",
    )
    (workspace / "nodes").mkdir()

    with pytest.raises(WorkspaceBootstrapError, match="unsupported workspace layout") as caught:
        bootstrap_workspace(workspace)

    assert caught.value.state is WorkspaceBootstrapState.UNSUPPORTED_LAYOUT
    assert not (workspace / "workspace.json").exists()
    assert not (workspace / "observations.json").exists()


def test_bootstrap_rejects_invalid_complete_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    (workspace / "claims.json").write_text("{}\n", encoding="utf-8")

    classification = classify_workspace(workspace)
    assert classification.state is WorkspaceBootstrapState.INVALID
    with pytest.raises(WorkspaceBootstrapError, match="invalid workspace"):
        bootstrap_workspace(workspace)


def test_bootstrap_rejects_symlinked_canonical_paths_before_writing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "external.json"
    target.write_text("{}\n", encoding="utf-8")
    (workspace / "research_state.json").symlink_to(target)

    with pytest.raises(WorkspaceBootstrapError, match="symbolic link") as caught:
        bootstrap_workspace(workspace)

    assert caught.value.state is WorkspaceBootstrapState.INVALID
    assert target.read_text(encoding="utf-8") == "{}\n"
