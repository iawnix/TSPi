from __future__ import annotations
from research_agent.foundation.layout import paths as layout_paths

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
from research_agent.bootstrap import launcher


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_VERSION = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]


def test_host_socket_limit_includes_private_pi_subdirectory(tmp_path, monkeypatch):
    # The public Host socket fits here, but the longest private Pi socket does not.
    base = "/" + "x" * 31
    monkeypatch.setenv("RESEARCH_AGENT_APP_SERVER_RUNTIME_DIR", base)
    with pytest.raises(launcher.ResearchAgentHostError, match="too long for Unix sockets"):
        launcher._private_socket_directory(tmp_path, create=False)


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
    entry = package / "apps/agent/main.mjs"
    entry.parent.mkdir(parents=True)
    entry.write_text("// test entry\n", encoding="utf-8")
    theme = package / "apps/agent/terminal/themes/research-agent.json"
    theme.parent.mkdir(parents=True)
    theme.write_text(json.dumps({"name": "research-agent"}) + "\n", encoding="utf-8")
    root = tmp_path / "install"
    root.mkdir()
    return launcher.Installation(
        root=root,
        package_root=package,
        workspaces_root=root / "workspaces",
        job_config_default=root / "etc/job.toml",
        notification_config_default=root / "etc/email.toml",
        runtime_home=root / "var/state/installation/python",
        runtime_manifest=root / "var/state/installation/python/env.json",
        env_root=root / ".agents/envs/research-agent",
        process_cache_root=root / "var/cache",
        model_icons_config=root / "etc/model-icons.json",
    )


def test_native_pi_settings_leave_unmanaged_values_unchanged(
    tmp_path: Path,
) -> None:
    installation = _installation(tmp_path)
    settings = installation.root / launcher.PI_AGENT_SETTINGS_RELATIVE
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"defaultProvider": "CPA", "defaultModel": "gpt-5.6-sol"}) + "\n",
        encoding="utf-8",
    )

    launcher._restore_native_pi_settings(installation)

    assert json.loads(settings.read_text(encoding="utf-8")) == {
        "defaultProvider": "CPA",
        "defaultModel": "gpt-5.6-sol",
    }


def test_native_pi_settings_remove_launcher_managed_theme(
    tmp_path: Path,
) -> None:
    installation = _installation(tmp_path)
    settings = installation.root / launcher.PI_AGENT_SETTINGS_RELATIVE
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "theme": "research-agent",
                "themes": [str(installation.package_root / launcher.RESEARCH_AGENT_THEME_RELATIVE)],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    launcher._restore_native_pi_settings(installation)

    assert json.loads(settings.read_text(encoding="utf-8")) == {"theme": "dark"}


def test_native_pi_settings_preserve_custom_theme_and_remove_old_release_theme(
    tmp_path: Path,
) -> None:
    installation = _installation(tmp_path)
    settings = installation.root / launcher.PI_AGENT_SETTINGS_RELATIVE
    settings.parent.mkdir(parents=True)
    theme_path = installation.root / "./releases/old/agent/apps/agent/terminal/themes/research-agent.json"
    settings.write_text(
        json.dumps({"theme": "lab-dark", "themes": [str(theme_path), "./custom-theme.json"]}) + "\n",
        encoding="utf-8",
    )

    launcher._restore_native_pi_settings(installation)

    assert json.loads(settings.read_text(encoding="utf-8")) == {
        "theme": "lab-dark",
        "themes": ["./custom-theme.json"],
    }


