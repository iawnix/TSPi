from __future__ import annotations

import http.client
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from ts_web import normalize_workspace, register_workspace
from ts_web.registry import list_workspaces
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
        node = _get_json(host, port, f"/api/workspace/{row['workspace_id']}/node/n001")
        assert node["node"]["program_status"] == "completed"
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


def _relative_files(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
