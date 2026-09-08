from __future__ import annotations

import json
import os
import select
import subprocess
from pathlib import Path

import pytest

from ts_agent.runtime import session_guard
from ts_agent.runtime.session_guard import (
    SessionGuardError, acquire_directory_guard, acquire_session_guard,
    assert_no_unguarded_writers, select_session, verify_session_writer,
    guard_installation_upgrade, installation_is_guarded, require_guarded_installation,
)
from tests.test_ts_phone_integration import ROOT, TS_LOADER, _copy_launcher


def test_daily_launcher_does_not_inspect_global_processes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ts_agent.runtime import launcher as host

    installation, executable = _copy_launcher(tmp_path)
    package = executable.resolve().parent
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(session_guard, "_PROC_ROOT", tmp_path / "unreadable-proc")
    launched = []

    class Started(Exception):
        pass

    def capture(command: list[str], workspace: Path) -> None:
        launched.append(workspace.name)
        raise Started

    monkeypatch.setattr(host, "exec_pi", capture)
    with pytest.raises(Started):
        host.launch(["--standalone", "--workspace", "ts_001"], package_root=package, install_root=installation)
    assert launched == ["ts_001"]
    assert host.launch(["--workspace", "ts_001", "--lifecycle-preflight"],
        package_root=package, install_root=installation) == 0


def test_guard_upgrade_requires_a_private_record_and_does_not_run_during_startup(tmp_path: Path) -> None:
    installation, executable = _copy_launcher(tmp_path)
    state = installation / ".pi/packages/tspi/install-state.json"
    assert installation_is_guarded(installation)
    state.unlink()
    result = subprocess.run([str(executable), "--workspace", "ts_001", "--phone-worker",
        "--session-id", "session-1", "--phone-access", "controller"], capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert json.loads(result.stderr.splitlines()[-1])["code"] == "session_guard_upgrade_required"
    assert not (installation / "workspaces").exists()
    with pytest.raises(SessionGuardError) as error:
        require_guarded_installation(installation)
    assert error.value.code == "session_guard_upgrade_required"
    state.write_text(json.dumps({"session_guard_contract": session_guard.CONTRACT}))
    state.chmod(0o644)
    with pytest.raises(SessionGuardError, match="owner-only"):
        installation_is_guarded(installation)


def test_upgrade_holds_workspace_locks_and_subsequent_upgrades_skip_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspaces/ts_001"
    workspace.mkdir(parents=True)
    inspected = []
    monkeypatch.setattr(session_guard, "assert_no_unguarded_writers", lambda root: inspected.append(root))
    with guard_installation_upgrade(tmp_path):
        with pytest.raises(SessionGuardError) as error:
            acquire_directory_guard(tmp_path, workspace)
        assert error.value.code == "session_writer_active"
    assert inspected == [workspace]
    state = tmp_path / ".pi/packages/tspi/install-state.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({
        "schema_version": "tspi-package-install/1", "current_release_id": "guarded-release",
        "package_root": str(state.parent / "releases/guarded-release"),
        "session_guard_contract": session_guard.CONTRACT,
    }))
    state.chmod(0o600)
    descriptor = acquire_directory_guard(tmp_path, workspace)
    try:
        with guard_installation_upgrade(tmp_path):
            pass
        assert inspected == [workspace]
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("change", [
    {"schema_version": "not-an-installation"}, {"current_release_id": "other-release"},
    {"package_root": "/another-installation/.pi/packages/tspi/releases/test"},
])
def test_guard_upgrade_record_cannot_be_reused_for_another_installation(tmp_path: Path, change: dict) -> None:
    installation, executable = _copy_launcher(tmp_path)
    state = installation / ".pi/packages/tspi/install-state.json"
    state.write_text(json.dumps({**json.loads(state.read_text()), **change}))
    with pytest.raises(SessionGuardError, match="does not match this installation"):
        installation_is_guarded(installation)
    result = subprocess.run([str(executable), "--session-host-capabilities"],
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert result.stdout == ""
    assert json.loads(result.stderr.splitlines()[-1])["code"] == "session_guard_invalid"


def test_guard_corruption_is_not_reported_as_an_active_writer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ts_agent.runtime import launcher as host

    installation, executable = _copy_launcher(tmp_path)
    monkeypatch.setattr(os, "environ", os.environ.copy())
    workspace = installation / "workspaces/ts_001"
    workspace.mkdir(parents=True)
    descriptor = acquire_directory_guard(installation, workspace)
    os.close(descriptor)
    (session_guard.guard_directory(installation, workspace) / "directory.lock").chmod(0o644)
    assert host.main(["--workspace", "ts_001", "--lifecycle-preflight"],
        package_root=executable.resolve().parent, install_root=installation) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err.splitlines()[-1])["code"] == "session_guard_invalid"


