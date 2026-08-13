from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.strict_helpers import bootstrap_strict_workspace
from ts_report import build_report_package
from ts_email import delivery as notification_delivery


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_AGENT = ROOT / "src" / "agents" / "artifacts"
REQUEST_CONTRACT = ARTIFACT_AGENT / "request-contract.cjs"
OUTPUT_SCHEMA = ARTIFACT_AGENT / "output-schema.cjs"


def test_pi_package_registers_artifact_and_notification_tools() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert "./extensions/ts-workflow-artifacts/index.ts" in package["pi"]["extensions"]
    source = (ROOT / "extensions" / "ts-workflow-artifacts" / "index.ts").read_text(encoding="utf-8")
    for key in ("subagentRender", "subagentReport", "notifyUser"):
        assert f"name: TS_PUBLIC_TOOL_NAMES.{key}" in source
    for name in ("ts_workspace_render_execute", "ts_workspace_report_build"):
        assert f'"{name}"' in source
    for retired in ("subagentEmailDraft", "emailSend", "createEmailDraftTool", "ts_workspace_email_draft_write"):
        assert retired not in source
    catalog = (ROOT / "extensions" / "shared" / "tool-catalog.ts").read_text(encoding="utf-8")
    assert 'notifyUser: "ts_notify_user"' in catalog
    assert '[TS_PUBLIC_TOOL_NAMES.notifyUser]: "deterministic_external"' in catalog


def test_artifact_runtime_is_fresh_policy_scoped_and_without_builtin_tools() -> None:
    runtime = (ARTIFACT_AGENT / "runtime.ts").read_text(encoding="utf-8")
    prompt = (ARTIFACT_AGENT / "prompt.md").read_text(encoding="utf-8")
    assert 'type ArtifactRole = "render" | "report"' in runtime
    assert 'noTools: "builtin"' in runtime
    assert "customTools: options.tools" in runtime
    assert "SessionManager.inMemory(options.workspaceRoot)" in runtime
    assert "SettingsManager.inMemory" in runtime
    assert "getAgentsFiles: () => ({ agentsFiles: [] })" in runtime
    assert "getSkills: () => ({ skills: [], diagnostics: [] })" in runtime
    assert "withDisposableSession" in runtime
    assert "loadArtifactPolicy(options.role)" in runtime
    assert "no general shell" in prompt
    assert "notification" in prompt
    assert not (ARTIFACT_AGENT / "roles" / "email.md").exists()


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


def test_render_success_requires_a_nonempty_bound_output(tmp_path: Path) -> None:
    workspace = _artifact_workspace(tmp_path)
    output = workspace / "nodes" / "n001" / "outputs" / "render.png"

    missing = _created_render_output(workspace, "nodes/n001/outputs/render.png", check=False)
    assert missing.returncode == 2
    assert "missing or empty" in missing.stderr

    output.touch()
    empty = _created_render_output(workspace, "nodes/n001/outputs/render.png", check=False)
    assert empty.returncode == 2
    assert "missing or empty" in empty.stderr

    output.write_bytes(b"png")
    assert _created_render_output(workspace, "nodes/n001/outputs/render.png") == "nodes/n001/outputs/render.png"


def test_report_success_requires_a_complete_digest_bound_package(tmp_path: Path) -> None:
    workspace = tmp_path / "report-workspace"
    bootstrap_strict_workspace(workspace)
    package_ref = "reports/operator-package"
    result = build_report_package(workspace, workspace / package_ref)

    verified = _created_report_package(
        workspace,
        package_ref,
        result["manifest_digest"],
        result["workspace_revision"],
    )
    assert verified["package_ref"] == package_ref
    assert verified["file_count"] >= 3


