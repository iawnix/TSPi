from __future__ import annotations

import http.client
import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from ts_workspace import end_node, init_workspace, report_workspace, start_node, update_workspace
from ts_web import normalize_workspace, register_workspace
from ts_web.normalize import explorer_graph_payload_from_view
from ts_web.registry import list_workspaces, register_workspaces
from ts_web.server import create_server


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "ts_web.py"


def test_normalize_workspace_uses_canonical_backtrack_events() -> None:
    fixture = ROOT / "fixtures" / "single_to_multistep_backtrack"
    tree = json.loads((fixture / "tree.json").read_text(encoding="utf-8"))
    view = normalize_workspace(fixture)
    assert view["backtrack_edges"] == [
        {
            "event_id": event.get("event_id"),
            "event_state": event.get("event_state"),
            "from_node": event.get("from_node"),
            "to_node": event.get("to_node"),
            "new_branch_node": event.get("new_branch_node"),
            "changed_variable": event.get("changed_variable"),
            "reason_code": event.get("reason_code"),
            "evidence_refs": event.get("evidence_refs", []),
        }
        for event in tree["backtrack_events"]
    ]
    assert view["nodes"][0]["display"]["claim_verdict"] == "refuted"


def test_backtrack_visual_semantics_are_distinct_from_refuted_status() -> None:
    fixture = ROOT / "fixtures" / "single_to_multistep_backtrack"
    graph = explorer_graph_payload_from_view(normalize_workspace(fixture))
    nodes = {node["id"]: node for node in graph["nodes"]}
    replacement_edges = [edge for edge in graph["edges"] if edge["kind"] == "backtrack_replacement"]

    assert nodes["n001"]["node_state"] == "refuted"
    assert nodes["n001"]["card_color"] == "red"
    assert nodes["n001"]["backtrack_badge"]["role"] == "backtrack_source"
    assert nodes["n001"]["backtrack_badge"]["color"] == "purple"
    assert replacement_edges
    assert {edge["edge_color"] for edge in replacement_edges} == {"blue"}
    assert graph["presentation"]["edge_kind"]["backtrack_replacement"]["color"] == "blue"
    assert graph["presentation"]["event_role"]["backtrack_source"]["color"] == "purple"


def test_static_ui_uses_outline_status_chips_and_explains_backtrack_symbol() -> None:
    html = (ROOT / "ts_web" / "static" / "index.html").read_text(encoding="utf-8")

    assert ".chip[data-color=\"red\"]" in html
    assert ".chip[data-color=\"red\"]    { color: var(--red);" in html
    assert ".chip[data-color=\"red\"]    { background:" not in html
    assert ".backtrack-badge { fill: none;" in html
    assert "symbol-legend" in html
    assert "↺" in html
    assert "backtracked from" in html


def test_backtrack_edges_and_events_dedupe_when_target_is_replacement(tmp_path: Path) -> None:
    workspace = tmp_path / "dedupe-backtrack"
    shutil.copytree(ROOT / "fixtures" / "single_to_multistep_backtrack", workspace)
    tree_path = workspace / "tree.json"
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    tree["backtrack_events"][0]["to_node"] = "n002"
    tree["backtrack_events"][0]["new_branch_node"] = "n002"
    tree_path.write_text(json.dumps(tree, indent=2) + "\n", encoding="utf-8")

    graph = explorer_graph_payload_from_view(normalize_workspace(workspace))
    backtrack_edges = [edge for edge in graph["edges"] if edge["kind"].startswith("backtrack")]
    n002_events = [
        event
        for event in graph["events"]
        if event["event_id"] == "bt_8b482922d2" and event["node_id"] == "n002"
    ]
    nodes = {node["id"]: node for node in graph["nodes"]}

    assert [(edge["kind"], edge["source"], edge["target"]) for edge in backtrack_edges] == [
        ("backtrack_replacement", "n001", "n002")
    ]
    assert [event["event_role"] for event in n002_events] == ["generated_from_backtrack"]
    assert nodes["n002"]["backtrack_target_event_ids"] == []
    assert nodes["n002"]["generated_from_backtrack_event_ids"] == ["bt_8b482922d2"]
    assert nodes["n002"]["backtrack_badge"]["role"] == "generated_from_backtrack"


