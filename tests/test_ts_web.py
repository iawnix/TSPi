from __future__ import annotations

import http.client
import json
import threading
from importlib.resources import files
from pathlib import Path

import pytest

from strict_helpers import make_accepted_workspace, make_branch_workspace
from ts_web import normalize_workspace, register_workspace
from ts_web import server as ts_web_server
from ts_web.normalize import explorer_graph_payload_from_view
from ts_web.registry import list_workspaces, register_workspaces
from ts_web.server import create_server


ROOT = Path(__file__).resolve().parents[1]


def test_normalize_workspace_uses_v2_branch_events(tmp_path: Path) -> None:
    workspace = tmp_path / "branch"
    make_branch_workspace(workspace)
    view = normalize_workspace(workspace)
    event = next(item for item in view["branch_edges"] if item["new_node"] == "n002")

    assert event["relation"] == "new_pathway_branch"
    assert event["from_node"] == "n001"
    assert event["anchor_node"] == "n000"
    assert event["parent_node"] == "n000"
    assert event["is_rebased"] is True


def test_graph_exposes_node_type_scope_without_phase_fallback(tmp_path: Path) -> None:
    workspace = tmp_path / "accepted"
    make_accepted_workspace(workspace)
    graph = explorer_graph_payload_from_view(normalize_workspace(workspace))
    nodes = {node["id"]: node for node in graph["nodes"]}

    assert nodes["n001"]["node_type"] == "validation"
    assert nodes["n001"]["scope"] == "tsfreq"
    assert nodes["n001"]["stage_label"] == "Validation / Tsfreq"
    assert nodes["n003"]["node_type"] == "audit"
    assert nodes["n003"]["scope"] == "transition_state"
    for node in nodes.values():
        assert "phase" not in node
        assert "card_phase" not in node
        assert "claim_verdict" not in node
        assert "program_status" not in node


def test_compute_status_is_separate_from_scientific_program_outcome(tmp_path: Path) -> None:
    workspace = tmp_path / "accepted"
    make_accepted_workspace(workspace)
    attempt = workspace / "nodes" / "n001" / "attempts" / "calc_test" / "outputs"
    attempt.mkdir(parents=True)
    (attempt / "calculation_result.json").write_text(
        json.dumps({"state": "failed", "program_status": "failed", "error_class": "scheduler_failure"}),
        encoding="utf-8",
    )

    graph = explorer_graph_payload_from_view(normalize_workspace(workspace))
    node = next(item for item in graph["nodes"] if item["id"] == "n001")

    assert node["program_outcome"] == "success"
    assert node["calculation_state"] == "failed"
    assert node["calculation_program_status"] == "failed"


def test_static_ui_uses_v2_scientific_fields() -> None:
    html = (ROOT / "ts_web" / "static" / "index.html").read_text(encoding="utf-8")

    assert 'summaryRow("node_type", node.node_type' in html
    assert 'summaryRow("scope", node.scope' in html
    assert 'summaryRow("program_outcome", node.program_outcome' in html
    assert 'summaryRow("claim_verdict"' not in html
    assert 'summaryRow("card_phase"' not in html
    assert "const NODE_TYPE_ICONS" in html
    assert "const STAGE_ICONS" not in html
    assert "function renderNoWorkspace()" in html


def test_static_asset_resolves_from_current_package() -> None:
    expected = files("ts_web").joinpath("static", "index.html").read_bytes()
    assert ts_web_server._static_asset("index.html").read_bytes() == expected


def test_continue_parent_events_do_not_duplicate_lineage_edges(tmp_path: Path) -> None:
    workspace = tmp_path / "accepted"
    make_accepted_workspace(workspace)
    graph = explorer_graph_payload_from_view(normalize_workspace(workspace))

    lineage = [edge for edge in graph["edges"] if edge["kind"] == "branch"]
    assert len(lineage) == len(graph["nodes"]) - 1
    assert not [edge for edge in graph["edges"] if edge["kind"] == "branch_trigger"]


def test_register_workspace_deduplicates_and_rejects_source_pollution(tmp_path: Path) -> None:
    source = tmp_path / "single-step"
    make_accepted_workspace(source)
    state = tmp_path / "web-state"
    first = register_workspace(source, state, "single")
    second = register_workspace(source, state, "single updated")

    assert first["workspace_id"] == second["workspace_id"]
    assert [row["label"] for row in list_workspaces(state)] == ["single updated"]
    with pytest.raises(ValueError, match="state_dir"):
        register_workspace(source, source / ".web")


def test_register_workspaces_validates_all_sources_before_writing(tmp_path: Path) -> None:
    accepted = tmp_path / "accepted"
    branch = tmp_path / "branch"
    make_accepted_workspace(accepted)
    make_branch_workspace(branch)
    state = branch / ".web-state"

    with pytest.raises(ValueError, match="state_dir"):
        register_workspaces([accepted, branch], state, ["A", "B"])
    assert not state.exists()


def test_web_server_api_is_read_only_and_v2_only(tmp_path: Path) -> None:
    source = tmp_path / "accepted"
    make_accepted_workspace(source)
    before = _relative_files(source)
    state = tmp_path / "web-state"
    row = register_workspace(source, state, "accepted")
    server = create_server("127.0.0.1", 0, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        assert _get_json(host, port, "/api/health") == {"ok": True}
        workspaces = _get_json(host, port, "/api/workspaces")
        assert workspaces["default_workspace"] == row["workspace_id"]
        job = _get_json(host, port, f"/api/workspace/{row['workspace_id']}/job")
        nodes = {node["id"]: node for node in job["graph"]["nodes"]}
        assert nodes["n003"]["audit_status"] == "accepted"
        assert "claim_verdict" not in nodes["n003"]
        node = _get_json(host, port, f"/api/workspace/{row['workspace_id']}/node/n001")
        assert node["node"]["program_outcome"] == "success"
        assert "## Program" in node["markdown"]["reflection"]
        preview = _get_json(host, port, f"/api/workspace/{row['workspace_id']}/file?path=nodes/n001/node.json")
        assert preview["path"] == "nodes/n001/node.json"
        assert "TS Hypothesis Explorer" in _get_text(host, port, "/")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert _relative_files(source) == before


def _relative_files(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}


def _get_json(host: str, port: int, path: str) -> dict:
    return json.loads(_get_text(host, port, path))


def _get_text(host: str, port: int, path: str) -> str:
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        assert response.status == 200, body
        return body
    finally:
        connection.close()
