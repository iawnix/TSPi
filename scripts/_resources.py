"""Validate installed resources using the generated release inventory."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class ResourceValidationError(ValueError):
    pass


def validate_resources(package_root: str | Path) -> None:
    root = Path(package_root).resolve()
    manifest = json.loads((root / "config/resources.json").read_text())
    if manifest["schema_version"] != "research-agent-resources/1":
        raise ResourceValidationError("unsupported resource inventory")
    for name, expected in manifest["files"].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ResourceValidationError("resource path escapes package")
        path = root / relative
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ResourceValidationError(f"invalid package resource: {name}")
        if "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ResourceValidationError(f"resource content changed: {name}")
