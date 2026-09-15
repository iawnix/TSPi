from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import install_wizard as wizard
from scripts import install_from_github as source_installer
from scripts._credentials import provision_service_credentials
from scripts.install_wizard import configure_phone, parse_args, phone_unit, validate_options
from scripts.install_from_github import install_uninstaller


ROOT = Path(__file__).resolve().parents[1]


def _options(tmp_path: Path):
    args = parse_args(["--install-root", str(tmp_path / "install"), "--with-phone", "--with-web",
                       "--service-scope", "user", "--enable-services", "--start-services",
                       "--non-interactive", "--yes"])
    validate_options(args)
    return args


def test_phone_configuration_is_private_and_bound_to_installation(tmp_path: Path) -> None:
    args = _options(tmp_path)
    validate_options(args)

    config = configure_phone(args)
    assert config is not None and config.stat().st_mode & 0o077 == 0
    content = config.read_text(encoding="utf-8")
    assert f'TS_PHONE_TSPI="{tmp_path / "install" / "TSPi"}"' in content
    assert f'TS_PHONE_WORKSPACES="{tmp_path / "install" / "workspaces"}"' in content
    config.write_text('TS_PHONE_PORT=23000\nCUSTOM_SETTING=preserved\n', encoding="utf-8")
    configure_phone(args)
    assert config.read_text(encoding="utf-8") == 'TS_PHONE_PORT=23000\nCUSTOM_SETTING=preserved\n'


@pytest.mark.parametrize("linked_release", [False, True])
def test_phone_unit_uses_installed_launcher_and_toolchain_path(tmp_path: Path, monkeypatch, linked_release) -> None:
    args = _options(tmp_path)
    root = Path(args.install_root)
    package_home = root / ".pi/packages/tspi"
    release = package_home / "releases/test" if linked_release else package_home / "current"
    shutil.copytree(ROOT / "apps/host", release / "agent/apps/host")
    if linked_release:
        (package_home / "current").symlink_to("releases/test", target_is_directory=True)
    for key in tuple(wizard.os.environ):
        if key.startswith("TS_PHONE_"):
            monkeypatch.delenv(key)
    configure_phone(args)
    unit = phone_unit(args)
    assert f"WorkingDirectory={root}" in unit
    assert f'ExecStart="{root / "TSPhoneServer"}"' in unit
    assert 'Environment="PATH=' in unit
    assert "ProtectHome=read-only" in unit


def test_phone_unit_requires_renderer_output(tmp_path: Path, monkeypatch) -> None:
    args = _options(tmp_path)
    monkeypatch.setattr(wizard.subprocess, "run", lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 0, "", ""))
    with pytest.raises(RuntimeError, match="did not produce a service unit"):
        phone_unit(args)


def test_web_unit_command_is_accepted_by_web_cli(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "components/ts-web"))
    monkeypatch.delenv("TSPI_WEB_AUTH_TOKEN", raising=False)
    from ts_web import cli

    args = _options(tmp_path)
    Path(args.install_root).mkdir(mode=0o700)
    credentials = provision_service_credentials(Path(args.install_root), with_phone=False, with_web=True)
    unit = wizard.web_unit(args)
    assert f"WorkingDirectory={Path(args.install_root)}" in unit
    assert f'WorkingDirectory="{Path(args.install_root)}"' not in unit
    command = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
    arguments = shlex.split(command.removeprefix("ExecStart="))
    calls = []
    monkeypatch.setattr(cli, "serve", lambda *args, **kwargs: calls.append((args, kwargs)))
    assert cli.main(arguments[1:]) == 0
    assert len(calls) == 1
    positional, keywords = calls[0]
    assert positional == ("127.0.0.1", 8766, str(Path(args.install_root) / ".pi/ts-web-state"))
    assert keywords["provider_command"] == str(Path(args.install_root) / ".pi/packages/tspi/current/agent/scripts/ts_web_provider.py")
    assert keywords["workspace_roots"] == [str(Path(args.install_root) / "workspaces")]
    assert keywords["auth_token"] == Path(credentials["web_http"]["path"]).read_text().strip()
    assert "--auth-token " not in command
    assert f'"--auth-token-file" "{credentials["web_http"]["path"]}"' in command


