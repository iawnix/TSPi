from __future__ import annotations

import http.client
import json
import threading
from importlib.resources import files
from pathlib import Path

import pytest

from ts_web import normalize_workspace, register_workspace
from ts_web import server as ts_web_server
from ts_web.normalize import explorer_graph_payload_from_view
from ts_web.registry import list_workspaces, register_workspaces
from ts_web.server import create_server
from ts_workspace.engine_v3 import end_node, init_workspace, report_workspace, start_node, update_workspace


ROOT = Path(__file__).resolve().parents[1]


def _decision(root: Path, action: str, payload: dict, decision_id: str) -> dict:
    report = report_workspace(root)
    return {
        "schema_version": "ts-decision/3",
        "decision_id": decision_id,
        "action": action,
        "rationale": f"Test {action}.",
        "basis_refs": [],
        "report_ref": {"report_id": report["report_id"], "workspace_root": str(root.resolve())},
        "base_revision": report["workspace_revision"],
        "payload": payload,
    }


def _start(root: Path, node_id: str, parent: str | None, claim_refs: list[str]) -> None:
    start_node(
        root,
        _decision(
            root,
            "start_node",
            {
                "node_id": node_id,
                "parent_node": parent,
                "objective": f"Research objective for {node_id}.",
                "tags": ["validation"] if parent else ["intake"],
                "claim_refs": claim_refs,
            },
            f"dec_start_{node_id}",
        ),
    )


def _make_workspace(root: Path, *, child: bool = True) -> None:
    init_workspace(root)
    _start(root, "n000", None, [])
    artifact = root / "nodes" / "n000" / "outputs" / "tsfreq.json"
    artifact.write_text("{}\n", encoding="utf-8")
    update_workspace(
        root,
        _decision(
            root,
            "update_workspace",
            {
                "append_claim": {
                    "claim_id": "claim_ts_web",
                    "node_id": "n000",
                    "kind": "transition-state/1",
                    "statement": "The candidate has one validated imaginary mode.",
                    "required_gates": ["tsfreq"],
                    "details": {},
                },
                "append_evidence": {
                    "schema_version": "ts-evidence/2",
                    "evidence_id": "ev_tsfreq_web",
                    "node_id": "n000",
                    "kind": "gaussian.validation/1",
                    "evidence_tier": "local_parse",
                    "summary": "Gaussian TS/Freq facts.",
                    "facts": {
                        "normal_termination": True,
                        "stationary_point": True,
                        "final_convergence_satisfied": True,
                        "imaginary_frequency_count": 1,
                        "route_match": True,
                    },
                    "artifact_refs": ["nodes/n000/outputs/tsfreq.json"],
                    "provenance": {"producer": "test-parser"},
                },
                "evaluate_gate": {
                    "gate_result_id": "gr_tsfreq_web",
                    "node_id": "n000",
                    "gate": "tsfreq",
                    "evidence_refs": ["ev_tsfreq_web"],
                    "target_ref": "claim_ts_web",
                },
                "set_focus_claim_refs": ["claim_ts_web"],
            },
            "dec_record_web",
        ),
    )
    end_node(
        root,
        _decision(
            root,
            "end_node",
            {
                "node_id": "n000",
                "result": {
                    "outcome": "completed",
                    "summary": "TS/Freq validation completed.",
                    "claim_updates": [
                        {
                            "claim_ref": "claim_ts_web",
                            "verdict": "supported",
                            "summary": "The deterministic TS/Freq gate passed.",
                            "evidence_refs": ["ev_tsfreq_web"],
                            "gate_result_refs": ["gr_tsfreq_web"],
                        }
                    ],
                    "audit": None,
                    "open_questions": [],
                },
            },
            "dec_end_n000",
        ),
    )
    if child:
        _start(root, "n001", "n000", ["claim_ts_web"])


def test_normalize_workspace_projects_v3_branch_events(tmp_path: Path) -> None:
    workspace = tmp_path / "branch"
    _make_workspace(workspace)
    view = normalize_workspace(workspace)
    event = next(item for item in view["branch_events"] if item["new_node"] == "n001")

    assert event["event_role"] == "node_created"
    assert event["from_node"] == "n000"
    assert event["parent_node"] == "n000"
    assert view["focus"]["focus_claim_refs"] == ["claim_ts_web"]


