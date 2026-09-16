from __future__ import annotations

import json
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


def test_app_server_service_is_workspace_template(tmp_path: Path) -> None:
    args = _options(tmp_path)
    root = Path(args.install_root)
    unit = wizard.app_server_unit(args)

    assert f"WorkingDirectory={root}" in unit
    assert f'ExecStart="{root / "TSPi"}" --app-server --workspace %i' in unit
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


def test_configure_services_installs_template_but_starts_only_web(
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

    assert (unit_dir / "ts-app-server-tspi@.service").is_file()
    assert (unit_dir / "ts-web-tspi.service").is_file()
    assert calls == [
        ("daemon-reload",),
        ("enable", "ts-web-tspi.service"),
        ("restart", "ts-web-tspi.service"),
    ]
    assert services[0]["name"] == "ts-app-server-tspi@.service"
    assert services[0]["active"] == "per-workspace"


def test_service_ownership_rejects_a_different_installation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _options(tmp_path)
    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    (unit_dir / "ts-app-server-tspi@.service").write_text(
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
        [{"name": "ts-app-server-tspi@.service", "scope": "user", "enabled": "per-workspace", "active": "per-workspace"}],
        {"web_http": {"path": "/token", "status": "created", "mode": "0600"}},
    )
    assert components["app_server"]["runtime"] == str(runtime)
    assert "<workspace>" in components["app_server"]["server_id"]
    assert "phone" not in components


def test_install_uninstaller_copies_recovery_files_and_marks_ownership(tmp_path: Path) -> None:
    root = tmp_path / "install"
    uninstaller = install_uninstaller(root, ROOT)
    assert uninstaller == root / "uninstall.sh"
    assert uninstaller.is_file()
    assert (root / ".pi/tspi/uninstall.py").is_file()
    marker = json.loads((root / ".pi/tspi/installation.json").read_text(encoding="utf-8"))
    assert marker["schema_version"] == "tspi-installation-root/1"