@pytest.mark.parametrize("unsafe_kind", ["mode", "symlink", "hardlink", "malformed"])
def test_web_cli_rejects_unsafe_token_files(tmp_path: Path, monkeypatch, unsafe_kind: str) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "components/ts-web"))
    monkeypatch.delenv("TSPI_WEB_AUTH_TOKEN", raising=False)
    from ts_web import cli

    token = tmp_path / "auth.token"
    token.write_text("a" * 43 + "\n", encoding="ascii")
    token.chmod(0o600)
    if unsafe_kind == "mode":
        token.chmod(0o644)
        match = "mode 0600"
    elif unsafe_kind == "symlink":
        original = tmp_path / "original.token"
        token.rename(original)
        token.symlink_to(original)
        match = "symbolic link"
    elif unsafe_kind == "hardlink":
        (tmp_path / "duplicate.token").hardlink_to(token)
        match = "without hard links"
    else:
        token.write_text("invalid\n", encoding="ascii")
        match = "invalid token"

    with pytest.raises(SystemExit, match=match):
        cli.main(["--provider", "/provider", "serve", "--state-dir", str(tmp_path / "state"),
                  "--auth-token-file", str(token)])


def test_phone_configuration_supports_unicode_and_spaces(tmp_path: Path) -> None:
    args = _options(tmp_path / "研究 projects")
    validate_options(args)
    config = configure_phone(args)
    result = subprocess.run(["node", "--input-type=module", "-e",
        'import {parseEnv} from "node:util"; import {readFileSync} from "node:fs"; '
        'console.log(JSON.stringify(parseEnv(readFileSync(process.argv[1],"utf8"))));', str(config)],
        check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)["TS_PHONE_TSPI"] == str(Path(args.install_root) / "TSPi")


def test_service_install_keeps_another_installations_unit(tmp_path: Path, monkeypatch) -> None:
    args = _options(tmp_path)
    unit_dir = tmp_path / "owner/.config/systemd/user"
    unit_dir.mkdir(parents=True)
    unit = unit_dir / "ts-phone-tspi.service"
    content = f"[Service]\nWorkingDirectory={tmp_path / 'other'}\n"
    unit.write_text(content)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "owner")
    monkeypatch.setattr(wizard, "phone_unit", lambda _: "[Service]\n")
    monkeypatch.setattr(wizard.subprocess, "run", lambda *args, **kwargs: pytest.fail("service should not be touched"))
    with pytest.raises(ValueError, match="another installation"):
        wizard.configure_services(args, Path(args.install_root) / ".pi/ts-phone/server.env")
    assert unit.read_text() == content


