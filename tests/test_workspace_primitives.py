"""Focused tests for reusable core workspace primitives."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from transition_state_workflow.config.state_contract import (
    EVIDENCE_REGISTRY_SCHEMA,
    TREE_SCHEMA,
    WORKSPACE_NODE_SCHEMA,
    derive_node_audit_view,
)
from transition_state_workflow.core.workspace import (
    BranchReferenceError,
    WORKSPACE_ROOT_DIRECTORIES,
    clean_optional_node_ref,
    normalize_branch_input_refs,
    parent_graph_would_cycle,
    validate_branch_references,
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

    for dirname in WORKSPACE_ROOT_DIRECTORIES:
        assert (root / dirname).is_dir()
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
    assert node["phase"] == "candidate_generation"
    assert node["node_disposition"] == "Running"
    audit = derive_node_audit_view(node, tree["nodes"]["n010_branch"])
    assert audit["lifecycle_state"] == "active"
    assert audit["claim_status"] == "not_evaluated"
    for old_field in ("stage", "lifecycle_state", "run_state", "claim_status", "outcome", "outcome_code", "claim_level"):
        assert old_field not in node
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


def test_branch_reference_helpers_validate_parent_and_input_refs() -> None:
    existing_nodes = {
        "n001_root": {"parent_id": None},
        "n010_parent": {"parent_id": "n001_root"},
        "n020_child": {"parent_id": "n010_parent"},
    }

    assert clean_optional_node_ref(" n010_parent ") == "n010_parent"
    assert clean_optional_node_ref(None) == ""
    assert normalize_branch_input_refs(("n001_root", "", "n001_root", " n010_parent ")) == [
        "n001_root",
        "n010_parent",
    ]
    validate_branch_references(
        node_id="n030_new",
        parent_id="n020_child",
        input_refs=["n001_root"],
        existing_nodes=existing_nodes,
    )
    assert parent_graph_would_cycle(node_id="n001_root", parent_id="n020_child", existing_nodes=existing_nodes)

    invalid_cases = (
        {
            "node_id": "n030_new",
            "parent_id": "missing",
            "input_refs": [],
            "message": "parent node does not exist in tree.json: missing",
        },
        {
            "node_id": "n030_new",
            "parent_id": None,
            "input_refs": ["missing"],
            "message": "input reference node does not exist in tree.json: missing",
        },
        {
            "node_id": "n030_new",
            "parent_id": None,
            "input_refs": ["n030_new"],
            "message": "node cannot depend on itself through --input-ref: n030_new",
        },
        {
            "node_id": "n001_root",
            "parent_id": "n020_child",
            "input_refs": [],
            "message": "parent link would create a cycle for node: n001_root",
        },
    )
    for case in invalid_cases:
        with pytest.raises(BranchReferenceError) as exc_info:
            validate_branch_references(
                node_id=str(case["node_id"]),
                parent_id=case["parent_id"],
                input_refs=list(case["input_refs"]),
                existing_nodes=existing_nodes,
            )
        assert str(exc_info.value) == case["message"]
