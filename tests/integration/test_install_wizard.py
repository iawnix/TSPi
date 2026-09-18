from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

from scripts import install_wizard as wizard
from scripts.install_from_github import install_uninstaller


ROOT = Path(__file__).resolve().parents[2]


def _options(tmp_path: Path):
    args = wizard.parse_args([
        "--install-root",
        str(tmp_path / "install"),
        "--with-web",
        "--service-scope",
        "user",
        "--enable-services",
        "--start-services",
        "--non-interactive",
        "--yes",
    ])
    wizard.validate_options(args)
    return args


def test_non_interactive_options_select_only_web_as_optional_component(tmp_path: Path) -> None:
    args = _options(tmp_path)
    assert args.with_web is True
    assert args.with_model_icons is False
    assert args.web_port == 8766
    assert not hasattr(args, "with_phone")


def test_interactive_web_token_reprompts_until_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    values = iter(("too-short", "a" * 8))
    monkeypatch.setattr(wizard.getpass, "getpass", lambda _prompt: next(values))

    assert wizard._ask_web_auth_token() == "a" * 8


def test_interactive_web_token_blank_uses_generated_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wizard.getpass, "getpass", lambda _prompt: "   ")

    assert wizard._ask_web_auth_token() is None


def test_interactive_compute_backends_accepts_one_file_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = wizard.parse_args([
        "--install-root", str(tmp_path / "install"),
        "--without-web", "--service-scope", "none", "--email-provider", "smtp",
    ])
    args.workspace_root = str(tmp_path / "workspaces")
    args.radius_gateway = "wss://radius.example.test"
    args.conda_root = "/opt/conda"
    prompts: list[str] = []
    monkeypatch.setattr(wizard.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(wizard.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(wizard, "ask", lambda prompt, default="": prompts.append(prompt) or "")
    monkeypatch.setattr(wizard, "ask_yes_no", lambda _prompt, default=True: default)

    wizard.interactive_options(args)

    assert prompts[0] == "Compute backend TOML path (blank preserves existing configuration)"
    assert not any("backend TOML" in prompt or "remote" in prompt.lower() for prompt in prompts[1:])
    assert args.compute_config is None


def test_model_icon_options_are_mutually_exclusive(tmp_path: Path) -> None:
    root = tmp_path / "install"
    with_icons = wizard.parse_args(["--install-root", str(root), "--with-model-icons", "--non-interactive"])
    without_icons = wizard.parse_args(["--install-root", str(root), "--without-model-icons", "--non-interactive"])

    assert with_icons.with_model_icons is True
    assert without_icons.with_model_icons is False
    with pytest.raises(SystemExit):
        wizard.parse_args([
            "--install-root",
            str(root),
            "--with-model-icons",
            "--without-model-icons",
            "--non-interactive",
        ])


def test_model_icon_font_install_writes_private_marker_and_handles_missing_fc_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "package"
    source = package / "assets/fonts/tspi-model-icons.ttf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"font fixture")
    install_root = tmp_path / "install"
    install_root.mkdir()
    data_home = tmp_path / "xdg-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setattr(wizard.shutil, "which", lambda _name: None)

    result = wizard.install_model_icon_font(package, install_root, enabled=True)

    target = data_home / "fonts/tspi/TSPi-Model-Icons.ttf"
    marker = install_root / ".pi/tspi/model-icons.json"
    assert result["status"] == "installed_cache_unavailable"
    assert result["enabled"] is True
    assert target.read_bytes() == source.read_bytes()
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600
    assert stat.S_IMODE(marker.parent.stat().st_mode) == 0o700
    document = json.loads(marker.read_text(encoding="utf-8"))
    assert document["enabled"] is True
    assert document["font_path"] == str(target)
    assert document["sha256"] == result["sha256"]


def test_model_icon_font_can_be_disabled_without_removing_shared_font(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "package"
    source = package / "assets/fonts/tspi-model-icons.ttf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"font fixture")
    install_root = tmp_path / "install"
    install_root.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    wizard.install_model_icon_font(package, install_root, enabled=True)

    result = wizard.install_model_icon_font(package, install_root, enabled=False)

    assert result["status"] == "disabled"
    assert (tmp_path / "xdg-data/fonts/tspi/TSPi-Model-Icons.ttf").is_file()
    assert json.loads((install_root / ".pi/tspi/model-icons.json").read_text(encoding="utf-8"))["enabled"] is False


def test_update_preserves_workspace_root_and_radius_gateway_defaults(tmp_path: Path) -> None:
    root = tmp_path / "install"
    workspace_root = tmp_path / "research"
    workspace_config = root / ".pi/tspi/workspace-root.json"
    workspace_config.parent.mkdir(parents=True)
    workspace_config.write_text(json.dumps({
        "schema_version": "tspi-workspace-root/1",
        "workspace_root": str(workspace_root),
    }), encoding="utf-8")
    phone = root / ".pi/app-server-host/phone-connection.json"
    phone.parent.mkdir(parents=True)
    phone.write_text(json.dumps({"radius_gateway": "wss://radius.example.test"}), encoding="utf-8")
    args = wizard.parse_args([
        "--install-root", str(root), "--without-web", "--service-scope", "none", "--non-interactive",
    ])

    wizard.validate_options(args)

    assert args.workspace_root == str(workspace_root)
    assert args.radius_gateway == "wss://radius.example.test"


def test_install_configuration_rollback_restores_owned_files_and_removes_new_release(
    tmp_path: Path,
) -> None:
    root = tmp_path / "install"
    workspace_root = tmp_path / "research"
    workspace_root.mkdir()
    root.mkdir()
    args = wizard.parse_args([
        "--install-root", str(root),
        "--workspace-root", str(workspace_root),
        "--without-web", "--service-scope", "none", "--non-interactive",
    ])
    wizard.validate_options(args)
    phone = root / ".pi/app-server-host/phone-connection.json"
    phone.parent.mkdir(parents=True)
    phone.write_text("old-phone\n", encoding="utf-8")
    release = root / ".pi/packages/tspi/releases/old"
    release.mkdir(parents=True)
    snapshot = wizard.snapshot_install_configuration(root, args)

    phone.write_text("new-phone\n", encoding="utf-8")
    (root / ".pi/compute.toml").parent.mkdir(parents=True, exist_ok=True)
    (root / ".pi/compute.toml").write_text("new\n", encoding="utf-8")
    (root / ".pi/packages/tspi/releases/new").mkdir(parents=True)

    wizard.restore_install_configuration(root, snapshot)

    assert phone.read_text(encoding="utf-8") == "old-phone\n"
    assert not (root / ".pi/compute.toml").exists()
    assert release.is_dir()
    assert not (root / ".pi/packages/tspi/releases/new").exists()


def test_non_interactive_smtp_options_write_only_a_secure_credential_reference(tmp_path: Path) -> None:
    root = tmp_path / "install"
    password_file = tmp_path / "smtp-password"
    password_file.write_text("qq-authorization-code\n", encoding="utf-8")
    password_file.chmod(0o600)
    args = wizard.parse_args([
        "--install-root", str(root),
        "--without-web",
        "--service-scope", "none",
        "--non-interactive",
        "--email-provider", "smtp",
        "--email-preset", "qq",
        "--email-recipient", "receiver@example.org",
        "--email-address", "sender@qq.com",
        "--email-password-file", str(password_file),
    ])
    wizard.validate_options(args)

    result = wizard.configure_notification_config(args)

    config = root / ".pi/notifications.toml"
    assert result["provider"] == "smtp"
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert stat.S_IMODE(password_file.stat().st_mode) == 0o600
    content = config.read_text(encoding="utf-8")
    assert 'preset = "qq"' in content
    assert f'password_file = "{password_file}"' in content
    assert "qq-authorization-code" not in content


def test_interactive_smtp_password_is_written_to_the_default_private_file(tmp_path: Path) -> None:
    root = tmp_path / "install"
    password_file = root / ".pi/email/smtp-password"
    args = wizard.parse_args([
        "--install-root", str(root),
        "--without-web",
        "--service-scope", "none",
        "--non-interactive",
        "--email-provider", "smtp",
        "--email-preset", "163",
        "--email-recipient", "receiver@example.org",
        "--email-username", "sender@163.com",
        "--email-password-file", str(password_file),
    ])
    args._email_password = "163-authorization-code"
    wizard.validate_options(args)

    wizard.configure_notification_config(args)

    assert password_file.read_text(encoding="utf-8") == "163-authorization-code\n"
    assert stat.S_IMODE(password_file.stat().st_mode) == 0o600
    assert "163-authorization-code" not in (root / ".pi/notifications.toml").read_text(encoding="utf-8")


def test_clawemail_options_write_compatible_configuration(tmp_path: Path) -> None:
    root = tmp_path / "install"
    clawemail = tmp_path / "clawemail"
    (clawemail / "bin").mkdir(parents=True)
    (clawemail / ".clawemail").mkdir()
    (clawemail / "SKILL.md").write_text("---\nname: clawemail\n---\n", encoding="utf-8")
    manager = clawemail / "bin/clawemail-manager"
    manager.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    manager.chmod(0o755)
    for name in ("skill.json", "mail-cli.json"):
        path = clawemail / ".clawemail" / name
        path.write_text("{}\n", encoding="utf-8")
        path.chmod(0o600)
    args = wizard.parse_args([
        "--install-root", str(root),
        "--without-web",
        "--service-scope", "none",
        "--non-interactive",
        "--email-provider", "clawemail",
        "--email-recipient", "receiver@example.org",
        "--clawemail-root", str(clawemail),
    ])
    wizard.validate_options(args)

    wizard.configure_notification_config(args)

    content = (root / ".pi/notifications.toml").read_text(encoding="utf-8")
    assert 'recipient = "receiver@example.org"' in content
    assert f'clawemail_root = "{clawemail}"' in content
    assert "provider =" not in content


def test_app_server_service_is_one_installation_host(tmp_path: Path) -> None:
    args = _options(tmp_path)
    root = Path(args.install_root)
    unit = wizard.app_server_unit(args)

    assert f"WorkingDirectory={root}" in unit
    assert f'ExecStart="{root / "TSPi"}" --service-host' in unit
    assert "Environment=TSPI_SYSTEMD_HOST=1" in unit
    assert 'Environment="XDG_RUNTIME_DIR=' in unit
    assert f'PI_CODING_AGENT_DIR={root / ".pi/agent"}' in unit
    assert 'ReadWritePaths="/run/user/' in unit
    assert f'ReadWritePaths="{root / ".pi/app-server-host"}"' in unit
    assert f'ReadWritePaths="{root / ".pi/session-guards"}"' in unit
    assert f'ReadWritePaths="{root / "workspaces"}"' in unit
    assert "WantedBy=default.target" in unit
    assert "TSPhone" not in unit
    assert "session-host" not in unit


def test_web_service_uses_installed_launcher_and_workspace_root(tmp_path: Path) -> None:
    args = _options(tmp_path)
    root = Path(args.install_root)
    unit = wizard.web_unit(args)

    assert f"WorkingDirectory={root}" in unit
    assert f'ExecStart="{root / "TSWeb"}"' in unit
    assert str(root / "workspaces") in unit
    assert str(root / ".pi/ts-web/auth.token") in unit
    assert f'ReadOnlyPaths="{root / "workspaces"}"' in unit
    assert f'ReadWritePaths="{root / "workspaces"}"' not in unit


def test_prepare_app_server_runtime_uses_installed_release_script(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "install"
    installer = root / ".pi/packages/tspi/current/agent/scripts/prepare_pi_source.py"
    installer.parent.mkdir(parents=True)
    installer.write_text("# fixture\n", encoding="utf-8")
    runtime = root / ".pi/runtime-cache/pi/test"
    runtime.mkdir(parents=True)
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="npm warn deprecated package\n" + str(runtime) + "\n",
            stderr="",
        )

    monkeypatch.setattr(wizard.subprocess, "run", run)
    assert wizard.prepare_app_server_runtime(root) == runtime
    assert commands == [[wizard.sys.executable, str(installer), "--install", str(root)]]


def test_prepare_app_server_runtime_reports_installer_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "install"
    installer = root / ".pi/packages/tspi/current/agent/scripts/prepare_pi_source.py"
    installer.parent.mkdir(parents=True)
    installer.write_text("# fixture\n", encoding="utf-8")
    monkeypatch.setattr(
        wizard.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, stdout="", stderr="npm failed"),
    )
    with pytest.raises(RuntimeError, match="npm failed"):
        wizard.prepare_app_server_runtime(root)


def test_configure_services_installs_and_starts_host_and_web(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _options(tmp_path)
    unit_dir = tmp_path / "units"
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(wizard, "_service_unit_directory", lambda _scope: unit_dir)
    monkeypatch.setattr(wizard, "verify_service_units", lambda *_args: None)
    monkeypatch.setattr(wizard, "app_server_service_instances", lambda _scope: [])
    monkeypatch.setattr(wizard, "_run_systemctl", lambda _scope, *values: calls.append(values))
    monkeypatch.setattr(
        wizard,
        "_service_status",
        lambda _scope, scope, name: {"name": name, "scope": scope, "enabled": "enabled", "active": "active"},
    )

    services = wizard.configure_services(args)

    assert (unit_dir / "ts-app-server-tspi.service").is_file()
    assert (unit_dir / "ts-web-tspi.service").is_file()
    assert calls == [
        ("daemon-reload",),
        ("enable", "ts-app-server-tspi.service"),
        ("enable", "ts-web-tspi.service"),
        ("restart", "ts-app-server-tspi.service"),
        ("restart", "ts-web-tspi.service"),
    ]
    assert services[0]["name"] == "ts-app-server-tspi.service"
    assert services[0]["active"] == "active"


def test_configure_services_stops_concrete_legacy_app_server_instances(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _options(tmp_path)
    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    (unit_dir / "ts-app-server-tspi@.service").write_text(
        f"[Service]\nWorkingDirectory={args.install_root}\n",
        encoding="utf-8",
    )
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(wizard, "_service_unit_directory", lambda _scope: unit_dir)
    monkeypatch.setattr(wizard, "verify_service_units", lambda *_args: None)
    monkeypatch.setattr(wizard, "app_server_service_instances", lambda _scope: [
        "ts-app-server-tspi@reaction-a.service",
        "ts-app-server-tspi@reaction-b.service",
    ])
    monkeypatch.setattr(wizard, "_run_systemctl", lambda _scope, *values: calls.append(values))
    monkeypatch.setattr(
        wizard,
        "_service_status",
        lambda _scope, scope, name: {"name": name, "scope": scope, "enabled": "disabled", "active": "inactive"},
    )

    wizard.configure_services(args)

    assert not (unit_dir / "ts-app-server-tspi@.service").exists()
    assert ("disable", "--now", "ts-app-server-tspi@reaction-a.service") in calls
    assert ("disable", "--now", "ts-app-server-tspi@reaction-b.service") in calls


def test_configure_services_removes_owned_web_unit_when_web_is_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = wizard.parse_args([
        "--install-root", str(tmp_path / "install"),
        "--without-web",
        "--service-scope", "user",
        "--non-interactive",
    ])
    wizard.validate_options(args)
    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    (unit_dir / "ts-web-tspi.service").write_text(
        f"[Service]\nWorkingDirectory={args.install_root}\n",
        encoding="utf-8",
    )
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(wizard, "_service_unit_directory", lambda _scope: unit_dir)
    monkeypatch.setattr(wizard, "verify_service_units", lambda *_args: None)
    monkeypatch.setattr(wizard, "_run_systemctl", lambda _scope, *values: calls.append(values))
    monkeypatch.setattr(
        wizard,
        "_service_status",
        lambda _scope, scope, name: {"name": name, "scope": scope, "enabled": "disabled", "active": "inactive"},
    )

    wizard.configure_services(args)

    assert not (unit_dir / "ts-web-tspi.service").exists()
    assert ("stop", "ts-web-tspi.service") in calls
    assert ("disable", "ts-web-tspi.service") in calls


def test_service_ownership_rejects_a_different_installation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _options(tmp_path)
    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    (unit_dir / "ts-app-server-tspi.service").write_text(
        "[Service]\nWorkingDirectory=/another/install\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(wizard, "_service_unit_directory", lambda _scope: unit_dir)
    with pytest.raises(ValueError, match="belongs to another installation"):
        wizard.validate_service_ownership(args)


def test_component_summary_exposes_app_server_and_phone_connection(tmp_path: Path) -> None:
    args = _options(tmp_path)
    runtime = tmp_path / "install/.pi/runtime-cache/pi/commit"
    components = wizard.build_component_summary(
        args,
        {"runtime": {"env_prefix": "/runtime", "runtime_probe": {"modules": {}, "commands": {}}}},
        runtime,
        [{"name": "ts-app-server-tspi.service", "scope": "user", "enabled": "enabled", "active": "active"}],
        {"web_http": {"path": "/token", "status": "created", "mode": "0600"}},
    )
    assert components["app_server"]["runtime"] == str(runtime)
    assert components["app_server"]["server_id"].endswith("/.pi/app-server-host/server-id")
    assert components["app_server"]["start"] == "systemctl --user start ts-app-server-tspi.service"
    assert components["phone"]["tool_access"] == "same_as_terminal"
    assert components["phone"]["protocol_version"] == 8


def test_custom_workspace_root_flows_into_host_and_web_services(tmp_path: Path) -> None:
    workspace_root = tmp_path / "research"
    args = wizard.parse_args([
        "--install-root", str(tmp_path / "install"),
        "--workspace-root", str(workspace_root),
        "--with-web",
        "--service-scope", "user",
        "--non-interactive",
    ])
    wizard.validate_options(args)

    assert args.workspace_root == str(workspace_root)
    assert f'ReadWritePaths="{workspace_root}"' in wizard.app_server_unit(args)
    web_unit = wizard.web_unit(args)
    assert '"--workspace-root"' in web_unit
    assert f'"{workspace_root}"' in web_unit
    assert f'ReadOnlyPaths="{workspace_root}"' in web_unit


def test_workspace_root_rejects_an_installation_ancestor(tmp_path: Path) -> None:
    args = wizard.parse_args([
        "--install-root", str(tmp_path / "install"),
        "--workspace-root", str(tmp_path),
        "--without-web", "--service-scope", "none", "--non-interactive",
    ])

    with pytest.raises(ValueError, match="dedicated directory"):
        wizard.validate_options(args)


def test_phone_manifest_is_secret_free_and_keeps_terminal_tool_access(tmp_path: Path) -> None:
    args = _options(tmp_path)
    root = Path(args.install_root)
    (root / ".pi/tspi").mkdir(parents=True)
    wizard.configure_workspace_root(args)
    args.radius_gateway = "wss://radius.example.test"

    result = wizard.configure_phone_connection(args)

    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["radius_gateway"] == "wss://radius.example.test"
    assert manifest["tool_access"] == "same_as_terminal"
    assert manifest["protocol_version"] == 8
    assert manifest["workspace_service"] == {
        "service_id": "tspi.workspace-directory",
        "members": ["list", "create"],
    }
    assert manifest["session_service"]["workspace_binding"] == "workspaceId"
    assert "token" not in manifest
    assert "secret" not in manifest


def test_custom_smtp_provider_writes_explicit_host(tmp_path: Path) -> None:
    password_file = tmp_path / "smtp-password"
    password_file.write_text("authorization-code\n", encoding="utf-8")
    password_file.chmod(0o600)
    args = wizard.parse_args([
        "--install-root", str(tmp_path / "install"),
        "--without-web", "--service-scope", "none", "--non-interactive",
        "--email-provider", "smtp", "--email-preset", "custom",
        "--email-host", "mail.example.test", "--email-port", "587",
        "--email-security", "starttls", "--email-recipient", "receiver@example.org",
        "--email-username", "sender@example.org", "--email-password-file", str(password_file),
    ])
    wizard.validate_options(args)

    wizard.configure_notification_config(args)

    content = (Path(args.install_root) / ".pi/notifications.toml").read_text(encoding="utf-8")
    assert 'preset = "custom"' in content
    assert 'host = "mail.example.test"' in content


def test_remote_probe_records_readiness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    args = _options(tmp_path)
    args.probe_remote = True
    configs = {"remote": {"status": "configured", "path": "/remote.toml", "doctor": "not_probed"}}
    monkeypatch.setattr(
        wizard.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout="ready\n", stderr=""),
    )

    wizard.probe_remote_backend(args, configs)

    assert configs["remote"]["doctor"] == "ready"


def test_install_log_is_date_named_and_appends_same_day_runs(tmp_path: Path) -> None:
    root = tmp_path / "install"
    path = wizard.append_install_log(root, "first-run", "status=success")
    same = wizard.append_install_log(root, "second-run", "status=failure")

    assert same == path
    assert path.name == f"install.{wizard.datetime.now().strftime('%Y.%m.%d')}.log"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    content = path.read_text(encoding="utf-8")
    assert "first-run" in content
    assert "===== install run " in content
    assert "second-run" in content


def test_logged_package_step_is_kept_in_date_named_log(tmp_path: Path) -> None:
    root = tmp_path / "install"
    result = wizard.run_logged_install(
        [wizard.sys.executable, "-c", "import json; print(json.dumps({'ok': True}))"],
        root,
        show_progress=False,
    )

    assert result == {"ok": True}
    log = root / ".pi" / "logs" / f"install.{wizard.datetime.now().strftime('%Y.%m.%d')}.log"
    assert log.is_file()
    assert '"ok": true' in log.read_text(encoding="utf-8")


def test_interactive_remote_toml_is_validated_and_written_private(tmp_path: Path) -> None:
    root = tmp_path / "install"
    ssh_config = tmp_path / "ssh-config"
    ssh_config.write_text("Host cluster\n", encoding="utf-8")
    ssh_config.chmod(0o600)
    args = wizard.parse_args([
        "--install-root", str(root), "--without-web", "--service-scope", "none", "--non-interactive",
    ])
    args._remote_config_content = "\n".join([
        'default_profile = "cluster"',
        '[profiles."cluster"]',
        'ssh_host = "cluster"',
        f'ssh_config = "{ssh_config}"',
        'scheduler = "torque"',
        'remote_root = "/srv/tspi"',
        'allowed_queues = ["batch"]',
        '',
    ])
    wizard.validate_options(args)
    configs = wizard.configure_backend_configs(args)

    destination = root / ".pi" / "remote.toml"
    assert configs["remote"]["source"] == "interactive"
    assert destination.read_text(encoding="utf-8") == args._remote_config_content
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_install_uninstaller_copies_recovery_files_and_marks_ownership(tmp_path: Path) -> None:
    root = tmp_path / "install"
    uninstaller = install_uninstaller(root, ROOT)
    assert uninstaller == root / "uninstall.sh"
    assert uninstaller.is_file()
    assert (root / ".pi/tspi/uninstall.py").is_file()
    marker = json.loads((root / ".pi/tspi/installation.json").read_text(encoding="utf-8"))
    assert marker["schema_version"] == "tspi-installation-root/1"
