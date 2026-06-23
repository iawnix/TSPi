from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ts_workspace import report_workspace
from v3_helpers import HYPOTHESIS_ID, bootstrap_v3_workspace


ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "extensions" / "ts-workflow-context" / "summary.cjs"


def test_pi_package_manifest_exposes_skill_and_extension() -> None:
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert "pi-package" in manifest["keywords"]
    assert manifest["pi"]["skills"] == ["."]
    assert manifest["pi"]["extensions"] == ["./extensions/ts-workflow-context"]
    assert manifest["peerDependencies"]["@earendil-works/pi-coding-agent"] == "*"
    assert manifest["peerDependencies"]["typebox"] == "*"
    assert "postinstall" not in manifest["scripts"]


def test_pi_context_summary_from_report_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    bootstrap_v3_workspace(workspace)
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
    assert "do not edit ledgers by hand" in payload["summary"]
    assert payload["details"]["workspaceRoot"] == str(workspace)
    assert payload["details"]["focusHypothesisId"] == HYPOTHESIS_ID
    assert payload["details"]["valid"] is True


def test_pi_context_helper_finds_workspace_from_ancestor(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    nested = workspace / "nodes" / "scratch"
    bootstrap_v3_workspace(workspace)
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