@pytest.fixture
def process_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    proc = tmp_path / "proc"
    process = proc / str(os.getpid() + 1)
    process.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (process / "cwd").symlink_to(workspace)
    (process / "cmdline").write_bytes(
        b"node\0pi/cli.js\0--session-dir\0" + os.fsencode(workspace / ".pi" / "sessions") + b"\0"
    )
    (process / "environ").write_bytes(b"TS_WORKSPACE_ROOT=" + os.fsencode(workspace) + b"\0")
    monkeypatch.setattr(session_guard, "_PROC_ROOT", proc)
    return process, workspace


@pytest.mark.parametrize("command", [b"/usr/lib/systemd/systemd\0--user\0", b"ssh-agent\0", b""])
def test_unrelated_process_private_state_is_never_read(
    process_snapshot: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, command: bytes,
) -> None:
    process, workspace = process_snapshot
    (process / "cmdline").write_bytes(command)
    read_bytes = Path.read_bytes
    resolve = Path.resolve

    def protected_read(path: Path) -> bytes:
        if path == process / "environ":
            pytest.fail("unrelated process environment must not be read")
        return read_bytes(path)

    def protected_resolve(path: Path, **kwargs: object) -> Path:
        if path == process / "cwd":
            raise PermissionError("unrelated privileged user service")
        return resolve(path, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", protected_read)
    monkeypatch.setattr(Path, "resolve", protected_resolve)
    assert_no_unguarded_writers(workspace)


@pytest.mark.parametrize("binding", ["absolute", "inline", "relative", "different-cwd", "systemd-name", "pi-title"])
def test_unguarded_writer_is_rejected_by_session_directory(
    process_snapshot: tuple[Path, Path], binding: str,
) -> None:
    process, workspace = process_snapshot
    directory = os.fsencode(workspace / ".pi" / "sessions")
    if binding == "inline":
        (process / "cmdline").write_bytes(b"node\0--session-dir=" + directory + b"\0")
    elif binding == "relative":
        (process / "cmdline").write_bytes(b"node\0--session-dir\0.pi/sessions\0")
    elif binding == "different-cwd":
        (process / "cwd").unlink()
        (process / "cwd").symlink_to(workspace.parent)
    elif binding == "systemd-name":
        (process / "cmdline").write_bytes(b"systemd\0--session-dir\0" + directory + b"\0")
    elif binding == "pi-title":
        (process / "cmdline").write_bytes(b"pi\0\0\0")
    with pytest.raises(SessionGuardError, match="unguarded TSPi writer") as error:
        assert_no_unguarded_writers(workspace)
    assert error.value.code == "session_writer_active"


def test_other_workspace_writer_does_not_require_private_environment(
    process_snapshot: tuple[Path, Path],
) -> None:
    process, workspace = process_snapshot
    (process / "cmdline").write_bytes(b"node\0--session-dir\0/another/workspace/.pi/sessions\0")
    (process / "environ").unlink()
    assert_no_unguarded_writers(workspace)


@pytest.mark.parametrize("retitled", [False, True])
def test_guarded_writer_must_also_match_workspace(process_snapshot: tuple[Path, Path], retitled: bool) -> None:
    process, workspace = process_snapshot
    if retitled:
        (process / "cmdline").write_bytes(b"pi\0\0")
    (process / "environ").write_bytes(
        b"TS_WORKSPACE_ROOT=" + os.fsencode(workspace) + b"\0TS_SESSION_GUARD=" + session_guard.CONTRACT.encode() + b"\0"
    )
    assert_no_unguarded_writers(workspace)
    (process / "environ").write_bytes(b"TS_SESSION_GUARD=" + session_guard.CONTRACT.encode() + b"\0")
    if retitled:
        assert_no_unguarded_writers(workspace)
        return
    with pytest.raises(SessionGuardError) as error:
        assert_no_unguarded_writers(workspace)
    assert error.value.code == "session_writer_active"


def test_retitled_pi_from_another_workspace_is_not_a_conflict(process_snapshot: tuple[Path, Path]) -> None:
    process, workspace = process_snapshot
    (process / "cmdline").write_bytes(b"pi\0")
    (process / "environ").write_bytes(b"TS_WORKSPACE_ROOT=/another/workspace\0")
    assert_no_unguarded_writers(workspace)


@pytest.mark.parametrize(("private_file", "retitled"), [("cmdline", False), ("environ", False), ("environ", True)])
def test_unverifiable_candidate_fails_closed_with_specific_code(
    process_snapshot: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, private_file: str, retitled: bool,
) -> None:
    process, workspace = process_snapshot
    if retitled:
        (process / "cmdline").write_bytes(b"pi\0")
    read_bytes = Path.read_bytes

    def protected_read(path: Path) -> bytes:
        if path == process / private_file:
            raise PermissionError("private diagnostic")
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", protected_read)
    with pytest.raises(SessionGuardError, match=process.name) as error:
        assert_no_unguarded_writers(workspace)
    assert error.value.code == "session_writer_inspection_failed"
    assert "private diagnostic" not in str(error.value)


def test_exited_process_does_not_block_startup(process_snapshot: tuple[Path, Path]) -> None:
    process, workspace = process_snapshot
    (process / "cmdline").unlink()
    assert_no_unguarded_writers(workspace)


def test_missing_proc_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_guard, "_PROC_ROOT", tmp_path / "missing-proc")
    with pytest.raises(SessionGuardError) as error:
        assert_no_unguarded_writers(tmp_path / "workspace")
    assert error.value.code == "session_writer_inspection_failed"


