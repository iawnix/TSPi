from __future__ import annotations

import hashlib
import json
import os
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
    for key in ("subagentRender", "subagentReport", "subagentEmailDraft", "emailSend"):
        assert f"name: TS_PUBLIC_TOOL_NAMES.{key}" in source
    for name in (
        "ts_workspace_render_execute",
        "ts_workspace_report_build",
        "ts_workspace_email_draft_write",
    ):
        assert f'"{name}"' in source
    assert "runArtifactOperator" in source
    assert "createEmailDraftTool" in source
    assert "external_side_effects: false" in source
    assert 'name: TS_PUBLIC_TOOL_NAMES.emailSend' in source
    assert '"ts_email_send"' in (ROOT / "extensions" / "shared" / "tool-catalog.ts").read_text(encoding="utf-8")
    assert "ts_workspace_email_send" not in source


def test_artifact_runtime_is_fresh_policy_scoped_and_without_builtin_tools() -> None:
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
    assert "loadArtifactPolicy(options.role)" in runtime
    assert "Artifact operator policy" in runtime
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


def test_email_cli_creates_fixed_template_local_draft(tmp_path: Path) -> None:
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
    assert draft["delivery"] == {
        "requires_active_policy": True,
        "send_available": True,
        "status": "not_sent",
    }
    assert draft["template_id"] == "ts-report-summary/1"
    assert draft["subject"] == "TS report"
    assert draft["body"] == "Ready.\n"
    assert draft["recipients"] == ["researcher@example.org"]
    assert draft["package_manifest_digest"] == binding["manifest_digest"]
    assert (workspace / "reports" / "email" / "draft-001.json").stat().st_mode & 0o777 == 0o600

    source = (ROOT / "scripts" / "ts_email.py").read_text(encoding="utf-8")
    assert "smtplib" not in source
    assert "requests" not in source


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


def test_fixed_email_policy_activates_and_sends_each_draft_once(tmp_path: Path) -> None:
    workspace = _artifact_workspace(tmp_path)
    draft_ref = _write_fixed_draft(workspace, tmp_path)
    clawemail_root, env = _fake_clawemail_skill(tmp_path)

    created = _email_cli(
        workspace,
        "policy-create",
        "--recipient",
        "researcher@example.org",
        "--attachment",
        "final_report.md",
        "--clawemail-root",
        str(clawemail_root),
        env=env,
    )
    policy = json.loads(created.stdout)
    assert policy["state"] == "pending_activation"
    assert policy["template_id"] == "ts-report-summary/1"
    assert policy["attachment_names"] == ["final_report.md"]
    assert (workspace / ".pi" / "ts-email-delivery-policy.json").stat().st_mode & 0o777 == 0o600

    blocked = _email_cli(workspace, "send", "--draft-ref", draft_ref, env=env, check=False)
    assert blocked.returncode == 2
    assert "delivery authorization is missing" in blocked.stderr
    assert not Path(env["TS_TEST_CLAWEMAIL_LOG"]).exists()

    activated = _email_cli(
        workspace,
        "policy-activate",
        "--token",
        policy["activation_token"],
        env=env,
    )
    assert json.loads(activated.stdout)["state"] == "active"
    authorization = workspace / ".pi" / "ts-email-delivery-authorization.json"
    assert authorization.stat().st_mode & 0o777 == 0o600
    status = json.loads(_email_cli(workspace, "policy-status", env=env).stdout)
    assert status["state"] == "active"

    sent = json.loads(
        _email_cli(workspace, "send", "--draft-ref", draft_ref, env=env).stdout
    )
    assert sent["state"] == "sent"
    assert sent["recipients"] == ["researcher@example.org"]
    assert sent["attachment_refs"] == ["reports/run-001/final_report.md"]
    receipt = workspace / sent["receipt_ref"]
    assert receipt.stat().st_mode & 0o777 == 0o600

    repeated = json.loads(
        _email_cli(workspace, "send", "--draft-ref", draft_ref, env=env).stdout
    )
    assert repeated["state"] == "already_sent"
    args = Path(env["TS_TEST_CLAWEMAIL_LOG"]).read_text(encoding="utf-8").splitlines()
    assert args.count("send") == 1
    assert "researcher@example.org" in args
    assert str(workspace / "reports" / "run-001" / "final_report.md") in args
    assert Path(env["TS_TEST_CLAWEMAIL_BODY"]).read_text(encoding="utf-8") == "Ready.\n"

    disabled = json.loads(_email_cli(workspace, "policy-disable", env=env).stdout)
    assert disabled["state"] == "disabled"
    assert json.loads(_email_cli(workspace, "policy-status", env=env).stdout)["state"] == "disabled"
    blocked = _email_cli(workspace, "send", "--draft-ref", draft_ref, env=env, check=False)
    assert blocked.returncode == 2
    assert "fixed delivery policy is not active" in blocked.stderr
    reactivated = json.loads(
        _email_cli(
            workspace,
            "policy-activate",
            "--token",
            policy["activation_token"],
            env=env,
        ).stdout
    )
    assert reactivated["state"] == "active"