def test_native_pi_settings_reject_invalid_json_and_symlinks(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    settings = installation.root / launcher.PI_AGENT_SETTINGS_RELATIVE
    settings.parent.mkdir(parents=True)
    settings.write_text("not json\n", encoding="utf-8")

    with pytest.raises(launcher.ResearchAgentHostError, match="invalid Pi agent settings"):
        launcher._restore_native_pi_settings(installation)

    settings.unlink()
    target = tmp_path / "settings-target.json"
    target.write_text("{}\n", encoding="utf-8")
    settings.symlink_to(target)

    with pytest.raises(launcher.ResearchAgentHostError, match="Pi agent settings cannot be a symbolic link"):
        launcher._restore_native_pi_settings(installation)


def test_native_pi_settings_do_not_require_the_release_theme(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    (installation.package_root / launcher.RESEARCH_AGENT_THEME_RELATIVE).unlink()

    launcher._restore_native_pi_settings(installation)

    assert not (installation.root / launcher.PI_AGENT_SETTINGS_RELATIVE).exists()


def test_research_agent_launcher_disables_retired_custom_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    workspace = installation.workspaces_root / "reaction-a"
    workspace.mkdir(parents=True)
    monkeypatch.setenv("RESEARCH_AGENT_CUSTOM_UI", "1")
    original_environment = dict(os.environ)

    try:
        launcher.configure_process_environment(installation, workspace, "reaction-a")
        assert "RESEARCH_AGENT_CUSTOM_UI" not in os.environ
    finally:
        os.environ.clear()
        os.environ.update(original_environment)


def test_research_agent_launcher_preserves_validated_custom_compute_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    workspace = installation.workspaces_root / "reaction-a"
    workspace.mkdir(parents=True)
    custom = tmp_path / "job.toml"
    custom.write_text("default_environment = 'local'\n", encoding="utf-8")
    monkeypatch.setenv("RESEARCH_AGENT_JOB_CONFIG", str(custom))

    launcher.configure_process_environment(installation, workspace, "reaction-a")

    assert os.environ["RESEARCH_AGENT_JOB_CONFIG"] == str(custom)


def _copy_launcher(tmp_path: Path) -> tuple[Path, Path]:
    install_root = tmp_path / "research-agent-install"
    package_home = install_root / "."
    suite_root = package_home / "releases/test-suite"
    package_root = suite_root / "agent"
    package_root.mkdir(parents=True)
    (package_root / "package.json").write_text(
        json.dumps({"name": "@iawnix/research-agent", "version": PACKAGE_VERSION}) + "\n",
        encoding="utf-8",
    )
    (package_root / "apps/agent/terminal/themes").mkdir(parents=True)
    shutil.copy2(ROOT / "apps/agent/terminal/themes/research-agent.json", package_root / "apps/agent/terminal/themes/research-agent.json")
    write_test_suite_manifest(suite_root, version=PACKAGE_VERSION)
    shutil.copy2(ROOT / "research-agent", package_root / "research-agent")
    (package_root / "research-agent").chmod(0o755)
    (package_root / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts" / "_bootstrap.py", package_root / "scripts" / "_bootstrap.py")
    (package_root / "apps/agent-cli").mkdir(parents=True)
    shutil.copy2(ROOT / "apps/agent-cli/launcher.py", package_root / "apps/agent-cli/launcher.py")
    shutil.copy2(ROOT / "scripts" / "pi-loader.mjs", package_root / "scripts" / "pi-loader.mjs")
    shutil.copytree(
        ROOT / "backend/src",
        package_root / "backend/src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
    )
    shutil.copy2(ROOT / "environment.yml", package_root / "environment.yml")
    shutil.copy2(ROOT / "environment.lock.txt", package_root / "environment.lock.txt")
    write_test_runtime_manifest(package_root, install_root)
    (package_home / "current").symlink_to("releases/test-suite")
    installed_launcher = install_root / "research-agent"
    installed_launcher.symlink_to("./current/agent/research-agent")
    return install_root, installed_launcher


def test_resolve_installation_uses_configured_workspace_root(tmp_path: Path) -> None:
    install_root, _launcher = _copy_launcher(tmp_path)
    workspace_root = tmp_path / "research-projects"
    layout_paths(install_root).update_config(workspace_root=str(workspace_root))
    package_root = install_root / "./current/agent"

    installation = launcher.resolve_installation(package_root, install_root)

    assert installation.workspaces_root == workspace_root


def test_resolve_installation_explains_stale_standalone_agent(tmp_path: Path) -> None:
    install_root, _launcher = _copy_launcher(tmp_path)
    stale_agent = tmp_path / "legacy-agent"
    stale_agent.mkdir()

    with pytest.raises(launcher.ResearchAgentHostError, match="old standalone Agent") as failure:
        launcher.resolve_installation(stale_agent, install_root)

    message = str(failure.value)
    assert "launcher=" in message
    assert "selected=" in message
    assert "restart research-agent.service" in message


def test_model_icon_marker_enables_research_agent_style_and_preserves_explicit_style(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    font = tmp_path / "fonts/ResearchAgent-Model-Icons.ttf"
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
    monkeypatch.delenv("RESEARCH_AGENT_ICON_STYLE", raising=False)

    assert launcher.configure_model_icon_environment(installation) is True
    assert os.environ["RESEARCH_AGENT_ICON_STYLE"] == "research-agent"

    monkeypatch.setenv("RESEARCH_AGENT_ICON_STYLE", "unicode")
    assert launcher.configure_model_icon_environment(installation) is False
    assert os.environ["RESEARCH_AGENT_ICON_STYLE"] == "unicode"


def test_invalid_model_icon_marker_does_not_enable_research_agent_style(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.delenv("RESEARCH_AGENT_ICON_STYLE", raising=False)

    assert launcher.configure_model_icon_environment(installation) is False
    assert "RESEARCH_AGENT_ICON_STYLE" not in os.environ


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
    request = launcher.parse_launch_request(["--host"])

    command = launcher.build_host_server_command(installation, request)

    state_root = installation.root / "var/state/host"
    assert command == [
        "/usr/bin/node",
        str(installation.package_root / "apps/agent/main.mjs"),
        "server",
        "--workspace",
        str(installation.workspaces_root),
        "--directory",
        str(socket_directory),
        "--server-id",
        server_id,
        "--state-root",
        str(state_root),
    ]
    assert request.host is True
    assert (installation.root / "workspaces").is_dir()
    assert state_root.is_dir()


def test_service_host_does_not_require_a_workspace_mode() -> None:
    request = launcher.parse_launch_request(["--service-host"])

    assert request.host is True
    assert request.workspace_mode == "research"


def test_launcher_usage_keeps_internal_transport_modes_out_of_daily_help() -> None:
    assert "research-agent --workspace <name>" in launcher.USAGE
    assert "research-agent.service" in launcher.USAGE
    for internal_mode in ("--service-host", "--app-server", "--app-client", "--gateway", "--standalone"):
        assert internal_mode not in launcher.USAGE


def test_standalone_is_removed_and_points_to_host_client() -> None:
    with pytest.raises(launcher.ResearchAgentHostError, match="--standalone was removed"):
        launcher.parse_launch_request(["--standalone", "--workspace", "reaction-a"])


def test_session_selection_is_workspace_scoped_and_explicit() -> None:
    new_session = launcher.parse_launch_request(["--workspace", "reaction-a"])
    latest = launcher.parse_launch_request(["--workspace", "reaction-a", "-c", "--provider", "anthropic"])

    assert new_session.continue_latest is False
    assert new_session.session_id is None
    assert latest.continue_latest is True
    assert latest.pi_args == ("--provider", "anthropic")

    with pytest.raises(launcher.ResearchAgentHostError, match="cannot be combined"):
        launcher.parse_launch_request([
            "--workspace", "reaction-a", "--continue", "--session-id", "session-1",
        ])


def test_remote_terminal_options_are_parsed_and_forwarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
    request = launcher.parse_launch_request([
        "--workspace", "reaction-a",
        "--remote-host", "pi.example",
        "--remote-host-socket", "/run/user/1000/research-agent/host.sock",
        "--remote-proxy-path", "/opt/research-agent/apps/agent/transport/ssh.mjs",
        "--ssh-config", "/home/test/.ssh/config",
        "--ssh-option", "-i",
        "--ssh-option", "/home/test/.ssh/id_ed25519",
    ])
    command = launcher.build_host_client_command(installation, request)
    assert "--socket-path" not in command
    assert command[command.index("--ssh-host") + 1] == "pi.example"
    assert command[command.index("--remote-host-socket") + 1] == "/run/user/1000/research-agent/host.sock"
    assert command[command.index("--remote-proxy-path") + 1].endswith("transport/ssh.mjs")
    assert command.count("--ssh-option") == 2


def test_remote_terminal_requires_proxy_paths() -> None:
    request = launcher.parse_launch_request(["--workspace", "reaction-a", "--remote-host", "pi.example"])
    with pytest.raises(launcher.ResearchAgentHostError, match="--remote-host-socket"):
        launcher._validate_remote_terminal_request(request)
    with pytest.raises(launcher.ResearchAgentHostError, match="--remote-host is required"):
        launcher.parse_launch_request(["--workspace", "reaction-a", "--remote-host-socket", "/run/research-agent/host.sock"])


def test_remote_terminal_uses_owner_only_installation_profile(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    profile = installation.root / launcher.REMOTE_HOST_CONFIG_RELATIVE
    profile.parent.mkdir(parents=True)
    profile.write_text(json.dumps({
        "schema_version": launcher.REMOTE_HOST_CONFIG_SCHEMA,
        "ssh_host": "pi.example",
        "host_socket": "/run/research-agent/host.sock",
        "proxy_path": "/opt/research-agent/apps/agent/transport/ssh.mjs",
        "ssh_config": None,
        "ssh_options": ["-i", "/home/test/.ssh/id_ed25519"],
    }) + "\n", encoding="utf-8")
    profile.chmod(0o600)
    configured = launcher.resolve_remote_terminal_request(
        replace(installation, remote_host_config=profile),
        launcher.parse_launch_request(["--workspace", "reaction-a"]),
    )
    assert configured.remote_host == "pi.example"
    assert configured.remote_host_socket == "/run/research-agent/host.sock"
    assert configured.ssh_options == ("-i", "/home/test/.ssh/id_ed25519")


@pytest.mark.parametrize("arguments", [
    ["--workspace", "reaction-a"],
])
def test_workspace_mode_is_parsed_by_the_public_research_agent_entrypoint(arguments: list[str]) -> None:
    request = launcher.parse_launch_request(arguments)
    assert request.workspace_mode == "research"


def test_workspace_mode_rejects_unknown_values() -> None:
    with pytest.raises(launcher.ResearchAgentHostError, match="mode selection was removed"):
        launcher.parse_launch_request(["--workspace", "reaction-a", "--mode", "compute"])


def test_launcher_binds_and_admits_research_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces" / "reaction-a"

    manifest = launcher.bind_workspace_mode(workspace, "reaction-a")

    assert manifest["workspace_mode"] == "research"
    assert manifest["state"] == "ready"
    assert json.loads((workspace / "research/journal.json").read_text(encoding="utf-8"))["schema_version"] == "research-journal/2"
    assert not (workspace / "research_map.json").exists()
    assert not (workspace / "research.db").exists()


@pytest.mark.parametrize("option", ["-r", "--resume"])
def test_startup_resume_rejects_the_false_selector_semantics(option: str) -> None:
    with pytest.raises(launcher.ResearchAgentHostError, match="use /resume inside the terminal") as failure:
        launcher.parse_launch_request(["--workspace", "reaction-a", option])

    assert failure.value.exit_code == 2


def test_phone_management_commands_are_parsed_before_workspace_selection() -> None:
    pairing = launcher.parse_launch_request(["phone", "pair"])
    devices = launcher.parse_launch_request(["phone", "devices"])
    revoke = launcher.parse_launch_request(["phone", "revoke", "223e4567-e89b-42d3-a456-426614174000"])

    assert pairing.phone_action == "pair"
    assert devices.phone_action == "devices"
    assert revoke.phone_action == "revoke"
    assert revoke.phone_device_id == "223e4567-e89b-42d3-a456-426614174000"

    with pytest.raises(launcher.ResearchAgentHostError, match="usage: research-agent phone"):
        launcher.parse_launch_request(["phone", "revoke"])


def test_host_state_prepares_private_pi_workspace_before_root_lock(tmp_path: Path) -> None:
    installation = _installation(tmp_path)

    host_workspace, state_root = launcher._prepare_host_state(installation)

    assert host_workspace == state_root / "workspace"
    assert (host_workspace / ".pi").is_dir()
    assert stat.S_IMODE((host_workspace / ".pi").stat().st_mode) == 0o700


def test_host_environment_publishes_owner_only_worker_diagnostics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESEARCH_AGENT_PI_RUNTIME_ROOT", raising=False)
    installation = _installation(tmp_path)
    pin = json.loads((ROOT / "config/pi-source.json").read_text(encoding="utf-8"))
    commit = pin["commit"]
    (installation.package_root / "config").mkdir(parents=True)
    (installation.package_root / "config/pi-source.json").write_text(json.dumps(pin) + "\n", encoding="utf-8")
    (installation.root / "runtimes/pi" / commit).mkdir(parents=True)
    diagnostic = installation.root / "var/log/worker-diagnostics.log"
    diagnostic.parent.mkdir(parents=True, exist_ok=True)
    diagnostic.write_text("stale worker error\n", encoding="utf-8")
    original_environment = dict(os.environ)
    try:
        launcher.configure_host_process_environment(installation)
        assert os.environ["RESEARCH_AGENT_PI_RUNTIME_ROOT"] == str(
            installation.root / "runtimes/pi" / commit
        )
        assert os.environ["RESEARCH_AGENT_PI_DIAGNOSTIC_FILE"] == str(diagnostic)
        assert diagnostic.is_file()
        assert diagnostic.read_text(encoding="utf-8") == ""
        assert stat.S_IMODE(diagnostic.stat().st_mode) == 0o600
    finally:
        os.environ.clear()
        os.environ.update(original_environment)



def test_host_state_rejects_an_insecure_installation_pi_directory(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    installation.root.joinpath("var/state").mkdir(mode=0o700, parents=True)
    installation.root.joinpath("var/state").chmod(0o755)

    with pytest.raises(launcher.ResearchAgentHostError, match="must be owner-only"):
        launcher._prepare_host_state(installation)


def test_host_endpoint_requires_one_unix_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
    monkeypatch.setattr(launcher, "_host_server_id", lambda *_args, **_kwargs: "stale")
    monkeypatch.setattr(launcher, "_host_socket_directory", lambda *_args, **_kwargs: tmp_path / "missing-socket")
    with pytest.raises(launcher.ResearchAgentHostUnavailableError, match="ResearchAgent Host is not running"):
        launcher.resolve_host_socket(installation)


def test_host_endpoint_removes_stale_unix_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    monkeypatch.setattr(launcher, "_host_server_id", lambda *_args, **_kwargs: "stale")
    socket_directory = tmp_path
    socket_directory.mkdir(exist_ok=True)
    monkeypatch.setattr(launcher, "_host_socket_directory", lambda *_args, **_kwargs: socket_directory)
    endpoint = socket_directory / "stale.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(endpoint))
    listener.close()

    with pytest.raises(launcher.ResearchAgentHostUnavailableError, match="socket is stale"):
        launcher.resolve_host_socket(installation)
    assert not endpoint.exists()


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
            raise launcher.ResearchAgentHostUnavailableError("not running")
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
        host_runtime_dir=Path("/run/research-agent"),
    )
    endpoint = tmp_path / "host.sock"
    monkeypatch.setattr(
        launcher,
        "resolve_host_socket",
        lambda _installation: (_ for _ in ()).throw(launcher.ResearchAgentHostUnavailableError("not running"))
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
        lambda _installation: (_ for _ in ()).throw(launcher.ResearchAgentHostUnavailableError("not running")),
    )
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/systemctl" if name == "systemctl" else None)
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 1, "", "unit failed"),
    )

    with pytest.raises(launcher.ResearchAgentHostError, match="unit failed"):
        launcher.ensure_host_running(installation)


def test_gateway_attaches_one_host_session_with_http_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)
    server_id = "123e4567-e89b-42d3-a456-426614174000"
    # AF_UNIX paths are capped at 108 bytes; keep the test socket root short.
    socket_directory = tmp_path.parent.parent / f"gw-{os.getpid()}"
    socket_directory.mkdir()
    monkeypatch.setattr(launcher, "_host_server_id", lambda *_args, **_kwargs: server_id)
    monkeypatch.setattr(launcher, "_host_socket_directory", lambda *_args, **_kwargs: socket_directory)
    endpoint = socket_directory / f"{server_id}.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(endpoint))
    listener.listen(1)
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
        str(installation.package_root / "apps/agent/transport/browser.mjs"),
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
    # AF_UNIX paths are capped at 108 bytes; keep the test socket root short.
    server = tmp_path.parent.parent / f"cl-{os.getpid()}"
    server.mkdir(mode=0o700, exist_ok=True)
    monkeypatch.setattr(launcher, "_host_server_id", lambda *_args, **_kwargs: server_id)
    monkeypatch.setattr(launcher, "_host_socket_directory", lambda *_args, **_kwargs: server)
    endpoint = server / f"{server_id}.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(endpoint))
    listener.listen(1)
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
        str(installation.package_root / "apps/agent/terminal/main.mjs"),
        "--socket-path", str(endpoint),
        "--workspace-id", "reaction-a",
        "--workspace-root", str(installation.workspaces_root / "reaction-a"),
        "--state-root", str(installation.root / "var/state/host"),
        "--install-root", str(installation.root),
        "--package-root", str(installation.package_root),
        "--continue",
        "--",
    ]


def test_default_terminal_binds_standalone_release_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = replace(
        _installation(tmp_path),
        package_root=tmp_path / "./releases/release-direct",
    )
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)

    command = launcher.build_host_client_command(
        installation,
        launcher.parse_launch_request(["--workspace", "reaction-a"]),
        socket_path=tmp_path / "host.sock",
    )

    assert "--expected-release-id" in command
    assert command[command.index("--expected-release-id") + 1] == "release-direct"


def test_default_terminal_exports_installation_pinned_pi_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = _installation(tmp_path)
    source = installation.root / "runtimes/pi/pinned"
    source.mkdir(parents=True)
    (installation.package_root / "config").mkdir(parents=True)
    (installation.package_root / "config/pi-source.json").write_text(
        json.dumps({"commit": "pinned"}) + "\n",
        encoding="utf-8",
    )
    endpoint = tmp_path / "host.sock"
    captured: dict[str, object] = {}

    def stop_exec(command: list[str], workspace: Path) -> None:
        captured["command"] = command
        captured["workspace"] = workspace
        raise RuntimeError("stop test client")

    monkeypatch.delenv("RESEARCH_AGENT_PI_RUNTIME_ROOT", raising=False)
    monkeypatch.setattr(launcher, "ensure_host_running", lambda _installation: endpoint)
    monkeypatch.setattr(launcher, "exec_pi", stop_exec)

    with pytest.raises(RuntimeError, match="stop test client"):
        launcher.launch_terminal(
            installation,
            launcher.parse_launch_request(["--workspace", "reaction-a"]),
            installation.workspaces_root / "reaction-a",
        )

    assert os.environ["RESEARCH_AGENT_PI_RUNTIME_ROOT"] == str(source.resolve())
    assert captured["workspace"] == installation.workspaces_root / "reaction-a"


def test_native_runtime_flag_is_rejected() -> None:
    with pytest.raises(launcher.ResearchAgentHostError, match="--native-runtime was removed"):
        launcher.parse_launch_request(["--workspace", "reaction-a", "--native-runtime"])


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
    with pytest.raises(launcher.ResearchAgentHostError, match=message):
        launcher.launch(arguments, package_root="/missing", install_root="/missing")
