from __future__ import annotations

import json
import subprocess
from pathlib import Path

from research_agent.research.workspace import initialize_workspace, validate_workspace_manifest


ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_MODULE = ROOT / "apps" / "agent" / "host" / "workspace.mjs"


def _node_create(root: Path, workspace_id: str) -> dict[str, object]:
    script = (
        "const { create_workspace_initializer } = await import(process.argv[1]);"
        "const value=await create_workspace_initializer().initialize_workspace({"
        "workspace_root:process.argv[2],workspace_id:process.argv[3],workspace_mode:'research'});"
        "process.stdout.write(JSON.stringify(value));"
    )
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script, WORKSPACE_MODULE.as_uri(), str(root), workspace_id],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return json.loads(completed.stdout)


def _node_attach(root: Path) -> dict[str, object]:
    script = (
        "const { create_workspace_initializer } = await import(process.argv[1]);"
        "const value=await create_workspace_initializer().attach_workspace(process.argv[2]);"
        "process.stdout.write(JSON.stringify(value));"
    )
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script, WORKSPACE_MODULE.as_uri(), str(root)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return json.loads(completed.stdout)


def test_js_created_workspace_is_accepted_by_python_authority(tmp_path: Path) -> None:
    root = tmp_path / "js-created"
    manifest = _node_create(root, "workspace_js_contract")
    accepted = validate_workspace_manifest(manifest, root)
    assert accepted["schema_version"] == "research_workspace/2"
    assert accepted["workspace_id"] == "workspace_js_contract"


def test_python_created_workspace_is_accepted_by_js_transport(tmp_path: Path) -> None:
    root = tmp_path / "python-created"
    manifest = initialize_workspace(root, "workspace_python_contract", "research")
    attached = _node_attach(root)
    assert attached["schema_version"] == manifest["schema_version"]
    assert attached["workspace_id"] == "workspace_python_contract"
    assert attached["research_memory"] == manifest["research_memory"]
