from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
from pathlib import Path

import pytest

from tests.runtime_helpers import write_test_runtime_manifest, write_test_suite_manifest
from ts_agent.runtime import launcher


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_VERSION = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]


def test_normalize_proxy_environment_accepts_host_port_and_drops_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "58.198.181.184:7897")
    monkeypatch.setenv("https_proxy", "https://proxy.example.test:8443")
    monkeypatch.setenv("ALL_PROXY", "not a proxy")

    launcher.normalize_proxy_environment()

    assert os.environ["HTTP_PROXY"] == "http://58.198.181.184:7897"
    assert os.environ["https_proxy"] == "https://proxy.example.test:8443"
    assert "ALL_PROXY" not in os.environ


class _ExecCalled(RuntimeError):
    pass


def _installation(tmp_path: Path) -> launcher.Installation:
    package = tmp_path / "package"
    entry = package / "apps/app-server/pi-app-server.mjs"
    entry.parent.mkdir(parents=True)
    entry.write_text("// test entry\n", encoding="utf-8")
    root = tmp_path / "install"
    root.mkdir()
    return launcher.Installation(
        root=root,
        package_root=package,
        workspaces_root=root / "workspaces",
        remote_config_default=root / ".pi/remote.toml",
        notification_config_default=root / ".pi/notifications.toml",
        runtime_home=root / ".agents/runtime/tspi",
        runtime_manifest=root / ".agents/runtime/tspi/env.json",
        env_root=root / ".agents/envs/tspi",
        process_cache_root=root / ".pi/runtime-cache",
    )


def _copy_launcher(tmp_path: Path) -> tuple[Path, Path]:
    install_root = tmp_path / "tspi-install"
    package_home = install_root / ".pi/packages/tspi"
    suite_root = package_home / "releases/test-suite"
    package_root = suite_root / "agent"
    package_root.mkdir(parents=True)
    (package_root / "package.json").write_text(
        json.dumps({"name": "@iawnix/ts-agent", "version": PACKAGE_VERSION}) + "\n",
        encoding="utf-8",
    )
    write_test_suite_manifest(suite_root, version=PACKAGE_VERSION)
    shutil.copy2(ROOT / "TSPi", package_root / "TSPi")
    (package_root / "TSPi").chmod(0o755)
    (package_root / "scripts").mkdir()
    for name in ("_bootstrap.py", "tspi_launcher.py", "pi-loader.mjs"):
        shutil.copy2(ROOT / "scripts" / name, package_root / "scripts" / name)
    shutil.copytree(
        ROOT / "packages/ts-agent-kernel",
        package_root / "packages/ts-agent-kernel",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
    )
    shutil.copy2(ROOT / "environment.yml", package_root / "environment.yml")
    shutil.copy2(ROOT / "requirements-runtime.txt", package_root / "requirements-runtime.txt")
    write_test_runtime_manifest(package_root, install_root)
    (package_home / "current").symlink_to("releases/test-suite")
    installed_launcher = install_root / "TSPi"
    installed_launcher.symlink_to(".pi/packages/tspi/current/agent/TSPi")
    return install_root, installed_launcher


def test_app_server_command_owns_workspace_state_and_forwards_pi_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    workspace = installation.root / "workspaces/reaction-a"
    (workspace / ".pi").mkdir(parents=True)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
    server_id = "123e4567-e89b-42d3-a456-426614174000"
    socket_directory = tmp_path / "sockets"
    monkeypatch.setattr(launcher, "_app_server_id", lambda *_args, **_kwargs: server_id)
    monkeypatch.setattr(launcher, "_app_server_socket_directory", lambda *_args, **_kwargs: socket_directory)
    request = launcher.parse_launch_request([
        "--app-server", "--workspace", "reaction-a", "--source-root", "/opt/pi-source", "--provider", "anthropic",
    ])

    command = launcher.build_app_server_command(installation, workspace, request)

    state_root = workspace / ".pi/app-server"
    assert command == [
        "/usr/bin/node",
        str(installation.package_root / "apps/app-server/pi-app-server.mjs"),
        "server",
        "--workspace",
        str(workspace),
        "--directory",
        str(socket_directory),
        "--server-id",
        server_id,
        "--session-dir",
        str(state_root / "sessions"),
        "--source-root",
        "/opt/pi-source",
        "--provider",
        "anthropic",
    ]
    assert request.app_server is True
    for path in (state_root, state_root / "sessions"):
        assert path.is_dir()
        assert stat.S_IMODE(path.stat().st_mode) == 0o700


