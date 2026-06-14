"""Focused tests for reusable core workspace primitives."""

from __future__ import annotations

import json
from pathlib import Path

from transition_state_workflow.config.state_contract import (
    EVIDENCE_REGISTRY_SCHEMA,
    TREE_SCHEMA,
    WORKSPACE_NODE_SCHEMA,
)
from transition_state_workflow.core.workspace import (
    write_initial_workspace_files,
    write_prepared_branch_state,
)


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


def test_write_prepared_branch_state_writes_node_tree_and_event(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    write_initial_workspace_files(
        root,
        system="unit_system",
        charge=0,
        multiplicity=1,
        timestamp="2026-06-14T00:00:00+00:00",
        overwrite_existing=True,
    )

    first = write_prepared_branch_state(
        root=root,
        node_id="n010_branch",
        parent_id=None,
        stage="candidate_generation",
        operation="unit-test-operation",
        hypothesis="Unit-test branch hypothesis.",
        input_refs=[],
        pathway_id="",
        step_id="",
        timestamp="2026-06-14T00:01:00+00:00",
        overwrite_existing=False,
    )

    for dirname in ("inputs", "outputs", "parsed", "scratch"):
        assert (first.node_dir / dirname).is_dir()
    node = json.loads((first.node_dir / "node.json").read_text(encoding="utf-8"))
    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))
    assert node["schema"] == WORKSPACE_NODE_SCHEMA
    assert node["lifecycle_state"] == "prepared"
    assert node["claim_status"] == "not_evaluated"
    assert node["artifact_policy"]["run_cwd"] == "nodes/n010_branch/outputs"
    assert tree["nodes"]["n010_branch"]["node_path"] == "nodes/n010_branch/node.json"
    assert tree["events"][0]["event_id"] == "evt_n010_branch_prepare"
    assert first.event_id == "evt_n010_branch_prepare"

    second = write_prepared_branch_state(
        root=root,
        node_id="n010_branch",
        parent_id=None,
        stage="candidate_generation",
        operation="unit-test-operation",
        hypothesis="Unit-test branch hypothesis.",
        input_refs=[],
        pathway_id="",
        step_id="",
        timestamp="2026-06-14T00:02:00+00:00",
        overwrite_existing=False,
    )
    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))
    assert second.event_id == "evt_n010_branch_prepare_02"
    assert [event["event_id"] for event in tree["events"]] == [
        "evt_n010_branch_prepare",
        "evt_n010_branch_prepare_02",
    ]
