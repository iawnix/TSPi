from __future__ import annotations

import json
import io
import stat
import subprocess
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from scripts import install_wizard as wizard
from scripts import _terminal_ui as terminal_ui
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
    values = iter(("short", "a" * 8))
    monkeypatch.setattr(wizard.getpass, "getpass", lambda _prompt: next(values))

    assert wizard._ask_web_auth_token() == "a" * 8


def test_interactive_web_token_blank_uses_generated_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wizard.getpass, "getpass", lambda _prompt: "   ")

    assert wizard._ask_web_auth_token() is None


def test_secret_input_shows_stars_without_echoing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeInput(io.StringIO):
        def isatty(self) -> bool:
            return True

        def fileno(self) -> int:
            return 0

    class FakeOutput(io.StringIO):
        def isatty(self) -> bool:
            return True

    fake_input = FakeInput("ab\x7fc\n")
    fake_output = FakeOutput()
    fake_termios = type(
        "FakeTermios",
        (),
        {"TCSADRAIN": 0, "tcgetattr": staticmethod(lambda _fd: object()), "tcsetattr": staticmethod(lambda *_args: None)},
    )
    fake_tty = type("FakeTTY", (), {"setcbreak": staticmethod(lambda _fd: None)})
    monkeypatch.setattr(terminal_ui.sys, "stdin", fake_input)
    monkeypatch.setattr(terminal_ui.sys, "stdout", fake_output)
    monkeypatch.setattr(terminal_ui, "termios", fake_termios)
    monkeypatch.setattr(terminal_ui, "tty", fake_tty)

    assert terminal_ui.ask_secret("Secret") == "ac"
    rendered = fake_output.getvalue()
    assert rendered.count("*") == 3
    assert "abc" not in rendered