def test_service_conflict_is_detected_before_installation_mutates_the_root(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "install"
    owner = tmp_path / "owner"
    unit_dir = owner / ".config/systemd/user"
    unit_dir.mkdir(parents=True)
    unit = unit_dir / "ts-phone-tspi.service"
    unit.write_text(f"[Service]\nWorkingDirectory={tmp_path / 'other'}\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: owner)
    monkeypatch.setattr(wizard, "prepare_phone", lambda *args, **kwargs: pytest.fail("Phone build must not start"))
    monkeypatch.setattr(wizard, "run_install", lambda *args, **kwargs: pytest.fail("Package install must not start"))

    result = wizard.main([
        "--install-root", str(root), "--with-phone", "--without-web",
        "--service-scope", "user", "--non-interactive", "--yes", "--json",
    ])

    assert result == 1
    assert not root.exists()
    assert "belongs to another installation" in capsys.readouterr().err


def test_interactive_phone_selection_and_web_skip(tmp_path: Path, monkeypatch) -> None:
    args = parse_args(["--install-root", str(tmp_path / "install"), "--service-scope", "none"])
    monkeypatch.setattr(wizard.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(wizard.sys.stdout, "isatty", lambda: True)
    replies = iter(["main", "n", "y", "main", "23000", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(replies))
    wizard.interactive_options(args)
    validate_options(args)
    assert args.with_phone is True
    assert args.phone_port == 23000
    assert args.with_web is False


def test_install_passes_prepared_phone_for_compatibility_check(tmp_path: Path, monkeypatch) -> None:
    args = _options(tmp_path)
    release = tmp_path / "phone-release"
    commands = []

    def run(command, install_root, **kwargs):
        commands.append(command)
        return {"release_id": "test"}

    monkeypatch.setattr(wizard, "run_logged_install", run)
    wizard.run_install(args, release)
    assert commands[0][-2:] == ["--phone-server-root", str(release)]


def test_without_phone_does_not_fetch_or_configure_phone(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(wizard, "prepare_phone", lambda *args: pytest.fail("Phone was not selected"))
    monkeypatch.setattr(
        wizard,
        "run_install",
        lambda args, *_: Path(args.install_root).mkdir(mode=0o700, parents=True, exist_ok=True)
        or {"release_id": "test"},
    )
    monkeypatch.setattr(wizard, "inspect_installation", lambda *args: {"operation": "install", "release_id": "test"})
    assert wizard.main(["--install-root", str(tmp_path / "install"), "--without-phone",
                        "--non-interactive", "--yes"]) == 0
    assert not (tmp_path / "install/.pi/ts-phone/server.env").exists()
    assert (tmp_path / "install/.pi/ts-web/auth.token").is_file()


def test_wizard_installs_phone_before_service_configuration(tmp_path: Path, monkeypatch, capsys) -> None:
    events = []
    release = tmp_path / "phone-release"
    real_install_uninstaller = wizard.install_uninstaller

    def install_recovery(root, source):
        events.append("recovery")
        return real_install_uninstaller(root, source)

    def prepare(*args, **kwargs):
        root = Path(args[0])
        assert (root / "uninstall.sh").is_file()
        assert (root / ".pi/tspi/installation.json").is_file()
        events.append("build")
        return release

    monkeypatch.setattr(wizard, "install_uninstaller", install_recovery)
    monkeypatch.setattr(wizard, "prepare_phone", prepare)
    def run_install(args, phone):
        events.append(("install", phone))
        Path(args.install_root).mkdir(mode=0o700, parents=True, exist_ok=True)
        return {"release_id": "test"}

    monkeypatch.setattr(wizard, "run_install", run_install)
    monkeypatch.setattr(wizard, "activate_phone", lambda *args: events.append("activate") or {"commit": "a" * 40})
    monkeypatch.setattr(wizard, "configure_services", lambda *args: events.append("services") or [])
    monkeypatch.setattr(wizard, "inspect_installation", lambda *args: {"operation": "install", "release_id": "test"})
    assert wizard.main(["--install-root", str(tmp_path / "install"), "--with-phone",
                        "--non-interactive", "--yes", "--json"]) == 0
    assert events == ["recovery", "build", ("install", release), "activate", "services"]
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["components"]["phone"]["commit"] == "a" * 40
    assert set(result["credentials"]) == {"phone_http", "phone_bridge", "web_http"}
    secret_values = [Path(item["path"]).read_text().strip() for item in result["credentials"].values()]
    assert all(secret not in captured.out and secret not in captured.err for secret in secret_values)


@pytest.mark.parametrize("arguments", [["--phone-port", "65536"], ["--phone-repo", "https://example.com/phone"], ["--phone-ref", "../escape"]])
def test_phone_options_reject_invalid_configuration_before_install(tmp_path: Path, arguments) -> None:
    args = parse_args(["--install-root", str(tmp_path / "install"), "--with-phone", *arguments])
    with pytest.raises(ValueError):
        validate_options(args)
    assert not (tmp_path / "install").exists()


def test_web_is_the_noninteractive_default_unless_explicitly_disabled(tmp_path: Path) -> None:
    selected = parse_args(["--install-root", str(tmp_path / "selected"), "--non-interactive", "--yes"])
    validate_options(selected)
    assert selected.with_web is True

    skipped = parse_args(["--install-root", str(tmp_path / "skipped"), "--without-web",
                          "--non-interactive", "--yes"])
    validate_options(skipped)
    assert skipped.with_web is False


def test_render_is_required_and_no_longer_has_an_installer_flag(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        parse_args(["--install-root", str(tmp_path / "install"), "--with-render"])


@pytest.mark.parametrize("port", [0, 65536])
def test_web_rejects_invalid_port(tmp_path: Path, port: int) -> None:
    args = parse_args(["--install-root", str(tmp_path / "install"), "--with-web", "--web-port", str(port)])
    with pytest.raises(ValueError, match="--web-port"):
        validate_options(args)


@pytest.mark.parametrize(
    ("component_flag", "port_flag"),
    [
        ("--without-web", "--web-port"),
        ("--without-phone", "--phone-port"),
    ],
)
def test_unselected_component_rejects_its_port(
    tmp_path: Path,
    component_flag: str,
    port_flag: str,
) -> None:
    args = parse_args(
        [
            "--install-root",
            str(tmp_path / "install"),
            component_flag,
            port_flag,
            "23000",
        ]
    )

    with pytest.raises(ValueError, match=f"{port_flag} requires"):
        validate_options(args)


def test_existing_phone_port_is_preserved_in_the_plan(tmp_path: Path) -> None:
    root = tmp_path / "install"
    config = root / ".pi/ts-phone/server.env"
    config.parent.mkdir(parents=True)
    config.write_text('TS_PHONE_PORT="23000"\n', encoding="utf-8")
    args = parse_args(["--install-root", str(root), "--with-phone"])

    validate_options(args)

    assert args.phone_port == 23000


def test_existing_phone_port_rejects_a_conflicting_override(tmp_path: Path) -> None:
    root = tmp_path / "install"
    config = root / ".pi/ts-phone/server.env"
    config.parent.mkdir(parents=True)
    config.write_text('TS_PHONE_PORT="23000"\n', encoding="utf-8")
    args = parse_args(["--install-root", str(root), "--with-phone", "--phone-port", "24000"])

    with pytest.raises(ValueError, match="does not match"):
        validate_options(args)


def test_web_and_phone_ports_must_be_distinct(tmp_path: Path) -> None:
    args = parse_args(
        [
            "--install-root",
            str(tmp_path / "install"),
            "--with-phone",
            "--phone-port",
            "8766",
            "--with-web",
            "--web-port",
            "8766",
        ]
    )

    with pytest.raises(ValueError, match="different ports"):
        validate_options(args)


def test_service_configuration_captures_systemctl_output(tmp_path: Path, monkeypatch) -> None:
    args = _options(tmp_path)
    validate_options(args)
    root = Path(args.install_root)
    (root / ".pi/packages/tspi/current/agent/apps/host").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "owner")
    monkeypatch.setattr(wizard, "phone_unit", lambda _: f"[Service]\nWorkingDirectory={root}\n")
    monkeypatch.setattr(wizard, "verify_service_units", lambda *_: None)
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs.get("stdout") is subprocess.PIPE
        assert kwargs.get("stderr") is subprocess.PIPE
        if "is-enabled" in command:
            return subprocess.CompletedProcess(command, 0, "enabled\n", "")
        if "is-active" in command:
            return subprocess.CompletedProcess(command, 0, "active\n", "")
        return subprocess.CompletedProcess(command, 0, "Created symlink\n", "")

    monkeypatch.setattr(wizard.subprocess, "run", run)
    services = wizard.configure_services(args, root / ".pi/ts-phone/server.env")

    assert {service["name"] for service in services} == {"ts-phone-tspi.service", "ts-web-tspi.service"}
    assert all(service["enabled"] == "enabled" and service["active"] == "active" for service in services)
    assert ["systemctl", "--user", "enable", "ts-web-tspi.service"] in calls


def test_generated_web_service_passes_systemd_validation(tmp_path: Path) -> None:
    if shutil.which("systemd-analyze") is None:
        pytest.skip("systemd-analyze is unavailable")
    args = _options(tmp_path / "root with spaces%value")
    root = Path(args.install_root)
    root.mkdir(mode=0o700, parents=True)
    for name in ("TSPi", "TSWeb", "TSPhoneServer"):
        launcher = root / name
        launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        launcher.chmod(0o700)
    phone = f"""[Unit]
Description=TSPi test Phone service
After=network-online.target

[Service]
Type=simple
WorkingDirectory={wizard._systemd_value(root)}
ExecStart={wizard._systemd_quote(root / 'TSPhoneServer')}

[Install]
WantedBy=default.target
"""

    wizard.prepare_runtime_dirs(root)
    wizard.verify_service_units(
        args,
        [("ts-phone-tspi.service", phone), ("ts-web-tspi.service", wizard.web_unit(args))],
    )


def test_invalid_generated_service_does_not_replace_existing_unit(tmp_path: Path, monkeypatch) -> None:
    args = _options(tmp_path)
    root = Path(args.install_root)
    owner = tmp_path / "owner"
    unit_dir = owner / ".config/systemd/user"
    unit_dir.mkdir(parents=True)
    existing = unit_dir / "ts-web-tspi.service"
    original = f"[Service]\nWorkingDirectory={root}\n"
    existing.write_text(original, encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: owner)
    monkeypatch.setattr(wizard, "phone_unit", lambda _: f"[Service]\nWorkingDirectory={root}\n")
    monkeypatch.setattr(
        wizard,
        "verify_service_units",
        lambda *_: (_ for _ in ()).throw(RuntimeError("invalid generated unit")),
    )
    monkeypatch.setattr(wizard.subprocess, "run", lambda *args, **kwargs: pytest.fail("systemctl must not run"))

    with pytest.raises(RuntimeError, match="invalid generated unit"):
        wizard.configure_services(args, root / ".pi/ts-phone/server.env")

    assert existing.read_text(encoding="utf-8") == original


def test_install_plan_separates_component_and_service_state(tmp_path: Path, capsys) -> None:
    args = _options(tmp_path)
    validate_options(args)

    wizard.show_install_plan(args, {"operation": "install", "release_id": None})
    output = capsys.readouterr().out

    assert "Molecular rendering" in output
    assert "install and verify (xyzrender, Matplotlib)" in output
    assert "http://127.0.0.1:8766" in output
    assert "http://127.0.0.1:22113" in output
    assert str(Path(args.install_root) / "TSPhoneServer") in output
    assert str(Path(args.install_root) / "TSPhoneCtl") in output
    assert "user (configure, enable, start)" in output


def test_wizard_rejects_install_root_with_symbolic_link_parent(tmp_path: Path) -> None:
    physical_parent = tmp_path / "physical"
    physical_parent.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(physical_parent, target_is_directory=True)
    args = parse_args(["--install-root", str(linked_parent / "install"), "--without-phone"])

    with pytest.raises(ValueError, match="physical directory path"):
        validate_options(args)

    assert not (physical_parent / "install").exists()


def test_install_places_local_uninstaller_in_installation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "scripts").mkdir(parents=True)
    (source / "uninstall.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (source / "scripts/uninstall.py").write_text("print('ok')\n", encoding="utf-8")
    (source / "scripts/_terminal_ui.py").write_text("# terminal UI\n", encoding="utf-8")
    shutil.copy2(ROOT / "scripts/_installation_metadata.py", source / "scripts/_installation_metadata.py")
    destination = tmp_path / "install"

    uninstaller = install_uninstaller(destination, source)

    assert uninstaller == destination / "uninstall.sh"
    assert uninstaller.is_file()
    assert (destination / ".pi/tspi/uninstall.py").is_file()
    assert (destination / ".pi/tspi/_terminal_ui.py").is_file()
    assert (destination / ".pi/tspi/_installation_metadata.py").is_file()
    marker = json.loads((destination / ".pi/tspi/installation.json").read_text(encoding="utf-8"))
    assert marker == {"schema_version": "tspi-installation-root/1", "install_root": str(destination)}
    assert uninstaller.stat().st_mode & 0o111


def test_direct_package_failure_leaves_a_recoverable_installation(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "install"

    def checkout(repo: str, ref: str, destination: Path) -> str:
        (destination / "scripts").mkdir(parents=True)
        for relative in (
            "uninstall.sh",
            "scripts/uninstall.py",
            "scripts/_terminal_ui.py",
            "scripts/_installation_metadata.py",
        ):
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        return "a" * 40

    def run(command: list[str], *, cwd: Path | None = None) -> str:
        if "scripts/build_package.py" in command:
            return json.dumps({"manifest": "/tmp/manifest.json", "archive": "/tmp/archive.tgz"})
        if "scripts/install_package.py" in command:
            assert (root / "uninstall.sh").is_file()
            assert wizard.inspect_installation(root) == {"operation": "restore", "release_id": None}
            raise RuntimeError("simulated package failure")
        raise AssertionError(command)

    monkeypatch.setattr(source_installer, "checkout_github", checkout)
    monkeypatch.setattr(source_installer, "run", run)

    result = source_installer.main([
        "--repo", "git@github.com:iawnix/TSPi.git", "--ref", "main",
        "--install-root", str(root), "--without-web", "--json",
    ])

    assert result == 1
    assert wizard.inspect_installation(root) == {"operation": "restore", "release_id": None}
    assert (root / "uninstall.sh").is_file()


def test_preflight_rejects_old_node_and_requires_npm_only_for_phone(monkeypatch) -> None:
    checks = [
        {"key": "python", "label": "Python", "ok": True, "required": True, "detail": "3.11"},
        {"key": "git", "label": "Git", "ok": True, "required": True, "detail": "git"},
        {"key": "node", "label": "Node.js", "ok": False, "required": True, "detail": "20"},
        {"key": "npm", "label": "npm", "ok": False, "required": False, "detail": "not found"},
    ]
    with pytest.raises(RuntimeError, match="Node.js"):
        wizard.require_preflight(checks)
    checks[2]["ok"] = True
    wizard.require_preflight(checks)
    with pytest.raises(RuntimeError, match="npm"):
        wizard.require_preflight(checks, with_phone=True)


def test_inspect_installation_distinguishes_fresh_restore_and_update(tmp_path: Path) -> None:
    root = tmp_path / "install"
    assert wizard.inspect_installation(root) == {"operation": "install", "release_id": None}

    private = root / ".pi/tspi"
    private.mkdir(parents=True)
    (private / "installation.json").write_text(json.dumps({
        "schema_version": "tspi-installation-root/1",
        "install_root": str(root),
    }))
    assert wizard.inspect_installation(root) == {"operation": "restore", "release_id": None}

    release_id = "1.0.0-sha256-0123456789abcdef"
    package_home = root / ".pi/packages/tspi"
    release = package_home / "releases" / release_id
    release.mkdir(parents=True)
    (package_home / "current").symlink_to(f"releases/{release_id}")
    (package_home / "install-state.json").write_text(json.dumps({
        "schema_version": "tspi-package-install/1",
        "current_release_id": release_id,
        "package_root": str(release),
    }))
    assert wizard.inspect_installation(root) == {"operation": "update", "release_id": release_id}


def test_inspect_installation_rejects_source_checkout_as_install_root(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / "TSPi").write_text("#!/bin/sh\n")
    with pytest.raises(RuntimeError, match="without trusted package state"):
        wizard.inspect_installation(root)


def test_logged_install_hides_success_log_and_keeps_failure_diagnostics(tmp_path: Path, capsys) -> None:
    success_command = [
        wizard.sys.executable,
        "-c",
        "import json,sys; print('@@tspi-progress@@Checking release', file=sys.stderr); print(json.dumps({'ok': True}))",
    ]
    assert wizard.run_logged_install(success_command, tmp_path / "success") == {"ok": True}
    assert not (tmp_path / "success/.pi/logs").exists()
    assert "Checking release" in capsys.readouterr().err

    failure_command = [
        wizard.sys.executable,
        "-c",
        "import sys; print('@@tspi-progress@@Building release', file=sys.stderr); print('build failed', file=sys.stderr); raise SystemExit(7)",
    ]
    with pytest.raises(RuntimeError, match="build failed") as captured:
        wizard.run_logged_install(failure_command, tmp_path / "failure")
    logs = list((tmp_path / "failure/.pi/logs").glob("install-failure-*.log"))
    assert len(logs) == 1
    assert str(logs[0]) in str(captured.value)
    assert "build failed" in logs[0].read_text(encoding="utf-8")
    assert logs[0].stat().st_mode & 0o077 == 0
