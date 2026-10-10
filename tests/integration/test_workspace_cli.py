from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "apps" / "agent-cli" / "workspace_mode.py"
API = ROOT / "apps" / "agent-cli" / "research_api.py"


def _run(script: Path, *args: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(script), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    completed.check_returncode()
    return json.loads(completed.stdout)


def test_workspace_cli_roundtrip_uses_canonical_research_workspace(tmp_path):
    workspace=tmp_path/"workspace"
    initialized=_run(CLI,"--root",str(workspace),"--workspace-id","workspace_cli")
    assert initialized["schema_version"]=="research_workspace/2"
    assert initialized["state"]=="ready"
    request=tmp_path/"create.json"
    request.write_text(json.dumps({"goal": "Verify the optimized structure"}))
    created=_run(API,"research.create","--root",str(workspace),"--params-file",str(request))
    node_id=created["node"]["id"]
    request=tmp_path/"note.json"
    request.write_text(json.dumps({"node_id":node_id,"note":"Optimization done; need frequency validation"}))
    result=_run(API,"research.update","--root",str(workspace),"--params-file",str(request))
    assert result["accepted"]
    shown=_run(API,"research.read","--root",str(workspace))
    assert shown["schema_version"]=="research-snapshot/3"
    assert any(node["id"]==node_id for node in shown["nodes"])
    assert shown["research"]["nodes"] == []
    request = tmp_path / "scope.json"
    request.write_text(json.dumps({"entry_node_ids": [node_id], "focus_node_ids": [node_id]}))
    scoped = _run(API, "research.read", "--root", str(workspace), "--params-file", str(request))
    assert scoped["research"]["entry_node_ids"] == [node_id]
    assert scoped["research"]["focus_node_ids"] == [node_id]
    assert scoped["research"]["nodes"][0]["id"] == node_id
    found=_run(API,"research.search","--root",str(workspace),"--query","frequency")
    assert found["total"]==1 and found["records"][0]["node_id"]==node_id
    assert not (workspace/"research/progress.json").exists()


def test_workspace_rebuild_cli_recovers_missing_projections(tmp_path):
    workspace = tmp_path / 'repair'
    _run(CLI, '--root', str(workspace), '--workspace-id', 'repair')
    node = _run(API, 'research.create', '--root', str(workspace), '--goal', 'Preserve original research')['node']
    (workspace / 'research/map.json').unlink()
    fixed = _run(ROOT / 'apps/agent-cli/workspace.py', 'rebuild', '--root', str(workspace))
    assert fixed['rebuilt'] and fixed['nodes'] == 1
    report = _run(ROOT / 'apps/agent-cli/workspace.py', 'doctor', '--root', str(workspace))
    assert report['valid'] and report['status'] == 'healthy'
    assert _run(API, 'research.read', '--root', str(workspace), '--ref', node['id'])['node']['goal'] == 'Preserve original research'
