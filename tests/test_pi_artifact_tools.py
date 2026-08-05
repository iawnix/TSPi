from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.strict_helpers import bootstrap_strict_workspace
from ts_report import build_report_package


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_AGENT = ROOT / "src" / "agents" / "artifacts"
REQUEST_CONTRACT = ARTIFACT_AGENT / "request-contract.cjs"
OUTPUT_SCHEMA = ARTIFACT_AGENT / "output-schema.cjs"


def test_pi_package_registers_artifact_extension_and_root_tools() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert "./extensions/ts-workflow-artifacts/index.ts" in package["pi"]["extensions"]
    assert "tests/test_pi_artifact_tools.py" in package["scripts"]["test:pi-adapter"]

    source = (ROOT / "extensions" / "ts-workflow-artifacts" / "index.ts").read_text(encoding="utf-8")
    for name in (
        "ts_workspace_render_operator",
        "ts_workspace_report_operator",
        "ts_workspace_email_operator",
        "ts_workspace_render_execute",
        "ts_workspace_report_build",
        "ts_workspace_email_draft_write",
    ):
        assert f'"{name}"' in source
    assert "runArtifactOperator" in source
    assert "createEmailDraftTool" in source
    assert "external_side_effects: false" in source
    assert "ts_workspace_email_send" not in source


def test_artifact_runtime_is_fresh_skill_scoped_and_without_builtin_tools() -> None:
    runtime = (ARTIFACT_AGENT / "runtime.ts").read_text(encoding="utf-8")
    prompt = (ARTIFACT_AGENT / "prompt.md").read_text(encoding="utf-8")
    assert 'noTools: "builtin"' in runtime
    assert "customTools: options.tools" in runtime
    assert "SessionManager.inMemory(options.workspaceRoot)" in runtime
    assert "SettingsManager.inMemory" in runtime
    assert "getAgentsFiles: () => ({ agentsFiles: [] })" in runtime
    assert "getSystemPromptSource: () => undefined" in runtime
    assert "getAppendSystemPromptSources: () => []" in runtime
    assert "getSkills: () => ({ skills: [], diagnostics: [] })" in runtime
    assert "withDisposableSession" in runtime
    assert "loadArtifactSkill(options.role)" in runtime
    assert "external_side_effects: false as const" in runtime
    assert "no general shell" in prompt
    assert "email-send" in prompt


def test_artifact_request_contract_binds_paths_and_rejects_escapes(tmp_path: Path) -> None:
    workspace = _artifact_workspace(tmp_path)
    render = _request_contract(
        "validateRenderRequest",
        workspace,
        {
            "operation": "compare",
            "nodeId": "n001",
            "inputRefs": ["inputs/reactant.xyz", "nodes/n001/inputs/product.xyz"],
            "outputRef": "nodes/n001/outputs/compare.png",
        },
    )
    assert render["outputRef"] == "nodes/n001/outputs/compare.png"
    assert len(render["inputPaths"]) == 2

    report = _request_contract(
        "validateReportRequest",
        workspace,
        {"operation": "build", "packageRef": "reports/run-002"},
    )
    assert report["packageRef"] == "reports/run-002"

    email = _request_contract(
        "validateEmailRequest",
        workspace,
        {
            "operation": "draft",
            "summaryRef": "reports/run-001/email_summary.md",
            "draftRef": "reports/email/draft-001.json",
            "recipients": ["researcher@example.org"],
        },
    )
    assert email["contextRef"] == "reports/run-001/report_context.json"

    failed = _request_contract(
        "validateRenderRequest",
        workspace,
        {
            "operation": "render",
            "nodeId": "n001",
            "inputRefs": ["../outside.xyz"],
            "outputRef": "nodes/n001/outputs/render.png",
        },
        check=False,
    )
    assert "parent segment" in failed.stderr

    failed = _request_contract(
        "validateEmailRequest",
        workspace,
        {
            "operation": "send",
            "summaryRef": "reports/run-001/email_summary.md",
            "draftRef": "reports/email/draft-001.json",
            "recipients": ["researcher@example.org"],
        },
        check=False,
    )
    assert "sending is unavailable" in failed.stderr