def test_register_workspace_deduplicates_and_rejects_source_pollution(tmp_path: Path) -> None:
    source = ROOT / "fixtures" / "single_step_success"
    state = tmp_path / "web-state"
    first = register_workspace(source, state, "single")
    second = register_workspace(source, state, "single updated")
    assert first["workspace_id"] == second["workspace_id"]
    rows = list_workspaces(state)
    assert len(rows) == 1
    assert rows[0]["label"] == "single updated"

    with pytest.raises(ValueError, match="state_dir"):
        register_workspace(source, source / ".web")


def test_web_server_api_is_read_only(tmp_path: Path) -> None:
    source = ROOT / "fixtures" / "single_to_multistep_backtrack"
    before = _relative_files(source)
    state = tmp_path / "web-state"
    row = register_workspace(source, state, "backtrack")
    server = create_server("127.0.0.1", 0, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        health = _get_json(host, port, "/api/health")
        assert health == {"ok": True}
        workspaces = _get_json(host, port, "/api/workspaces")
        assert workspaces["workspaces"][0]["workspace_id"] == row["workspace_id"]
        assert workspaces["workspaces"][0]["id"] == row["workspace_id"]
        assert workspaces["default_workspace"] == row["workspace_id"]
        payload = _get_json(host, port, f"/api/workspace?id={row['workspace_id']}")
        assert payload["view"]["label"] == "backtrack"
        assert payload["view"]["backtrack_edges"][0]["new_branch_node"] == "n002"
        job = _get_json(host, port, f"/api/workspace/{row['workspace_id']}/job")
        assert job["graph"]["nodes"][0]["claim_verdict"] == "refuted"
        assert job["graph"]["edges"][0]["kind"] == "backtrack_replacement"
        single_tree = _get_json(host, port, "/api/tree")
        assert single_tree["edges"][0]["kind"] == "backtrack_replacement"
        node = _get_json(host, port, f"/api/workspace/{row['workspace_id']}/node/n001")
        assert node["node"]["program_status"] == "completed"
        single_node = _get_json(host, port, "/api/node/n001")
        assert single_node["node"]["program_status"] == "completed"
        assert node["markdown"]["decision_card"]
        assert "## Program" in node["markdown"]["reflection"]
        assert "Frequency job completed." in node["markdown"]["reflection"]
        assert "## Mechanism" in node["markdown"]["reflection"]
        preview = _get_json(host, port, f"/api/workspace/{row['workspace_id']}/file?path=nodes/n001/node.json")
        assert preview["path"] == "nodes/n001/node.json"
        html = _get_text(host, port, "/")
        assert "TS Hypothesis Explorer" in html
        assert 'id="workspaceList"' in html
        assert 'id="graphSvg"' in html
        assert 'id="detail"' in html
        assert 'id="toggleLeft"' in html
        assert 'id="toggleRight"' in html
        assert 'id="zoomReset"' in html
        assert 'id="minimapSvg"' in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert _relative_files(source) == before


def test_web_server_accepts_existing_registry_row_shape(tmp_path: Path) -> None:
    source = ROOT / "fixtures" / "single_step_success"
    state = tmp_path / "web-state"
    state.mkdir()
    (state / "workspaces.json").write_text(
        json.dumps({"workspaces": [{"id": "single-step", "name": "single", "source": str(source)}]}),
        encoding="utf-8",
    )
    server = create_server("127.0.0.1", 0, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        workspaces = _get_json(host, port, "/api/workspaces")
        assert workspaces["workspaces"][0]["id"] == "single-step"
        job = _get_json(host, port, "/api/workspace/single-step/job")
        assert job["graph"]["nodes"][0]["claim_verdict"] == "supported"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_ts_web_cli_register(tmp_path: Path) -> None:
    source = ROOT / "fixtures" / "single_step_success"
    state = tmp_path / "web-state"
    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "register",
            "--source-root",
            str(source),
            "--state-dir",
            str(state),
            "--label",
            "single",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    row = json.loads(completed.stdout)
    assert row["label"] == "single"
    assert (state / "workspaces.json").exists()


def test_ts_web_cli_serve_registers_multiple_source_roots(tmp_path: Path) -> None:
    """`serve --source-root` uses the same pre-registration helper."""
    sources = [ROOT / "fixtures" / "single_step_success", ROOT / "fixtures" / "single_to_multistep_backtrack"]
    state = tmp_path / "web-state"
    register_workspaces(sources, state, ["A", "B"])
    rows = json.loads((state / "workspaces.json").read_text(encoding="utf-8"))["workspaces"]
    labels = sorted(row["label"] for row in rows)
    assert labels == ["A", "B"]

    with pytest.raises(ValueError, match="more labels"):
        register_workspaces(sources, state, ["A", "B", "C"])


def test_ts_web_cli_list_and_remove(tmp_path: Path) -> None:
    source = ROOT / "fixtures" / "single_step_success"
    state = tmp_path / "web-state"
    register = subprocess.run(
        [sys.executable, str(CLI), "register", "--source-root", str(source), "--state-dir", str(state), "--label", "x"],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    workspace_id = json.loads(register.stdout)["workspace_id"]

    listed = subprocess.run(
        [sys.executable, str(CLI), "list", "--state-dir", str(state)],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    rows = json.loads(listed.stdout)
    assert any(row["workspace_id"] == workspace_id for row in rows)

    removed = subprocess.run(
        [sys.executable, str(CLI), "remove", "--state-dir", str(state), "--workspace-id", workspace_id],
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    assert json.loads(removed.stdout) == {"removed": workspace_id, "remaining": 0}


def test_web_server_unknown_workspace_returns_400(tmp_path: Path) -> None:
    """Unknown workspace id is a client error, not a server error."""
    source = ROOT / "fixtures" / "single_step_success"
    state = tmp_path / "web-state"
    register_workspace(source, state, "single")
    server = create_server("127.0.0.1", 0, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        status, body = _get_status_text(host, port, "/api/workspace/ws_does_not_exist/job")
        assert status == 400, body
        assert "unknown workspace" in body
        status, body = _get_status_text(host, port, "/api/workspace/ws_does_not_exist/node/n001")
        assert status == 400, body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_claim_state_reflects_pathway_model(tmp_path: Path) -> None:
    """Workspace claim_state is backend-derived from pathway and accepted TS state."""
    state = tmp_path / "web-state"
    accepted_row = register_workspace(ROOT / "fixtures" / "single_step_success", state, "accepted")
    hypothesis_row = register_workspace(ROOT / "fixtures" / "single_to_multistep_backtrack", state, "hypothesis")
    pathway_complete = tmp_path / "pathway-complete"
    shutil.copytree(ROOT / "fixtures" / "single_step_success", pathway_complete)
    (pathway_complete / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "ts-workspace",
                "accepted_ts_refs": ["accepted/upstream.json", "accepted/downstream.json"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (pathway_complete / "pathway_model.json").write_text(
        json.dumps(
            {
                "schema_version": "ts-pathway",
                "focus_pathway_id": "p_two_step",
                "pathways": [
                    {
                        "pathway_id": "p_two_step",
                        "label": "two step",
                        "status": "supported",
                        "steps": [
                            {"step_id": "s_reactant_to_intermediate", "status": "supported"},
                            {"step_id": "s_intermediate_to_product", "status": "supported"},
                            {"step_id": "s_full_pathway", "status": "supported"},
                        ],
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    complete_row = register_workspace(pathway_complete, state, "complete")
    server = create_server("127.0.0.1", 0, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        payload = _get_json(host, port, "/api/workspaces")
        by_id = {row["workspace_id"]: row for row in payload["workspaces"]}
        assert by_id[accepted_row["workspace_id"]]["claim_state"] == "accepted_ts"
        assert by_id[hypothesis_row["workspace_id"]]["claim_state"] == "pathway_hypothesis"
        assert by_id[complete_row["workspace_id"]]["claim_state"] == "pathway_complete"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_mechanism_analysis_uses_latest_tree_record(tmp_path: Path) -> None:
    workspace = tmp_path / "latest-mechanism"
    shutil.copytree(ROOT / "fixtures" / "single_step_success", workspace)

    node_id = "n999_pathway_audit"
    source_node = json.loads((workspace / "nodes" / "n001" / "node.json").read_text(encoding="utf-8"))
    latest_node = {
        **source_node,
        "node_id": node_id,
        "parent_node": "n001",
        "phase": "pathway_audit",
        "hypothesis": "The full route has a latest two-step pathway-level mechanism.",
        "closure": {
            **source_node["closure"],
            "mechanism": {
                "summary": "Latest mechanism analysis: reactant -> intermediate -> product.",
                "evidence_refs": ["ev_conn_001", "ev_tsfreq_001"],
            },
        },
    }
    (workspace / "nodes" / node_id).mkdir()
    (workspace / "nodes" / node_id / "node.json").write_text(
        json.dumps(latest_node, indent=2) + "\n",
        encoding="utf-8",
    )

    tree = json.loads((workspace / "tree.json").read_text(encoding="utf-8"))
    tree["nodes"].append(
        {
            "node_id": node_id,
            "parent_node": "n001",
            "phase": "pathway_audit",
            "lifecycle": "closed",
            "program_status": "completed",
            "claim_verdict": "supported",
            "hypothesis": latest_node["hypothesis"],
        }
    )
    tree["edges"].append({"parent_node": "n001", "child_node": node_id})
    (workspace / "tree.json").write_text(json.dumps(tree, indent=2) + "\n", encoding="utf-8")

    mechanism = json.loads((workspace / "mechanism_model.json").read_text(encoding="utf-8"))
    old_record = mechanism["accepted_facts"][0]
    new_record = {
        "node_id": node_id,
        "phase": "pathway_audit",
        "claim_verdict": "supported",
        "program_status": "completed",
        "hypothesis": latest_node["hypothesis"],
        "mechanism_summary": "Latest mechanism analysis: reactant -> intermediate -> product.",
        "evidence_refs": ["ev_conn_001", "ev_tsfreq_001"],
    }
    mechanism["accepted_facts"] = [new_record, old_record]
    (workspace / "mechanism_model.json").write_text(json.dumps(mechanism, indent=2) + "\n", encoding="utf-8")

    state = tmp_path / "web-state"
    row = register_workspace(workspace, state, "latest")
    server = create_server("127.0.0.1", 0, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        job = _get_json(host, port, f"/api/workspace/{row['workspace_id']}/job")
        latest = job["mechanism"]["latest_analysis"]
        assert latest == [
            "n999_pathway_audit / pathway_audit / supported: "
            "Latest mechanism analysis: reactant -> intermediate -> product."
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_pathway_audit_not_accepted_is_not_rendered_as_success(tmp_path: Path) -> None:
    workspace = tmp_path / "negative-pathway-audit"
    init_workspace(workspace)
    report = report_workspace(workspace)
    report_ref = {"report_id": report["report_id"], "workspace_root": str(workspace)}
    node_id = "n001_pathway_audit"

    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Audit a strict pathway after connectivity failures.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "node_id": node_id,
                "phase": "pathway_audit",
                "hypothesis": "The current evidence may not support strict R to P connectivity.",
                "expected_evidence": ["pathway_audit_summary"],
                "pathway_ref": {"pathway_id": "p_r_to_i_to_p", "step_id": "s_i_to_p"},
            },
        },
    )
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register a negative strict pathway audit.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": {
                    "evidence_id": "ev_negative_pathway_audit",
                    "kind": "pathway_audit_summary",
                    "role": "pathway_audit",
                    "evidence_tier": "local_parse",
                    "node_id": node_id,
                    "summary": "Strict R->P pathway is not accepted because the connectivity gate is missing.",
                    "quality": {
                        "strict_pathway_supported": False,
                        "strict_pathway_decision": "not_accepted",
                        "accepted_ts_available": False,
                    },
                    "diagnostics": ["no_accepted_ts", "second_step_connectivity_gate_missing"],
                }
            },
        },
    )
    end_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "end_node",
            "rationale": "Close the negative pathway audit.",
            "evidence_refs": ["ev_negative_pathway_audit"],
            "report_ref": report_ref,
            "payload": {
                "node_id": node_id,
                "closure": {
                    "program_status": "completed",
                    "claim_verdict": "supported",
                    "reason_code": "strict_r_to_p_not_accepted_missing_second_step_connectivity",
                    "program": {"summary": "Audit completed.", "evidence_refs": ["ev_negative_pathway_audit"]},
                    "mechanism": {
                        "summary": "The audit supports not accepting the pathway.",
                        "evidence_refs": ["ev_negative_pathway_audit"],
                    },
                    "implication": "Agent decides whether to open a new hypothesis branch.",
                    "open_questions": [],
                },
            },
        },
    )

    view = normalize_workspace(workspace)
    graph = explorer_graph_payload_from_view(view)
    node = graph["nodes"][0]

    assert view["valid"] is True
    assert node["claim_verdict"] == "supported"
    assert node["node_state"] == "pathway_not_accepted"
    assert node["state_label"] == "pathway not accepted"
    assert node["card_color"] == "amber"
    assert graph["presentation"]["node_state"]["pathway_not_accepted"]["color"] == "amber"

    state = tmp_path / "web-state"
    row = register_workspace(workspace, state, "negative-audit")
    server = create_server("127.0.0.1", 0, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        payload = _get_json(host, port, "/api/workspaces")
        summary = payload["workspaces"][0]
        assert summary["workspace_id"] == row["workspace_id"]
        assert summary["claim_state"] == "pathway_not_accepted"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_claim_state_marks_terminal_refute_as_needs_followup(tmp_path: Path) -> None:
    state = tmp_path / "web-state"
    workspace = tmp_path / "terminal-refute"
    _make_refuted_terminal_workspace(workspace)
    row = register_workspace(workspace, state, "terminal")
    server = create_server("127.0.0.1", 0, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        payload = _get_json(host, port, "/api/workspaces")
        summary = payload["workspaces"][0]
        assert summary["workspace_id"] == row["workspace_id"]
        assert summary["claim_state"] == "needs_followup"
        assert "accepted_ts" not in summary
        assert "charge" not in summary
        assert "multiplicity" not in summary
        job = _get_json(host, port, f"/api/workspace/{row['workspace_id']}/job")
        assert job["workspace"]["claim_state"] == "needs_followup"
        assert job["graph"]["presentation"]["workspace_state"]["needs_followup"]["color"] == "amber"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _get_json(host: str, port: int, path: str) -> dict:
    return json.loads(_get_text(host, port, path))


def _get_text(host: str, port: int, path: str) -> str:
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        body = response.read().decode("utf-8")
        assert response.status == 200, body
        return body
    finally:
        conn.close()


def _get_status_text(host: str, port: int, path: str) -> tuple[int, str]:
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        return response.status, response.read().decode("utf-8")
    finally:
        conn.close()


def _relative_files(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}


def _make_refuted_terminal_workspace(workspace: Path) -> None:
    init_workspace(workspace)
    report = report_workspace(workspace)
    report_ref = {"report_id": report["report_id"], "workspace_root": str(workspace)}
    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Start a connectivity validation node.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "node_id": "n001",
                "phase": "connectivity_validation",
                "hypothesis": "Candidate connects the expected endpoints.",
                "expected_evidence": [],
            },
        },
    )
    end_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "end_node",
            "rationale": "Close the connectivity validation node as refuted.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "node_id": "n001",
                "closure": {
                    "program_status": "completed",
                    "claim_verdict": "refuted",
                    "program": {"summary": "Connectivity check completed.", "evidence_refs": []},
                    "mechanism": {"summary": "Endpoint assignment is not connected.", "evidence_refs": []},
                    "implication": "Open a replacement branch.",
                    "open_questions": ["Find a different candidate."],
                },
            },
        },
    )
