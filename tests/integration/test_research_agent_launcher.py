from __future__ import annotations

import json
import importlib.util
from pathlib import Path

import pytest



_LAUNCHER_PATH = Path(__file__).resolve().parents[2] / "apps/agent-cli/research_agent_launcher.py"
_LAUNCHER_SPEC = importlib.util.spec_from_file_location("research_agent_launcher", _LAUNCHER_PATH)
assert _LAUNCHER_SPEC is not None and _LAUNCHER_SPEC.loader is not None
launcher = importlib.util.module_from_spec(_LAUNCHER_SPEC)
_LAUNCHER_SPEC.loader.exec_module(launcher)


def test_launcher_writes_owner_only_server_config(tmp_path: Path) -> None:
    install_root = tmp_path / "install"

    assert launcher.main(
        [
            "--install-root",
            str(install_root),
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
        "port": 8799,
        "schema_version": "research_agent_server/1",
    }
    assert config_path.stat().st_mode & 0o777 == 0o600


def test_launcher_reports_missing_installed_pi_runtime_without_starting_node(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    result = launcher.main(["--install-root", str(tmp_path / "install")])
    assert result == 2
    assert "installed Pi Runtime is missing" in capsys.readouterr().err


def test_launcher_rejects_removed_runtime_injection_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    install_root = tmp_path / "install"
    config_path = install_root / ".pi/research-agent/server.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"schema_version": "research_agent_server/1", "runtime_module": "legacy.mjs"}),
        encoding="utf-8",
    )
    result = launcher.main(["--install-root", str(install_root)])
    assert result == 2
    assert "removed Runtime injection fields" in capsys.readouterr().err


def test_launcher_resolves_installed_pi_runtime_and_replaces_process(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TSPI_PI_RUNTIME_ROOT", raising=False)
    install_root = tmp_path / "install"
    pin = json.loads((launcher.ROOT / "config/pi-source.json").read_text(encoding="utf-8"))
    source = install_root / ".pi/runtime-cache/pi" / pin["commit"]
    source.mkdir(parents=True)
    config_path = install_root / ".pi/research-agent/server.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "schema_version": "research_agent_server/1",
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
    assert environment["TSPI_PI_RUNTIME_ROOT"] == str(source.resolve())
    assert environment["TSP_APP_SERVER_PORT"] == "0"
    assert environment["TSPI_INSTALL_ROOT"] == str(install_root.resolve())