def test_artifact_request_contract_rejects_symlink_and_overwrite(tmp_path: Path) -> None:
    workspace = _artifact_workspace(tmp_path)
    outside = tmp_path / "outside.xyz"
    outside.write_text("1\nH\nH 0 0 0\n", encoding="utf-8")
    (workspace / "inputs" / "linked.xyz").symlink_to(outside)
    failed = _request_contract(
        "validateRenderRequest",
        workspace,
        {
            "operation": "render",
            "nodeId": "n001",
            "inputRefs": ["inputs/linked.xyz"],
            "outputRef": "nodes/n001/outputs/render.png",
        },
        check=False,
    )
    assert "symbolic link" in failed.stderr

    (workspace / "nodes" / "n001" / "outputs" / "render.png").write_bytes(b"existing")
    failed = _request_contract(
        "validateRenderRequest",
        workspace,
        {
            "operation": "render",
            "nodeId": "n001",
            "inputRefs": ["inputs/reactant.xyz"],
            "outputRef": "nodes/n001/outputs/render.png",
        },
        check=False,
    )
    assert "already exists" in failed.stderr


def test_artifact_node_scope_must_match_workspace_report(tmp_path: Path) -> None:
    report = {"node_index": [{"node_id": "n001"}]}
    accepted = _node_scope_contract(report, ["n001"])
    assert accepted == ["n001"]

    failed = _node_scope_contract(report, ["n999"], check=False)
    assert failed.returncode == 2
    assert "absent from workspace report" in failed.stderr


def test_email_cli_creates_local_draft_without_send_surface(tmp_path: Path) -> None:
    workspace = _artifact_workspace(tmp_path)
    binding = _package_binding(workspace)
    request = {
        "schema_version": "ts-email-draft/1",
        "summary_ref": "reports/run-001/email_summary.md",
        "summary_digest": binding["summary_digest"],
        "manifest_ref": "reports/run-001/package_manifest.json",
        "manifest_digest": binding["manifest_digest"],
        "source_workspace_revision": binding["workspace_revision"],
        "draft_ref": "reports/email/draft-001.json",
        "recipients": ["researcher@example.org"],
        "subject": "TS study update",
        "body": "The validated report package is ready for review.",
    }
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(request), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "ts_email.py"),
            "draft",
            "--root",
            str(workspace),
            "--request-file",
            str(request_file),
            "--json",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    result = json.loads(completed.stdout)
    assert result["external_side_effects"] is False
    assert result["artifact_refs"] == ["reports/email/draft-001.json"]
    draft = json.loads((workspace / "reports" / "email" / "draft-001.json").read_text(encoding="utf-8"))
    assert draft["delivery"] == {"send_available": False, "status": "draft_only"}
    assert draft["recipients"] == ["researcher@example.org"]
    assert draft["package_manifest_digest"] == binding["manifest_digest"]

    source = (ROOT / "scripts" / "ts_email.py").read_text(encoding="utf-8")
    assert "smtplib" not in source
    assert "requests" not in source
    assert "send_message" not in source


def test_email_cli_rechecks_summary_digest_at_write_time(tmp_path: Path) -> None:
    workspace = _artifact_workspace(tmp_path)
    binding = _package_binding(workspace)
    (workspace / "reports" / "run-001" / "email_summary.md").write_text("changed\n", encoding="utf-8")
    request = {
        "schema_version": "ts-email-draft/1",
        "summary_ref": "reports/run-001/email_summary.md",
        "summary_digest": binding["summary_digest"],
        "manifest_ref": "reports/run-001/package_manifest.json",
        "manifest_digest": binding["manifest_digest"],
        "source_workspace_revision": binding["workspace_revision"],
        "draft_ref": "reports/email/draft-changed.json",
        "recipients": ["researcher@example.org"],
        "subject": "TS study update",
        "body": "Bound body.",
    }
    request_file = tmp_path / "changed-request.json"
    request_file.write_text(json.dumps(request), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "ts_email.py"),
            "draft",
            "--root",
            str(workspace),
            "--request-file",
            str(request_file),
            "--json",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 2
    assert "summary digest changed" in completed.stderr
    assert not (workspace / "reports" / "email" / "draft-changed.json").exists()


