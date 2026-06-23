"""Dependency discovery for TSAgentSkill rendering."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from ts_runtime import load_manifest

XYZRENDER_OVERRIDE = "TS_RENDER_XYZRENDER"


class EnvironmentChecker:
    """Discover render dependencies without mutating the workspace."""

    def __init__(self, package_root: str | Path | None = None):
        self.package_root = Path(package_root).resolve() if package_root else Path(__file__).resolve().parents[1]

    def xyzrender_path(self) -> str | None:
        override = os.environ.get(XYZRENDER_OVERRIDE)
        if override:
            path = Path(override).expanduser().resolve()
            return str(path) if path.exists() else None

        manifest = load_manifest(self.package_root)
        if manifest and manifest.get("env_prefix"):
            candidate = Path(str(manifest["env_prefix"])) / "bin" / "xyzrender"
            if candidate.exists():
                return str(candidate)

        found = shutil.which("xyzrender")
        return str(Path(found).resolve()) if found else None

    def check_command(self, command: str, args: list[str] | None = None, timeout: int = 30) -> dict[str, Any]:
        path = self.xyzrender_path() if command == "xyzrender" else None
        if not path:
            return {"available": False, "path": None, "returncode": None}
        completed = subprocess.run(
            [path, *(args or ["--help"])],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return {
            "available": completed.returncode == 0,
            "path": path,
            "returncode": completed.returncode,
            "stdout": completed.stdout[:500],
            "stderr": completed.stderr[:500],
        }

    def run_diagnostic(self) -> dict[str, Any]:
        manifest = load_manifest(self.package_root)
        return {
            "python": {
                "executable": sys.executable,
                "version": sys.version,
            },
            "runtime": {
                "manifest_present": manifest is not None,
                "env_prefix": manifest.get("env_prefix") if manifest else None,
                "python_executable": manifest.get("python_executable") if manifest else None,
            },
            "xyzrender": self.check_command("xyzrender"),
        }

    def list_available_engines(self) -> list[str]:
        if not self.xyzrender_path():
            return []
        return ["xyzrender"]
