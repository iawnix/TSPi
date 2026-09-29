from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import research_agent_launcher as launcher


def test_launcher_writes_owner_only_server_config(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.mjs"
    runtime.write_text("export function create_runtime() {}\n", encoding="utf-8")
    install_root = tmp_path / "install"

    assert launcher.main(
        [
            "--install-root",
            str(install_root),
            "--runtime-module",
            str(runtime),
            "--kernel-module",
            str(runtime),
            "--host",
            "127.0.0.1",
            "--port",
            "8799",
            "--write-config",
        ]
    ) == 0

    config_path = install_root / ".pi/research-agent/server.json"
    document = json.loads(config_path.read_text(encoding="utf-8"))
    assert document == {
        "host": "127.0.0.1",
        "kernel_module": str(runtime),
        "port": 8799,
        "runtime_module": str(runtime),
        "schema_version": "research_agent_server/1",
    }
    assert config_path.stat().st_mode & 0o777 == 0o600


def test_launcher_reports_missing_runtime_module_without_starting_node(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    result = launcher.main(["--install-root", str(tmp_path / "install")])
    assert result == 2
    assert "runtime_module is required" in capsys.readouterr().err


def test_launcher_resolves_local_modules_and_replaces_process(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime module.mjs"
    runtime.write_text("export function create_runtime() {}\n", encoding="utf-8")
    kernel = tmp_path / "kernel.mjs"
    kernel.write_text("export function create_kernel() {}\n", encoding="utf-8")
    install_root = tmp_path / "install"
    config_path = install_root / ".pi/research-agent/server.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "schema_version": "research_agent_server/1",
                "runtime_module": str(runtime),
                "kernel_module": str(kernel),
                "port": 0,
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    class ExecCalled(BaseException):
        pass

    def fake_exec(node: str, argv: list[str], env: dict[str, str]) -> None:
        captured.update(node=node, argv=argv, env=env)
        raise ExecCalled()

    monkeypatch.setattr(launcher.os, "execvpe", fake_exec)
    with pytest.raises(ExecCalled):
        launcher.main(["--install-root", str(install_root), "--", "--diagnostic"])
    assert captured["node"]
    argv = captured["argv"]
    assert isinstance(argv, list)
    assert argv[-1] == "--diagnostic"
    environment = captured["env"]
    assert isinstance(environment, dict)
    assert environment["RESEARCH_AGENT_RUNTIME_MODULE"].startswith("file:")
    assert "%20" in environment["RESEARCH_AGENT_RUNTIME_MODULE"]
    assert environment["RESEARCH_AGENT_KERNEL_MODULE"].startswith("file:")
    assert environment["TSP_APP_SERVER_PORT"] == "0"
    assert environment["TSPI_INSTALL_ROOT"] == str(install_root.resolve())
