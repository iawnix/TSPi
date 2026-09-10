from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_ts_phone_integration import ROOT, _copy_launcher


@pytest.mark.skipif(os.environ.get("TSPI_TEST_SYSTEMD") != "1", reason="requires an explicitly enabled user-systemd sandbox test")
def test_real_sandbox_ignores_unreadable_unrelated_pi_but_enforces_writer_guards(tmp_path: Path) -> None:
    installation, launcher = _copy_launcher(tmp_path)
    fake = tmp_path / "fake-pi"
    fake.write_text("#!/usr/bin/python3\nimport json,os,sys\n"
        "print(json.dumps({'pid':os.getpid(),'session':os.environ['TS_SESSION_ID']}),flush=True)\n"
        "sys.stdin.readline()\n")
    fake.chmod(0o700)
    probe = tmp_path / "probe.py"
    shutil.copy2(ROOT / "tests/fixtures/session_guard_sandbox.py", probe)
    unrelated = subprocess.Popen([
        "pi", "-c", "import ctypes; ctypes.CDLL(None).prctl(4,0,0,0,0); print('ready',flush=True); input()",
    ], executable="/usr/bin/python3", cwd=tmp_path, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([unrelated.stdout], [], [], 10)[0]
        assert unrelated.stdout.readline().strip() == "ready"
        properties = [
            "NoNewPrivileges=yes", "PrivateTmp=yes", "ProtectSystem=strict", "ProtectHome=read-only",
            "ProtectControlGroups=yes", "ProtectKernelModules=yes", "ProtectKernelTunables=yes",
            "RestrictSUIDSGID=yes", "LockPersonality=yes", "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
            "RuntimeMaxSec=60", f"BindPaths={tmp_path}", f"ReadWritePaths={tmp_path}",
            f"BindReadOnlyPaths={sys.prefix}",
        ]
        runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        assert (Path(runtime) / "bus").is_socket(), "user-systemd bus is unavailable"
        bus_environment = {**os.environ, "XDG_RUNTIME_DIR": runtime,
            "DBUS_SESSION_BUS_ADDRESS": os.environ.get("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")}
        result = subprocess.run([
            "systemd-run", "--user", "--wait", "--pipe", "--collect",
            *[f"--property={value}" for value in properties],
            f"--setenv=PATH={sys.prefix}/bin:/usr/bin:/bin", "--setenv=PYTHONDONTWRITEBYTECODE=1",
            sys.executable, str(probe), str(launcher), str(fake), str(unrelated.pid),
        ], env=bus_environment, capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr
        record = json.loads(result.stdout.strip().splitlines()[-1])
        assert record == {"unrelated_private": True, "writer_verified": True, "duplicate_blocked": True,
            "other_workspace_started": True, "history_preserved": True, "session_resumed": True}
    finally:
        unrelated.communicate("\n", timeout=10)
