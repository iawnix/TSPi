from __future__ import annotations

import json
import os
import subprocess
import stat
from pathlib import Path

import pytest

from ts_agent.runtime import launcher
from tests.test_ts_phone_integration import _copy_launcher


class _ExecCalled(RuntimeError):
    pass


def _installation(tmp_path: Path) -> launcher.Installation:
    package = tmp_path / "package"
    entry = package / "apps" / "host" / "pi-app-server.mjs"
    entry.parent.mkdir(parents=True)
    entry.write_text("// test entry\n", encoding="utf-8")
    root = tmp_path / "install"
    root.mkdir()
    return launcher.Installation(
        root=root,
        package_root=package,
        workspaces_root=root / "workspaces",
        remote_config_default=root / ".pi" / "remote.toml",
        notification_config_default=root / ".pi" / "notifications.toml",
        runtime_home=root / ".agents" / "runtime" / "tspi",
        runtime_manifest=root / ".agents" / "runtime" / "tspi" / "env.json",
        env_root=root / ".agents" / "envs" / "tspi",
        process_cache_root=root / ".pi" / "runtime-cache",
    )


def test_app_server_launcher_uses_workspace_owned_state_and_explicit_write_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    workspace = installation.root / "workspaces" / "reaction-a"
    (workspace / ".pi").mkdir(parents=True)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
    request = launcher.parse_launch_request([
        "--app-server",
        "--workspace",
        "reaction-a",
        "--allow-writes",
        "--source-root",
        "/opt/pi-source",
        "--provider",
        "anthropic",
    ])

    command = launcher.build_app_server_command(installation, workspace, request)

    state_root = workspace / ".pi" / "app-server"
    assert command == [
        "/usr/bin/node",
        str(installation.package_root / "apps" / "host" / "pi-app-server.mjs"),
        "server",
        "--workspace",
        str(workspace),
        "--directory",
        str(state_root / "server"),
        "--session-dir",
        str(state_root / "sessions"),
        "--allow-writes",
        "--source-root",
        "/opt/pi-source",
        "--provider",
        "anthropic",
    ]
    assert request.app_server is True
    assert request.app_client is False
    assert request.allow_writes is True
    for path in (state_root, state_root / "server", state_root / "sessions"):
        assert path.is_dir()
        assert stat.S_IMODE(path.stat().st_mode) == 0o700


def test_app_client_launcher_is_thin_and_keeps_connection_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
    request = launcher.parse_launch_request([
        "--app-client",
        "--connect",
        "unix:///run/tspi.sock",
        "--session-id",
        "session-1",
        "--continue",
    ])

    assert launcher.build_app_client_command(installation, request) == [
        "/usr/bin/node",
        str(installation.package_root / "apps" / "host" / "pi-app-server.mjs"),
        "client",
        "--session-id",
        "session-1",
        "--connect",
        "unix:///run/tspi.sock",
        "--continue",
    ]
    assert request.app_client is True
    assert request.app_server is False
    assert request.allow_writes is False


def test_app_client_launch_skips_scientific_runtime_and_workspace_locks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    monkeypatch.setattr(launcher, "resolve_installation", lambda *_args: installation)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
    for name in (
        "require_guarded_installation",
        "configure_runtime_environment",
        "ensure_runtime_python",
        "configure_remote",
        "configure_notifications",
        "acquire_directory_guard",
        "acquire_root_agent_lock",
    ):
        monkeypatch.setattr(launcher, name, lambda *_args, _name=name, **_kwargs: pytest.fail(f"called {_name}"))
    captured: dict[str, object] = {}

    def fake_exec(command: list[str], cwd: Path) -> None:
        captured.update(command=command, cwd=cwd)
        raise _ExecCalled

    monkeypatch.setattr(launcher, "exec_pi", fake_exec)

    with pytest.raises(_ExecCalled):
        launcher.launch(
            ["--app-client", "--connect", "unix:///run/tspi.sock", "--session-id", "session-1"],
            package_root=tmp_path / "unused-package",
            install_root=tmp_path / "unused-install",
        )

    assert captured == {
        "command": [
            "/usr/bin/node",
            str(installation.package_root / "apps" / "host" / "pi-app-server.mjs"),
            "client",
            "--session-id",
            "session-1",
            "--connect",
            "unix:///run/tspi.sock",
        ],
        "cwd": installation.root,
    }