def test_child_workspace_inherits_installation_email_policy_and_keeps_receipts_local(
    tmp_path: Path,
) -> None:
    installation = tmp_path / "installation"
    installation.mkdir()
    workspace = _artifact_workspace_at(installation / "ts_0000")
    draft_ref = _write_fixed_draft(workspace, tmp_path)
    clawemail_root, env = _fake_clawemail_skill(tmp_path)
    env.pop("TS_EMAIL_POLICY_ROOT", None)
    env["TS_WORKSPACE_ROOT"] = str(installation)
    parent = _activate_fixed_email_policy(installation, clawemail_root, env)

    status = json.loads(_email_cli(workspace, "policy-status", env=env).stdout)
    assert status["state"] == "active"
    assert status["policy_scope"] == "inherited"
    assert status["policy_source_root"] == str(installation)
    assert status["local_policy_state"] == "not_configured"
    assert status["policy_id"] == parent["policy_id"]

    sent = json.loads(_email_cli(workspace, "send", "--draft-ref", draft_ref, env=env).stdout)
    assert sent["state"] == "sent"
    assert sent["policy_scope"] == "inherited"
    assert sent["policy_source_root"] == str(installation)
    assert (workspace / sent["receipt_ref"]).is_file()
    assert not (installation / "reports").exists()

    repeated = json.loads(_email_cli(workspace, "send", "--draft-ref", draft_ref, env=env).stdout)
    assert repeated["state"] == "already_sent"
    assert repeated["policy_scope"] == "inherited"
    args = Path(env["TS_TEST_CLAWEMAIL_LOG"]).read_text(encoding="utf-8").splitlines()
    assert args.count("send") == 1


def test_matching_pending_child_email_policy_inherits_without_local_activation(
    tmp_path: Path,
) -> None:
    installation = tmp_path / "installation"
    installation.mkdir()
    workspace = _artifact_workspace_at(installation / "ts_0000")
    draft_ref = _write_fixed_draft(workspace, tmp_path)
    clawemail_root, env = _fake_clawemail_skill(tmp_path)
    env["TS_EMAIL_POLICY_ROOT"] = str(installation)
    env.pop("TS_WORKSPACE_ROOT", None)
    parent = _activate_fixed_email_policy(installation, clawemail_root, env)
    child = json.loads(
        _email_cli(
            workspace,
            "policy-create",
            "--recipient",
            "researcher@example.org",
            "--attachment",
            "final_report.md",
            "--clawemail-root",
            str(clawemail_root),
            env=env,
        ).stdout
    )

    status = json.loads(_email_cli(workspace, "policy-status", env=env).stdout)
    assert status["state"] == "active"
    assert status["policy_scope"] == "inherited"
    assert status["local_policy_state"] == "pending_activation"
    assert status["policy_id"] == parent["policy_id"]
    assert status["local_policy_id"] == child["policy_id"]
    assert not (workspace / ".pi" / "ts-email-delivery-authorization.json").exists()

    sent = json.loads(_email_cli(workspace, "send", "--draft-ref", draft_ref, env=env).stdout)
    assert sent["state"] == "sent"
    assert sent["policy_id"] == parent["policy_id"]
    assert not (workspace / ".pi" / "ts-email-delivery-authorization.json").exists()


@pytest.mark.parametrize(
    ("recipient", "attachment"),
    [
        ("other@example.org", "final_report.md"),
        ("researcher@example.org", "report_context.json"),
    ],
)
def test_different_pending_child_email_policy_does_not_inherit(
    tmp_path: Path,
    recipient: str,
    attachment: str,
) -> None:
    installation = tmp_path / "installation"
    installation.mkdir()
    workspace = _artifact_workspace_at(installation / "ts_0000")
    draft_ref = _write_fixed_draft(workspace, tmp_path)
    clawemail_root, env = _fake_clawemail_skill(tmp_path)
    env["TS_EMAIL_POLICY_ROOT"] = str(installation)
    _activate_fixed_email_policy(installation, clawemail_root, env)
    child = json.loads(
        _email_cli(
            workspace,
            "policy-create",
            "--recipient",
            recipient,
            "--attachment",
            attachment,
            "--clawemail-root",
            str(clawemail_root),
            env=env,
        ).stdout
    )

    status = json.loads(_email_cli(workspace, "policy-status", env=env).stdout)
    assert status["state"] == "pending_activation"
    assert status["policy_scope"] == "local"
    assert status["policy_id"] == child["policy_id"]
    blocked = _email_cli(workspace, "send", "--draft-ref", draft_ref, env=env, check=False)
    assert blocked.returncode == 2
    assert "delivery authorization is missing" in blocked.stderr
    assert not Path(env["TS_TEST_CLAWEMAIL_LOG"]).exists()


