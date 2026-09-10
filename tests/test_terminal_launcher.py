from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.test_ts_phone_integration import _copy_launcher


@pytest.mark.parametrize("arguments", [[], ["--workspace", "ts_001", "--phone"],
    ["--workspace", "ts_001", "--session-id", "session_1"], ["--workspace", "ts_001", "-c"]])
def test_thin_launcher_does_not_require_scientific_runtime_or_create_workspace(tmp_path: Path, arguments: list[str]) -> None:
    installation, launcher = _copy_launcher(tmp_path)
    package = (installation / ".pi/packages/tspi/current/agent").resolve()
    terminal = package / "apps/terminal/index.mjs"
    terminal.parent.mkdir(parents=True)
    terminal.write_text("// fixture entry\n", encoding="utf-8")
    (installation / ".agents/runtime/tspi/env.json").unlink()
    node = tmp_path / "node"
    node.write_text("#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8")
    node.chmod(0o755)
    result = subprocess.run([str(launcher), *arguments], cwd=installation,
        env={**os.environ, "PI_BIN": str(node), "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    forwarded = json.loads(result.stdout)
    assert forwarded[:5] == ["--import", str(package / "scripts/pi-loader.mjs"), str(terminal), "--install-root", str(installation)]
    assert ("--latest" in forwarded) == ("-c" in arguments)
    assert not (installation / "workspaces").exists()
    assert not (installation / ".pi/remote.toml").exists()


@pytest.mark.parametrize("arguments", [["--model", "example/model"], ["--mode", "rpc"], ["--session-id", "bad/path"]])
def test_thin_launcher_rejects_native_passthrough(tmp_path: Path, arguments: list[str]) -> None:
    installation, launcher = _copy_launcher(tmp_path)
    result = subprocess.run([str(launcher), "--workspace", "ts_001", *arguments], cwd=installation,
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert not (installation / "workspaces").exists()
