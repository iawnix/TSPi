from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ts_workspace import report_lineage_context, report_node, report_workspace
from strict_helpers import CLAIM_ID, bootstrap_strict_workspace, end_research_node, start_research_node


ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "extensions" / "ts-workflow-control" / "summary.cjs"
CONTROL_EXTENSION = ROOT / "extensions" / "ts-workflow-control" / "index.ts"
TOOL_CATALOG = ROOT / "extensions" / "shared" / "tool-catalog.ts"
SKILL_ROOT = ROOT / "skills" / "transition-state-workflow"
TS_LOADER = ROOT / "tests" / "typescript_loader.mjs"
PI_PACKAGE = ROOT / "node_modules" / "@earendil-works" / "pi-coding-agent" / "package.json"


def test_pi_package_manifest_exposes_skill_and_extension() -> None:
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert "pi-package" in manifest["keywords"]
    assert manifest["name"] == "@iawnix/ts-agent"
    assert manifest["version"] == "0.5.0"
    assert manifest["private"] is True
    assert manifest["pi"]["skills"] == ["./skills/transition-state-workflow"]
    assert manifest["pi"]["extensions"] == [
        "./extensions/ts-workflow-control",
        "./extensions/ts-workflow-ui/index.ts",
        "./extensions/ts-workflow-review/index.ts",
        "./extensions/ts-workflow-compute/index.ts",
        "./extensions/ts-workflow-artifacts/index.ts",
    ]
    assert "subagents" not in manifest["pi"]
    assert not any("subagent" in name for name in manifest.get("dependencies", {}))
    assert manifest["peerDependencies"]["@earendil-works/pi-ai"] == ">=0.81.1 <1.0.0"
    assert manifest["peerDependencies"]["@earendil-works/pi-coding-agent"] == ">=0.81.1 <1.0.0"
    assert manifest["peerDependencies"]["@earendil-works/pi-tui"] == ">=0.81.1 <1.0.0"
    assert manifest["dependencies"]["typebox"] == "^1.3.7"
    assert manifest["engines"]["node"] == ">=22.19.0"
    assert "--workspace-root" in manifest["scripts"]["install-env"]
    assert "TS_WORKSPACE_ROOT" in manifest["scripts"]["install-env"]
    assert "tests/test_pi_subagent_contract.py" in manifest["scripts"]["test:pi-adapter"]
    assert "postinstall" not in manifest["scripts"]

    extension_source = (ROOT / "extensions" / "ts-workflow-control" / "index.ts").read_text(encoding="utf-8")
    assert 'const DECISION_ACTIONS = ["start_node", "update_workspace", "end_node"]' in extension_source
    assert "name: TS_PUBLIC_TOOL_NAMES.workspaceDecisionDraft" in extension_source
    assert "name: TS_PUBLIC_TOOL_NAMES.workspaceDecisionValidate" in extension_source
    assert "name: TS_PUBLIC_TOOL_NAMES.workspaceDecisionApply" in extension_source
    assert 'name: "ts_workspace_decision"' not in extension_source
    assert '"artifacts"' in extension_source
    assert 'runComputeJson(pi, "list-artifacts"' in extension_source
    assert "mode=artifacts" in extension_source
    assert 'runComputeJson(pi, "capabilities"' in extension_source
    assert "mode=capabilities" in extension_source


