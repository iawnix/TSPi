from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from tests.support.runtime_helpers import write_test_runtime_manifest, write_test_suite_manifest
from ts_agent.runtime import launcher


ROOT = Path(__file__).resolve().parents[2]
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
        compute_config_default=root / ".pi/compute.toml",
        notification_config_default=root / ".pi/notifications.toml",
        runtime_home=root / ".agents/runtime/tspi",
        runtime_manifest=root / ".agents/runtime/tspi/env.json",
        env_root=root / ".agents/envs/tspi",
        process_cache_root=root / ".pi/runtime-cache",
        model_icons_config=root / ".pi/tspi/model-icons.json",
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


def test_resolve_installation_uses_configured_workspace_root(tmp_path: Path) -> None:
    install_root, _launcher = _copy_launcher(tmp_path)
    workspace_root = tmp_path / "research-projects"
    config = install_root / ".pi/tspi/workspace-root.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({
        "schema_version": "tspi-workspace-root/1",
        "workspace_root": str(workspace_root),
    }) + "\n", encoding="utf-8")
    package_root = install_root / ".pi/packages/tspi/current/agent"

    installation = launcher.resolve_installation(package_root, install_root)

    assert installation.workspaces_root == workspace_root


def test_model_icon_marker_enables_tspi_style_and_preserves_explicit_style(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    font = tmp_path / "fonts/TSPi-Model-Icons.ttf"
    font.parent.mkdir()
    font.write_bytes(b"font fixture")
    marker = installation.model_icons_config
    assert marker is not None
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps(
            {
                "schema_version": launcher.MODEL_ICON_CONFIG_SCHEMA,
                "enabled": True,
                "font_path": str(font),
                "sha256": hashlib.sha256(font.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("TSPI_ICON_STYLE", raising=False)

    assert launcher.configure_model_icon_environment(installation) is True
    assert os.environ["TSPI_ICON_STYLE"] == "tspi"

    monkeypatch.setenv("TSPI_ICON_STYLE", "unicode")
    assert launcher.configure_model_icon_environment(installation) is False
    assert os.environ["TSPI_ICON_STYLE"] == "unicode"


def test_invalid_model_icon_marker_does_not_enable_tspi_style(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installation = _installation(tmp_path)
    marker = installation.model_icons_config
    assert marker is not None
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps(
            {
                "schema_version": launcher.MODEL_ICON_CONFIG_SCHEMA,
                "enabled": True,
                "font_path": str(tmp_path / "missing.ttf"),
                "sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("TSPI_ICON_STYLE", raising=False)

    assert launcher.configure_model_icon_environment(installation) is False
    assert "TSPI_ICON_STYLE" not in os.environ


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


def test_launcher_usage_keeps_internal_transport_modes_out_of_daily_help() -> None:
    assert "TSPi --workspace <name>" in launcher.USAGE
    assert "ts-app-server-tspi.service" in launcher.USAGE
    for internal_mode in ("--service-host", "--app-server", "--app-client", "--gateway", "--standalone"):
        assert internal_mode not in launcher.USAGE


def test_session_selection_is_workspace_scoped_and_explicit() -> None:
    new_session = launcher.parse_launch_request(["--workspace", "reaction-a"])
    latest = launcher.parse_launch_request(["--workspace", "reaction-a", "-c", "--provider", "anthropic"])

    assert new_session.continue_latest is False
    assert new_session.session_id is None
    assert latest.continue_latest is True
    assert latest.pi_args == ("--provider", "anthropic")

    with pytest.raises(launcher.TSPiHostError, match="cannot be combined"):
        launcher.parse_launch_request([
            "--workspace", "reaction-a", "--continue", "--session-id", "session-1",
        ])


def test_phone_management_commands_are_parsed_before_workspace_selection() -> None:
    pairing = launcher.parse_launch_request(["phone", "pair"])
    devices = launcher.parse_launch_request(["phone", "devices"])
    revoke = launcher.parse_launch_request(["phone", "revoke", "223e4567-e89b-42d3-a456-426614174000"])

    assert pairing.phone_action == "pair"
    assert devices.phone_action == "devices"
    assert revoke.phone_action == "revoke"
    assert revoke.phone_device_id == "223e4567-e89b-42d3-a456-426614174000"

    with pytest.raises(launcher.TSPiHostError, match="usage: TSPi phone"):
        launcher.parse_launch_request(["phone", "revoke"])


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


def test_host_endpoint_requires_one_unix_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
    monkeypatch.setattr(launcher, "_host_server_id", lambda *_args, **_kwargs: "123e4567-e89b-42d3-a456-426614174000")
    monkeypatch.setattr(launcher, "_host_socket_directory", lambda *_args, **_kwargs: tmp_path / "missing-socket")
    with pytest.raises(launcher.TSPiHostUnavailableError, match="TSPi Host is not running"):
        launcher.resolve_host_socket(installation)


def test_missing_host_is_started_once_and_waited_until_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    endpoint = tmp_path / "host.sock"
    resolutions = 0

    def resolve(_installation: launcher.Installation) -> Path:
        nonlocal resolutions
        resolutions += 1
        if resolutions == 1:
            raise launcher.TSPiHostUnavailableError("not running")
        return endpoint

    commands: list[list[str]] = []
    monkeypatch.setattr(launcher, "resolve_host_socket", resolve)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/systemctl" if name == "systemctl" else None)
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command) or subprocess.CompletedProcess(command, 0, "", ""),
    )

    assert launcher.ensure_host_running(installation) == endpoint
    assert commands == [["/usr/bin/systemctl", "--user", "start", launcher.APP_SERVER_SERVICE]]
    assert resolutions == 2


def test_missing_host_uses_system_scope_when_installation_configures_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = replace(
        _installation(tmp_path),
        service_scope="system",
        host_runtime_dir=Path("/run/tspi"),
    )
    endpoint = tmp_path / "host.sock"
    monkeypatch.setattr(
        launcher,
        "resolve_host_socket",
        lambda _installation: (_ for _ in ()).throw(launcher.TSPiHostUnavailableError("not running"))
        if not endpoint.exists()
        else endpoint,
    )
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/systemctl" if name == "systemctl" else None)
    commands: list[list[str]] = []

    def start(command, **_kwargs):
        commands.append(command)
        endpoint.touch()
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(launcher.subprocess, "run", start)

    assert launcher.ensure_host_running(installation) == endpoint
    assert commands == [["/usr/bin/systemctl", "start", launcher.APP_SERVER_SERVICE]]


def test_host_start_failure_preserves_systemd_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    monkeypatch.setattr(
        launcher,
        "resolve_host_socket",
        lambda _installation: (_ for _ in ()).throw(launcher.TSPiHostUnavailableError("not running")),
    )
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/systemctl" if name == "systemctl" else None)
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 1, "", "unit failed"),
    )

    with pytest.raises(launcher.TSPiHostError, match="unit failed"):
        launcher.ensure_host_running(installation)


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
        "--workspace",
        str(installation.workspaces_root / "reaction-a"),
        "--connect",
        f"unix://{endpoint}",
        "--session-id",
        "session-1",
        "--port",
        "8080",
        "--auth-token",
        "secret",
    ]


def test_default_terminal_connects_to_host_and_continues_latest_workspace_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    server_id = "123e4567-e89b-42d3-a456-426614174000"
    server = Path(f"/tmp/tspi-test-{os.getpid()}")
    server.mkdir(mode=0o700, exist_ok=True)
    monkeypatch.setattr(launcher, "_host_server_id", lambda *_args, **_kwargs: server_id)
    monkeypatch.setattr(launcher, "_host_socket_directory", lambda *_args, **_kwargs: server)
    endpoint = server / f"{server_id}.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(endpoint))
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
    try:
        command = launcher.build_host_client_command(
            installation,
            launcher.parse_launch_request(["--workspace", "reaction-a", "-c"]),
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
        "--continue",
    ]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--host"], "managed by systemd"),
        (["--app-server"], "was removed"),
        (["--app-client"], "was removed"),
        (["--workspace", "reaction-a", "-c", "--session-id", "session-1"], "cannot be combined"),
    ],
)
def test_invalid_launch_modes_fail_before_installation_resolution(
    arguments: list[str],
    message: str,
) -> None:
    with pytest.raises(launcher.TSPiHostError, match=message):
        launcher.launch(arguments, package_root="/missing", install_root="/missing")
