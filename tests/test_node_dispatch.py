from __future__ import annotations

import json

import pytest

from tests.workspace_helpers import bootstrap_workspace_fixture, start_research_node
from tests.test_compute_control import _prepared_remote, _workspace, _create, _gaussian_log
from tests.test_scientific_analysis import request
from ts_agent.compute.analysis import run_analysis
from ts_agent.compute.control import submit_calculation, prepare_calculation, parse_calculation, _default_parse_ref, _load_prepared
from ts_agent.workspace.context import compile_context
from ts_agent.workspace.dispatch import set_node_dispatch, require_dispatch_allowed, dispatch_history
from ts_agent.workspace.operational import operational_snapshot
from ts_agent.projection.normalize import node_payload


def test_pause_blocks_analysis_preserves_science_and_survives_reload(tmp_path):
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    node = start_research_node(root)["node_id"]
    other = start_research_node(root, title="Independent branch")["node_id"]
    scientific_before = (root / "research_nodes.json").read_bytes()
    initial_revision = operational_snapshot(root)["operational_revision"]
    receipt = set_node_dispatch(root, node, "pause", "User paused this branch")
    assert receipt["operation"] == "pause" and not receipt["replayed"]
    assert set_node_dispatch(root, node, "pause", "repeat")["replayed"]
    assert (root / "research_nodes.json").read_bytes() == scientific_before
    assert operational_snapshot(root)["operational_revision"] != initial_revision
    assert compile_context(root, mode="node", node_ref=node)["node_dispatch"][0]["paused"]
    assert node_payload(root, node)["node_dispatch"][0]["paused"]
    with pytest.raises(ValueError, match="node_dispatch_paused"):
        run_analysis(root, request(node, "reaction.parse", {"reaction_smiles": "O>>O", "multiplicities": {"reactants": [1], "products": [1]}}))
    from ts_agent.compute.artifacts import create_structure_seed_artifact
    with pytest.raises(ValueError, match="node_dispatch_paused"):
        create_structure_seed_artifact(root, {"schema_version": "ts-structure-seed-request/1", "node_id": node,
            "smiles": "O", "charge": 0, "multiplicity": 1, "optimization": "uff"})
    assert run_analysis(root, request(other, "reaction.parse", {"reaction_smiles": "O>>O", "multiplicities": {"reactants": [1], "products": [1]}}))["verdict"] == "valid"
    set_node_dispatch(root, node, "resume", "User resumed this branch")
    assert len(dispatch_history(root, node)) == 2
    require_dispatch_allowed(root, node)
    assert run_analysis(root, request(node, "reaction.parse", {"reaction_smiles": "O>>O", "multiplicities": {"reactants": [1], "products": [1]}}))["verdict"] == "valid"
    assert (root / "research_nodes.json").read_bytes() == scientific_before


def test_pause_is_checked_at_submit_boundary(tmp_path, monkeypatch):
    root, node, created = _prepared_remote(tmp_path, monkeypatch)
    set_node_dispatch(root, node, "pause", "Hold after preparation")
    calls = []
    monkeypatch.setattr("ts_agent.compute.control.remote_lifecycle.submit", lambda config: calls.append(config))
    with pytest.raises(ValueError, match="node_dispatch_paused"):
        submit_calculation(root, created["intent_id"])
    assert calls == []
    assert not list((root / "nodes" / node / "attempts").glob("*/submit*_guard.json"))


def test_dispatch_receipt_tamper_fails_closed(tmp_path):
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    node = start_research_node(root)["node_id"]
    set_node_dispatch(root, node, "pause", "hold")
    set_node_dispatch(root, node, "resume", "continue")
    path = root / "nodes" / node / "dispatch" / "00000001.json"
    record = json.loads(path.read_text())
    record["rationale"] = "altered"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="chain"):
        require_dispatch_allowed(root, node)


def test_finalize_primary_inference_from_bound_local_intent(tmp_path):
    root, node = _workspace(tmp_path)
    created = _create(root, node)
    prepare_calculation(root, created["intent_ref"], created["intent_digest"])
    _, intent, prepared = _load_prepared(root, created["intent_id"])
    primary = _default_parse_ref(root, intent, prepared)
    path = root / primary
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_gaussian_log())
    set_node_dispatch(root, node, "pause", "collect existing work only")
    parsed = parse_calculation(root, created["intent_id"])
    assert parsed["state"] == "parsed"
