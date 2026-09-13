from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import install_wizard as wizard
from scripts.install_wizard import configure_phone, parse_args, phone_unit, validate_options
from scripts.install_from_github import install_uninstaller


ROOT = Path(__file__).resolve().parents[1]


def _options(tmp_path: Path):
    return parse_args(["--install-root", str(tmp_path / "install"), "--with-phone", "--with-web",
                       "--service-scope", "user", "--non-interactive", "--yes"])


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
    from ts_web import cli

    args = _options(tmp_path)
    unit = wizard.web_unit(args)
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
    assert args.without_web is True


def test_install_passes_prepared_phone_for_compatibility_check(tmp_path: Path, monkeypatch) -> None:
    args = _options(tmp_path)
    release = tmp_path / "phone-release"
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, '{"release_id":"test"}', '')

    monkeypatch.setattr(wizard.subprocess, "run", run)
    wizard.run_install(args, release)
    assert commands[0][-2:] == ["--phone-server-root", str(release)]


def test_without_phone_does_not_fetch_or_configure_phone(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(wizard, "prepare_phone", lambda *args: pytest.fail("Phone was not selected"))
    monkeypatch.setattr(wizard, "run_install", lambda *args: {"release_id": "test"})
    assert wizard.main(["--install-root", str(tmp_path / "install"), "--without-phone",
                        "--non-interactive", "--yes"]) == 0
    assert not (tmp_path / "install/.pi/ts-phone/server.env").exists()


def test_wizard_installs_phone_before_service_configuration(tmp_path: Path, monkeypatch, capsys) -> None:
    events = []
    release = tmp_path / "phone-release"
    monkeypatch.setattr(wizard, "prepare_phone", lambda *args: events.append("build") or release)
    monkeypatch.setattr(wizard, "run_install", lambda args, phone: events.append(("install", phone)) or {"release_id": "test"})
    monkeypatch.setattr(wizard, "activate_phone", lambda *args: events.append("activate") or {"commit": "a" * 40})
    monkeypatch.setattr(wizard, "configure_services", lambda *args: events.append("services") or [])
    assert wizard.main(["--install-root", str(tmp_path / "install"), "--with-phone",
                        "--non-interactive", "--yes", "--json"]) == 0
    assert events == ["build", ("install", release), "activate", "services"]
    assert json.loads(capsys.readouterr().out)["phone"]["commit"] == "a" * 40


@pytest.mark.parametrize("arguments", [["--phone-port", "65536"], ["--phone-repo", "https://example.com/phone"], ["--phone-ref", "../escape"]])
def test_phone_options_reject_invalid_configuration_before_install(tmp_path: Path, arguments) -> None:
    args = parse_args(["--install-root", str(tmp_path / "install"), "--with-phone", *arguments])
    with pytest.raises(ValueError):
        validate_options(args)
    assert not (tmp_path / "install").exists()


def test_install_places_local_uninstaller_in_installation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "scripts").mkdir(parents=True)
    (source / "uninstall.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (source / "scripts/uninstall.py").write_text("print('ok')\n", encoding="utf-8")
    destination = tmp_path / "install"

    uninstaller = install_uninstaller(destination, source)

    assert uninstaller == destination / "uninstall.sh"
    assert uninstaller.is_file()
    assert (destination / ".pi/tspi/uninstall.py").is_file()
    assert uninstaller.stat().st_mode & 0o111