def test_graph_exposes_strategy_neutral_node_fields(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _make_workspace(workspace)
    graph = explorer_graph_payload_from_view(normalize_workspace(workspace))
    nodes = {node["id"]: node for node in graph["nodes"]}

    assert nodes["n000"]["tags"] == ["intake"]
    assert nodes["n000"]["state"] == "closed"
    assert nodes["n001"]["state"] == "open"
    assert nodes["n001"]["frontier"] is True
    for node in nodes.values():
        assert "phase" not in node
        assert "node_type" not in node
        assert "lifecycle" not in node
        assert "scope" not in node


def test_compute_status_is_separate_from_node_outcome(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _make_workspace(workspace, child=False)
    attempt = workspace / "nodes" / "n000" / "attempts" / "calc_test" / "outputs"
    attempt.mkdir(parents=True)
    (attempt / "calculation_result.json").write_text(
        json.dumps({"state": "failed", "program_status": "failed", "error_class": "scheduler_failure"}),
        encoding="utf-8",
    )

    node = explorer_graph_payload_from_view(normalize_workspace(workspace))["nodes"][0]
    assert node["outcome"] == "completed"
    assert node["calculation_state"] == "failed"
    assert node["calculation_program_status"] == "failed"


def test_static_ui_uses_v3_claim_gate_and_node_fields() -> None:
    html = (ROOT / "ts_web" / "static" / "index.html").read_text(encoding="utf-8")

    assert "TS Research Explorer" in html
    assert 'summaryRow("tags",' in html
    assert 'summaryRow("outcome",' in html
    assert 'summaryRow("node_type"' not in html
    assert 'summaryRow("lifecycle"' not in html
    assert 'summaryRow("validation_scope"' not in html
    assert "const NODE_TYPE_ICONS" not in html


def test_static_asset_resolves_from_current_package() -> None:
    expected = files("ts_web").joinpath("static", "index.html").read_bytes()
    assert ts_web_server._static_asset("index.html").read_bytes() == expected


def test_lineage_edges_follow_node_parents_once(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _make_workspace(workspace)
    graph = explorer_graph_payload_from_view(normalize_workspace(workspace))

    lineage = [edge for edge in graph["edges"] if edge["kind"] == "branch"]
    assert lineage == [{"id": "edge:n000:n001", "source": "n000", "target": "n001", "kind": "branch"}]


def test_register_workspace_deduplicates_and_rejects_source_pollution(tmp_path: Path) -> None:
    source = tmp_path / "single-step"
    _make_workspace(source)
    state = tmp_path / "web-state"
    first = register_workspace(source, state, "single")
    second = register_workspace(source, state, "single updated")

    assert first["workspace_id"] == second["workspace_id"]
    assert [row["label"] for row in list_workspaces(state)] == ["single updated"]
    with pytest.raises(ValueError, match="state_dir"):
        register_workspace(source, source / ".web")


def test_register_workspaces_validates_all_sources_before_writing(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _make_workspace(first)
    _make_workspace(second)
    state = second / ".web-state"

    with pytest.raises(ValueError, match="state_dir"):
        register_workspaces([first, second], state, ["A", "B"])
    assert not state.exists()


def test_web_server_api_is_read_only_and_v3_only(tmp_path: Path) -> None:
    source = tmp_path / "workspace"
    _make_workspace(source)
    before = _relative_files(source)
    state = tmp_path / "web-state"
    row = register_workspace(source, state, "workspace")
    server = create_server("127.0.0.1", 0, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        assert _get_json(host, port, "/api/health") == {"ok": True}
        workspaces = _get_json(host, port, "/api/workspaces")
        assert workspaces["default_workspace"] == row["workspace_id"]
        job = _get_json(host, port, f"/api/workspace/{row['workspace_id']}/job")
        assert job["app"] == "TS Research Explorer"
        assert job["research"]["focus_claim_refs"] == ["claim_ts_web"]
        claims = _get_json(host, port, f"/api/workspace/{row['workspace_id']}/claims")
        gates = _get_json(host, port, f"/api/workspace/{row['workspace_id']}/gates")
        assert claims["schema_version"] == "ts-claim-registry/1"
        assert gates["schema_version"] == "ts-gate-registry/1"
        node = _get_json(host, port, f"/api/workspace/{row['workspace_id']}/node/n000")
        assert node["node"]["outcome"] == "completed"
        assert "# Node Result" in node["markdown"]["reflection"]
        preview = _get_json(host, port, f"/api/workspace/{row['workspace_id']}/file?path=nodes/n000/node.json")
        assert preview["path"] == "nodes/n000/node.json"
        assert "TS Research Explorer" in _get_text(host, port, "/")
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
