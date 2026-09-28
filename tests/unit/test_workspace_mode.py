from __future__ import annotations

import json
from pathlib import Path

import pytest

from ts_agent.runtime.workspace_mode import (
    WorkspaceModeError,
    admit_research_workspace,
    initialize_workspace,
    read_workspace_mode,
)


def test_light_workspace_is_ready_and_has_only_light_profile(tmp_path: Path) -> None:
    root = tmp_path / "light"
    manifest = initialize_workspace(root, "light_one", "light")

    assert manifest["state"] == "ready"
    assert manifest["workspace_mode"] == "light"
    assert (root / "workspace_manifest.json").is_file()
    assert (root / "scratch").is_dir()
    assert not (root / "research_map/context.json").exists()
    assert read_workspace_mode(root) == "light"


def test_research_workspace_requires_and_accepts_host_admission(tmp_path: Path) -> None:
    root = tmp_path / "research"
    manifest = initialize_workspace(root, "research_one", "research")

    assert manifest["state"] == "admission_pending"
    context = json.loads((root / "research_map/context.json").read_text(encoding="utf-8"))
    assert context["lifecycle_state"] == "admission_pending"

    admitted = admit_research_workspace(root)
    assert admitted["state"] == "ready"
    assert admitted["research_kernel"]["admission_required"] is False
    assert json.loads((root / "lifecycle/liveness.json").read_text(encoding="utf-8"))["state"] == "admitted"


def test_workspace_mode_is_immutable(tmp_path: Path) -> None:
    root = tmp_path / "immutable"
    initialize_workspace(root, "immutable_one", "light")

    with pytest.raises(WorkspaceModeError, match="workspace_mode_mismatch"):
        initialize_workspace(root, "immutable_one", "research")
