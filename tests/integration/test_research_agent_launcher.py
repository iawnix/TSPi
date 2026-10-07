from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_server_launcher_uses_canonical_host_path(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "libexec").mkdir()
    shutil.copy2(ROOT / "libexec/research-agent-host", package / "libexec/research-agent-host")
    launcher = package / "apps/agent-cli/tspi_launcher.py"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("# canonical launcher\n")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    python = binaries / "python3"
    python.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
    python.chmod(0o755)
    env = {**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}", "TSPI_INSTALL_ROOT": str(tmp_path / "install")}
    result = subprocess.run([str(package / "libexec/research-agent-host")], env=env, text=True, capture_output=True, check=True)
    assert result.stdout.splitlines() == [
        str(launcher), "--install-root", str(tmp_path / "install"), "--", "--service-host",
    ]


def test_release_has_no_second_server_launcher() -> None:
    package = json.loads((ROOT / "package.json").read_text())
    assert "apps/agent-cli/research_agent_launcher.py" not in package["files"]
    assert not (ROOT / "apps/agent-cli/research_agent_launcher.py").exists()