def test_real_retitled_unguarded_pi_is_detected_without_relying_on_cwd(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    environment = {key: value for key, value in os.environ.items() if key != "TS_SESSION_GUARD"}
    environment["TS_WORKSPACE_ROOT"] = str(workspace)
    child = subprocess.Popen([
        "node", "--input-type=module", "-e",
        "process.title='pi'; console.log('ready'); process.stdin.resume(); process.stdin.on('end',()=>process.exit(0));",
    ], cwd=tmp_path, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([child.stdout], [], [], 10)[0]
        assert child.stdout.readline().strip() == "ready"
        assert (Path("/proc") / str(child.pid) / "cmdline").read_bytes().split(b"\0")[0] == b"pi"
        with pytest.raises(SessionGuardError, match=str(child.pid)) as error:
            assert_no_unguarded_writers(workspace)
        assert error.value.code == "session_writer_active"
    finally:
        child.communicate("", timeout=10)
    assert_no_unguarded_writers(workspace)


def test_phone_worker_emits_structured_guard_failure_before_pi(tmp_path: Path) -> None:
    installation, launcher = _copy_launcher(tmp_path)
    sessions = installation / "workspaces" / "ts_001" / ".pi" / "sessions"
    sessions.mkdir(parents=True)
    original = '{"type":"invalid-history-header"}\n'
    history = sessions / "history.jsonl"
    history.write_text(original)
    completed = subprocess.run([
        str(launcher), "--workspace", "ts_001", "--phone-worker", "--phone-access", "controller",
        "--session-id", "history-1",
    ], input="", text=True, capture_output=True, timeout=15)
    assert completed.returncode == 1, completed.stderr
    assert completed.stdout == ""
    assert json.loads(completed.stderr.splitlines()[-1]) == {
        "type": "tspi.startup_error", "code": "session_guard_invalid",
    }
    assert history.read_text() == original
    assert list(sessions.iterdir()) == [history]


def test_shared_directory_and_exclusive_history_guards(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces" / "ts_001"
    first = acquire_directory_guard(tmp_path, workspace)
    second = acquire_directory_guard(tmp_path, workspace)
    session = acquire_session_guard(tmp_path, workspace, "session-1", "observer")
    try:
        verify_session_writer(tmp_path, workspace, "session-1", "observer", os.getpid())
        with pytest.raises(SessionGuardError):
            acquire_directory_guard(tmp_path, workspace, exclusive=True)
        with pytest.raises(SessionGuardError):
            acquire_session_guard(tmp_path, workspace, "session-1", "observer")
        with pytest.raises(SessionGuardError):
            verify_session_writer(tmp_path, workspace, "session-2", "observer", os.getpid())
        with pytest.raises(SessionGuardError):
            verify_session_writer(tmp_path, workspace, "session-1", "controller", os.getpid())
    finally:
        for descriptor in (session, second, first):
            os.close(descriptor)
    released = acquire_directory_guard(tmp_path, workspace, exclusive=True)
    os.close(released)


def test_selects_exact_history_without_copying_or_rewriting(tmp_path: Path) -> None:
    directory = tmp_path / ".pi" / "sessions"
    directory.mkdir(parents=True)
    original = directory / "history.jsonl"
    data = json.dumps({"type": "session", "id": "old-session", "cwd": str(tmp_path), "version": 3}) + "\n"
    original.write_text(data)
    for args in (["--continue"], ["--session", str(original)], ["--session-id", "old-session"]):
        identity, args = select_session(tmp_path, args)
        assert identity == "old-session"
        assert args == ["--session-id", "old-session"]
        assert original.read_text() == data
        assert list(directory.iterdir()) == [original]
    new_id, _ = select_session(tmp_path, [])
    assert new_id != "old-session"


@pytest.mark.parametrize("arguments", [
    ["--resume"], ["--fork", "old-session"], ["--session-dir", "/tmp"],
    ["--no-session"], ["--session-id", "../escape"],
    ["--continue", "--session-id", "old-session"], ["--session", "/tmp/outside.jsonl"],
])
def test_unguarded_selectors_are_rejected(tmp_path: Path, arguments: list[str]) -> None:
    with pytest.raises(SessionGuardError):
        select_session(tmp_path, arguments)


def test_symlink_guards_and_history_fail_closed(tmp_path: Path) -> None:
    (tmp_path / ".pi").symlink_to(tmp_path / "outside")
    with pytest.raises(SessionGuardError):
        acquire_directory_guard(tmp_path, tmp_path / "workspaces" / "test")
    with pytest.raises(SessionGuardError):
        select_session(tmp_path, [])


@pytest.mark.parametrize("runtime", ["python", "node"])
def test_observer_blocks_same_session_and_lifecycle_until_exit(tmp_path: Path, runtime: str) -> None:
    installation, launcher = _copy_launcher(tmp_path)
    fake = tmp_path / ("pi.py" if runtime == "python" else "pi.mjs")
    fake.write_text(
        "#!/usr/bin/env python3\nimport os,json\nprint(json.dumps({'pid':os.getpid(), 'session':os.environ['TS_SESSION_ID']}),flush=True)\ninput()\n"
        if runtime == "python" else
        "#!/usr/bin/env node\nimport {createInterface} from 'node:readline';\nprocess.title='pi';\n"
        "console.log(JSON.stringify({pid:process.pid,session:process.env.TS_SESSION_ID}));\n"
        "createInterface({input:process.stdin}).once('line',()=>process.exit(0));\n"
    )
    fake.chmod(0o700)
    environment = {**os.environ, "PI_BIN": str(fake)}
    bootstrap = subprocess.run([str(launcher), "--standalone", "--workspace", "ts_001"], input="\n", text=True,
        capture_output=True, env=environment, timeout=15)
    assert bootstrap.returncode == 0, bootstrap.stderr
    command = [str(launcher), "--standalone", "--workspace", "ts_001", "--phone", "--phone-access", "observer", "--session-id", "history-1"]
    holder = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=environment)
    try:
        assert select.select([holder.stdout], [], [], 15)[0]
        identity = json.loads(holder.stdout.readline())
        check = subprocess.run([str(launcher), "--workspace", "ts_001", "--session-writer-check",
            "--session-id", "history-1", "--phone-access", "observer", "--writer-pid", str(identity["pid"])],
            text=True, capture_output=True, env=environment, timeout=15)
        assert check.returncode == 0, check.stderr
        assert json.loads(check.stdout)["verified"] is True
        duplicate = subprocess.run(command, input="\n", text=True, capture_output=True, env=environment, timeout=15)
        assert duplicate.returncode == 1
        assert "session writer" in duplicate.stderr
        guard = subprocess.run([str(launcher), "--workspace", "ts_001", "--lifecycle-guard"],
            input="", text=True, capture_output=True, timeout=15)
        value = json.loads(guard.stdout)
        assert value["root_agent_active"] is False
        assert value["session_writers_active"] is True
        assert value["guard_acquired"] is False
    finally:
        holder.communicate("\n", timeout=10)
    reopened = subprocess.run(command, input="\n", text=True, capture_output=True, env=environment, timeout=15)
    assert reopened.returncode == 0, reopened.stderr
    assert json.loads(reopened.stdout)["session"] == "history-1"


def test_in_process_session_changes_are_cancelled_before_open() -> None:
    result = subprocess.run(["node", "--loader", str(TS_LOADER), "--input-type=module", "-e", f"""
import assert from 'node:assert/strict';
import {{ registerSessionGuard }} from {json.dumps((ROOT / 'extensions/shared/session-guard.ts').as_uri())};
process.env.TS_SESSION_GUARD = 'tspi-session-guard/1';
process.env.TS_SESSION_WRITER_PID = String(process.pid);
const handlers = {{}};
registerSessionGuard({{ on: (name, handler) => handlers[name] = handler }});
for (const event of ['session_before_switch', 'session_before_fork']) {{
  assert.deepEqual(await handlers[event]({{}}, {{hasUI:false}}), {{cancel:true}});
}}
"""], text=True, capture_output=True, cwd=ROOT, timeout=15)
    assert result.returncode == 0, result.stderr