@pytest.mark.parametrize(("allow_writes", "expected_mode"), [(False, "observer"), (True, "controller")])
def test_app_server_launch_binds_workspace_lifecycle_before_exec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    allow_writes: bool,
    expected_mode: str,
) -> None:
    installation = _installation(tmp_path)
    workspace = installation.workspaces_root / "reaction-a"
    (workspace / ".pi").mkdir(parents=True)
    (workspace / "workspace.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(launcher, "resolve_installation", lambda *_args: installation)
    monkeypatch.setattr(launcher, "require_guarded_installation", lambda *_args: None)
    monkeypatch.setattr(launcher, "configure_runtime_environment", lambda *_args: None)
    monkeypatch.setattr(launcher, "ensure_runtime_python", lambda *_args, **_kwargs: Path("/managed/python"))
    monkeypatch.setattr(launcher, "bind_runtime_process_environment", lambda *_args: None)
    monkeypatch.setattr(launcher, "configure_remote", lambda *_args: None)
    monkeypatch.setattr(launcher, "configure_notifications", lambda *_args: None)
    monkeypatch.setattr(launcher, "configure_process_environment", lambda *_args: None)
    monkeypatch.setattr(launcher, "resolve_existing_workspace", lambda *_args: workspace)
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
    captured: dict[str, object] = {}

    def fake_exec(command: list[str], cwd: Path) -> None:
        captured.update(command=command, cwd=cwd)
        raise _ExecCalled

    monkeypatch.setattr(launcher, "exec_pi", fake_exec)
    arguments = ["--app-server", "--workspace", "reaction-a", "--source-root", "/opt/pi-source"]
    if allow_writes:
        arguments.append("--allow-writes")

    with pytest.raises(_ExecCalled):
        launcher.launch(arguments, package_root=tmp_path / "unused-package", install_root=tmp_path / "unused-install")

    request = launcher.parse_launch_request(arguments)
    assert launcher._launch_access_mode(request) == expected_mode
    assert acquired == (["directory", "root"] if allow_writes else ["directory"])
    assert bootstrap_calls == ([workspace] if allow_writes else [])
    assert captured["cwd"] == workspace
    command = captured["command"]
    assert isinstance(command, list)
    assert ("--allow-writes" in command) is allow_writes


@pytest.mark.parametrize("allow_writes", [False, True])
def test_installed_app_server_launcher_executes_managed_native_entry(
    tmp_path: Path,
    allow_writes: bool,
) -> None:
    installation, installed_launcher = _copy_launcher(tmp_path)
    package = (installation / ".pi" / "packages" / "tspi" / "current" / "agent").resolve()
    entry = package / "apps" / "host" / "pi-app-server.mjs"
    entry.parent.mkdir(parents=True)
    entry.write_text("// fixture entry\n", encoding="utf-8")
    workspace = installation / "workspaces" / "reaction-a"
    if not allow_writes:
        (workspace / ".pi").mkdir(parents=True)
        (workspace / "workspace.json").write_text("{}\n", encoding="utf-8")
    fake_node = tmp_path / "node"
    fake_node.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "print(json.dumps({'args': sys.argv[1:], 'workspace': os.environ.get('TS_WORKSPACE_ROOT')}))\n",
        encoding="utf-8",
    )
    fake_node.chmod(0o755)
    arguments = [str(installed_launcher), "--app-server", "--workspace", "reaction-a", "--source-root", "/opt/pi-source"]
    if allow_writes:
        arguments.append("--allow-writes")

    completed = subprocess.run(
        arguments,
        cwd=installation,
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    state_root = workspace / ".pi" / "app-server"
    assert result["args"] == [
        str(entry),
        "server",
        "--workspace",
        str(workspace),
        "--directory",
        str(state_root / "server"),
        "--session-dir",
        str(state_root / "sessions"),
        *(["--allow-writes"] if allow_writes else []),
        "--source-root",
        "/opt/pi-source",
    ]
    assert result["workspace"] == str(workspace)
    assert (workspace / "workspace.json").is_file()
    assert (workspace / ".pi" / "root-agent.lock").exists() is allow_writes


def test_installed_writable_app_server_releases_root_lock_on_exit(tmp_path: Path) -> None:
    installation, installed_launcher = _copy_launcher(tmp_path)
    package = (installation / ".pi" / "packages" / "tspi" / "current" / "agent").resolve()
    entry = package / "apps" / "host" / "pi-app-server.mjs"
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
    command = [str(installed_launcher), "--app-server", "--workspace", "reaction-a", "--allow-writes"]
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
        ready = json.loads(holder.stdout.readline())
        assert ready["ready"] is True
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
    assert json.loads(replacement.stdout)["ready"] is True


def test_app_server_launcher_rejects_state_overrides_and_symlinks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    workspace = installation.root / "workspaces" / "reaction-a"
    (workspace / ".pi").mkdir(parents=True)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
    overridden = launcher.parse_launch_request([
        "--app-server",
        "--workspace",
        "reaction-a",
        "--directory",
        "/tmp/unbound-state",
    ])
    with pytest.raises(launcher.TSPiHostError, match="--directory is managed"):
        launcher.build_app_server_command(installation, workspace, overridden)

    app_state = workspace / ".pi" / "app-server"
    app_state.symlink_to(tmp_path / "elsewhere")
    normal = launcher.parse_launch_request(["--app-server", "--workspace", "reaction-a"])
    with pytest.raises(launcher.TSPiHostError, match="cannot be a symbolic link"):
        launcher.build_app_server_command(installation, workspace, normal)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--app-server", "--app-client"], "cannot be combined"),
        (["--app-client", "--allow-writes"], "requires --app-server"),
        (["--app-client", "--workspace", "reaction-a"], "does not accept --workspace"),
        (["--app-server", "--session-id", "session-1"], "belongs to --app-client"),
    ],
)
def test_app_server_launch_modes_fail_before_installation_resolution(
    arguments: list[str],
    message: str,
) -> None:
    with pytest.raises(launcher.TSPiHostError, match=message):
        launcher.launch(arguments, package_root="/missing", install_root="/missing")
