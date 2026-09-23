from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from ts_agent.runtime import session_guard
from ts_agent.runtime.session_guard import (
    SessionGuardError,
    acquire_directory_guard,
    acquire_session_guard,
    assert_no_unguarded_writers,
    guard_installation_upgrade,
    installation_is_guarded,
    require_guarded_installation,
    select_session,
)
from ts_agent.workspace import init_workspace


def _install_state(root: Path) -> Path:
    state = root / ".pi/packages/tspi/install-state.json"
    release = state.parent / "releases/release-1"
    release.mkdir(parents=True)
    state.write_text(
        json.dumps({
            "schema_version": "tspi-package-install/1",
            "current_release_id": "release-1",
            "package_root": str(release),
            "session_guard_contract": session_guard.CONTRACT,
        }) + "\n",
        encoding="utf-8",
    )
    state.chmod(0o600)
    return state


def test_guarded_installation_requires_private_bound_state(tmp_path: Path) -> None:
    state = _install_state(tmp_path)
    assert installation_is_guarded(tmp_path)
    require_guarded_installation(tmp_path)

    state.chmod(0o644)
    with pytest.raises(SessionGuardError, match="owner-only"):
        installation_is_guarded(tmp_path)


def test_guards_live_outside_retired_shared_host_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces/reaction-a"
    directory = acquire_directory_guard(tmp_path, workspace)
    session = acquire_session_guard(tmp_path, workspace, "session-1", "controller")
    try:
        guard_root = session_guard.guard_directory(tmp_path, workspace)
        assert guard_root.is_relative_to(tmp_path / ".pi/session-guards")
        assert not (tmp_path / ".pi/session-host").exists()
        with pytest.raises(SessionGuardError):
            acquire_session_guard(tmp_path, workspace, "session-1", "controller")
    finally:
        os.close(session)
        os.close(directory)


def test_upgrade_holds_workspace_directory_and_root_locks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspaces/reaction-a"
    (workspace / ".pi").mkdir(parents=True)
    inspected: list[Path] = []
    monkeypatch.setattr(session_guard, "assert_no_unguarded_writers", inspected.append)
    with guard_installation_upgrade(tmp_path):
        with pytest.raises(SessionGuardError) as error:
            acquire_directory_guard(tmp_path, workspace)
        assert error.value.code == "session_writer_active"
    assert inspected == [workspace]


def test_upgrade_prepares_pi_state_for_research_workspace_without_pi_directory(
    tmp_path: Path,
) -> None:
    """Web-created ResearchMap workspaces may not have Pi state yet."""

    workspace = tmp_path / "workspaces" / "ts_001"
    init_workspace(workspace)
    pi_root = workspace / ".pi"
    assert not pi_root.exists()

    with guard_installation_upgrade(tmp_path):
        assert pi_root.is_dir()
        assert stat.S_IMODE(pi_root.stat().st_mode) == 0o700
        assert (pi_root / "root-agent.lock").is_file()


def test_upgrade_uses_persisted_external_workspace_root(tmp_path: Path) -> None:
    external_root = tmp_path / "research-projects"
    workspace = external_root / "ts_001"
    init_workspace(workspace)
    control = tmp_path / ".pi" / "tspi"
    control.mkdir(parents=True)
    (control / "workspace-root.json").write_text(
        json.dumps({
            "schema_version": "tspi-workspace-root/1",
            "workspace_root": str(external_root),
        }) + "\n",
        encoding="utf-8",
    )

    with guard_installation_upgrade(tmp_path):
        assert (workspace / ".pi" / "root-agent.lock").is_file()

    assert not (tmp_path / "workspaces").exists()


def test_select_session_uses_exact_workspace_history(tmp_path: Path) -> None:
    directory = tmp_path / ".pi/sessions"
    directory.mkdir(parents=True)
    history = directory / "history.jsonl"
    original = json.dumps({"type": "session", "id": "old-session", "cwd": str(tmp_path), "version": 3}) + "\n"
    history.write_text(original, encoding="utf-8")

    for arguments in (["--continue"], ["--session", str(history)], ["--session-id", "old-session"]):
        identity, forwarded = select_session(tmp_path, list(arguments))
        assert identity == "old-session"
        assert forwarded == ["--session-id", "old-session"]
        assert history.read_text(encoding="utf-8") == original


def test_select_session_leaves_new_identity_to_pi(tmp_path: Path) -> None:
    (tmp_path / ".pi/sessions").mkdir(parents=True)

    identity, forwarded = select_session(tmp_path, ["--model", "gpt-5.5"])
    continued_identity, continued = select_session(tmp_path, ["--continue"])

    assert identity is None
    assert forwarded == ["--model", "gpt-5.5"]
    assert continued_identity is None
    assert continued == ["--continue"]


@pytest.mark.parametrize("arguments", [
    ["--resume"],
    ["--fork", "old-session"],
    ["--session-dir", "/tmp"],
    ["--no-session"],
    ["--session-id", "../escape"],
    ["--continue", "--session-id", "old-session"],
])
def test_unguarded_session_selectors_are_rejected(tmp_path: Path, arguments: list[str]) -> None:
    with pytest.raises(SessionGuardError):
        select_session(tmp_path, arguments)


def test_installer_detects_an_unguarded_workspace_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = tmp_path / "proc"
    process = proc / str(os.getpid() + 1)
    process.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (process / "cmdline").write_bytes(
        b"node\0pi/cli.js\0--session-dir\0" + os.fsencode(workspace / ".pi/sessions") + b"\0"
    )
    (process / "environ").write_bytes(b"TS_WORKSPACE_ROOT=" + os.fsencode(workspace) + b"\0")
    monkeypatch.setattr(session_guard, "_PROC_ROOT", proc)

    with pytest.raises(SessionGuardError, match="unguarded TSPi writer") as error:
        assert_no_unguarded_writers(workspace)
    assert error.value.code == "session_writer_active"