def test_public_tool_catalog_separates_workspace_subagent_and_remote_execution() -> None:
    catalog = TOOL_CATALOG.read_text(encoding="utf-8")
    expected = {
        "workspaceContext": "ts_workspace_context",
        "workspaceDecisionDraft": "ts_workspace_decision_draft",
        "workspaceDecisionValidate": "ts_workspace_decision_validate",
        "workspaceDecisionApply": "ts_workspace_decision_apply",
        "remoteInspect": "ts_remote_inspect",
        "subagentReview": "ts_subagent_review",
        "reviewDisposition": "ts_review_disposition",
        "subagentCompute": "ts_subagent_compute",
        "subagentRender": "ts_subagent_render",
        "subagentReport": "ts_subagent_report",
        "notifyUser": "ts_notify_user",
    }
    for key, name in expected.items():
        assert f'{key}: "{name}"' in catalog

    for key in ("workspaceContext", "workspaceDecisionDraft", "workspaceDecisionValidate", "workspaceDecisionApply"):
        assert f'[TS_PUBLIC_TOOL_NAMES.{key}]: "deterministic_workspace"' in catalog
    assert '[TS_PUBLIC_TOOL_NAMES.remoteInspect]: "deterministic_infrastructure"' in catalog
    assert '[TS_PUBLIC_TOOL_NAMES.reviewDisposition]: "deterministic_operational"' in catalog
    for key in ("subagentReview", "subagentCompute", "subagentRender", "subagentReport"):
        assert f'[TS_PUBLIC_TOOL_NAMES.{key}]: "child_agent"' in catalog
    assert '[TS_PUBLIC_TOOL_NAMES.notifyUser]: "deterministic_external"' in catalog

    for legacy in (
        "ts_workspace_decide",
        "ts_workspace_validate",
        "ts_workspace_apply",
        "ts_workspace_subagent",
        "ts_workspace_compute_operator",
        "ts_workspace_render_operator",
        "ts_workspace_report_operator",
        "ts_workspace_email_operator",
        "ts_workspace_mcp_status",
    ):
        assert f'"{legacy}"' not in catalog


def test_pi_documentation_matches_loaded_extensions_and_tool_boundary() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    adapter = (SKILL_ROOT / "references" / "pi_agent_adapter.md").read_text(encoding="utf-8")
    maintainer = (ROOT / "docs" / "MAINTAINER_GUIDE.md").read_text(encoding="utf-8")

    assert "Pi `>=0.81.1 <1.0.0`" in readme
    assert "`ts_workspace_decision_draft`" in readme
    assert "`ts_workspace_decision_validate`" in readme
    assert "`ts_workspace_decision_apply`" in readme
    assert "`ts_subagent_review`" in readme
    assert "`ts_review_disposition`" in readme
    assert "run `validate_decision`, `start_node`" not in readme
    assert "one Root Skill and five extensions" in adapter
    assert "fresh child session with exactly one" in adapter
    assert "Provider failure takes precedence over output-contract failure" in readme
    assert "extensions/ts-workflow-review" in maintainer
    assert "extensions/ts-workflow-artifacts" in maintainer


