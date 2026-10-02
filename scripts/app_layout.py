"""Standalone Research Agent installation layout and diagnostic contracts.

The installer still supports the historical ``.pi/packages/tspi`` store.  This
module is deliberately read-only: it gives launchers and migration tooling one
place to classify an installation without silently moving or merging files.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LAYOUT_SCHEMA_VERSION = "research-agent-layout/1"
STANDALONE_MARKER = "etc/research-agent-layout.json"
LEGACY_PACKAGE_HOME = ".pi/packages/tspi"
DIRECT_PACKAGE_HOME = ".pi/packages/tspi"


@dataclass(frozen=True)
class AppLayoutPaths:
    """Canonical paths for an installation layout."""

    root: Path
    layout: str

    @property
    def releases(self) -> Path:
        return self.root / ("releases" if self.layout == "standalone" else f"{LEGACY_PACKAGE_HOME}/releases")

    @property
    def current(self) -> Path:
        return self.root / ("current" if self.layout == "standalone" else f"{LEGACY_PACKAGE_HOME}/current")

    @property
    def bin(self) -> Path:
        return self.root / "bin"

    @property
    def config(self) -> Path:
        return self.root / ("etc" if self.layout == "standalone" else ".pi/tspi")

    @property
    def state(self) -> Path:
        return self.root / ("var" if self.layout == "standalone" else ".pi")


def paths(root: str | Path, layout: str = "legacy") -> AppLayoutPaths:
    """Return canonical paths, rejecting unknown layout names."""

    value = Path(root).expanduser()
    if not value.is_absolute():
        raise ValueError("installation root must be absolute")
    if layout not in {"legacy", "standalone"}:
        raise ValueError("layout must be 'legacy' or 'standalone'")
    return AppLayoutPaths(value, layout)


def inspect_installation(root: str | Path) -> dict[str, Any]:
    """Inspect an installation without changing any file.

    A mixed installation is intentionally unhealthy.  In particular, a root
    ``current`` symlink alone does not imply standalone layout because current
    releases also publish that compatibility pointer in legacy installs.
    """

    root_path = Path(root).expanduser()
    findings: list[dict[str, str]] = []
    if not root_path.is_absolute():
        findings.append({"code": "root_not_absolute", "message": "installation root must be absolute"})
        return _report(root_path, "unknown", findings)
    if root_path.is_symlink():
        findings.append({"code": "root_symlink", "message": "installation root must be a physical directory"})
    if not root_path.is_dir():
        findings.append({"code": "root_missing", "message": "installation root is not a directory"})
        return _report(root_path, "unknown", findings)

    legacy = paths(root_path, "legacy")
    direct_store = root_path / DIRECT_PACKAGE_HOME
    standalone_marker = root_path / STANDALONE_MARKER
    standalone_marker_valid = _validate_standalone_marker(standalone_marker, root_path, findings)
    legacy_present = (root_path / LEGACY_PACKAGE_HOME).exists()
    direct_present = direct_store.exists() or direct_store.is_symlink()
    standalone_candidate = (root_path / "releases").is_dir() or (root_path / "current").is_symlink()

    if (standalone_marker_valid or direct_present) and legacy_present:
        layout = "mixed"
        findings.append({
            "code": "mixed_layout",
            "message": "standalone/direct and legacy package stores coexist; run an explicit migration",
        })
    elif standalone_marker_valid:
        layout = "standalone"
    elif direct_present:
        layout = "standalone_unmarked"
        findings.append({
            "code": "standalone_unmarked",
            "message": f"direct ResearchAgent store exists but {STANDALONE_MARKER} is missing",
        })
    elif legacy_present:
        layout = "legacy"
    elif standalone_candidate:
        layout = "standalone_unmarked"
        findings.append({
            "code": "standalone_unmarked",
            "message": f"standalone-looking paths exist but {STANDALONE_MARKER} is missing",
        })
    else:
        layout = "uninitialized"
        findings.append({"code": "uninitialized", "message": "no supported application layout was found"})

    if layout == "legacy":
        _check_release_store(legacy, findings)
        _check_legacy_state(root_path, legacy, findings)
    elif layout == "standalone":
        _check_release_store(paths(root_path, "standalone"), findings)
        _check_standalone_directories(root_path, findings)
    elif layout == "mixed":
        _check_release_store(legacy, findings)
        _check_release_store(paths(root_path, "standalone"), findings)
        _check_direct_store(direct_store, findings)
        _check_legacy_state(root_path, legacy, findings)
    elif layout == "standalone_unmarked" and direct_present:
        _check_direct_store(direct_store, findings)

    selected_paths = paths(root_path, "standalone" if layout == "standalone" else "legacy")
    release_id = _release_id(selected_paths.current)
    if direct_present:
        release_id = _release_id(direct_store / "current") or release_id
    return _report(root_path, layout, findings, release_id=release_id)


def _report(root: Path, layout: str, findings: list[dict[str, str]], *, release_id: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": LAYOUT_SCHEMA_VERSION,
        "root": str(root),
        "layout": layout,
        "ok": not findings,
        "migration_required": layout in {"legacy", "mixed", "standalone_unmarked"},
        "release_id": release_id,
        "findings": findings,
    }


def _validate_standalone_marker(path: Path, root: Path, findings: list[dict[str, str]]) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_symlink() or not path.is_file():
        findings.append({"code": "standalone_marker_unsafe", "message": f"standalone marker is not a regular file: {path}"})
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        findings.append({"code": "standalone_marker_invalid", "message": f"standalone marker is invalid: {path}"})
        return False
    expected = {"schema_version": LAYOUT_SCHEMA_VERSION, "install_root": str(root)}
    if value != expected:
        findings.append({"code": "standalone_marker_mismatch", "message": f"standalone marker does not belong to {root}"})
        return False
    return True


def _check_release_store(layout: AppLayoutPaths, findings: list[dict[str, str]]) -> None:
    if layout.releases.is_symlink() or not layout.releases.is_dir():
        findings.append({"code": "releases_missing", "message": f"release directory is missing or unsafe: {layout.releases}"})
    if layout.current.is_symlink():
        try:
            target = layout.current.resolve(strict=True)
        except (OSError, RuntimeError):
            findings.append({"code": "current_dangling", "message": f"current pointer is dangling: {layout.current}"})
            return
        try:
            target.relative_to(layout.releases.resolve())
        except ValueError:
            findings.append({"code": "current_escapes_releases", "message": f"current pointer escapes release store: {layout.current}"})
    elif layout.current.exists():
        findings.append({"code": "current_not_symlink", "message": f"current pointer must be a symbolic link: {layout.current}"})
    else:
        findings.append({"code": "current_missing", "message": f"current pointer is missing: {layout.current}"})


def _check_legacy_state(root: Path, layout: AppLayoutPaths, findings: list[dict[str, str]]) -> None:
    state = root / f"{LEGACY_PACKAGE_HOME}/install-state.json"
    if not state.is_file() or state.is_symlink():
        findings.append({"code": "legacy_state_missing", "message": f"legacy install state is missing: {state}"})
        return
    try:
        value = json.loads(state.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        findings.append({"code": "legacy_state_invalid", "message": f"legacy install state is invalid: {state}"})
        return
    release_id = value.get("current_release_id") if isinstance(value, dict) else None
    package_root = value.get("package_root") if isinstance(value, dict) else None
    expected = layout.releases / release_id if isinstance(release_id, str) else None
    if expected is None or package_root != str(expected):
        findings.append({"code": "legacy_state_mismatch", "message": f"legacy state package_root does not match current release: {state}"})
    current_id = _release_id(layout.current)
    if isinstance(release_id, str) and current_id is not None and release_id != current_id:
        findings.append({
            "code": "legacy_current_state_mismatch",
            "message": f"legacy current pointer selects {current_id}, state selects {release_id}",
        })
    stable_current = root / "current"
    if stable_current.is_symlink():
        try:
            stable_target = stable_current.resolve(strict=True)
            package_target = layout.current.resolve(strict=True)
        except (OSError, RuntimeError):
            findings.append({"code": "stable_current_dangling", "message": f"root current pointer is dangling: {stable_current}"})
        else:
            if stable_target != package_target:
                findings.append({
                    "code": "stable_current_mismatch",
                    "message": f"root current pointer does not match package current: {stable_current}",
                })
    elif stable_current.exists():
        findings.append({"code": "stable_current_not_symlink", "message": f"root current must be a symbolic link: {stable_current}"})


def _check_standalone_directories(root: Path, findings: list[dict[str, str]]) -> None:
    for name in ("etc", "var", "bin"):
        path = root / name
        if path.is_symlink() or not path.is_dir():
            findings.append({"code": "standalone_directory_missing", "message": f"standalone directory is missing or unsafe: {path}"})


def _check_direct_store(store: Path, findings: list[dict[str, str]]) -> None:
    """Validate the transitional direct-release store without treating it as root layout."""

    releases = store / "releases"
    current = store / "current"
    if releases.is_symlink() or not releases.is_dir():
        findings.append({"code": "direct_releases_missing", "message": f"direct release directory is missing or unsafe: {releases}"})
    if not current.is_symlink():
        findings.append({"code": "direct_current_missing", "message": f"direct current pointer is missing or not a symlink: {current}"})
        return
    try:
        target = current.resolve(strict=True)
        target.relative_to(releases.resolve())
    except (OSError, RuntimeError, ValueError):
        findings.append({"code": "direct_current_invalid", "message": f"direct current pointer is invalid: {current}"})


def _release_id(current: Path) -> str | None:
    if not current.is_symlink():
        return None
    try:
        return current.resolve(strict=True).name
    except (OSError, RuntimeError):
        return None


def write_standalone_marker(root: str | Path) -> Path:
    """Create an explicit standalone marker for a prepared migration target.

    This does not copy or delete application state.  Callers must prepare and
    validate the standalone directories before invoking it.
    """

    root_path = Path(root).expanduser()
    if not root_path.is_absolute() or root_path.is_symlink() or not root_path.is_dir():
        raise ValueError("standalone installation root must be an existing physical directory")
    for name in ("etc", "var", "bin", "releases"):
        directory = root_path / name
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError(f"standalone directory is missing or unsafe: {directory}")
    marker = root_path / STANDALONE_MARKER
    marker.parent.mkdir(mode=0o700, exist_ok=True)
    payload = {"schema_version": LAYOUT_SCHEMA_VERSION, "install_root": str(root_path.resolve())}
    temporary = marker.with_name(f".{marker.name}.{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, marker)
    return marker
