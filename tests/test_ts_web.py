from __future__ import annotations

import http.client
import json
import subprocess
import sys
import threading
from importlib.resources import files
from pathlib import Path

import pytest

from ts_workspace import end_node, start_node, update_workspace
from ts_web import normalize_workspace, register_workspace
from ts_web.normalize import explorer_graph_payload_from_view
from ts_web.registry import list_workspaces, register_workspaces
from ts_web import server as ts_web_server
from ts_web.server import create_server
from v3_helpers import (
    HYPOTHESIS_ID,
    HYPOTHESIS_REF,
    bootstrap_v3_workspace,
    gate_artifact_metadata,
    make_accepted_workspace,
    make_branch_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "ts_web.py"


def test_normalize_workspace_uses_canonical_branch_events(tmp_path: Path) -> None:
    workspace = tmp_path / "branch"
    make_branch_workspace(workspace)
    tree = json.loads((workspace / "tree.json").read_text(encoding="utf-8"))
    view = normalize_workspace(workspace)
    assert view["branch_edges"] == [
        {
            "event_id": event.get("event_id"),
            "event_state": event.get("event_state"),
            "relation": event.get("relation"),
            "from_node": event.get("from_node"),
            "anchor_node": event.get("anchor_node"),
            "new_node": event.get("new_node"),
            "parent_node": event.get("parent_node"),
            "is_rebased": event.get("is_rebased"),
            "changed_variable": event.get("changed_variable"),
            "reason_code": event.get("reason_code"),
            "evidence_refs": event.get("evidence_refs", []),
        }
        for event in tree["branch_events"]
    ]
    nodes = {node["node_id"]: node for node in view["nodes"]}
    assert nodes["n001"]["display"]["claim_verdict"] == "refuted"


def test_branch_visual_semantics_are_distinct_from_refuted_status(tmp_path: Path) -> None:
    workspace = tmp_path / "branch"
    make_branch_workspace(workspace)
    graph = explorer_graph_payload_from_view(normalize_workspace(workspace))
    nodes = {node["id"]: node for node in graph["nodes"]}
    generated_edges = [edge for edge in graph["edges"] if edge["kind"] == "branch_generated"]

    assert nodes["n001"]["node_state"] == "refuted"
    assert nodes["n001"]["card_color"] == "red"
    assert nodes["n001"]["branch_badge"]["role"] == "branch_source"
    assert nodes["n001"]["branch_badge"]["color"] == "purple"
    assert generated_edges
    assert {edge["edge_color"] for edge in generated_edges} == {"blue"}
    assert graph["presentation"]["edge_kind"]["branch_generated"]["color"] == "blue"
    assert graph["presentation"]["event_role"]["branch_source"]["color"] == "purple"


def test_static_ui_uses_outline_status_chips_and_explains_branch_symbol() -> None:
    html = (ROOT / "ts_web" / "static" / "index.html").read_text(encoding="utf-8")

    assert ".chip[data-color=\"red\"]" in html
    assert ".chip[data-color=\"red\"]    { color: var(--red);" in html
    assert ".chip[data-color=\"red\"]    { background:" not in html
    assert ".branch-badge { fill: none;" in html
    assert "symbol-legend" in html
    assert "↺" in html
    assert "branched from" in html


def test_static_ui_only_anchor_edges_render_as_back_edges() -> None:
    html = (ROOT / "ts_web" / "static" / "index.html").read_text(encoding="utf-8")

    assert 'const back = e.kind === "branch_anchor";' in html
    assert 'e.kind.startsWith("branch")' not in html


def test_static_ui_refresh_without_workspace_renders_empty_state() -> None:
    html = (ROOT / "ts_web" / "static" / "index.html").read_text(encoding="utf-8")

    assert "function renderNoWorkspace()" in html
    assert "renderNoWorkspace();\n      return;" in html
    assert 'throw new Error("workspace_required")' not in html
    assert "Select a workspace" in html
    assert "No workspaces" in html


def test_static_asset_resolves_from_current_ts_web_package() -> None:
    expected = files("ts_web").joinpath("static", "index.html").read_bytes()
    assert ts_web_server._static_asset("index.html").read_bytes() == expected

    server_source = (ROOT / "ts_web" / "server.py").read_text(encoding="utf-8")
    assert "STATIC_DIR" not in server_source
    assert "Path(__file__).resolve().parent / \"static\"" not in server_source
    assert "files(STATIC_PACKAGE)" in server_source


def test_branch_edges_and_events_dedupe_when_target_is_replacement(tmp_path: Path) -> None:
    workspace = tmp_path / "dedupe-branch"
    make_branch_workspace(workspace)
    tree_path = workspace / "tree.json"
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    event = next(item for item in tree["branch_events"] if item["new_node"] == "n002")
    event_id = event["event_id"]
    event["anchor_node"] = "n002"
    tree_path.write_text(json.dumps(tree, indent=2) + "\n", encoding="utf-8")

    graph = explorer_graph_payload_from_view(normalize_workspace(workspace))
    branch_edges = [edge for edge in graph["edges"] if edge["kind"] == "branch_generated" and edge.get("event_id") == event_id]
    n002_events = [
        event
        for event in graph["events"]
        if event["event_id"] == event_id and event["node_id"] == "n002"
    ]
    nodes = {node["id"]: node for node in graph["nodes"]}

    assert [(edge["kind"], edge["source"], edge["target"]) for edge in branch_edges] == [
        ("branch_generated", "n001", "n002")
    ]
    assert [event["event_role"] for event in n002_events] == ["generated_from_branch"]
    assert nodes["n002"]["branch_anchor_event_ids"] == []
    assert nodes["n002"]["generated_from_branch_event_ids"] == [event_id]
    assert nodes["n002"]["branch_badge"]["role"] == "generated_from_branch"


def test_continue_parent_branch_events_do_not_duplicate_lineage_edges(tmp_path: Path) -> None:
    workspace = tmp_path / "accepted"
    make_accepted_workspace(workspace)
    graph = explorer_graph_payload_from_view(normalize_workspace(workspace))

    lineage_edges = [edge for edge in graph["edges"] if edge["kind"] == "branch"]
    assert len(lineage_edges) == len(graph["nodes"]) - 1
    assert not [edge for edge in graph["edges"] if edge["kind"] == "branch_generated"]
    assert not [edge for edge in graph["edges"] if edge["kind"] == "branch_anchor"]


def test_register_workspace_deduplicates_and_rejects_source_pollution(tmp_path: Path) -> None:
    source = tmp_path / "single-step"
    make_accepted_workspace(source)
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
    source = tmp_path / "branch"
    make_branch_workspace(source)
    before = _relative_files(source)
    state = tmp_path / "web-state"
    row = register_workspace(source, state, "branch")
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
        assert payload["view"]["label"] == "branch"
        assert any(edge["new_node"] == "n002" for edge in payload["view"]["branch_edges"])
        job = _get_json(host, port, f"/api/workspace/{row['workspace_id']}/job")
        graph_nodes = {node["id"]: node for node in job["graph"]["nodes"]}
        assert graph_nodes["n001"]["claim_verdict"] == "refuted"
        assert any(edge["kind"] == "branch_generated" for edge in job["graph"]["edges"])
        single_tree = _get_json(host, port, "/api/tree")
        assert any(edge["kind"] == "branch_generated" for edge in single_tree["edges"])
        node = _get_json(host, port, f"/api/workspace/{row['workspace_id']}/node/n001")
        assert node["node"]["program_status"] == "completed"
        single_node = _get_json(host, port, "/api/node/n001")
        assert single_node["node"]["program_status"] == "completed"
        assert node["markdown"]["decision_card"]
        assert "## Program" in node["markdown"]["reflection"]
        assert "Program completed." in node["markdown"]["reflection"]
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
    source = tmp_path / "single-step"
    make_accepted_workspace(source)
    state = tmp_path / "web-state"
    state.mkdir()
    (state / "workspaces.json").write_text(
        json.dumps({"workspaces": [{}, {"id": "single-step", "name": "single", "source": str(source)}]}),
        encoding="utf-8",
    )
    server = create_server("127.0.0.1", 0, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        workspaces = _get_json(host, port, "/api/workspaces")
        assert len(workspaces["workspaces"]) == 1
        assert workspaces["workspaces"][0]["id"] == "single-step"
        assert workspaces["default_workspace"] == "single-step"
        job = _get_json(host, port, "/api/workspace/single-step/job")
        assert job["graph"]["nodes"][0]["claim_verdict"] == "supported"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_ts_web_cli_register(tmp_path: Path) -> None:
    source = tmp_path / "single-step"
    make_accepted_workspace(source)
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
    accepted = tmp_path / "accepted"
    branch = tmp_path / "branch"
    make_accepted_workspace(accepted)
    make_branch_workspace(branch)
    sources = [accepted, branch]
    state = tmp_path / "web-state"
    register_workspaces(sources, state, ["A", "B"])
    rows = json.loads((state / "workspaces.json").read_text(encoding="utf-8"))["workspaces"]
    labels = sorted(row["label"] for row in rows)
    assert labels == ["A", "B"]

    with pytest.raises(ValueError, match="more labels"):
        register_workspaces(sources, state, ["A", "B", "C"])


def test_ts_web_cli_list_and_remove(tmp_path: Path) -> None:
    source = tmp_path / "single-step"
    make_accepted_workspace(source)
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
    source = tmp_path / "single-step"
    make_accepted_workspace(source)
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
    accepted = tmp_path / "accepted"
    hypothesis = tmp_path / "hypothesis"
    pathway_audited = tmp_path / "pathway-audited"
    make_accepted_workspace(accepted)
    make_branch_workspace(hypothesis)
    report_ref = make_accepted_workspace(pathway_audited)
    start_node(
        pathway_audited,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Start accepted pathway audit.",
            "evidence_refs": ["ev_tsfreq_001", "ev_conn_001"],
            "report_ref": report_ref,
            "payload": {
                "node_id": "n004",
                "parent_node": "n003",
                "phase": "pathway_audit",
                "hypothesis": "The strict pathway is accepted.",
                "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": ["pred_pathway_001"]},
                "branch_context": {"relation": "continue_parent", "from_node": "n003", "anchor_node": "n000"},
                "expected_evidence": ["pathway_audit_summary"],
                "pathway_ref": {"pathway_id": "p_single", "step_id": "s1"},
            },
        },
    )
    update_workspace(
        pathway_audited,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register accepted pathway audit evidence.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": {
                    "evidence_id": "ev_pathway_accepted",
                    "kind": "pathway_audit_summary",
                    "role": "pathway_audit_summary",
                    "evidence_tier": "local_parse",
                    "node_id": "n004",
                    "summary": "The strict pathway is accepted.",
                    **gate_artifact_metadata("nodes/n004/outputs/pathway_audit.json"),
                    "quality": {
                        "hypothesis_id": HYPOTHESIS_ID,
                        "strict_pathway_supported": True,
                        "strict_pathway_decision": "accepted",
                    },
                    "facts": {"whole_R_to_P_pathway_accepted": True},
                }
            },
        },
    )
    end_node(
        pathway_audited,
        {
            "schema_version": "ts-decision",
            "action": "end_node",
            "rationale": "Close accepted pathway audit.",
            "evidence_refs": ["ev_pathway_accepted"],
            "report_ref": report_ref,
            "payload": {
                "node_id": "n004",
                "closure": {
                    "program_status": "completed",
                    "claim_verdict": "supported",
                    "reason_code": "strict_r_to_p_pathway_accepted",
                    "program": {"summary": "Audit completed.", "evidence_refs": ["ev_pathway_accepted"]},
                    "mechanism": {
                        "summary": "Pathway accepted.",
                        "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": ["pred_pathway_001"]},
                        "evidence_refs": ["ev_pathway_accepted"],
                    },
                    "implication": "Report the accepted pathway.",
                    "open_questions": [],
                },
            },
        },
    )
    accepted_row = register_workspace(accepted, state, "accepted")
    hypothesis_row = register_workspace(hypothesis, state, "hypothesis")
    pathway_audited_row = register_workspace(pathway_audited, state, "pathway-audited")
    pathway_complete = tmp_path / "pathway-complete"
    make_accepted_workspace(pathway_complete)
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
        assert by_id[pathway_audited_row["workspace_id"]]["claim_state"] == "pathway_complete"
        assert by_id[complete_row["workspace_id"]]["claim_state"] == "pathway_complete"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_mechanism_analysis_uses_latest_tree_record(tmp_path: Path) -> None:
    workspace = tmp_path / "latest-mechanism"
    make_accepted_workspace(workspace)

    node_id = "n999_pathway_audit"
    source_node = json.loads((workspace / "nodes" / "n001" / "node.json").read_text(encoding="utf-8"))
    latest_node = {
        **source_node,
        "node_id": node_id,
        "parent_node": "n001",
        "branch_context": {"relation": "continue_parent", "from_node": "n001", "anchor_node": "n000"},
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
            "branch_context": latest_node["branch_context"],
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
        assert latest[:1] == [
            "n999_pathway_audit / pathway_audit / supported: "
            "Latest mechanism analysis: reactant -> intermediate -> product."
        ]
        assert any("evidence ev_conn_001 / connectivity_gate" in line for line in latest)
        assert any("evidence ev_tsfreq_001 / tsfreq_gate" in line for line in latest)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_mechanism_analysis_includes_closure_facts_and_evidence_quality(tmp_path: Path) -> None:
    workspace = tmp_path / "mechanism-evidence"
    report_ref = bootstrap_v3_workspace(workspace)
    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Validate TS/Freq.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "node_id": "n001",
                "parent_node": "n000",
                "phase": "tsfreq_validation",
                "hypothesis": "The TS candidate is a first-order saddle.",
                "hypothesis_ref": HYPOTHESIS_REF,
                "branch_context": {"relation": "continue_parent", "from_node": "n000", "anchor_node": "n000"},
                "expected_evidence": ["tsfreq_gate"],
            },
        },
    )
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register TS/Freq gate.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": {
                    "evidence_id": "ev_tsfreq_rich",
                    "kind": "gaussian_tsfreq_validation",
                    "role": "tsfreq_gate",
                    "evidence_tier": "local_parse",
                    "node_id": "n001",
                    "summary": "One imaginary mode matches the reaction center.",
                    **gate_artifact_metadata("nodes/n001/outputs/tsfreq_rich.json"),
                    "quality": {
                        "hypothesis_id": HYPOTHESIS_ID,
                        "prediction_ids": ["pred_mode_001"],
                        "verdict_against_prediction": "supported",
                        "imaginary_frequency_count": 1,
                        "imaginary_frequencies_cm-1": [-659.8838],
                        "mode_verdict": "mode_matches_reaction_center",
                        "final_reaction_center_distances_A": {"C2-C3": 2.122249, "C2-O6": 1.827943},
                    },
                }
            },
        },
    )
    end_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "end_node",
            "rationale": "Close TS/Freq.",
            "evidence_refs": ["ev_tsfreq_rich"],
            "report_ref": report_ref,
            "payload": {
                "node_id": "n001",
                "closure": {
                    "program_status": "completed",
                    "claim_verdict": "supported",
                    "program": {
                        "summary": "Gaussian completed.",
                        "evidence_refs": ["ev_tsfreq_rich"],
                        "facts": ["Normal Gaussian termination."],
                    },
                    "mechanism": {
                        "summary": "The mode matches C2-C3/C2-O6 exchange.",
                        "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": ["pred_mode_001"]},
                        "evidence_refs": ["ev_tsfreq_rich"],
                        "facts": ["C2-C3 elongates while C2-O6 forms."],
                    },
                    "implication": "Run IRC next.",
                    "open_questions": [],
                },
            },
        },
    )

    view = normalize_workspace(workspace)
    state = tmp_path / "web-state"
    row = register_workspace(workspace, state, "mechanism")
    server = create_server("127.0.0.1", 0, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        job = _get_json(host, port, f"/api/workspace/{row['workspace_id']}/job")
        latest = job["mechanism"]["latest_analysis"]
        graph = explorer_graph_payload_from_view(view)
        n001_events = [event for event in graph["events"] if event.get("node_id") == "n001"]

        assert any("mechanism fact: C2-C3 elongates while C2-O6 forms." in line for line in latest)
        assert any("program fact: Normal Gaussian termination." in line for line in latest)
        assert any("imaginary_frequency_count=1" in line for line in latest)
        assert any("mode_verdict=mode_matches_reaction_center" in line for line in latest)
        assert any(event["event_type"] == "branch" for event in n001_events)
        assert [event["decision"] for event in n001_events if event["event_type"] != "branch"] == ["start_node", "end_node"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_pathway_audit_not_accepted_is_not_rendered_as_success(tmp_path: Path) -> None:
    workspace = tmp_path / "negative-pathway-audit"
    report_ref = bootstrap_v3_workspace(workspace)
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
                "parent_node": "n000",
                "phase": "pathway_audit",
                "hypothesis": "The current evidence may not support strict R to P connectivity.",
                "hypothesis_ref": HYPOTHESIS_REF,
                "branch_context": {"relation": "continue_parent", "from_node": "n000", "anchor_node": "n000"},
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
                    "role": "pathway_audit_summary",
                    "evidence_tier": "local_parse",
                    "node_id": node_id,
                    "summary": "Strict R->P pathway is not accepted because the connectivity gate is missing.",
                    **gate_artifact_metadata("nodes/n001_pathway_audit/outputs/pathway_audit.json"),
                    "quality": {
                        "hypothesis_id": HYPOTHESIS_ID,
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
                        "hypothesis_ref": HYPOTHESIS_REF,
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
    node = next(item for item in graph["nodes"] if item["id"] == node_id)

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
    report_ref = bootstrap_v3_workspace(workspace)
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
                "parent_node": "n000",
                "phase": "connectivity_validation",
                "hypothesis": "Candidate connects the expected endpoints.",
                "hypothesis_ref": HYPOTHESIS_REF,
                "branch_context": {"relation": "continue_parent", "from_node": "n000", "anchor_node": "n000"},
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
                    "mechanism": {
                        "summary": "Endpoint assignment is not connected.",
                        "hypothesis_ref": HYPOTHESIS_REF,
                        "revision": {
                            "action": "refute_prediction",
                            "prediction_ids": HYPOTHESIS_REF["prediction_ids"],
                            "changed_variable": "reaction_center",
                        },
                        "evidence_refs": [],
                    },
                    "implication": "Open a replacement branch.",
                    "open_questions": ["Find a different candidate."],
                },
            },
        },
    )