def test_pi_context_summary_from_report_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_strict_workspace(workspace)
    report = report_workspace(workspace)
    report_file = tmp_path / "report.json"
    report_file.write_text(json.dumps(report), encoding="utf-8")

    completed = subprocess.run(
        ["node", str(SUMMARY), "--report", str(report_file)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(completed.stdout)

    assert "TS workspace context:" in payload["summary"]
    assert f"focus_claims: {CLAIM_ID}/inconclusive" in payload["summary"]
    assert "operational_revision:" in payload["summary"]
    assert f"compute_workspace_id: {report['workspace_id']}" in payload["summary"]
    assert "do not edit canonical state files by hand" in payload["summary"]
    assert "scripts/ts_workspace.py" not in payload["summary"]
    assert "ts_workspace_context/ts_workspace_decision_draft/ts_workspace_decision_validate/ts_workspace_decision_apply" in payload["summary"]
    assert payload["details"]["workspaceRoot"] == str(workspace)
    assert payload["details"]["workspaceId"] == report["workspace_id"]
    assert payload["details"]["operationalRevision"].startswith("sha256:")
    assert payload["details"]["operationalSummary"]["controlUnresolvedCount"] == 0
    assert payload["details"]["operationalSummary"]["ambiguousSubmissionCount"] == 0
    assert payload["details"]["operationalSummary"]["reviewDispositionCount"] == 0
    assert payload["details"]["operationalSummary"]["reviewDispositionPendingCount"] == 0
    assert "unresolved_controls=0" in payload["summary"]
    assert "ambiguous_submissions=0" in payload["summary"]
    assert "pending_review_responses=0" in payload["summary"]
    assert payload["details"]["focusClaimRefs"] == [CLAIM_ID]
    assert payload["details"]["valid"] is True


def test_workspace_commands_use_active_root_and_append_expandable_history(tmp_path: Path) -> None:
    workspace = tmp_path / "active-ts-workspace"
    bootstrap_strict_workspace(workspace)
    script = f"""
import installControl from {json.dumps(CONTROL_EXTENSION.as_uri())};
import {{ createRequire }} from "node:module";
import {{ pathToFileURL }} from "node:url";
const requireFromPi = createRequire({json.dumps(str(PI_PACKAGE))});
const {{ KeybindingsManager, setKeybindings, TUI_KEYBINDINGS }} = await import(
  pathToFileURL(requireFromPi.resolve("@earendil-works/pi-tui")).href
);
setKeybindings(new KeybindingsManager({{
  ...TUI_KEYBINDINGS,
  "app.tools.expand": {{ defaultKeys: "ctrl+o", description: "Toggle tool output" }},
}}));
process.env.TS_AGENT_PYTHON = "/usr/bin/python3";
process.env.TS_WORKSPACE_ROOT = {json.dumps(str(workspace))};
const commands = {{}};
const renderers = {{}};
const entries = [];
const execCalls = [];
const pi = {{
  on: () => {{}},
  registerTool: () => {{}},
  registerCommand: (name, command) => {{ commands[name] = command; }},
  registerEntryRenderer: (name, renderer) => {{ renderers[name] = renderer; }},
  appendEntry: (type, data) => entries.push([type, data]),
  exec: async (command, args) => {{
    execCalls.push([command, args]);
    if (args[1] === "report_workspace") return {{ stdout: JSON.stringify({{
      valid: true,
      workspace_root: {json.dumps(str(workspace))},
      workspace_id: "ws_test",
      workspace_revision: "sha256:revision",
      operational_revision: "sha256:operational",
      operational_summary: {{}},
      focus: {{ current_node: "n003" }},
      open_nodes: [],
      validation_findings: [],
    }}) }};
    if (args[1] === "validate_workspace") return {{ stdout: JSON.stringify({{
      valid: false,
      findings: [
        {{ severity: "error", code: "broken" }},
        {{ severity: "warning", code: "review" }},
      ],
    }}) }};
    throw new Error(`unexpected workspace command: ${{args[1]}}`);
  }},
}};
installControl(pi);
const notifications = [];
const ctx = {{
  cwd: {json.dumps(str(workspace))},
  signal: new AbortController().signal,
  ui: {{ notify: (...args) => notifications.push(args) }},
}};
await commands["ts-context"].handler("", ctx);
await commands["ts-validate"].handler("", ctx);
const executed = execCalls.length;
await commands["ts-context"].handler("../other", ctx);
await commands["ts-validate"].handler("--root elsewhere", ctx);
const theme = {{ fg: (_color, text) => text }};
const rendered = entries.map(([type, data]) => ({{
  type,
  collapsed: renderers[type]({{ data }}, {{ expanded: false }}, theme).render(200).join("\\n"),
  expanded: renderers[type]({{ data }}, {{ expanded: true }}, theme).render(200).join("\\n"),
}}));
process.stdout.write(JSON.stringify({{
  commandDescriptions: Object.fromEntries(Object.entries(commands).map(([name, value]) => [name, value.description])),
  rendered,
  notifications,
  execCalls,
  executed,
}}));
"""
    result = _node_json(script)

    assert result["commandDescriptions"] == {
        "ts-context": "Show active TS workspace context · read-only · local.",
        "ts-validate": "Validate active TS workspace · read-only · local.",
    }
    assert result["executed"] == 2
    assert len(result["execCalls"]) == 2
    assert all(str(workspace) in call[1] for call in result["execCalls"])
    assert [item["type"] for item in result["rendered"]] == [
        "ts-workspace-context-result",
        "ts-workspace-validation-result",
    ]
    assert "TS Context: valid · n003" in result["rendered"][0]["collapsed"]
    assert "TS workspace context:" in result["rendered"][0]["expanded"]
    assert "TS Validation: invalid · 1 errors · 1 warnings" in result["rendered"][1]["collapsed"]
    assert '"code": "broken"' in result["rendered"][1]["expanded"]
    assert all("ctrl+o expand all details" in item["collapsed"].lower() for item in result["rendered"])
    assert all("ctrl+o collapse all details" in item["expanded"].lower() for item in result["rendered"])
    assert any("/ts-context takes no arguments" in item[0] for item in result["notifications"])
    assert any("/ts-validate takes no arguments" in item[0] for item in result["notifications"])


def test_pi_context_helper_finds_workspace_from_ancestor(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    nested = workspace / "nodes" / "scratch"
    bootstrap_strict_workspace(workspace)
    nested.mkdir(parents=True)

    script = (
        "const helper = require('./extensions/ts-workflow-control/summary.cjs');"
        "process.stdout.write(helper.findWorkspaceRoot(process.argv[1]) || '');"
    )
    completed = subprocess.run(
        ["node", "-e", script, str(nested)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    assert completed.stdout == str(workspace)


def test_pi_json_parser_surfaces_structured_stderr() -> None:
    script = (
        "const helper=require('./extensions/ts-workflow-control/summary.cjs');"
        "try { helper.parseJsonOutput({stdout:'',stderr:JSON.stringify({"
        "ok:false,error:'collect requires a terminal calculation status'})}); }"
        "catch (error) { process.stdout.write(String(error.message || error)); }"
    )
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    assert completed.stdout == "collect requires a terminal calculation status"


def test_historical_node_and_backtrack_context_are_compact_and_explicit(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    report_ref = bootstrap_strict_workspace(workspace)
    start_research_node(
        workspace,
        report_ref,
        node_id="n001",
        objective="Generate and inspect one candidate.",
        tags=["candidate"],
    )
    end_research_node(workspace, report_ref, node_id="n001")
    start_research_node(
        workspace,
        report_ref,
        node_id="n002",
        parent_node="n001",
        objective="Test connectivity for the current Claim.",
        tags=["connectivity"],
    )
    end_research_node(workspace, report_ref, node_id="n002", program_outcome="failure")

    node_context = report_node(workspace, "n001")
    lineage_context = report_lineage_context(workspace, "n002", "n001")

    assert node_context["node"]["node_id"] == "n001"
    assert node_context["lineage"] == ["n000", "n001"]
    assert node_context["agent_runs"] == []
    assert "closure" not in node_context["node"]
    assert lineage_context["anchor_node"]["node"]["node_id"] == "n001"
    assert [item["node_id"] for item in lineage_context["path_delta"]] == ["n002"]

    context_file = tmp_path / "lineage_context.json"
    context_file.write_text(json.dumps(lineage_context), encoding="utf-8")
    script = (
        "const fs=require('node:fs');"
        "const helper=require('./extensions/ts-workflow-control/summary.cjs');"
        "const value=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));"
        "process.stdout.write(helper.buildLineageContextSummary(value));"
    )
    completed = subprocess.run(
        ["node", "-e", script, str(context_file)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert "TS lineage context:" in completed.stdout
    assert "trigger: n002[connectivity]/closed/completed" in completed.stdout
    assert "selected_checkpoint: n001[candidate]/closed/completed" in completed.stdout
    assert "kernel only validates parent-node topology" in completed.stdout

    node_context_file = tmp_path / "node_context.json"
    node_context_file.write_text(json.dumps(node_context), encoding="utf-8")
    node_script = (
        "const fs=require('node:fs');"
        "const helper=require('./extensions/ts-workflow-control/summary.cjs');"
        "const value=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));"
        "process.stdout.write(helper.buildNodeContextSummary(value));"
    )
    node_completed = subprocess.run(
        ["node", "-e", node_script, str(node_context_file)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert "artifact_paths: inputs=nodes/n001/inputs" in node_completed.stdout
    assert "outputs=nodes/n001/outputs" in node_completed.stdout
    assert "claim_refs: claim_reaction_0001" in node_completed.stdout
    assert "evidence: (none)" in node_completed.stdout


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
