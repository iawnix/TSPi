#!/usr/bin/env python3
"""Remove a standalone TSPi Link Relay installation and its service."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


SERVICE_NAME = "tspi-link-relay.service"
DEFAULT_INSTALL_ROOT = Path("/opt/tspi-link-relay")
DEFAULT_STATE_ROOT = Path("/var/lib/tspi-link-relay")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-root", default=str(DEFAULT_INSTALL_ROOT))
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_ROOT))
    parser.add_argument("--service-scope", choices=("auto", "system", "user", "none"), default="auto")
    parser.add_argument("--purge-state", action="store_true", help="Delete the Relay SQLite state and enrolled credentials.")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _user_defaults(args: argparse.Namespace) -> None:
    user_scope = args.service_scope == "user" or (args.service_scope in {"auto", "none"} and os.geteuid() != 0)
    if user_scope:
        if args.install_root == str(DEFAULT_INSTALL_ROOT):
            args.install_root = str(Path.home() / ".local/share/tspi-link-relay")
        if args.state_dir == str(DEFAULT_STATE_ROOT):
            args.state_dir = str(Path.home() / ".local/state/tspi-link-relay")


def validate_root(value: str, *, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    if path.is_symlink():
        raise ValueError(f"{label} cannot be a symbolic link")
    resolved = path.resolve()
    if resolved in {Path("/"), Path.home(), Path.home().parent}:
        raise ValueError(f"refusing to remove broad path: {resolved}")
    return resolved


def validate_install_root(path: Path) -> None:
    if not path.exists():
        return
    if not path.is_dir():
        raise ValueError(f"installation root is not a directory: {path}")
    allowed = {"current", "releases"}
    unexpected = sorted(child.name for child in path.iterdir() if child.name not in allowed)
    if unexpected:
        raise ValueError(f"installation root contains unmanaged entries: {', '.join(unexpected)}")
    current = path / "current"
    releases = path / "releases"
    if current.exists() and not current.is_symlink():
        raise ValueError(f"installation current path is not a symbolic link: {current}")
    if releases.exists() and not releases.is_dir():
        raise ValueError(f"installation releases path is not a directory: {releases}")


def service_directory(scope: str) -> Path:
    if scope == "system":
        return Path("/etc/systemd/system")
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd/user"


def service_unit(scope: str) -> Path:
    return service_directory(scope) / SERVICE_NAME


def unit_belongs_to_root(unit: Path, root: Path) -> bool:
    try:
        lines = unit.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    expected = str(root / "current" / "service")
    has_description = False
    has_working_directory = False
    for line in lines:
        key, _, value = line.partition("=")
        if key == "Description" and value == "TSPi Link Relay":
            has_description = True
        if key == "WorkingDirectory" and _unquote_systemd(value) == expected:
            has_working_directory = True
    return has_description and has_working_directory


def _unquote_systemd(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1].replace("\\\"", '"').replace("\\\\", "\\").replace("%%", "%")
    return value


def systemctl_args(scope: str) -> list[str]:
    return ["systemctl", "--user"] if scope == "user" else ["systemctl"]


def remove_service(args: argparse.Namespace, root: Path) -> list[str]:
    if args.service_scope == "none" or shutil.which("systemctl") is None:
        return []
    scopes = [args.service_scope] if args.service_scope in {"system", "user"} else ["user", "system"]
    removed: list[str] = []
    for scope in scopes:
        unit = service_unit(scope)
        if not unit.is_file() or unit.is_symlink() or not unit_belongs_to_root(unit, root):
            continue
        command = systemctl_args(scope)
        subprocess.run([*command, "disable", "--now", SERVICE_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        unit.unlink()
        subprocess.run([*command, "daemon-reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        removed.append(str(unit))
    return removed


def remove_tree(path: Path) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_symlink() or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)
    return True


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.yes:
            args.non_interactive = True
        _user_defaults(args)
        root = validate_root(args.install_root, label="--install-root")
        state = validate_root(args.state_dir, label="--state-dir")
        if state == root or root in state.parents or state in root.parents:
            raise ValueError("--state-dir must be independent from --install-root")
        validate_install_root(root)
        if args.service_scope == "system" and os.geteuid() != 0:
            raise ValueError("system Relay service removal requires root; choose --service-scope user")
        if not args.non_interactive:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise RuntimeError("interactive Relay uninstall requires a TTY; use --non-interactive --yes")
            print(f"Remove TSPi Link Relay code from {root}? [y/N] ", end="", flush=True)
            if input().strip().lower() not in {"y", "yes"}:
                return 0
            if args.purge_state:
                print(f"Delete Relay state and enrolled credentials from {state}? [y/N] ", end="", flush=True)
                args.purge_state = input().strip().lower() in {"y", "yes"}
        elif not args.yes:
            raise ValueError("--non-interactive requires --yes")
        service_units = remove_service(args, root)
        removed = []
        if remove_tree(root):
            removed.append(str(root))
        if args.purge_state and remove_tree(state):
            removed.append(str(state))
        result = {"ok": True, "removed": removed, "service_units": service_units, "state_preserved": not args.purge_state}
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else format_result(result))
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"TSPi Link Relay uninstall failed: {exc}", file=sys.stderr)
        return 1


def format_result(result: dict[str, object]) -> str:
    state = "preserved" if result["state_preserved"] else "removed"
    return f"TSPi Link Relay removed. Service units: {len(result['service_units'])}. State: {state}."


if __name__ == "__main__":
    raise SystemExit(main())
