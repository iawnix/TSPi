"""Focused tests for reusable core workspace primitives."""

from __future__ import annotations

import json
from pathlib import Path

from transition_state_workflow.config.state_contract import (
    EVIDENCE_REGISTRY_SCHEMA,
    TREE_SCHEMA,
    WORKSPACE_NODE_SCHEMA,
)
from transition_state_workflow.core.workspace import write_initial_workspace_files


def test_write_initial_workspace_files_creates_root_json_and_preserves_existing(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    write_initial_workspace_files(
        root,
        system="unit_system",
        charge=0,
        multiplicity=1,
        timestamp="2026-06-14T00:00:00+00:00",
        overwrite_existing=False,
    )

    assert (root / "nodes").is_dir()
    assert (root / "reports").is_dir()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))
    registry = json.loads((root / "evidence_registry.json").read_text(encoding="utf-8"))
    assert manifest["system"] == "unit_system"
    assert manifest["charge"] == 0
    assert manifest["multiplicity"] == 1
    assert manifest["node_schema"] == WORKSPACE_NODE_SCHEMA
    assert tree["schema"] == TREE_SCHEMA
    assert tree["nodes"] == {}
    assert registry["schema"] == EVIDENCE_REGISTRY_SCHEMA
    assert registry["records"] == []

    (root / "manifest.json").write_text('{"sentinel": true}\n', encoding="utf-8")
    write_initial_workspace_files(
        root,
        system="changed_system",
        charge=1,
        multiplicity=2,
        timestamp="2026-06-14T01:00:00+00:00",
        overwrite_existing=False,
    )
    preserved = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert preserved == {"sentinel": True}
