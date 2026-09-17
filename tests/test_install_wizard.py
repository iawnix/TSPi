from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

from scripts import install_wizard as wizard
from scripts.install_from_github import install_uninstaller


ROOT = Path(__file__).resolve().parents[1]


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
    assert args.web_port == 8766
    assert not hasattr(args, "with_phone")


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
        "--email-username", "sender@qq.com",
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
    clawemail.mkdir()
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
    assert f'ExecStart="{root / "TSPi"}" --host' in unit
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


def test_component_summary_exposes_app_server_and_no_phone(tmp_path: Path) -> None:
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
    assert components["app_server"]["start"].endswith("/TSPi --host")
    assert "phone" not in components


def test_install_uninstaller_copies_recovery_files_and_marks_ownership(tmp_path: Path) -> None:
    root = tmp_path / "install"
    uninstaller = install_uninstaller(root, ROOT)
    assert uninstaller == root / "uninstall.sh"
    assert uninstaller.is_file()
    assert (root / ".pi/tspi/uninstall.py").is_file()
    marker = json.loads((root / ".pi/tspi/installation.json").read_text(encoding="utf-8"))
    assert marker["schema_version"] == "tspi-installation-root/1"
