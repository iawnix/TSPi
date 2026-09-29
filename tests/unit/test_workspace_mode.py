from __future__ import annotations

import json
from pathlib import Path

import pytest

from ts_agent.runtime.workspace_mode import (
    RESEARCH_CONTEXT_COLLECTIONS,
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
    for collection in RESEARCH_CONTEXT_COLLECTIONS:
        assert context[collection] == []

    admitted = admit_research_workspace(root)
    assert admitted["state"] == "ready"
    assert admitted["research_kernel"]["admission_required"] is False
    assert json.loads((root / "lifecycle/liveness.json").read_text(encoding="utf-8"))["state"] == "admitted"
    memory = json.loads((root / "memory/index.json").read_text(encoding="utf-8"))
    assert memory["lifecycle"] == "idle"
    assert memory["context_revision"] == 0


def test_admission_repairs_context_liveness_commit_gap(tmp_path: Path) -> None:
    root = tmp_path / "partial-admission"
    initialize_workspace(root, "partial_admission", "research")

    context_path = root / "research_map/context.json"
    context = json.loads(context_path.read_text(encoding="utf-8"))
    context.update({"lifecycle_state": "admitted", "lifecycle": "idle", "disposition": None})
    context_path.write_text(json.dumps(context), encoding="utf-8")

    admitted = admit_research_workspace(root)
    assert admitted["state"] == "ready"
    liveness = json.loads((root / "lifecycle/liveness.json").read_text(encoding="utf-8"))
    assert liveness["state"] == "admitted"
    assert liveness["lifecycle"] == "idle"


def test_admission_preserves_liveness_first_projection(tmp_path: Path) -> None:
    root = tmp_path / "liveness-first-admission"
    initialize_workspace(root, "liveness_first", "research")

    liveness_path = root / "lifecycle/liveness.json"
    liveness = json.loads(liveness_path.read_text(encoding="utf-8"))
    liveness.update({
        "state": "admitted",
        "lifecycle": "waiting_external",
        "disposition": "waiting_external",
        "checkpoint_id": "checkpoint_waiting",
    })
    liveness_path.write_text(json.dumps(liveness), encoding="utf-8")

    reopened = initialize_workspace(root, "liveness_first", "research")
    assert reopened["state"] == "admission_pending"
    admitted = admit_research_workspace(root)
    assert admitted["state"] == "ready"
    context = json.loads((root / "research_map/context.json").read_text(encoding="utf-8"))
    recovered = json.loads(liveness_path.read_text(encoding="utf-8"))
    assert context["lifecycle_state"] == "admitted"
    assert context["lifecycle"] == "waiting_external"
    assert context["disposition"] == "waiting_external"
    assert recovered["lifecycle"] == "waiting_external"
    assert recovered["disposition"] == "waiting_external"


def test_workspace_mode_is_immutable(tmp_path: Path) -> None:
    root = tmp_path / "immutable"
    initialize_workspace(root, "immutable_one", "light")

    with pytest.raises(WorkspaceModeError, match="workspace_mode_mismatch"):
        initialize_workspace(root, "immutable_one", "research")


@pytest.mark.parametrize("retired_name", ["claims.json", "research_nodes.json", "observations.json"])
def test_initializer_rejects_every_retired_research_file(tmp_path: Path, retired_name: str) -> None:
    root = tmp_path / "mixed"
    root.mkdir()
    (root / retired_name).touch()

    with pytest.raises(WorkspaceModeError, match=rf"legacy_workspace_layout: {retired_name}"):
        initialize_workspace(root, "mixed_one", "light")
