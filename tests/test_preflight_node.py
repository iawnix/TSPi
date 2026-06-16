"""Mechanism-preflight root node scaffolding and validation."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import WORKSPACE_CLI, run_cli, validate_workspace


def test_init_can_create_canonical_preflight_root_node(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"

    run_cli(
        str(WORKSPACE_CLI),
        "init",
        "--root",
        str(root),
        "--system",
        "unit_test_system",
        "--charge",
        "0",
        "--multiplicity",
        "1",
        "--reaction-class",
        "bond_switch",
        "--key-atoms",
        "O1",
        "C5",
        "--bond-change",
        "breaking:O1-C5",
        "--with-preflight-node",
    )

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    tree = json.loads((root / "tree.json").read_text(encoding="utf-8"))
    node = json.loads((root / "nodes" / "n000_mechanism_preflight" / "node.json").read_text(encoding="utf-8"))
    registry = json.loads((root / "evidence_registry.json").read_text(encoding="utf-8"))

    assert manifest["mechanism_preflight_storage"] == "node"
    assert manifest["mechanism_preflight_node_id"] == "n000_mechanism_preflight"
    assert tree["nodes"]["n000_mechanism_preflight"]["parent_id"] is None
    assert tree["nodes"]["n000_mechanism_preflight"]["stage"] == "mechanism_preflight"
    assert node["stage"] == "mechanism_preflight"
    assert node["operation"] == "mechanism-preflight"
    assert node["claim_status"] == "not_evaluated"
    assert node["evidence"]["preflight_summary"] == (
        "nodes/n000_mechanism_preflight/parsed/mechanism_preflight_summary.json"
    )
    assert (root / "nodes" / "n000_mechanism_preflight" / "decision_card.md").exists()
    assert any(record["kind"] == "mechanism_preflight" for record in registry["records"])

    validation = validate_workspace(root)
    assert validation["summary"]["errors"] == 0
    assert validation["summary"]["warnings"] == 0


def test_preflight_node_helper_adds_root_to_existing_workspace(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    run_cli(
        str(WORKSPACE_CLI),
        "init",
        "--root",
        str(root),
        "--system",
        "unit_test_system",
        "--charge",
        "0",
        "--multiplicity",
        "1",
        "--reaction-class",
        "unknown",
    )

    run_cli(str(WORKSPACE_CLI), "preflight-node", "--root", str(root))

    node = json.loads((root / "nodes" / "n000_mechanism_preflight" / "node.json").read_text(encoding="utf-8"))
    assert node["stage"] == "mechanism_preflight"
    assert node["parent_id"] is None
    validation = validate_workspace(root)
    assert validation["summary"]["errors"] == 0


def test_validator_warns_for_legacy_compute_root_without_preflight_declaration(tmp_path: Path) -> None:
    root = tmp_path / "tssearch_unit"
    run_cli(
        str(WORKSPACE_CLI),
        "init",
        "--root",
        str(root),
        "--system",
        "unit_test_system",
        "--charge",
        "0",
        "--multiplicity",
        "1",
        "--reaction-class",
        "unknown",
    )
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("mechanism_preflight_storage", None)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    run_cli(
        str(WORKSPACE_CLI),
        "decision-card",
        "--root",
        str(root),
        "--node-id",
        "n010_compute_branch",
        "--stage",
        "candidate_generation",
        "--hypothesis",
        "Legacy workspace starts directly from a compute branch.",
        "--operation",
        "unit-test-candidate",
    )

    validation = validate_workspace(root)
    codes = {finding["code"] for finding in validation["findings"]}
    assert "mechanism_preflight_node_missing" in codes
