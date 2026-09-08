from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_ts_phone_integration import ROOT, _copy_launcher


@pytest.mark.parametrize("entrypoint", ["TSPhoneServer", "TSPhoneCtl"])
def test_installed_phone_entrypoints_share_configuration_without_science_or_shell_execution(
    tmp_path: Path, entrypoint: str,
) -> None:
    installation, launcher = _copy_launcher(tmp_path)
    package = launcher.resolve().parent
    shutil.copytree(ROOT / "src/host", package / "src/host")
    phone = package.parent / "phone"
    dist = phone / "services/server/dist"
    dist.mkdir(parents=True)
    (phone / "package.json").write_text('{"type":"module"}')
    program = "index.js" if entrypoint == "TSPhoneServer" else "cli.js"
    (dist / program).write_text(
        "console.log(JSON.stringify({cwd:process.cwd(),args:process.argv.slice(2),"
        "port:process.env.TS_PHONE_PORT,state:process.env.TS_PHONE_STATE_DIR,"
        "tspi:process.env.TS_PHONE_TSPI,workspaces:process.env.TS_PHONE_WORKSPACES,"
        "agent:process.env.PI_CODING_AGENT_DIR,probe:process.env.TSPI_CONFIG_PROBE}));"
    )
    command = installation / entrypoint
    command.symlink_to(".pi/packages/tspi/current/agent/TSPi")
    config = installation / ".pi/ts-phone/server.env"
    config.parent.mkdir()
    state = tmp_path / "phone state"
    agent = tmp_path / "another user agent"
    injected = tmp_path / "not-created"
    config.write_text(f"TS_PHONE_PORT=22555\nTS_PHONE_STATE_DIR='{state}'\n"
        f"PI_CODING_AGENT_DIR='{agent}'\nTSPI_CONFIG_PROBE='$(touch {injected})'\n")
    config.chmod(0o600)
    (installation / ".agents/runtime/transition-state-workflow/env.json").unlink()
    environment = {key: value for key, value in os.environ.items()
        if not key.startswith("TS_PHONE_") and key not in {"TS_AGENT_INSTALL_ROOT", "PI_CODING_AGENT_DIR"}}
    result = subprocess.run([str(command), "--help"], cwd=tmp_path, env=environment,
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    values = json.loads(result.stdout)
    assert values == {"cwd": str(installation), "args": ["--help"], "port": "22555", "state": str(state),
        "tspi": str(installation / "TSPi"), "workspaces": str(installation / "workspaces"),
        "agent": str(agent), "probe": f"$(touch {injected})"}
    assert not injected.exists()
    assert not state.exists()
    assert not agent.exists()
    assert not (installation / "workspaces").exists()
    override = subprocess.run([str(command)], cwd=tmp_path,
        env={**environment, "TS_PHONE_PORT": "22666"}, capture_output=True, text=True, timeout=10)
    assert json.loads(override.stdout)["port"] == "22666"
    config.chmod(0o644)
    rejected = subprocess.run([str(command)], cwd=tmp_path, env=environment,
        capture_output=True, text=True, timeout=10)
    assert rejected.returncode == 1
    assert rejected.stdout == ""
    assert "private regular file" in rejected.stderr


def test_service_template_has_installation_scoped_paths_and_no_embedded_secrets(tmp_path: Path) -> None:
    installation, launcher = _copy_launcher(tmp_path / "root with spaces%$VAR")
    package = launcher.resolve().parent
    shutil.copytree(ROOT / "src/host", package / "src/host")
    command = installation / "TSPhoneServer"
    command.symlink_to(".pi/packages/tspi/current/agent/TSPi")
    config = installation / ".pi/ts-phone/server.env"
    config.parent.mkdir()
    config.write_text(f"PI_CODING_AGENT_DIR='{tmp_path}/custom-agent'\nPRIVATE_TEST_TOKEN=never-publish-this\n")
    config.chmod(0o600)
    environment = {key: value for key, value in os.environ.items()
        if not key.startswith("TS_PHONE_") and key not in {"TS_AGENT_INSTALL_ROOT", "PI_CODING_AGENT_DIR"}}
    result = subprocess.run([str(command), "--print-service"], env=environment,
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "never-publish-this" not in result.stdout
    executable_root = str(installation).replace("%", "%%")
    assert f'ExecStart="{executable_root}/TSPhoneServer"' in result.stdout
    assert f'ReadWritePaths="-{tmp_path}/custom-agent"' in result.stdout
    assert "ProtectHome=read-only" in result.stdout
    assert "ReadWritePaths=\"-/home\"" not in result.stdout
    assert not (installation / "workspaces").exists()
    if shutil.which("systemd-analyze"):
        service = tmp_path / "ts-phone-test.service"
        service.write_text(result.stdout)
        runtime = tmp_path / "systemd-runtime"
        runtime.mkdir(mode=0o700)
        for name in ("basic.target", "network-online.target"):
            (tmp_path / name).write_text("[Unit]\nDescription=Test dependency\n")
        verified = subprocess.run(["systemd-analyze", "--user", "--man=no", "verify", str(service)],
            env={**environment, "XDG_RUNTIME_DIR": str(runtime), "SYSTEMD_UNIT_PATH": str(tmp_path)},
            capture_output=True, text=True, timeout=10)
        assert verified.returncode == 0, verified.stdout + verified.stderr


@pytest.mark.parametrize("directory", ["/", str(Path.home()), "installation", "parent"])
def test_service_template_rejects_broad_write_access(tmp_path: Path, directory: str) -> None:
    installation = tmp_path / "install"
    config = installation / ".pi/ts-phone/server.env"
    config.parent.mkdir(parents=True)
    target = {"installation": str(installation), "parent": str(tmp_path)}.get(directory, directory)
    config.write_text(f"TS_PHONE_STATE_DIR='{target}'\n")
    config.chmod(0o600)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("TS_PHONE_")}
    result = subprocess.run(["node", str(ROOT / "src/host/service.mjs"), "--install-root", str(installation)],
        env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "cannot cover a home directory or the whole installation" in result.stderr