def test_disabled_child_email_policy_blocks_installation_policy_inheritance(tmp_path: Path) -> None:
    installation = tmp_path / "installation"
    installation.mkdir()
    workspace = _artifact_workspace_at(installation / "ts_0000")
    draft_ref = _write_fixed_draft(workspace, tmp_path)
    clawemail_root, env = _fake_clawemail_skill(tmp_path)
    env["TS_EMAIL_POLICY_ROOT"] = str(installation)
    _activate_fixed_email_policy(installation, clawemail_root, env)
    _activate_fixed_email_policy(workspace, clawemail_root, env)
    _email_cli(workspace, "policy-disable", env=env)

    status = json.loads(_email_cli(workspace, "policy-status", env=env).stdout)
    assert status["state"] == "disabled"
    assert status["policy_scope"] == "local"
    blocked = _email_cli(workspace, "send", "--draft-ref", draft_ref, env=env, check=False)
    assert blocked.returncode == 2
    assert "fixed delivery policy is not active" in blocked.stderr
    assert not Path(env["TS_TEST_CLAWEMAIL_LOG"]).exists()


def test_changed_child_email_policy_blocks_installation_policy_inheritance(tmp_path: Path) -> None:
    installation = tmp_path / "installation"
    installation.mkdir()
    workspace = _artifact_workspace_at(installation / "ts_0000")
    draft_ref = _write_fixed_draft(workspace, tmp_path)
    clawemail_root, env = _fake_clawemail_skill(tmp_path)
    env["TS_EMAIL_POLICY_ROOT"] = str(installation)
    _activate_fixed_email_policy(installation, clawemail_root, env)
    _activate_fixed_email_policy(workspace, clawemail_root, env)
    policy_path = workspace / ".pi" / "ts-email-delivery-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["attachment_names"] = ["report_context.json"]
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    status = json.loads(_email_cli(workspace, "policy-status", env=env).stdout)
    assert status["state"] == "policy_changed"
    assert status["policy_scope"] == "local"
    blocked = _email_cli(workspace, "send", "--draft-ref", draft_ref, env=env, check=False)
    assert blocked.returncode == 2
    assert "delivery policy changed after activation" in blocked.stderr
    assert not Path(env["TS_TEST_CLAWEMAIL_LOG"]).exists()


def test_workspace_outside_installation_root_cannot_inherit_email_policy(tmp_path: Path) -> None:
    installation = tmp_path / "installation"
    installation.mkdir()
    workspace = _artifact_workspace_at(tmp_path / "external-workspace")
    draft_ref = _write_fixed_draft(workspace, tmp_path)
    clawemail_root, env = _fake_clawemail_skill(tmp_path)
    env["TS_EMAIL_POLICY_ROOT"] = str(installation)
    _activate_fixed_email_policy(installation, clawemail_root, env)

    status = json.loads(_email_cli(workspace, "policy-status", env=env).stdout)
    assert status["state"] == "not_configured"
    assert status["policy_scope"] == "local"
    blocked = _email_cli(workspace, "send", "--draft-ref", draft_ref, env=env, check=False)
    assert blocked.returncode == 2
    assert "delivery policy is missing" in blocked.stderr


def test_inherited_email_policy_rejects_symlinked_root_and_non_private_state(tmp_path: Path) -> None:
    installation = tmp_path / "installation"
    installation.mkdir()
    workspace = _artifact_workspace_at(installation / "ts_0000")
    clawemail_root, env = _fake_clawemail_skill(tmp_path)
    _activate_fixed_email_policy(installation, clawemail_root, env)

    policy_link = tmp_path / "policy-root-link"
    policy_link.symlink_to(installation, target_is_directory=True)
    symlink_env = {**env, "TS_EMAIL_POLICY_ROOT": str(policy_link)}
    failed = _email_cli(workspace, "policy-status", env=symlink_env, check=False)
    assert failed.returncode == 2
    assert "must not contain symbolic links" in failed.stderr

    policy_path = installation / ".pi" / "ts-email-delivery-policy.json"
    policy_path.chmod(0o644)
    unsafe_env = {**env, "TS_EMAIL_POLICY_ROOT": str(installation)}
    failed = _email_cli(workspace, "policy-status", env=unsafe_env, check=False)
    assert failed.returncode == 2
    assert "delivery policy must have mode 0600" in failed.stderr


