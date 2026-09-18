"""Install and describe the optional TSPi model icon font.

This module intentionally uses only the Python standard library because it is
called by the bootstrap installer before the managed runtime is available.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MODEL_ICON_FONT_RELATIVE = Path("assets/fonts/tspi-model-icons.ttf")
MODEL_ICON_CONFIG_RELATIVE = Path(".pi/tspi/model-icons.json")
MODEL_ICON_CONFIG_SCHEMA = "tspi-model-icons/1"
MODEL_ICON_FONT_NAME = "TSPi-Model-Icons.ttf"


def install_model_icon_font(
    package_root: Path,
    install_root: Path,
    *,
    enabled: bool,
    font_home: Path | None = None,
) -> dict[str, Any]:
    """Install the bundled font and write the installation marker.

    ``enabled=False`` only changes the marker.  It deliberately leaves a
    shared user font in place so another TSPi installation is not disrupted.
    """

    requested_root = install_root.expanduser()
    if requested_root.is_symlink():
        raise ValueError(f"installation root must not be a symbolic link: {requested_root}")
    root = _require_directory(requested_root.resolve(), "installation root")
    marker = root / MODEL_ICON_CONFIG_RELATIVE
    if enabled:
        requested_package = package_root.expanduser()
        if requested_package.is_symlink():
            raise ValueError(f"package root must not be a symbolic link: {requested_package}")
        source = requested_package.resolve() / MODEL_ICON_FONT_RELATIVE
        _require_regular_file(source, "bundled model icon font")
        font_dir = _font_directory(font_home)
        _ensure_directory_tree(font_dir, mode=0o755)
        target = font_dir / MODEL_ICON_FONT_NAME
        if target.is_symlink():
            raise ValueError(f"model icon font target cannot be a symbolic link: {target}")
        _atomic_copy(source, target, mode=0o644)
        digest = _sha256_file(target)
        cache_status, warning = _refresh_font_cache(font_dir)
        result: dict[str, Any] = {
            "status": cache_status,
            "enabled": True,
            "font_path": str(target),
            "sha256": digest,
            "config_path": str(marker),
        }
        if warning:
            result["warning"] = warning
        document = {
            "schema_version": MODEL_ICON_CONFIG_SCHEMA,
            "enabled": True,
            "font_path": str(target),
            "sha256": digest,
            "installed_at_utc": _utc_now(),
        }
    else:
        result = {
            "status": "disabled",
            "enabled": False,
            "config_path": str(marker),
        }
        document = {
            "schema_version": MODEL_ICON_CONFIG_SCHEMA,
            "enabled": False,
            "installed_at_utc": _utc_now(),
        }
    _atomic_write_json(marker, document, mode=0o600)
    return result


def _font_directory(home: Path | None = None) -> Path:
    configured = os.environ.get("XDG_DATA_HOME")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            raise ValueError("XDG_DATA_HOME must be an absolute path")
    else:
        path = (home or Path.home()) / ".local" / "share"
    return path / "fonts" / "tspi"


def _require_directory(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"{label} must be a regular directory: {path}")
    return path


def _require_regular_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file: {path}")


def _ensure_directory_tree(path: Path, *, mode: int = 0o755) -> None:
    # Check every existing component so a user-controlled symlink cannot move
    # the font outside the configured data directory.
    missing: list[Path] = []
    cursor = path
    while not cursor.exists() and not cursor.is_symlink():
        missing.append(cursor)
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    if cursor.is_symlink() or not cursor.is_dir():
        raise ValueError(f"font directory parent is unsafe: {cursor}")
    ancestor = cursor
    while True:
        if ancestor.is_symlink() or not ancestor.is_dir():
            raise ValueError(f"font directory parent is unsafe: {ancestor}")
        parent = ancestor.parent
        if parent == ancestor:
            break
        ancestor = parent
    for directory in reversed(missing):
        directory.mkdir(mode=mode)
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"font directory is unsafe: {path}")
    path.chmod(mode)


def _atomic_copy(source: Path, target: Path, *, mode: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
            descriptor = -1
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _atomic_write_json(path: Path, value: dict[str, Any], *, mode: int) -> None:
    _ensure_directory_tree(path.parent, mode=0o700)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"model icon marker must be a regular file: {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            descriptor = -1
            json.dump(value, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _refresh_font_cache(font_dir: Path) -> tuple[str, str | None]:
    command = shutil.which("fc-cache")
    if command is None:
        return "installed_cache_unavailable", "fc-cache was not found; restart the terminal after installing fontconfig"
    try:
        completed = subprocess.run(
            [command, "-f", str(font_dir)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return "installed_cache_unavailable", f"font cache refresh unavailable: {error}"
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip() or f"exit status {completed.returncode}"
        return "installed_cache_unavailable", f"font cache refresh failed: {detail}"
    return "installed", None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