def test_interactive_menu_can_edit_multiple_sections_before_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "install"
    workspace = tmp_path / "research"
    args = wizard.parse_args(["--install-root", str(root)])
    choices = iter(("1", str(workspace), "2", "8777", "127.0.0.1", "8"))
    monkeypatch.setattr(wizard.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(wizard.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(wizard, "ask", lambda _prompt, default="": next(choices))
    monkeypatch.setattr(wizard, "ask_yes_no", lambda _prompt, default=True: default)

    wizard.interactive_menu_options(args)

    assert args.workspace_root == str(workspace)
    assert args.with_web is True
    assert args.web_port == 8777
    assert args.web_host == "127.0.0.1"


def test_menu_defaults_read_existing_configuration(tmp_path: Path) -> None:
    root = tmp_path / "install"
    workspace = tmp_path / "research"
    marker = root / ".pi/tspi/model-icons.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"enabled": True}), encoding="utf-8")
    (root / ".pi/tspi/workspace-root.json").write_text(
        json.dumps({"schema_version": "tspi-workspace-root/1", "workspace_root": str(workspace)}),
        encoding="utf-8",
    )
    (root / "TSWeb").write_text("launcher", encoding="utf-8")
    args = wizard.parse_args(["--install-root", str(root)])

    wizard._load_existing_menu_defaults(args)

    assert args.workspace_root == str(workspace)
    assert args.with_web is True
    assert args.with_model_icons is True


def test_interactive_menu_can_disable_existing_email_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "install"
    config = root / ".pi/notifications.toml"
    config.parent.mkdir(parents=True)
    config.write_text("[notifications.email]\nenabled = true\n", encoding="utf-8")
    args = wizard.parse_args(["--install-root", str(root)])
    args.email_binding = "smtp"
    args.email_recipient = "receiver@example.org"
    args.email_preset = "qq"
    args.email_username = "sender@qq.com"
    args.email_port = 465
    args.email_security = "ssl"
    answers = iter((False, True))
    monkeypatch.setattr(wizard, "ask_yes_no", lambda _prompt, _default=False: next(answers))

    wizard.configure_email_interactively(args, force=True)

    assert args.email_binding is None
    assert args.email_recipient is None
    assert wizard.configure_notification_config(args)["status"] == "disabled"
    assert not config.exists()


def test_interactive_compute_backends_accepts_one_file_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = wizard.parse_args([
        "--install-root", str(tmp_path / "install"),
        "--without-web", "--service-scope", "none", "--email-binding", "smtp",
    ])
    args.workspace_root = str(tmp_path / "workspaces")
    args.phone_access = "disabled"
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


def test_interactive_smtp_uses_sender_as_from_without_a_redundant_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = wizard.parse_args([
        "--install-root", str(tmp_path / "install"),
        "--without-web", "--service-scope", "none", "--non-interactive",
    ])
    prompts: list[str] = []
    values = {
        "Email binding (smtp or clawemail)": "smtp",
        "Notification recipient": "receiver@example.org",
        "SMTP mailbox preset (163, qq, or custom)": "qq",
        "SMTP port": "465",
        "SMTP security (ssl or starttls)": "ssl",
        "SMTP sender email address": "sender@qq.com",
    }

    def fake_ask(prompt: str, default: str = "") -> str:
        prompts.append(prompt)
        return values.get(prompt, default)

    monkeypatch.setattr(wizard, "ask", fake_ask)
    monkeypatch.setattr(wizard, "ask_yes_no", lambda prompt, default=False: prompt == "Configure email notifications")
    monkeypatch.setattr(wizard.getpass, "getpass", lambda _prompt: "authorization-code")

    wizard.configure_email_interactively(args)

    assert args.email_username == "sender@qq.com"
    assert not hasattr(args, "email_from")
    assert not any("From email" in prompt for prompt in prompts)


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


def test_bundled_model_icon_font_avoids_the_nerd_font_private_use_range() -> None:
    with TTFont(ROOT / "assets/fonts/tspi-model-icons.ttf") as font:
        codepoints = set(font.getBestCmap() or {})
        revision = font["head"].fontRevision

    assert codepoints == set(range(0xF0000, 0xF0005))
    assert not codepoints.intersection(range(0xE000, 0xF900))
    assert revision == 2.0


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


def test_update_preserves_workspace_root_and_link_defaults(tmp_path: Path) -> None:
    root = tmp_path / "install"
    workspace_root = tmp_path / "research"
    workspace_config = root / ".pi/tspi/workspace-root.json"
    workspace_config.parent.mkdir(parents=True)
    workspace_config.write_text(json.dumps({
        "schema_version": "tspi-workspace-root/1",
        "workspace_root": str(workspace_root),
    }), encoding="utf-8")
    phone = root / ".pi/app-server-host/link.json"
    phone.parent.mkdir(parents=True)
    phone.write_text(json.dumps({
        "schema_version": "tspi-link/1",
        "protocol": "tspi-link.v1",
        "relay_url": "https://relay.example.test",
        "host_id": "123e4567-e89b-42d3-a456-426614174000",
    }), encoding="utf-8")
    (phone.parent / "host.token").write_text("tsph_" + "a" * 43, encoding="utf-8")
    args = wizard.parse_args([
        "--install-root", str(root), "--without-web", "--service-scope", "none", "--non-interactive",
    ])

    wizard.validate_options(args)

    assert args.workspace_root == str(workspace_root)
    assert args.phone_access == "link"
    assert args.link_url == "https://relay.example.test"


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
    phone = root / ".pi/app-server-host/link.json"
    phone.parent.mkdir(parents=True)
    phone.write_text("old-phone\n", encoding="utf-8")
    release = root / ".pi/packages/tspi/releases/old"
    release.mkdir(parents=True)
    snapshot = wizard.snapshot_install_configuration(root, args)

    phone.write_text("new-phone\n", encoding="utf-8")
    (root / ".pi/compute.toml").parent.mkdir(parents=True, exist_ok=True)
    (root / ".pi/compute.toml").write_text("new\n", encoding="utf-8")
    new_release = root / ".pi/packages/tspi/releases/new"
    nested = new_release / "nested"
    nested.mkdir(parents=True)
    payload = nested / "payload"
    payload.write_text("generated\n", encoding="utf-8")
    payload.chmod(0o400)
    nested.chmod(0o300)
    new_release.chmod(0o300)

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
        "--email-binding", "smtp",
        "--email-preset", "qq",
        "--email-recipient", "receiver@example.org",
        "--email-address", "sender@qq.com",
        "--email-password-file", str(password_file),
    ])
    wizard.validate_options(args)

    result = wizard.configure_notification_config(args)

    config = root / ".pi/notifications.toml"
    assert result["binding"] == "smtp"
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert stat.S_IMODE(password_file.stat().st_mode) == 0o600
    content = config.read_text(encoding="utf-8")
    assert 'provider = "smtp"' in content
    assert "binding =" not in content
    assert 'preset = "qq"' in content
    assert f'password_file = "{password_file}"' in content
    assert "from_address" not in content
    assert "qq-authorization-code" not in content


def test_interactive_smtp_password_is_written_to_the_default_private_file(tmp_path: Path) -> None:
    root = tmp_path / "install"
    password_file = root / ".pi/email/smtp-password"
    args = wizard.parse_args([
        "--install-root", str(root),
        "--without-web",
        "--service-scope", "none",
        "--non-interactive",
        "--email-binding", "smtp",
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
        "--email-binding", "clawemail",
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
    assert '"--provider"' in unit
    assert '"--binding"' not in unit
    assert str(root / "workspaces") in unit
    assert str(root / ".pi/ts-web/auth.token") in unit
    assert f'ReadOnlyPaths="{root / "workspaces"}"' in unit
    assert f'ReadWritePaths="{root / "workspaces"}"' not in unit


def test_service_readiness_treats_restart_loop_as_failed() -> None:
    assert wizard._service_readiness({"active": "activating"}, probed=True) == "failed"


def test_service_runtime_configuration_records_scope_and_socket_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _options(tmp_path)
    runtime_parent = tmp_path / "xdg-runtime"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_parent))

    configured = wizard.configure_service_runtime(args)

    assert configured["scope"] == "user"
    document = json.loads((Path(args.install_root) / ".pi/tspi/service.json").read_text(encoding="utf-8"))
    assert document["schema_version"] == "tspi-service/1"
    assert document["scope"] == "user"
    assert document["runtime_dir"] == str(runtime_parent / "tspi")


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
    assert components["phone"]["protocol"] == "tspi-link.v1"


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


