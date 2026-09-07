from __future__ import annotations

import json
import os
import select
import subprocess
from pathlib import Path

import pytest

from ts_agent.runtime.session_guard import (
    SessionGuardError, acquire_directory_guard, acquire_session_guard,
    select_session, verify_session_writer,
)
from tests.test_ts_phone_integration import ROOT, TS_LOADER, _copy_launcher


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
        "#!/usr/bin/env node\nimport {createInterface} from 'node:readline';\n"
        "console.log(JSON.stringify({pid:process.pid,session:process.env.TS_SESSION_ID}));\n"
        "createInterface({input:process.stdin}).once('line',()=>process.exit(0));\n"
    )
    fake.chmod(0o700)
    environment = {**os.environ, "PI_BIN": str(fake)}
    bootstrap = subprocess.run([str(launcher), "--workspace", "ts_001"], input="\n", text=True,
        capture_output=True, env=environment, timeout=15)
    assert bootstrap.returncode == 0, bootstrap.stderr
    command = [str(launcher), "--workspace", "ts_001", "--phone", "--phone-access", "observer", "--session-id", "history-1"]
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
