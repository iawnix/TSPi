from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "extensions" / "shared" / "package-source-policy.ts"
CONTROL = ROOT / "extensions" / "ts-workflow-control" / "index.ts"
TS_LOADER = ROOT / "tests" / "typescript_loader.mjs"


def test_installed_runtime_routes_package_reads_to_public_skill(tmp_path: Path) -> None:
    implementation_link = tmp_path / "implementation"
    implementation_link.symlink_to(ROOT / "tests", target_is_directory=True)
    script = f"""
import {{
  guardPackageSourceRead,
  packageSourceSystemPrompt,
}} from {json.dumps(POLICY.as_uri())};
const call = (toolName, path) => ({{ type: "tool_call", toolCallId: `${{toolName}}-1`, toolName, input: {{ path }} }});
const cwd = {json.dumps(str(tmp_path))};
const decision = (toolName, path) => guardPackageSourceRead(call(toolName, path), cwd) ?? null;
process.stdout.write(JSON.stringify({{
  skill: decision("read", {json.dumps(str(ROOT / 'skills' / 'transition-state-workflow' / 'SKILL.md'))}),
  reference: decision("grep", {json.dumps(str(ROOT / 'skills' / 'transition-state-workflow' / 'references'))}),
  workspace: decision("find", {json.dumps(str(tmp_path / 'workspace'))}),
  tests: decision("read", {json.dumps(str(ROOT / 'tests' / 'test_pi_runtime_integration.py'))}),
  extension: decision("ls", {json.dumps(str(ROOT / 'extensions'))}),
  symlink: decision("read", {json.dumps(str(implementation_link / 'test_pi_compute_tools.py'))}),
  systemPrompt: packageSourceSystemPrompt(),
}}));
"""
    result = _node_json(script)

    assert result["skill"] is None
    assert result["reference"] is None
    assert result["workspace"] is None
    for key in ("tests", "extension", "symlink"):
        assert result[key]["block"] is True
        assert "not usage documentation" in result[key]["reason"]
        assert "authored checkout" in result[key]["reason"]
    assert "Installed TS research runtime" in result["systemPrompt"]


def test_control_extension_applies_one_policy_to_root_entrypoints() -> None:
    script = f"""
import installControl from {json.dumps(CONTROL.as_uri())};
const handlers = {{}};
const pi = {{
  on: (name, handler) => handlers[name] = handler,
  registerEntryRenderer: () => {{}},
  registerTool: () => {{}},
  registerCommand: () => {{}},
}};
installControl(pi);
const ctx = {{ cwd: "/tmp/no-ts-workspace" }};
const before = await handlers.before_agent_start({{ systemPrompt: "base" }}, ctx);
const blocked = await handlers.tool_call({{
  type: "tool_call",
  toolCallId: "read-1",
  toolName: "read",
  input: {{ path: {json.dumps(str(ROOT / 'tests' / 'test_pi_runtime_integration.py'))} }},
}}, ctx);
process.stdout.write(JSON.stringify({{ before, blocked }}));
"""
    result = _node_json(script)

    assert result["before"]["systemPrompt"].startswith("base\n\nInstalled TS research runtime")
    assert result["blocked"]["block"] is True


def _node_json(script: str):
    completed = subprocess.run(
        ["node", "--experimental-loader", str(TS_LOADER), "--input-type=module", "--eval", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)
