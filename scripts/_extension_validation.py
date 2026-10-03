"""Validate first-party extension manifests at build and test boundaries."""

from __future__ import annotations

import subprocess
from pathlib import Path


class ExtensionValidationError(RuntimeError):
    """An installed extension manifest or artifact failed validation."""


def validate_extensions(package_root: str | Path) -> None:
    """Run the canonical Node manifest loader against one package root."""

    root = Path(package_root).expanduser().resolve()
    loader = root / "apps" / "app-server" / "extension-manifest-loader.mjs"
    if not loader.is_file():
        raise ExtensionValidationError(f"extension manifest loader is missing: {loader}")
    program = (
        "const { discoverInstalledExtensions } = await import(process.argv[1]);"
        "await discoverInstalledExtensions({ packageRoot: process.argv[2] });"
    )
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", program, loader.as_uri(), str(root)],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "extension discovery failed"
        raise ExtensionValidationError(detail)