def test_ambiguous_email_delivery_is_recorded_and_not_retried(tmp_path: Path) -> None:
    workspace = _artifact_workspace(tmp_path)
    draft_ref = _write_fixed_draft(workspace, tmp_path)
    clawemail_root, env = _fake_clawemail_skill(tmp_path)
    policy = json.loads(
        _email_cli(
            workspace,
            "policy-create",
            "--recipient",
            "researcher@example.org",
            "--clawemail-root",
            str(clawemail_root),
            env=env,
        ).stdout
    )
    _email_cli(
        workspace,
        "policy-activate",
        "--token",
        policy["activation_token"],
        env=env,
    )

    failing_env = {**env, "TS_TEST_CLAWEMAIL_FAIL": "1"}
    failed = _email_cli(
        workspace,
        "send",
        "--draft-ref",
        draft_ref,
        env=failing_env,
        check=False,
    )
    assert failed.returncode == 2
    assert "delivery result is ambiguous" in failed.stderr
    receipt_paths = list((workspace / "reports" / "email" / "deliveries").glob("*.json"))
    assert len(receipt_paths) == 1
    assert json.loads(receipt_paths[0].read_text(encoding="utf-8"))["state"] == "unknown"

    retry = _email_cli(workspace, "send", "--draft-ref", draft_ref, env=env, check=False)
    assert retry.returncode == 2
    assert "delivery remains unknown" in retry.stderr
    args = Path(env["TS_TEST_CLAWEMAIL_LOG"]).read_text(encoding="utf-8").splitlines()
    assert args.count("send") == 1


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
    return _artifact_workspace_at(tmp_path / "workspace")


def _artifact_workspace_at(workspace: Path) -> Path:
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
    (workspace / "reports" / "run-001" / "final_report.md").write_text("# Final report\n", encoding="utf-8")
    _write_package_manifest(workspace / "reports" / "run-001")
    return workspace


def _write_package_manifest(package_dir: Path) -> None:
    files = []
    for name in ("email_summary.md", "report_context.json", "final_report.md"):
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
            "template_id": "ts-report-summary/1",
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


def _write_fixed_draft(workspace: Path, tmp_path: Path) -> str:
    binding = _package_binding(workspace)
    draft_ref = "reports/email/draft-policy.json"
    request = {
        "schema_version": "ts-email-draft/1",
        "summary_ref": "reports/run-001/email_summary.md",
        "summary_digest": binding["summary_digest"],
        "manifest_ref": "reports/run-001/package_manifest.json",
        "manifest_digest": binding["manifest_digest"],
        "source_workspace_revision": binding["workspace_revision"],
        "draft_ref": draft_ref,
        "recipients": ["researcher@example.org"],
    }
    request_file = tmp_path / "fixed-draft-request.json"
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
    assert json.loads(completed.stdout)["draft_ref"] == draft_ref
    return draft_ref


def _email_cli(
    workspace: Path,
    command: str,
    *args: str,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "ts_email.py"),
            command,
            "--root",
            str(workspace),
            *args,
            "--json",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def _activate_fixed_email_policy(
    workspace: Path,
    clawemail_root: Path,
    env: dict[str, str],
) -> dict[str, object]:
    policy = json.loads(
        _email_cli(
            workspace,
            "policy-create",
            "--recipient",
            "researcher@example.org",
            "--attachment",
            "final_report.md",
            "--clawemail-root",
            str(clawemail_root),
            env=env,
        ).stdout
    )
    _email_cli(
        workspace,
        "policy-activate",
        "--token",
        str(policy["activation_token"]),
        env=env,
    )
    return policy


def _fake_clawemail_skill(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    skill_root = tmp_path / "clawemail"
    bin_dir = skill_root / "bin"
    state_dir = skill_root / ".clawemail"
    bin_dir.mkdir(parents=True)
    state_dir.mkdir(mode=0o700)
    (skill_root / "SKILL.md").write_text("---\nname: clawemail\n---\n", encoding="utf-8")
    for name in ("skill.json", "mail-cli.json"):
        path = state_dir / name
        path.write_text("{}\n", encoding="utf-8")
        path.chmod(0o600)
    manager = bin_dir / "clawemail-manager"
    manager.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$@" >> "$TS_TEST_CLAWEMAIL_LOG"
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  if [[ "${args[$i]}" == "--body-file" ]]; then
    cp -- "${args[$((i + 1))]}" "$TS_TEST_CLAWEMAIL_BODY"
  fi
done
if [[ "${TS_TEST_CLAWEMAIL_FAIL:-0}" == "1" ]]; then
  printf 'simulated provider failure\\n' >&2
  exit 9
fi
printf '{"sent":true}\\n'
""",
        encoding="utf-8",
    )
    manager.chmod(0o755)
    return skill_root, {
        **os.environ,
        "TS_TEST_CLAWEMAIL_LOG": str(tmp_path / "clawemail-args.log"),
        "TS_TEST_CLAWEMAIL_BODY": str(tmp_path / "clawemail-body.txt"),
    }