def test_link_manifest_is_secret_free_and_host_token_is_private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    args = _options(tmp_path)
    root = Path(args.install_root)
    (root / ".pi/tspi").mkdir(parents=True)
    wizard.configure_workspace_root(args)
    args.phone_access = "link"
    args.link_url = "https://relay.example.test"
    args.link_enrollment_code = "ABCD-EFGH-IJKL"
    host_id = wizard.ensure_host_identity(root).read_text(encoding="ascii").strip()
    monkeypatch.setattr(wizard, "_redeem_link_enrollment", lambda *_args: {
        "hostId": host_id,
        "protocol": "tspi-link.v1",
        "hostToken": "tsph_" + "a" * 43,
    })

    result = wizard.configure_phone_connection(args)

    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["relay_url"] == "https://relay.example.test"
    assert manifest["protocol"] == "tspi-link.v1"
    assert result["tool_access"] == "same_as_terminal"
    assert "token" not in manifest
    assert "secret" not in manifest
    token_file = root / ".pi/app-server-host/host.token"
    assert token_file.read_text(encoding="utf-8").strip().startswith("tsph_")
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600


def test_changing_relay_requires_a_new_host_enrollment(tmp_path: Path) -> None:
    args = _options(tmp_path)
    root = Path(args.install_root)
    state = root / ".pi/app-server-host"
    state.mkdir(parents=True)
    (state / "link.json").write_text(json.dumps({
        "schema_version": "tspi-link/1",
        "protocol": "tspi-link.v1",
        "relay_url": "https://old-relay.example.test",
        "host_id": "123e4567-e89b-42d3-a456-426614174000",
    }), encoding="utf-8")
    (state / "host.token").write_text("tsph_" + "a" * 43, encoding="ascii")
    args.phone_access = "link"
    args.link_url = "https://new-relay.example.test"
    args.link_enrollment_code = None

    with pytest.raises(RuntimeError, match="enrollment code is required"):
        wizard.configure_phone_connection(args)


@pytest.mark.parametrize("relay_url", ["https://", "https://relay.example.test:invalid"])
def test_link_url_must_be_a_valid_origin(relay_url: str) -> None:
    with pytest.raises(ValueError, match="link-url"):
        wizard._validate_link_url(relay_url)


def test_custom_smtp_provider_writes_explicit_host(tmp_path: Path) -> None:
    password_file = tmp_path / "smtp-password"
    password_file.write_text("authorization-code\n", encoding="utf-8")
    password_file.chmod(0o600)
    args = wizard.parse_args([
        "--install-root", str(tmp_path / "install"),
        "--without-web", "--service-scope", "none", "--non-interactive",
        "--email-binding", "smtp", "--email-preset", "custom",
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
    source = tmp_path / "compute.toml"
    source.write_text(
        """default_environment = \"local\"\n\n[environments.local]\nkind = \"local\"\n""",
        encoding="utf-8",
    )
    args.compute_config = str(source)
    configs = wizard.configure_backend_configs(args)
    monkeypatch.setattr(
        wizard.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, stdout="", stderr="doctor unavailable\n"),
    )

    with pytest.raises(RuntimeError, match="remote environment readiness check failed"):
        wizard.probe_remote_backend(args, configs)


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


def test_compute_toml_is_validated_and_written_private(tmp_path: Path) -> None:
    root = tmp_path / "install"
    ssh_config = tmp_path / "ssh-config"
    ssh_config.write_text("Host cluster\n", encoding="utf-8")
    ssh_config.chmod(0o600)
    args = wizard.parse_args([
        "--install-root", str(root), "--without-web", "--service-scope", "none", "--non-interactive",
    ])
    source = tmp_path / "compute.toml"
    source.write_text("\n".join([
        'default_environment = "local"',
        '[environments."local"]',
        'kind = "local"',
        '',
        '[environments."cluster"]',
        'kind = "remote"',
        'ssh_host = "cluster"',
        f'ssh_config = "{ssh_config}"',
        'scheduler = "torque"',
        'remote_root = "/srv/tspi"',
        'allowed_queues = ["batch"]',
        '',
    ]) + "\n", encoding="utf-8")
    args.compute_config = str(source)
    wizard.validate_options(args)
    configs = wizard.configure_backend_configs(args)

    destination = root / ".pi" / "compute.toml"
    assert configs["compute"]["status"] == "configured"
    assert destination.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_install_uninstaller_copies_recovery_files_and_marks_ownership(tmp_path: Path) -> None:
    root = tmp_path / "install"
    uninstaller = install_uninstaller(root, ROOT)
    assert uninstaller == root / "uninstall.sh"
    assert uninstaller.is_file()
    assert (root / ".pi/tspi/uninstall.py").is_file()
    marker = json.loads((root / ".pi/tspi/installation.json").read_text(encoding="utf-8"))
    assert marker["schema_version"] == "tspi-installation-root/1"