def test_report_cli_returns_structured_package_refs(tmp_path: Path) -> None:
    workspace = tmp_path / "report-workspace"
    bootstrap_strict_workspace(workspace)
    package_dir = workspace / "reports" / "operator-package"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "ts_report.py"),
            "--root",
            str(workspace),
            "--package-dir",
            str(package_dir),
            "--json",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    result = json.loads(completed.stdout)
    assert result["package_dir"] == str(package_dir)
    assert result["report"] == str(package_dir / "final_report.md")
    assert result["context"] == str(package_dir / "report_context.json")
    assert result["email_summary"] == str(package_dir / "email_summary.md")
    assert result["assets_dir"] == str(package_dir / "assets")
    assert result["manifest"] == str(package_dir / "package_manifest.json")
    assert result["manifest_digest"].startswith("sha256:")
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "ts-report-package/1"
    assert manifest["workspace_revision"] == result["workspace_revision"]
    assert {row["ref"] for row in manifest["files"]} >= {
        "final_report.md",
        "report_context.json",
        "email_summary.md",
    }


def test_report_package_validates_before_creating_output(tmp_path: Path) -> None:
    workspace = tmp_path / "invalid-workspace"
    workspace.mkdir()
    package_dir = workspace / "reports" / "operator-package"
    with pytest.raises(ValueError, match="workspace is invalid"):
        build_report_package(workspace, package_dir)
    assert not package_dir.exists()


def test_report_package_is_no_overwrite_and_email_rejects_tampering(tmp_path: Path) -> None:
    workspace = tmp_path / "report-workspace"
    bootstrap_strict_workspace(workspace)
    package_dir = workspace / "reports" / "operator-package"
    build_report_package(workspace, package_dir)
    with pytest.raises(ValueError, match="already exists"):
        build_report_package(workspace, package_dir)
    assert not list(package_dir.parent.glob(f".{package_dir.name}.tmp-*"))

    (package_dir / "email_summary.md").write_text("tampered\n", encoding="utf-8")
    failed = _request_contract(
        "validateEmailRequest",
        workspace,
        {
            "operation": "draft",
            "summaryRef": "reports/operator-package/email_summary.md",
            "draftRef": "reports/email/tampered.json",
            "recipients": ["researcher@example.org"],
        },
        check=False,
    )
    assert "digest mismatch" in failed.stderr


@pytest.mark.parametrize("role", ["render", "report", "email"])
def test_artifact_output_is_bound_to_one_typed_action(tmp_path: Path, role: str) -> None:
    packet, action, report = _artifact_protocol_fixture(role)
    completed = _validate_artifact_output(tmp_path, packet, [action], report)
    assert json.loads(completed.stdout)["role"] == role

    report["artifact_refs"] = ["reports/invented.txt"]
    failed = _validate_artifact_output(tmp_path, packet, [action], report, check=False)
    assert failed.returncode == 2
    assert "do not match" in failed.stderr


def test_email_output_cannot_change_recipients_or_include_body(tmp_path: Path) -> None:
    packet, action, report = _artifact_protocol_fixture("email")
    report["payload"]["recipients"] = ["other@example.org"]
    failed = _validate_artifact_output(tmp_path, packet, [action], report, check=False)
    assert "recipients do not match" in failed.stderr

    report["payload"]["recipients"] = ["researcher@example.org"]
    report["payload"]["body"] = "Injected body"
    failed = _validate_artifact_output(tmp_path, packet, [action], report, check=False)
    assert "unknown fields" in failed.stderr


