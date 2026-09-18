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

try:
    from ._installation_metadata import read_installation_metadata, read_workspace_root
    from ._terminal_ui import Spinner, ask_text as ask, ask_yes_no, failure, field, note, section, success, title
except ImportError:
    from _installation_metadata import read_installation_metadata, read_workspace_root
    from _terminal_ui import Spinner, ask_text as ask, ask_yes_no, failure, field, note, section, success, title


SERVICE_NAMES = (
    "ts-app-server-tspi.service",
    "ts-app-server-tspi@.service",
    "ts-web-tspi.service",
    # Remove service units left by pre-App-Server installations.
    "ts-phone-tspi.service",
    "ts-phone.service",
    "ts-web.service",
)
# Retired Phone entrypoints are included only so upgrades can remove them.
ENTRYPOINTS = ("TSPi", "TSWeb", "TSPhoneCtl", "TSPhoneServer")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-root")
    parser.add_argument("--service-scope", choices=("auto", "user", "system", "none"), default="auto")
    parser.add_argument("--purge-workspaces", action="store_true", help="Delete research workspaces and Pi session files.")
    parser.add_argument("--purge-config", action="store_true", help="Delete installation configuration and Phone/Web credentials.")
    parser.add_argument("--purge-runtime", action="store_true", help="Delete managed Conda/venv runtime state.")
    parser.add_argument("--remove-root", action="store_true", help="Remove the installation directory after cleanup.")
    parser.add_argument("--purge-all", action="store_true", help="Enable all purge and root removal options.")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def installation_identity(root: Path) -> dict[str, str | None]:
    metadata = read_installation_metadata(root, require_ownership=True, strict_package_state=False)
    ownership = metadata["ownership"]
    release_id = metadata["release_id"]
    state_error = metadata["state_error"]
    return {
        "ownership": str(ownership) if ownership is not None else None,
        "release_id": str(release_id) if release_id is not None else None,
        "state_error": str(state_error) if state_error is not None else None,
    }