@pytest.mark.parametrize("tamper", ["manifest_digest", "workspace_revision", "file", "required_file", "unlisted_file"])
def test_report_package_verification_rejects_inconsistent_output(tmp_path: Path, tamper: str) -> None:
    workspace = tmp_path / f"report-{tamper}"
    bootstrap_strict_workspace(workspace)
    package_ref = "reports/operator-package"
    result = build_report_package(workspace, workspace / package_ref)
    manifest_digest = result["manifest_digest"]
    workspace_revision = result["workspace_revision"]

    if tamper == "manifest_digest":
        manifest_digest = "sha256:" + "0" * 64
    elif tamper == "workspace_revision":
        workspace_revision = "sha256:" + "0" * 64
    elif tamper == "file":
        (workspace / package_ref / "final_report.md").write_text("tampered\n", encoding="utf-8")
    elif tamper == "required_file":
        manifest_path = workspace / package_ref / "package_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"] = [entry for entry in manifest["files"] if entry["ref"] != "email_summary.md"]
        manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        manifest_digest = _sha256(manifest_path)
    else:
        (workspace / package_ref / "unlisted.txt").write_text("unexpected\n", encoding="utf-8")

    failed = _created_report_package(
        workspace,
        package_ref,
        manifest_digest,
        workspace_revision,
        check=False,
    )
    assert failed.returncode == 2
    expected = {
        "manifest_digest": "manifest digest does not match",
        "workspace_revision": "workspace revision does not match",
        "file": "file size does not match",
        "required_file": "missing required file",
        "unlisted_file": "contents do not match",
    }[tamper]
    assert expected in failed.stderr


def test_artifact_node_scope_must_match_workspace_report(tmp_path: Path) -> None:
    report = {"node_index": [{"node_id": "n001"}]}
    assert _node_scope_contract(report, ["n001"]) == ["n001"]
    failed = _node_scope_contract(report, ["n999"], check=False)
    assert failed.returncode == 2
    assert "absent from workspace report" in failed.stderr


def test_notification_uses_installation_recipient_and_is_idempotent(tmp_path: Path) -> None:
    workspace = _notification_workspace(tmp_path)
    clawemail_root, env = _fake_clawemail_skill(tmp_path)
    config = _write_notification_config(tmp_path, clawemail_root)
    env["TS_NOTIFICATION_CONFIG"] = str(config)
    request = _notification_request(tmp_path, report_refs=["reports/node-n000/final_report.md"])

    first = _email_cli(workspace, request, env=env)
    second = _email_cli(workspace, request, env=env)
    first_result = json.loads(first.stdout)
    second_result = json.loads(second.stdout)
    assert first_result["state"] == "sent"
    assert first_result["external_side_effects"] is True
    assert second_result["state"] == "already_sent"
    assert second_result["external_side_effects"] is False
    assert first_result["attachment_refs"] == ["reports/node-n000/final_report.md"]

    receipt = json.loads((workspace / first_result["receipt_ref"]).read_text(encoding="utf-8"))
    for public_value in (first.stdout, second.stdout, json.dumps(receipt)):
        assert "researcher@example.org" not in public_value
        assert str(clawemail_root) not in public_value
    args = Path(env["TS_TEST_CLAWEMAIL_LOG"]).read_text(encoding="utf-8").splitlines()
    assert args.count("send") == 1
    assert "researcher@example.org" in args
    assert "reports/node-n000/final_report.md" not in "\n".join(args)
    assert Path(env["TS_TEST_CLAWEMAIL_BODY"]).read_text(encoding="utf-8") == "n000 intake is ready.\n"
    assert Path(env["TS_TEST_CLAWEMAIL_ATTACHMENT"]).read_text(encoding="utf-8") == "# n000\n\nIntake ready.\n"


def test_concurrent_identical_notifications_send_once(tmp_path: Path) -> None:
    workspace = _notification_workspace(tmp_path)
    clawemail_root, env = _fake_clawemail_skill(tmp_path)
    env["TS_NOTIFICATION_CONFIG"] = str(_write_notification_config(tmp_path, clawemail_root))
    env["TS_TEST_CLAWEMAIL_SLEEP"] = "1"
    request = _notification_request(tmp_path)
    command = [
        sys.executable,
        str(ROOT / "scripts" / "ts_email.py"),
        "notify",
        "--root",
        str(workspace),
        "--request-file",
        str(request),
        "--json",
    ]
    processes = [
        subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _index in range(2)
    ]
    completed = [process.communicate(timeout=15) for process in processes]
    assert [process.returncode for process in processes] == [0, 0], completed
    states = {json.loads(stdout)["state"] for stdout, _stderr in completed}
    assert states == {"sent", "already_sent"}
    args = Path(env["TS_TEST_CLAWEMAIL_LOG"]).read_text(encoding="utf-8").splitlines()
    assert args.count("send") == 1