def test_artifact_output_rejects_started_or_failed_action(tmp_path: Path) -> None:
    packet, action, report = _artifact_protocol_fixture("report")
    action["result"]["state"] = "started"
    failed = _validate_artifact_output(tmp_path, packet, [action], report, check=False)
    assert "report state does not match" in failed.stderr


def _artifact_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    for path in (
        workspace / "inputs",
        workspace / "nodes" / "n001" / "inputs",
        workspace / "nodes" / "n001" / "outputs",
        workspace / "reports" / "run-001",
    ):
        path.mkdir(parents=True, exist_ok=True)
    (workspace / "inputs" / "reactant.xyz").write_text("1\nR\nH 0 0 0\n", encoding="utf-8")
    (workspace / "nodes" / "n001" / "inputs" / "product.xyz").write_text("1\nP\nH 0 0 1\n", encoding="utf-8")
    (workspace / "nodes" / "n001" / "node.json").write_text("{}\n", encoding="utf-8")
    (workspace / "reports" / "run-001" / "email_summary.md").write_text("Subject: TS report\n\nReady.\n", encoding="utf-8")
    (workspace / "reports" / "run-001" / "report_context.json").write_text("{}\n", encoding="utf-8")
    _write_package_manifest(workspace / "reports" / "run-001")
    return workspace