def validate_root(path: Path) -> Path:
    if not path.is_absolute():
        raise ValueError("--install-root must be absolute")
    if path.expanduser().is_symlink():
        raise ValueError(f"installation root cannot be a symbolic link: {path.expanduser()}")
    resolved = path.expanduser().resolve()
    if resolved == Path("/") or resolved == Path.home() or resolved == Path.home().parent:
        raise ValueError(f"refusing to remove broad path: {resolved}")
    for relative in (".pi", ".pi/tspi", ".pi/packages", ".pi/ts-phone", ".agents", ".agents/runtime", ".agents/envs"):
        if (resolved / relative).is_symlink():
            raise ValueError(f"installation state directory cannot be a symbolic link: {resolved / relative}")
    installation_identity(resolved)
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

    identity = installation_identity(root)
    section("Installation")
    field("Target", root, tone="accent")
    field("Ownership", identity["ownership"], tone="success")
    if identity["state_error"]:
        field("Package state", "damaged; application files will still be removed", tone="warning")
    else:
        field("Active release", identity["release_id"] or "application already removed")

    section("Data cleanup")
    note("Application releases and matching services are always removed.")
    args.purge_workspaces = args.purge_workspaces or ask_yes_no("Delete workspaces and Pi session files", False)
    args.purge_config = args.purge_config or ask_yes_no("Delete installation config and Phone/Web credentials", False)
    args.purge_runtime = args.purge_runtime or ask_yes_no("Delete managed Python runtime state", False)
    all_data_selected = args.purge_workspaces and args.purge_config and args.purge_runtime
    if not args.remove_root and all_data_selected:
        args.remove_root = ask_yes_no("Remove the installation directory", False)

    section("Removal plan")
    field("Target", root, tone="accent")
    field("Application", "Remove", tone="warning")
    field("Workspaces", "Delete" if args.purge_workspaces else "Keep",
          tone="danger" if args.purge_workspaces else "success")
    field("Config and secrets", "Delete" if args.purge_config else "Keep",
          tone="danger" if args.purge_config else "success")
    field("Python runtime", "Delete" if args.purge_runtime else "Keep",
          tone="danger" if args.purge_runtime else "success")
    root_state = "Delete" if args.remove_root else "Keep"
    if not all_data_selected:
        root_state += " (requires all data cleanup options)"
    field("Installation root", root_state, tone="danger" if args.remove_root else "success")
    if not args.yes and not ask_yes_no("Proceed with uninstall", True):
        note("Uninstall cancelled.", tone="warning")
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
            if name == "ts-app-server-tspi@.service":
                for instance in app_server_instances(command):
                    subprocess.run(
                        [*command, "disable", "--now", instance],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                    stopped.append(f"{scope}:{instance}")
                    scope_stopped = True
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


def app_server_instances(command: list[str]) -> list[str]:
    completed = subprocess.run(
        [*command, "list-units", "--all", "--plain", "--no-legend", "ts-app-server-tspi@*.service"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        return []
    names = []
    for line in completed.stdout.splitlines():
        name = line.split(None, 1)[0] if line.strip() else ""
        if name.startswith("ts-app-server-tspi@") and name.endswith(".service") and "/" not in name:
            names.append(name)
    return names


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
    for relative in (
        ".pi/app-server-host/workspace/.pi",
        ".pi/app-server-host/workspace",
        ".pi/app-server-host/sessions",
        ".pi/app-server-host",
        ".pi/ts-phone",
        ".pi/packages",
        ".pi",
        ".agents/runtime",
        ".agents/envs",
        ".agents",
    ):
        directory = root / relative
        if not directory.is_dir():
            continue
        try:
            directory.rmdir()
        except OSError:
            pass


def uninstall(args: argparse.Namespace, *, show_progress: bool = False) -> dict[str, object]:
    root = validate_root(Path(args.install_root))
    choose_options(args, root)
    try:
        workspace_root = read_workspace_root(root)
    except ValueError:
        if args.purge_workspaces:
            raise
        workspace_root = root / "workspaces"
    if args.purge_workspaces:
        workspace_root = _validated_workspace_purge_target(root, workspace_root)
    activity = Spinner("Stopping TSPi services", stream=sys.stderr, enabled=show_progress)
    activity.start()
    try:
        stopped = stop_services(args, root)
        activity.update("Removing service registrations")
        service_units = remove_service_units(args, root)
        activity.update("Removing installed application files")
        removed = remove_entrypoints(root)
        managed = [
            root / ".pi/packages/tspi",
            root / ".pi/runtime-cache",
            root / ".pi/app-server-runtime",
            root / ".pi/logs",
            root / ".pi/session-guards",
            # Remove state left by the retired shared session process.
            root / ".pi/session-host",
            root / ".pi/ts-web-state",
            root / ".pi/ts-phone/ts-phone.service",
            root / ".pi/ts-phone/current",
            root / ".pi/ts-phone/releases",
        ]
        if args.purge_config:
            managed.extend([
                root / ".pi/tspi",
                root / ".pi/app-server-host/server-id",
                root / ".pi/app-server-host/phone-connection.json",
                root / ".pi/app-server-host/workspace",
                root / ".pi/agent",
                root / ".pi/email",
                root / ".pi/ts-phone",
                root / ".pi/ts-phone-state",
                root / ".pi/ts-web",
                root / ".pi/remote.toml",
                root / ".pi/local.toml",
                root / ".pi/compute.toml",
                root / ".pi/notifications.toml",
                root / "uninstall.sh",
            ])
        if args.purge_runtime:
            managed.extend([root / ".agents/runtime/tspi", root / ".agents/envs/tspi"])
        if args.purge_workspaces:
            managed.extend([
                workspace_root,
                root / ".pi/app-server-host/sessions",
            ])
        if args.purge_all:
            managed.append(root / "ts-phone")
        removed.extend(remove_paths(managed))
        prune_empty_parents(root)
        if args.remove_root:
            activity.update("Removing the installation directory")
            removed.extend(remove_paths([root]))
        removed.extend(service_units)
        activity.succeed("TSPi application files removed")
        return {"ok": True, "install_root": str(root), "workspace_root": str(workspace_root), "stopped_services": stopped, "removed": removed,
                "preserved_workspaces": not args.purge_workspaces, "preserved_config": not args.purge_config,
                "preserved_runtime": not args.purge_runtime}
    except BaseException:
        activity.fail("TSPi uninstall failed")
        raise


def _validated_workspace_purge_target(root: Path, configured: Path) -> Path:
    if not configured.is_absolute() or configured.is_symlink():
        raise ValueError(f"configured workspace root is unsafe: {configured}")
    resolved = configured.resolve()
    home = Path.home().resolve()
    if (
        resolved.parent == Path("/")
        or resolved == home
        or resolved in home.parents
        or resolved == root
        or resolved in root.parents
    ):
        raise ValueError(f"refusing to purge broad workspace root: {resolved}")
    for protected in (root / ".pi", root / ".agents"):
        if resolved == protected or protected in resolved.parents:
            raise ValueError(f"refusing to purge workspace root inside installation state: {resolved}")
    return resolved


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if not args.non_interactive:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise RuntimeError("interactive uninstall requires a TTY; use --non-interactive --yes")
            title("TSPi Uninstaller", "Remove TSPi while keeping research data by default.", tone="warning")
        if not args.install_root and not args.non_interactive:
            bundled = Path(__file__).resolve()
            default = str(bundled.parents[2]) if bundled.parent.name == "tspi" and bundled.parent.parent.name == ".pi" else str(Path.home() / ".local/share/tspi")
            args.install_root = ask("TSPi installation directory", default)
        if not args.install_root:
            raise ValueError("--install-root is required")
        result = uninstall(args, show_progress=not args.json)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            success("Uninstall complete")
            section("Summary")
            field("Installation", result["install_root"], tone="accent")
            field("Paths removed", len(result["removed"]))
            field("Services stopped", len(result["stopped_services"]))
            preserved = []
            if result["preserved_workspaces"]:
                preserved.append("workspaces")
            if result["preserved_config"]:
                preserved.append("config and secrets")
            if result["preserved_runtime"]:
                preserved.append("Python runtime")
            field("Preserved", ", ".join(preserved) if preserved else "nothing", tone="success" if preserved else "muted")
            section("Removed paths")
            for item in result["removed"]:
                note(item)
            for item in result["stopped_services"]:
                note(f"Stopped service: {item}")
        return 0
    except SystemExit as error:
        return int(error.code or 0)
    except (OSError, RuntimeError, ValueError) as error:
        failure(f"TSPi uninstall failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
