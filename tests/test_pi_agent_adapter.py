from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ts_workspace import report_branch_context, report_node, report_workspace
from strict_helpers import HYPOTHESIS_ID, bootstrap_strict_workspace, end_v3_node, start_v3_node


ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "extensions" / "ts-workflow-context" / "summary.cjs"


def test_pi_package_manifest_exposes_skill_and_extension() -> None:
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert "pi-package" in manifest["keywords"]
    assert manifest["pi"]["skills"] == ["."]
    assert manifest["pi"]["extensions"] == [
        "./extensions/ts-workflow-context",
        "./extensions/ts-workflow-subagent/index.ts",
        "./extensions/ts-workflow-compute/index.ts",
        "./extensions/ts-workflow-artifacts/index.ts",
    ]
    assert "subagents" not in manifest["pi"]
    assert not any("subagent" in name for name in manifest.get("dependencies", {}))
    assert manifest["peerDependencies"]["@earendil-works/pi-ai"] == ">=0.81.1 <1.0.0"
    assert manifest["peerDependencies"]["@earendil-works/pi-coding-agent"] == ">=0.81.1 <1.0.0"
    assert manifest["peerDependencies"]["typebox"] == "^1.1.38"
    assert "--workspace-root" in manifest["scripts"]["install-env"]
    assert "TS_WORKSPACE_ROOT" in manifest["scripts"]["install-env"]
    assert "tests/test_pi_subagent_contract.py" in manifest["scripts"]["test:pi-adapter"]
    assert "postinstall" not in manifest["scripts"]

    extension_source = (ROOT / "extensions" / "ts-workflow-context" / "index.ts").read_text(encoding="utf-8")
    assert 'const DECISION_ACTIONS = ["start_node", "update_workspace", "end_node"]' in extension_source
    assert 'name: "ts_workspace_decide"' in extension_source
    assert 'name: "ts_workspace_validate"' in extension_source
    assert 'name: "ts_workspace_apply"' in extension_source
    assert 'name: "ts_workspace_decision_validate"' not in extension_source
    assert 'name: "ts_workspace_decision"' not in extension_source


def test_pi_documentation_matches_loaded_extensions_and_tool_boundary() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    adapter = (ROOT / "references" / "pi_agent_adapter.md").read_text(encoding="utf-8")
    maintainer = (ROOT / "docs" / "MAINTAINER_GUIDE.md").read_text(encoding="utf-8")

    assert "Pi `>=0.81.1 <1.0.0`" in readme
    assert "extensions/ts-workflow-subagent" in readme
    assert "extensions/ts-workflow-artifacts" in readme
    assert "`ts_workspace_decide`" in readme
    assert "`ts_workspace_validate`" in readme
    assert "`ts_workspace_apply`" in readme
    assert "`ts_workspace_subagent`" in readme
    assert "run `validate_decision`, `start_node`" not in readme
    assert adapter.count("-e \"$TS_AGENT_SKILL_ROOT/extensions/") == 4
    assert "temporary\nnon-OAuth API key" in adapter
    assert "extensions/ts-workflow-subagent" in maintainer
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
    assert f"focus_hypothesis: {HYPOTHESIS_ID}" in payload["summary"]
    assert "required_next_evidence:" in payload["summary"]
    assert "operational_revision:" in payload["summary"]
    assert "do not edit workspace state files by hand" in payload["summary"]
    assert "scripts/ts_workspace.py" not in payload["summary"]
    assert "explicit TSAgentSkill root" in payload["summary"]
    assert "ts_workspace_context/ts_workspace_decide/ts_workspace_validate/ts_workspace_apply" in payload["summary"]
    assert payload["details"]["workspaceRoot"] == str(workspace)
    assert payload["details"]["operationalRevision"].startswith("sha256:")
    assert payload["details"]["focusHypothesisId"] == HYPOTHESIS_ID
    assert payload["details"]["valid"] is True


def test_pi_context_helper_finds_workspace_from_ancestor(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    nested = workspace / "nodes" / "scratch"
    bootstrap_strict_workspace(workspace)
    nested.mkdir(parents=True)

    script = (
        "const helper = require('./extensions/ts-workflow-context/summary.cjs');"
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
        "const helper=require('./extensions/ts-workflow-context/summary.cjs');"
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
    start_v3_node(workspace, report_ref, node_id="n001", phase="candidate_generation")
    end_v3_node(workspace, report_ref, node_id="n001", claim_verdict="supported")
    start_v3_node(
        workspace,
        report_ref,
        node_id="n002",
        parent_node="n001",
        phase="connectivity_validation",
    )
    end_v3_node(workspace, report_ref, node_id="n002", claim_verdict="refuted")

    node_context = report_node(workspace, "n001")
    branch_context = report_branch_context(workspace, "n002", "n001")

    assert node_context["node"]["node_id"] == "n001"
    assert node_context["lineage"] == ["n000", "n001"]
    assert node_context["agent_runs"] == []
    assert "closure" not in node_context["node"]
    assert branch_context["anchor_node"]["node"]["node_id"] == "n001"
    assert [item["node_id"] for item in branch_context["path_delta"]] == ["n002"]

    context_file = tmp_path / "branch_context.json"
    context_file.write_text(json.dumps(branch_context), encoding="utf-8")
    script = (
        "const fs=require('node:fs');"
        "const helper=require('./extensions/ts-workflow-context/summary.cjs');"
        "const value=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));"
        "process.stdout.write(helper.buildBranchContextSummary(value));"
    )
    completed = subprocess.run(
        ["node", "-e", script, str(context_file)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert "TS backtrack context:" in completed.stdout
    assert "trigger: n002" in completed.stdout
    assert "selected_checkpoint: n001" in completed.stdout
    assert "tooling only validates the resulting topology" in completed.stdout

    node_context_file = tmp_path / "node_context.json"
    node_context_file.write_text(json.dumps(node_context), encoding="utf-8")
    node_script = (
        "const fs=require('node:fs');"
        "const helper=require('./extensions/ts-workflow-context/summary.cjs');"
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
    assert "evidence_paths: (none)" in node_completed.stdout
    assert "source_files: (none)" in node_completed.stdout