def test_notification_rejects_agent_addressing_and_missing_or_disabled_config(tmp_path: Path) -> None:
    workspace = _notification_workspace(tmp_path)
    clawemail_root, env = _fake_clawemail_skill(tmp_path)
    request = _notification_request(tmp_path)
    value = json.loads(request.read_text(encoding="utf-8"))
    value["recipient"] = "other@example.org"
    request.write_text(json.dumps(value), encoding="utf-8")
    config = _write_notification_config(tmp_path, clawemail_root)
    env["TS_NOTIFICATION_CONFIG"] = str(config)
    failed = _email_cli(workspace, request, env=env, check=False)
    assert failed.returncode == 2
    assert "unknown fields: recipient" in failed.stderr
    assert not Path(env["TS_TEST_CLAWEMAIL_LOG"]).exists()

    env.pop("TS_NOTIFICATION_CONFIG")
    missing = _email_cli(workspace, _notification_request(tmp_path, name="missing.json"), env=env, check=False)
    assert missing.returncode == 2
    assert "TS_NOTIFICATION_CONFIG is not configured" in missing.stderr

    disabled = _write_notification_config(tmp_path, clawemail_root, enabled=False, name="disabled.toml")
    env["TS_NOTIFICATION_CONFIG"] = str(disabled)
    blocked = _email_cli(workspace, _notification_request(tmp_path, name="disabled.json"), env=env, check=False)
    assert blocked.returncode == 2
    assert "notifications are disabled" in blocked.stderr


@pytest.mark.parametrize(
    ("report_ref", "message"),
    [
        ("../outside.md", "safe reports/"),
        ("inputs/reactant.xyz", "safe reports/"),
        ("reports/missing.md", "does not exist"),
    ],
)
def test_notification_rejects_unsafe_report_refs(tmp_path: Path, report_ref: str, message: str) -> None:
    workspace = _notification_workspace(tmp_path)
    clawemail_root, env = _fake_clawemail_skill(tmp_path)
    env["TS_NOTIFICATION_CONFIG"] = str(_write_notification_config(tmp_path, clawemail_root))
    request = _notification_request(tmp_path, report_refs=[report_ref])
    failed = _email_cli(workspace, request, env=env, check=False)
    assert failed.returncode == 2
    assert message in failed.stderr
    assert not Path(env["TS_TEST_CLAWEMAIL_LOG"]).exists()


