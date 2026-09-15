#!/usr/bin/env python3
"""Safely remove a TSPi installation and its optional runtime state."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path


SERVICE_NAMES = (
    "ts-phone-tspi.service",
    "ts-web-tspi.service",
    "ts-phone.service",
    "ts-web.service",
)
ENTRYPOINTS = ("TSPi", "TSWeb", "TSPhoneCtl", "TSPhoneServer")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-root")
    parser.add_argument("--service-scope", choices=("auto", "user", "system", "none"), default="auto")
    parser.add_argument("--purge-workspaces", action="store_true", help="Delete research workspaces and Pi session files.")
    parser.add_argument("--purge-config", action="store_true", help="Delete installation configuration and Phone credentials.")
    parser.add_argument("--purge-runtime", action="store_true", help="Delete managed Conda/venv runtime state.")
    parser.add_argument("--remove-root", action="store_true", help="Remove the installation directory after cleanup.")
    parser.add_argument("--purge-all", action="store_true", help="Enable all purge and root removal options.")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def ask(prompt: str, default: bool = False) -> bool:
    marker = "Y/n" if default else "y/N"
    value = input(f"{prompt} [{marker}]: ").strip().lower()
    return default if not value else value in {"y", "yes"}


def validate_root(path: Path) -> Path:
    if not path.is_absolute():
        raise ValueError("--install-root must be absolute")
    resolved = path.expanduser().resolve()
    if resolved == Path("/") or resolved == Path.home() or resolved == Path.home().parent:
        raise ValueError(f"refusing to remove broad path: {resolved}")
    for relative in (".pi", ".pi/packages", ".pi/ts-phone", ".agents", ".agents/runtime", ".agents/envs"):
        if (resolved / relative).is_symlink():
            raise ValueError(f"installation state directory cannot be a symbolic link: {resolved / relative}")
    marker = resolved / ".pi/packages/tspi"
    if not marker.is_dir() and not (resolved / "TSPi").exists() and not (resolved / ".pi/tspi/uninstall.py").is_file():
        raise ValueError(f"does not look like a TSPi installation: {resolved}")
    return resolved


def choose_options(args: argparse.Namespace, root: Path) -> None:
    if args.purge_all:
        args.purge_workspaces = args.purge_config = args.purge_runtime = args.remove_root = True
    if args.remove_root and not (args.purge_workspaces and args.purge_config and args.purge_runtime):
        raise ValueError("--remove-root requires --purge-workspaces, --purge-config, and --purge-runtime")
    if args.non_interactive:
        if not args.yes:
            raise ValueError("--non-interactive requires --yes")
        return
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError("interactive uninstall requires a TTY; use --non-interactive --yes")
    print(f"\nTSPi installation: {root}")
    print("The default keeps workspaces, research sessions, and user Pi credentials.")
    args.purge_workspaces = args.purge_workspaces or ask("Delete workspaces and Pi session files", False)
    args.purge_config = args.purge_config or ask("Delete installation config, Phone tokens, and bridge secrets", False)
    args.purge_runtime = args.purge_runtime or ask("Delete managed Python runtime state", False)
    args.remove_root = args.remove_root or ask("Remove the installation directory", False)
    if args.remove_root and not (args.purge_workspaces and args.purge_config and args.purge_runtime):
        raise ValueError("removing the installation directory requires selecting all data cleanup options")
    if not args.yes and not ask("Proceed with uninstall", False):
        raise SystemExit(0)


def systemctl_args(scope: str) -> list[str]:
    if scope == "user":
        return ["systemctl", "--user"]
    return ["systemctl"]


def service_belongs_to_root(name: str, root: Path, scope: str) -> bool:
    directory = Path.home() / ".config/systemd/user" if scope == "user" else Path("/etc/systemd/system")
    path = directory / name
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False
    root_value = str(root).replace("%", "%%")
    for line in content.splitlines():
        key, _, value = line.partition("=")
        value = value.strip().strip('"')
        if key == "WorkingDirectory" and value == root_value:
            return True
        if key == "EnvironmentFile" and value == f"{root_value}/.pi/ts-phone/server.env":
            return True
    return False


def stop_services(args: argparse.Namespace, root: Path) -> list[str]:
    if args.service_scope == "none" or shutil.which("systemctl") is None:
        return []
    scopes = [args.service_scope] if args.service_scope in {"user", "system"} else ["user", "system"]
    stopped: list[str] = []
    for scope in scopes:
        scope_stopped = False
        command = systemctl_args(scope)
        for name in SERVICE_NAMES:
            if not service_belongs_to_root(name, root, scope):
                continue
            probe = subprocess.run([*command, "is-enabled", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            active = subprocess.run([*command, "is-active", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            if probe.returncode != 0 and active.returncode != 0:
                continue
            subprocess.run([*command, "disable", "--now", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            stopped.append(f"{scope}:{name}")
            scope_stopped = True
        if scope_stopped:
            subprocess.run([*command, "daemon-reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return stopped


def remove_service_units(args: argparse.Namespace, root: Path) -> list[str]:
    locations: list[Path] = []
    if args.service_scope in {"auto", "user"}:
        locations.append(Path.home() / ".config/systemd/user")
    if args.service_scope in {"auto", "system"}:
        locations.append(Path("/etc/systemd/system"))
    removed: list[str] = []
    for directory in locations:
        changed = False
        for name in SERVICE_NAMES:
            path = directory / name
            scope = "user" if directory == Path.home() / ".config/systemd/user" else "system"
            if path.is_file() and not path.is_symlink() and service_belongs_to_root(name, root, scope):
                path.unlink()
                removed.append(str(path))
                changed = True
        if changed and shutil.which("systemctl"):
            scope = "user" if directory == Path.home() / ".config/systemd/user" else "system"
            subprocess.run([*systemctl_args(scope), "daemon-reload"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return removed


def remove_entrypoints(root: Path) -> list[str]:
    removed: list[str] = []
    for name in ENTRYPOINTS:
        path = root / name
        if path.is_symlink() or (path.is_file() and name in ENTRYPOINTS):
            path.unlink()
            removed.append(str(path))
    return removed


def make_tree_removable(root: Path) -> None:
    """Restore owner-write permission on directories without following links."""
    for current, _, _ in os.walk(root, followlinks=False):
        directory = Path(current)
        mode = stat.S_IMODE(directory.stat().st_mode)
        if not mode & stat.S_IWUSR:
            directory.chmod(mode | stat.S_IWUSR)


def remove_paths(paths: list[Path]) -> list[str]:
    removed: list[str] = []
    for path in paths:
        if path.is_symlink() or path.is_file():
            path.unlink()
            removed.append(str(path))
        elif path.is_dir():
            make_tree_removable(path)
            shutil.rmtree(path)
            removed.append(str(path))
    return removed


def prune_empty_parents(root: Path) -> None:
    for relative in (".pi/ts-phone", ".pi/packages", ".pi", ".agents/runtime", ".agents/envs", ".agents"):
        directory = root / relative
        if not directory.is_dir():
            continue
        try:
            directory.rmdir()
        except OSError:
            pass


def uninstall(args: argparse.Namespace) -> dict[str, object]:
    root = validate_root(Path(args.install_root))
    choose_options(args, root)
    stopped = stop_services(args, root)
    service_units = remove_service_units(args, root)
    removed = remove_entrypoints(root)
    managed = [
        root / ".pi/packages/tspi",
        root / ".pi/runtime-cache",
        root / ".pi/session-host",
        root / ".pi/ts-web-state",
        root / ".pi/ts-phone/ts-phone.service",
        root / ".pi/ts-phone/current",
        root / ".pi/ts-phone/releases",
    ]
    if args.purge_config:
        managed.extend([root / ".pi/ts-phone", root / ".pi/ts-phone-state", root / ".pi/remote.toml", root / ".pi/notifications.toml"])
    if args.purge_runtime:
        managed.extend([root / ".agents/runtime/tspi", root / ".agents/envs/tspi"])
    if args.purge_workspaces:
        managed.append(root / "workspaces")
    if args.purge_all:
        managed.append(root / "ts-phone")
    removed.extend(remove_paths(managed))
    prune_empty_parents(root)
    if args.remove_root:
        removed.extend(remove_paths([root]))
    removed.extend(service_units)
    return {"ok": True, "install_root": str(root), "stopped_services": stopped, "removed": removed,
            "preserved_workspaces": not args.purge_workspaces, "preserved_config": not args.purge_config,
            "preserved_runtime": not args.purge_runtime}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if not args.install_root and not args.non_interactive:
            bundled = Path(__file__).resolve()
            default = str(bundled.parents[2]) if bundled.parent.name == "tspi" and bundled.parent.parent.name == ".pi" else str(Path.home() / ".local/share/tspi")
            args.install_root = input(f"TSPi installation directory [{default}]: ").strip() or default
        if not args.install_root:
            raise ValueError("--install-root is required")
        result = uninstall(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("Uninstall complete")
            for item in result["removed"]:
                print(f"removed: {item}")
            for item in result["stopped_services"]:
                print(f"stopped: {item}")
        return 0
    except SystemExit as error:
        return int(error.code or 0)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"TSPi uninstall failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
