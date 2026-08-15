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
from ts_workspace.state_v3 import REQUIRED_FILES


def test_bootstrap_initializes_fresh_workspace_and_preserves_inputs(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    input_path = workspace / "reactant.xyz"
    input_path.write_text("1\nreactant\nH 0 0 0\n", encoding="utf-8")

    result = bootstrap_workspace(workspace)

    assert result["state"] == "initialized"
    assert result["created"] is True
    assert result["validation"]["valid"] is True
    assert input_path.read_text(encoding="utf-8") == "1\nreactant\nH 0 0 0\n"
    assert classify_workspace(workspace).state is WorkspaceBootstrapState.VALID_V3


def test_bootstrap_existing_v3_is_read_only_and_idempotent(tmp_path: Path) -> None:
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


def test_bootstrap_rejects_partial_v3_without_filling_missing_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    partial = workspace / "research_state.json"
    partial.write_text('{"schema_version":"ts-research-state/3"}\n', encoding="utf-8")

    with pytest.raises(WorkspaceBootstrapError, match="partially initialized") as caught:
        bootstrap_workspace(workspace)

    assert caught.value.state is WorkspaceBootstrapState.PARTIAL_V3
    assert partial.is_file()
    assert not any((workspace / name).exists() for name in REQUIRED_FILES if name != partial.name)


def test_bootstrap_rejects_legacy_v2_and_requires_copy_migration(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "research_state.json").write_text(
        json.dumps({"schema_version": "ts-research-state"}),
        encoding="utf-8",
    )
    (workspace / "hypotheses.json").write_text(
        json.dumps({"schema_version": "ts-hypotheses"}),
        encoding="utf-8",
    )

    with pytest.raises(WorkspaceBootstrapError, match="explicit copy migration") as caught:
        bootstrap_workspace(workspace)

    assert caught.value.state is WorkspaceBootstrapState.LEGACY_V2
    assert not (workspace / "claims.json").exists()


def test_bootstrap_rejects_invalid_complete_v3(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    (workspace / "claims.json").write_text("{}\n", encoding="utf-8")

    classification = classify_workspace(workspace)
    assert classification.state is WorkspaceBootstrapState.INVALID_V3
    with pytest.raises(WorkspaceBootstrapError, match="invalid v3 workspace"):
        bootstrap_workspace(workspace)


def test_bootstrap_rejects_symlinked_canonical_paths_before_writing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "external.json"
    target.write_text("{}\n", encoding="utf-8")
    (workspace / "research_state.json").symlink_to(target)

    with pytest.raises(WorkspaceBootstrapError, match="symbolic link") as caught:
        bootstrap_workspace(workspace)

    assert caught.value.state is WorkspaceBootstrapState.INVALID_V3
    assert target.read_text(encoding="utf-8") == "{}\n"