def test_notification_rejects_symlinked_report_and_private_config_violation(tmp_path: Path) -> None:
    workspace = _notification_workspace(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    (workspace / "reports" / "linked.md").symlink_to(outside)
    clawemail_root, env = _fake_clawemail_skill(tmp_path)
    config = _write_notification_config(tmp_path, clawemail_root)
    env["TS_NOTIFICATION_CONFIG"] = str(config)
    failed = _email_cli(
        workspace,
        _notification_request(tmp_path, report_refs=["reports/linked.md"]),
        env=env,
        check=False,
    )
    assert "symbolic link" in failed.stderr

    config.chmod(0o644)
    failed = _email_cli(workspace, _notification_request(tmp_path, name="mode.json"), env=env, check=False)
    assert "must have mode 0600" in failed.stderr


def test_notification_does_not_expose_missing_clawemail_path(tmp_path: Path) -> None:
    workspace = _notification_workspace(tmp_path)
    missing_root = tmp_path / "private" / "missing-clawemail"
    config = _write_notification_config(tmp_path, missing_root)
    env = {**os.environ, "TS_NOTIFICATION_CONFIG": str(config)}

    failed = _email_cli(workspace, _notification_request(tmp_path), env=env, check=False)
    assert failed.returncode == 2
    assert "configured ClawEmail installation is unavailable" in failed.stderr
    assert str(missing_root) not in failed.stderr


def test_ambiguous_notification_is_recorded_and_not_retried(tmp_path: Path) -> None:
    workspace = _notification_workspace(tmp_path)
    clawemail_root, env = _fake_clawemail_skill(tmp_path)
    env["TS_NOTIFICATION_CONFIG"] = str(_write_notification_config(tmp_path, clawemail_root))
    request = _notification_request(tmp_path)
    failing_env = {**env, "TS_TEST_CLAWEMAIL_FAIL": "1"}
    failed = _email_cli(workspace, request, env=failing_env, check=False)
    assert failed.returncode == 2
    assert "result is ambiguous" in failed.stderr
    receipt_paths = list((workspace / "reports" / "email" / "deliveries").glob("*.json"))
    assert len(receipt_paths) == 1
    assert json.loads(receipt_paths[0].read_text(encoding="utf-8"))["state"] == "unknown"

    retry = _email_cli(workspace, request, env=env, check=False)
    assert retry.returncode == 2
    assert "remains unknown" in retry.stderr
    args = Path(env["TS_TEST_CLAWEMAIL_LOG"]).read_text(encoding="utf-8").splitlines()
    assert args.count("send") == 1


def test_notification_failure_before_provider_start_can_be_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _notification_workspace(tmp_path)
    clawemail_root, _env = _fake_clawemail_skill(tmp_path)
    config = _write_notification_config(tmp_path, clawemail_root)
    monkeypatch.setenv("TS_NOTIFICATION_CONFIG", str(config))
    request = _notification_request(tmp_path)
    attempts = 0

    def run_provider(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise notification_delivery._DeliveryNotStarted("provider executable unavailable")
        return '{"sent":true}\n'

    monkeypatch.setattr(notification_delivery, "_run_clawemail", run_provider)
    with pytest.raises(ValueError, match="was not started"):
        notification_delivery.notify_user(workspace, request)

    receipt_paths = list((workspace / "reports/email/deliveries").glob("*.json"))
    assert len(receipt_paths) == 1
    failed = json.loads(receipt_paths[0].read_text(encoding="utf-8"))
    assert failed["state"] == "failed"
    assert failed["error_class"] == "delivery_not_started"

    result = notification_delivery.notify_user(workspace, request)
    assert result["state"] == "sent"
    assert attempts == 2


def test_notification_detects_tampered_receipt(tmp_path: Path) -> None:
    workspace = _notification_workspace(tmp_path)
    clawemail_root, env = _fake_clawemail_skill(tmp_path)
    env["TS_NOTIFICATION_CONFIG"] = str(_write_notification_config(tmp_path, clawemail_root))
    request = _notification_request(tmp_path)
    result = json.loads(_email_cli(workspace, request, env=env).stdout)
    receipt_path = workspace / result["receipt_ref"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["notification_digest"] = "sha256:" + "0" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    failed = _email_cli(workspace, request, env=env, check=False)
    assert failed.returncode == 2
    assert "does not match the request" in failed.stderr


@pytest.mark.parametrize("tamper_target", ["attachment", "config"])
def test_notification_rechecks_inputs_after_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper_target: str,
) -> None:
    workspace = _notification_workspace(tmp_path)
    clawemail_root, env = _fake_clawemail_skill(tmp_path)
    config = _write_notification_config(tmp_path, clawemail_root)
    monkeypatch.setenv("TS_NOTIFICATION_CONFIG", str(config))
    request = _notification_request(tmp_path, report_refs=["reports/node-n000/final_report.md"])
    original_write = notification_delivery._write_private_json
    tampered = False

    def write_and_tamper(path, value, *, exclusive):
        nonlocal tampered
        original_write(path, value, exclusive=exclusive)
        if value.get("state") == "sending" and not tampered:
            tampered = True
            if tamper_target == "attachment":
                (workspace / "reports/node-n000/final_report.md").write_text("changed\n", encoding="utf-8")
            else:
                config.write_text(
                    "[notifications.email]\n"
                    "enabled = false\n"
                    'recipient = "researcher@example.org"\n'
                    f'clawemail_root = "{clawemail_root}"\n',
                    encoding="utf-8",
                )
                config.chmod(0o600)

    monkeypatch.setattr(notification_delivery, "_write_private_json", write_and_tamper)
    with pytest.raises(ValueError, match="changed after"):
        notification_delivery.notify_user(workspace, request)
    assert not Path(env["TS_TEST_CLAWEMAIL_LOG"]).exists()
    receipts = list((workspace / "reports/email/deliveries").glob("*.json"))
    assert len(receipts) == 1
    assert json.loads(receipts[0].read_text(encoding="utf-8"))["state"] == "failed"


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
    assert result["manifest_digest"].startswith("sha256:")


def test_report_package_validates_and_refuses_overwrite(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid-workspace"
    invalid.mkdir()
    with pytest.raises(ValueError, match="workspace is invalid"):
        build_report_package(invalid, invalid / "reports" / "package")

    workspace = tmp_path / "report-workspace"
    bootstrap_strict_workspace(workspace)
    package_dir = workspace / "reports" / "operator-package"
    build_report_package(workspace, package_dir)
    with pytest.raises(ValueError, match="already exists"):
        build_report_package(workspace, package_dir)


@pytest.mark.parametrize("role", ["render", "report"])
def test_artifact_output_is_bound_to_one_typed_action(tmp_path: Path, role: str) -> None:
    packet, action, report = _artifact_protocol_fixture(role)
    completed = _validate_artifact_output(tmp_path, packet, [action], report)
    assert json.loads(completed.stdout)["role"] == role
    report["artifact_refs"] = ["reports/invented.txt"]
    failed = _validate_artifact_output(tmp_path, packet, [action], report, check=False)
    assert failed.returncode == 2
    assert "do not match" in failed.stderr


def test_artifact_output_rejects_started_action(tmp_path: Path) -> None:
    packet, action, report = _artifact_protocol_fixture("report")
    action["result"]["state"] = "started"
    failed = _validate_artifact_output(tmp_path, packet, [action], report, check=False)
    assert "report state does not match" in failed.stderr


def test_report_output_revision_must_match_task_snapshot(tmp_path: Path) -> None:
    packet, action, report = _artifact_protocol_fixture("report")
    packet["workspace"]["revision"] = "sha256:" + "9" * 64
    failed = _validate_artifact_output(tmp_path, packet, [action], report, check=False)
    assert failed.returncode == 2
    assert "workspace_revision" in failed.stderr


@pytest.mark.parametrize("role", ["render", "report"])
def test_artifact_output_ignores_malformed_model_receipt_after_successful_action(tmp_path: Path, role: str) -> None:
    packet, action, _report = _artifact_protocol_fixture(role)
    malformed = {"facts": [{"state": "built"}]} if role == "report" else {"provenance": None}
    malformed["summary"] = "Model-authored summary must not become the canonical receipt."
    malformed["limitations"] = ["Model-authored limitation must be ignored."]
    completed = _parse_artifact_output(tmp_path, packet, [action], malformed)
    report = json.loads(completed.stdout)

    assert report["outcome"] == "success"
    assert report["facts"] == []
    assert report["provenance"] == {
        "source": "typed_artifact_tool",
        "action_name": action["tool"],
    }
    assert report["artifact_refs"] == action["result"]["artifact_refs"]
    assert "Model-authored" not in report["summary"]
    assert report["limitations"] == []


def _artifact_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    for path in (
        workspace / "inputs",
        workspace / "nodes" / "n001" / "inputs",
        workspace / "nodes" / "n001" / "outputs",
        workspace / "reports",
    ):
        path.mkdir(parents=True, exist_ok=True)
    (workspace / "inputs" / "reactant.xyz").write_text("1\nR\nH 0 0 0\n", encoding="utf-8")
    (workspace / "nodes" / "n001" / "inputs" / "product.xyz").write_text("1\nP\nH 0 0 1\n", encoding="utf-8")
    (workspace / "nodes" / "n001" / "node.json").write_text("{}\n", encoding="utf-8")
    return workspace


def _notification_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "notification-workspace"
    bootstrap_strict_workspace(workspace)
    package = workspace / "reports" / "node-n000"
    package.mkdir(parents=True)
    (package / "final_report.md").write_text("# n000\n\nIntake ready.\n", encoding="utf-8")
    return workspace


def _request_contract(function_name: str, workspace: Path, request: dict[str, object], *, check: bool = True):
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


def _node_scope_contract(report: dict[str, object], node_ids: list[str], *, check: bool = True):
    script = (
        f"const helper=require({json.dumps(str(REQUEST_CONTRACT))});"
        f"const report={json.dumps(report)};"
        f"const nodeIds={json.dumps(node_ids)};"
        "try { process.stdout.write(JSON.stringify(helper.validateTaskNodeScope(report,nodeIds))); }"
        "catch(error){ process.stderr.write(String(error.message||error)); process.exitCode=2; }"
    )
    completed = subprocess.run(
        ["node", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check
    )
    return json.loads(completed.stdout) if check else completed


def _created_render_output(workspace: Path, output_ref: str, *, check: bool = True):
    script = (
        f"const helper=require({json.dumps(str(REQUEST_CONTRACT))});"
        "try { process.stdout.write(JSON.stringify(helper.validateCreatedRenderOutput(process.argv[1],process.argv[2]))); }"
        "catch(error){ process.stderr.write(String(error.message||error)); process.exitCode=2; }"
    )
    completed = subprocess.run(
        ["node", "-e", script, str(workspace), output_ref],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )
    return json.loads(completed.stdout) if check else completed


def _created_report_package(
    workspace: Path,
    package_ref: str,
    manifest_digest: str,
    workspace_revision: str,
    *,
    check: bool = True,
):
    script = (
        f"const helper=require({json.dumps(str(REQUEST_CONTRACT))});"
        "try { process.stdout.write(JSON.stringify(helper.validateCreatedReportPackage(...process.argv.slice(1)))); }"
        "catch(error){ process.stderr.write(String(error.message||error)); process.exitCode=2; }"
    )
    completed = subprocess.run(
        ["node", "-e", script, str(workspace), package_ref, manifest_digest, workspace_revision],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )
    return json.loads(completed.stdout) if check else completed


def _sha256(path: Path) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_protocol_fixture(role: str):
    operation = {"render": "render", "report": "build"}[role]
    node_ids = ["n001"] if role == "render" else []
    packet = {
        "schema_version": "ts-agent-task/2",
        "task_id": f"agent_{role}_001",
        "role": role,
        "authority": "operational",
        "operation": operation,
        "objective": f"Execute bounded {role} operation.",
        "workspace": {
            "root": "/tmp/ws",
            "report_id": "rep_001",
            "revision": "sha256:" + "1" * 64,
        },
        "scope": {"report_id": "rep_001", "node_ids": node_ids, "hypothesis_id": None, "pathway_id": None},
        "inputs": {"basis_allowlist": ["inputs/reactant.xyz"]},
        "capabilities": [{"render": "ts_workspace_render_execute", "report": "ts_workspace_report_build"}[role]],
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
    }[role]
    tool = {"render": "ts_workspace_render_execute", "report": "ts_workspace_report_build"}[role]
    action = {"tool": tool, "result": canonical}
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
        "payload": {key: value for key, value in canonical.items() if key not in {"artifact_refs", "state"}},
        "limitations": [],
        "provenance": {},
    }
    return packet, action, report


def _validate_artifact_output(tmp_path: Path, packet, actions, report, *, check: bool = True):
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


def _parse_artifact_output(tmp_path: Path, packet, actions, report, *, check: bool = True):
    input_path = tmp_path / "artifact-parse-output.json"
    input_path.write_text(json.dumps({"packet": packet, "actions": actions, "report": report}), encoding="utf-8")
    script = (
        "const fs=require('node:fs');"
        f"const helper=require({json.dumps(str(OUTPUT_SCHEMA))});"
        "const input=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));"
        "try { process.stdout.write(JSON.stringify(helper.parseAndValidateArtifactReport(JSON.stringify(input.report),input.packet,input.actions))); }"
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


def _notification_request(tmp_path: Path, *, report_refs: list[str] | None = None, name: str = "notify.json") -> Path:
    request = tmp_path / name
    request.write_text(
        json.dumps(
            {
                "schema_version": "ts-user-notification/1",
                "event": "node_completed",
                "subject": "n000 intake completed",
                "summary": "n000 intake is ready.",
                "report_refs": report_refs or [],
            }
        ),
        encoding="utf-8",
    )
    return request


def _write_notification_config(
    tmp_path: Path,
    clawemail_root: Path,
    *,
    enabled: bool = True,
    name: str = "notifications.toml",
) -> Path:
    config = tmp_path / name
    config.write_text(
        "[notifications.email]\n"
        f"enabled = {'true' if enabled else 'false'}\n"
        'recipient = "researcher@example.org"\n'
        f'clawemail_root = "{clawemail_root}"\n',
        encoding="utf-8",
    )
    config.chmod(0o600)
    return config


def _email_cli(workspace: Path, request: Path, *, env: dict[str, str], check: bool = True):
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "ts_email.py"),
            "notify",
            "--root",
            str(workspace),
            "--request-file",
            str(request),
            "--json",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


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
  if [[ "${args[$i]}" == "--attach" ]]; then
    cp -- "${args[$((i + 1))]}" "$TS_TEST_CLAWEMAIL_ATTACHMENT"
  fi
done
if [[ "${TS_TEST_CLAWEMAIL_FAIL:-0}" == "1" ]]; then
  printf 'simulated provider failure\\n' >&2
  exit 9
fi
if [[ -n "${TS_TEST_CLAWEMAIL_SLEEP:-}" ]]; then
  sleep "$TS_TEST_CLAWEMAIL_SLEEP"
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
        "TS_TEST_CLAWEMAIL_ATTACHMENT": str(tmp_path / "clawemail-attachment.md"),
    }