def _write_package_manifest(package_dir: Path) -> None:
    files = []
    for name in ("email_summary.md", "report_context.json"):
        path = package_dir / name
        files.append({"ref": name, "sha256": _sha256(path), "size_bytes": path.stat().st_size})
    (package_dir / "package_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "ts-report-package/1",
                "workspace_revision": "sha256:" + "1" * 64,
                "files": files,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _package_binding(workspace: Path) -> dict[str, str]:
    package_dir = workspace / "reports" / "run-001"
    manifest = json.loads((package_dir / "package_manifest.json").read_text(encoding="utf-8"))
    summary = next(row for row in manifest["files"] if row["ref"] == "email_summary.md")
    return {
        "summary_digest": summary["sha256"],
        "manifest_digest": _sha256(package_dir / "package_manifest.json"),
        "workspace_revision": manifest["workspace_revision"],
    }


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _request_contract(
    function_name: str,
    workspace: Path,
    request: dict[str, object],
    *,
    check: bool = True,
) -> dict[str, object] | subprocess.CompletedProcess[str]:
    script = (
        f"const helper=require({json.dumps(str(REQUEST_CONTRACT))});"
        f"const input={json.dumps(request)};"
        "try { process.stdout.write(JSON.stringify(helper[process.argv[1]](process.argv[2],input))); }"
        "catch(error){ process.stderr.write(String(error.message||error)); process.exitCode=2; }"
    )
    completed = subprocess.run(
        ["node", "-e", script, function_name, str(workspace)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )
    return json.loads(completed.stdout) if check else completed


def _node_scope_contract(
    report: dict[str, object],
    node_ids: list[str],
    *,
    check: bool = True,
) -> list[str] | subprocess.CompletedProcess[str]:
    script = (
        f"const helper=require({json.dumps(str(REQUEST_CONTRACT))});"
        f"const report={json.dumps(report)};"
        f"const nodeIds={json.dumps(node_ids)};"
        "try { process.stdout.write(JSON.stringify(helper.validateTaskNodeScope(report,nodeIds))); }"
        "catch(error){ process.stderr.write(String(error.message||error)); process.exitCode=2; }"
    )
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )
    return json.loads(completed.stdout) if check else completed


def _artifact_protocol_fixture(role: str) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    operation = {"render": "render", "report": "build", "email": "draft"}[role]
    node_ids = ["n001"] if role == "render" else []
    packet = {
        "schema_version": "ts-agent-task/1",
        "task_id": f"agent_{role}_001",
        "role": role,
        "authority": "operational",
        "operation": operation,
        "objective": f"Execute bounded {role} operation.",
        "workspace": {"root": "/tmp/ws", "report_id": "rep_001", "revision": "rev_001"},
        "scope": {"report_id": "rep_001", "node_ids": node_ids, "hypothesis_id": None, "pathway_id": None},
        "inputs": {"basis_allowlist": ["inputs/reactant.xyz"]},
        "capabilities": [{"render": "ts_workspace_render_execute", "report": "ts_workspace_report_build", "email": "ts_workspace_email_draft_write"}[role]],
        "constraints": {
            "canonical_workspace_mutation": False,
            "scientific_decision": False,
            "recursive_delegation": False,
            "remote_authority": "execution_mirror",
            "external_side_effects": False,
        },
        "output_contract": "ts-agent-result/1",
    }
    canonical = {
        "render": {
            "operation": "render",
            "state": "rendered",
            "node_id": "n001",
            "output_ref": "nodes/n001/outputs/render.png",
            "artifact_refs": ["nodes/n001/outputs/render.png"],
        },
        "report": {
            "operation": "build",
            "state": "built",
            "package_ref": "reports/run-001",
            "report_ref": "reports/run-001/final_report.md",
            "context_ref": "reports/run-001/report_context.json",
            "email_summary_ref": "reports/run-001/email_summary.md",
            "assets_ref": "reports/run-001/assets",
            "manifest_ref": "reports/run-001/package_manifest.json",
            "manifest_digest": "sha256:" + "2" * 64,
            "workspace_revision": "sha256:" + "1" * 64,
            "artifact_refs": [
                "reports/run-001/final_report.md",
                "reports/run-001/report_context.json",
                "reports/run-001/email_summary.md",
                "reports/run-001/assets",
                "reports/run-001/package_manifest.json",
            ],
        },
        "email": {
            "operation": "draft",
            "state": "drafted",
            "summary_ref": "reports/run-001/email_summary.md",
            "summary_digest": "sha256:" + "3" * 64,
            "manifest_ref": "reports/run-001/package_manifest.json",
            "manifest_digest": "sha256:" + "2" * 64,
            "source_workspace_revision": "sha256:" + "1" * 64,
            "draft_ref": "reports/email/draft-001.json",
            "recipients": ["researcher@example.org"],
            "subject": "TS study update",
            "artifact_refs": ["reports/email/draft-001.json"],
        },
    }[role]
    tool = {"render": "ts_workspace_render_execute", "report": "ts_workspace_report_build", "email": "ts_workspace_email_draft_write"}[role]
    action = {"tool": tool, "result": canonical}
    payload = {key: value for key, value in canonical.items() if key not in {"artifact_refs", "state"}}
    report = {
        "schema_version": "ts-agent-result/1",
        "task_id": packet["task_id"],
        "role": role,
        "authority": "operational",
        "operation": operation,
        "outcome": "success",
        "summary": f"The {role} operation completed.",
        "scope": packet["scope"],
        "facts": [],
        "artifact_refs": canonical["artifact_refs"],
        "program": None,
        "payload": payload,
        "limitations": [],
        "provenance": {},
    }
    return packet, action, report


def _validate_artifact_output(
    tmp_path: Path,
    packet: dict[str, object],
    actions: list[dict[str, object]],
    report: dict[str, object],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    input_path = tmp_path / "artifact-output.json"
    input_path.write_text(json.dumps({"packet": packet, "actions": actions, "report": report}), encoding="utf-8")
    script = (
        "const fs=require('node:fs');"
        f"const helper=require({json.dumps(str(OUTPUT_SCHEMA))});"
        "const input=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));"
        "try { process.stdout.write(JSON.stringify(helper.validateArtifactReport(input.report,input.packet,input.actions))); }"
        "catch(error){ process.stderr.write(String(error.message||error)); process.exitCode=2; }"
    )
    return subprocess.run(
        ["node", "-e", script, str(input_path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )
