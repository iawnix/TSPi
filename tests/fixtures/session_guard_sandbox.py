"""Disposable launcher exercise under the real Host service sandbox."""

import json
import os
import select
import subprocess
import sys
from pathlib import Path


launcher, fake, unrelated = sys.argv[1:]
try:
    Path(f"/proc/{unrelated}/environ").read_bytes()
except PermissionError:
    pass
else:
    raise AssertionError("fixture did not reproduce the protected Pi process")

root = Path(launcher).parent
workspace = root / "workspaces/ts_001"
sessions = workspace / ".pi/sessions"
sessions.mkdir(parents=True)
history = sessions / "original.jsonl"
original = json.dumps({"type": "session", "version": 3, "id": "original-session", "cwd": str(workspace)}) + "\n"
history.write_text(original)
environment = {**os.environ, "PI_BIN": fake}
arguments = [launcher, "--standalone", "--workspace", "ts_001", "--session-id", "original-session"]
worker = subprocess.Popen(arguments, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
try:
    assert select.select([worker.stdout], [], [], 20)[0], "Worker did not become ready"
    line = worker.stdout.readline()
    assert line, worker.stderr.read()
    identity = json.loads(line)
    verified = subprocess.run([launcher, "--session-writer-check", "--workspace", "ts_001",
        "--session-id", "original-session", "--phone-access", "controller", "--writer-pid", str(identity["pid"])],
        env=environment, capture_output=True, text=True, timeout=15)
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["verified"] is True
    for extra in [[], ["--phone", "--phone-access", "observer"]]:
        duplicate = subprocess.run([*arguments, *extra], env=environment, input="", capture_output=True, text=True, timeout=15)
        assert duplicate.returncode == 1, duplicate.stdout
        assert "session writer" in duplicate.stderr or "another Root Agent" in duplicate.stderr
    other = subprocess.run([launcher, "--standalone", "--workspace", "ts_002"],
        env=environment, input="", capture_output=True, text=True, timeout=15)
    assert other.returncode == 0, other.stderr
finally:
    worker.terminate()
    worker.communicate(timeout=10)

resumed = subprocess.run(arguments, env=environment, input="", capture_output=True, text=True, timeout=15)
assert resumed.returncode == 0, resumed.stderr
assert json.loads(resumed.stdout)["session"] == "original-session"
assert history.read_text() == original
assert list(sessions.iterdir()) == [history]
print(json.dumps({"unrelated_private": True, "writer_verified": True, "duplicate_blocked": True,
    "other_workspace_started": True, "history_preserved": True, "session_resumed": True}))