def test_host_command_owns_installation_state_and_workspace_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
    server_id = "123e4567-e89b-42d3-a456-426614174000"
    socket_directory = tmp_path / "sockets"
    monkeypatch.setattr(launcher, "_host_server_id", lambda *_args, **_kwargs: server_id)
    monkeypatch.setattr(launcher, "_host_socket_directory", lambda *_args, **_kwargs: socket_directory)
    request = launcher.parse_launch_request(["--host", "--provider", "anthropic"])

    command = launcher.build_host_server_command(installation, request)

    state_root = installation.root / ".pi/app-server-host"
    assert command == [
        "/usr/bin/node",
        str(installation.package_root / "apps/app-server/pi-app-server.mjs"),
        "server",
        "--workspace",
        str(state_root / "workspace"),
        "--directory",
        str(socket_directory),
        "--server-id",
        server_id,
        "--session-dir",
        str(state_root / "sessions"),
        "--provider",
        "anthropic",
    ]
    assert request.host is True
    assert (installation.root / "workspaces").is_dir()
    assert state_root.is_dir()


def test_host_state_prepares_private_pi_workspace_before_root_lock(tmp_path: Path) -> None:
    installation = _installation(tmp_path)

    host_workspace, state_root = launcher._prepare_host_state(installation)

    assert host_workspace == state_root / "workspace"
    assert (host_workspace / ".pi").is_dir()
    assert stat.S_IMODE((host_workspace / ".pi").stat().st_mode) == 0o700


def test_host_state_rejects_an_insecure_installation_pi_directory(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    installation.root.joinpath(".pi").mkdir(mode=0o700)
    installation.root.joinpath(".pi").chmod(0o755)

    with pytest.raises(launcher.TSPiHostError, match="must be owner-only"):
        launcher._prepare_host_state(installation)


def test_host_client_requires_one_host_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
    monkeypatch.setattr(launcher, "_host_server_id", lambda *_args, **_kwargs: "123e4567-e89b-42d3-a456-426614174000")
    monkeypatch.setattr(launcher, "_host_socket_directory", lambda *_args, **_kwargs: tmp_path / "missing-socket")
    with pytest.raises(launcher.TSPiHostError, match="TSPi Host is not running"):
        launcher.build_host_client_command(installation, launcher.parse_launch_request(["--workspace", "reaction-a"]))


@pytest.mark.parametrize("endpoint", ["unix:///run/tspi.sock", "radius://123e4567-e89b-42d3-a456-426614174000"])
def test_explicit_app_client_forwards_native_connection_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    installation = _installation(tmp_path)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
    request = launcher.parse_launch_request([
        "--app-client", "--connect", endpoint, "--session-id", "session-1", "--continue",
    ])

    assert launcher.build_app_client_command(installation, request) == [
        "/usr/bin/node",
        str(installation.package_root / "apps/app-server/pi-app-server.mjs"),
        "client",
        "--session-id",
        "session-1",
        "--connect",
        endpoint,
        "--continue",
    ]


def test_gateway_attaches_one_host_session_with_http_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
    server_id = "123e4567-e89b-42d3-a456-426614174000"
    socket_directory = Path(f"/tmp/tspi-gateway-{os.getpid()}")
    socket_directory.mkdir()
    monkeypatch.setattr(launcher, "_host_server_id", lambda *_args, **_kwargs: server_id)
    monkeypatch.setattr(launcher, "_host_socket_directory", lambda *_args, **_kwargs: socket_directory)
    endpoint = socket_directory / f"{server_id}.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(endpoint))
    try:
        request = launcher.parse_launch_request([
            "--gateway", "--workspace", "reaction-a", "--session-id", "session-1",
            "--port", "8080", "--auth-token", "secret",
        ])
        command = launcher.build_gateway_command(installation, request)
    finally:
        listener.close()
        endpoint.unlink(missing_ok=True)
        socket_directory.rmdir()

    assert request.gateway is True
    assert command == [
        "/usr/bin/node",
        str(installation.package_root / "apps/app-server/pi-app-server.mjs"),
        "gateway",
        "--connect",
        f"unix://{endpoint}",
        "--session-id",
        "session-1",
        "--port",
        "8080",
        "--auth-token",
        "secret",
    ]


def test_default_terminal_connects_to_workspace_unix_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    workspace = installation.workspaces_root / "reaction-a"
    state = workspace / ".pi/app-server"
    state.mkdir(parents=True)
    server_id = "123e4567-e89b-42d3-a456-426614174000"
    identity = state / "server-id"
    identity.write_text(server_id + "\n", encoding="ascii")
    identity.chmod(0o600)
    server = Path(f"/tmp/tspi-test-{os.getpid()}")
    server.mkdir(mode=0o700, exist_ok=True)
    monkeypatch.setattr(launcher, "_app_server_socket_directory", lambda *_args, **_kwargs: server)
    endpoint = server / f"{server_id}.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(endpoint))
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
    try:
        command = launcher.build_app_client_command(
            installation,
            launcher.parse_launch_request(["--workspace", "reaction-a", "-c"]),
            workspace,
        )
    finally:
        listener.close()
        endpoint.unlink(missing_ok=True)
        server.rmdir()

    assert command == [
        "/usr/bin/node",
        str(installation.package_root / "apps/app-server/pi-app-server.mjs"),
        "client",
        "--directory",
        str(server),
        "--connect",
        f"unix://{endpoint}",
        "-c",
    ]


def test_app_server_acquires_root_ownership_before_exec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    workspace = installation.workspaces_root / "reaction-a"
    (workspace / ".pi").mkdir(parents=True)
    monkeypatch.setattr(launcher, "resolve_installation", lambda *_args: installation)
    monkeypatch.setattr(launcher, "require_guarded_installation", lambda *_args: None)
    monkeypatch.setattr(launcher, "configure_runtime_environment", lambda *_args: None)
    monkeypatch.setattr(launcher, "ensure_runtime_python", lambda *_args, **_kwargs: Path("/managed/python"))
    monkeypatch.setattr(launcher, "bind_runtime_process_environment", lambda *_args: None)
    monkeypatch.setattr(launcher, "configure_remote", lambda *_args: None)
    monkeypatch.setattr(launcher, "configure_notifications", lambda *_args: None)
    monkeypatch.setattr(launcher, "configure_process_environment", lambda *_args: None)
    monkeypatch.setattr(launcher, "prepare_workspace", lambda *_args: workspace)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
    acquired: list[str] = []

    def lock(label: str) -> int:
        acquired.append(label)
        return os.open(tmp_path / f"{label}.lock", os.O_RDWR | os.O_CREAT, 0o600)

    monkeypatch.setattr(launcher, "acquire_directory_guard", lambda *_args: lock("directory"))
    monkeypatch.setattr(launcher, "acquire_root_agent_lock", lambda *_args: lock("root"))
    bootstrap_calls: list[Path] = []
    monkeypatch.setattr("ts_agent.workspace.bootstrap.bootstrap_workspace", bootstrap_calls.append)

    def fake_exec(_command: list[str], cwd: Path) -> None:
        assert cwd == workspace
        raise _ExecCalled

    monkeypatch.setattr(launcher, "exec_pi", fake_exec)
    with pytest.raises(_ExecCalled):
        launcher.launch(
            ["--app-server", "--workspace", "reaction-a", "--source-root", "/opt/pi-source"],
            package_root=tmp_path / "unused-package",
            install_root=tmp_path / "unused-install",
        )
    assert acquired == ["directory", "root"]
    assert bootstrap_calls == [workspace]


def test_installed_app_server_is_the_exclusive_workspace_owner(tmp_path: Path) -> None:
    installation, installed_launcher = _copy_launcher(tmp_path)
    package = (installation / ".pi/packages/tspi/current/agent").resolve()
    entry = package / "apps/app-server/pi-app-server.mjs"
    entry.parent.mkdir(parents=True)
    entry.write_text("// fixture entry\n", encoding="utf-8")
    fake_node = tmp_path / "node"
    fake_node.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "print(json.dumps({'ready': True, 'args': sys.argv[1:]}), flush=True)\n"
        "if os.environ.get('HOLD_APP_SERVER') == '1': sys.stdin.buffer.read(1)\n",
        encoding="utf-8",
    )
    fake_node.chmod(0o755)
    command = [str(installed_launcher), "--app-server", "--workspace", "reaction-a"]
    base_env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"}
    holder = subprocess.Popen(
        command,
        cwd=installation,
        env={**base_env, "HOLD_APP_SERVER": "1"},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert json.loads(holder.stdout.readline())["ready"] is True
        conflict = subprocess.run(
            command,
            cwd=installation,
            env={**base_env, "HOLD_APP_SERVER": "0"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=20,
        )
        assert conflict.returncode != 0
        assert "another Root Agent already owns workspace" in conflict.stderr
    finally:
        if holder.stdin is not None:
            holder.stdin.close()
        holder.wait(timeout=10)

    replacement = subprocess.run(
        command,
        cwd=installation,
        env={**base_env, "HOLD_APP_SERVER": "0"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    assert replacement.returncode == 0, replacement.stderr


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--app-server", "--app-client"], "cannot be combined"),
        (["--app-client", "--allow-writes"], "was removed"),
        (["--app-client", "--workspace", "reaction-a"], "does not accept --workspace"),
        (["--app-server", "--session-id", "session-1"], "belongs to --app-client"),
    ],
)
def test_invalid_app_server_modes_fail_before_installation_resolution(
    arguments: list[str],
    message: str,
) -> None:
    with pytest.raises(launcher.TSPiHostError, match=message):
        launcher.launch(arguments, package_root="/missing", install_root="/missing")
