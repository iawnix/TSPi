"""Python lifecycle host for one installed TSPi Root Agent process."""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from .env import (
    DISABLE_REEXEC,
    ENV_OVERRIDE,
    RuntimeEnvironmentError,
    bind_runtime_process_environment,
    ensure_runtime_python,
)


PACKAGE_NAME = "@iawnix/ts-agent"
WORKSPACE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
NOTIFICATION_FIELDS = {"enabled", "recipient", "clawemail_root"}
EMAIL_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+$")


class TSPiHostError(RuntimeError):
    def __init__(self, message: str, *, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class LaunchRequest:
    workspace_name: str | None
    check_remote: bool
    phone_mode: bool
    show_help: bool
    pi_args: tuple[str, ...]


@dataclass(frozen=True)
class Installation:
    root: Path
    package_root: Path
    workspaces_root: Path
    remote_config_default: Path
    notification_config_default: Path
    runtime_home: Path
    runtime_manifest: Path
    env_root: Path
    process_cache_root: Path


USAGE = """Usage:
  ./TSPi --workspace <name> [Pi arguments...]
  ./TSPi --workspace <name> --phone
  ./TSPi --check-remote

Each workspace name creates or reuses an isolated research directory under
./workspaces/. Only one Root Agent may write one workspace at a time.
Remote computation uses the installation-owned .pi/remote.toml profile.
Phone mode starts the visible TSPi session with the local TS Phone bridge.
When another Root Agent owns the workspace, phone mode starts a separate
read-only observer session instead of sharing the writer's Pi session.
TSPi loads only the validated release selected by .pi/packages/ts-agent/current.
Package development runs separately in the authored checkout.
"""


def parse_launch_request(argv: list[str]) -> LaunchRequest:
    check_remote = False
    phone_mode = False
    show_help = False
    workspace_name: str | None = None
    pi_args: list[str] = []
    index = 0
    while index < len(argv):
        value = argv[index]
        if value == "--":
            pi_args.extend(argv[index + 1 :])
            break
        if value == "--check-remote":
            check_remote = True
        elif value == "--phone":
            phone_mode = True
        elif value == "--phone-worker":
            raise TSPiHostError(
                "--phone-worker was removed; use --phone to start the visible bridged TUI",
                exit_code=2,
            )
        elif value == "--workspace":
            index += 1
            if index >= len(argv) or not argv[index]:
                raise TSPiHostError("--workspace requires a name", exit_code=2)
            workspace_name = argv[index]
        elif value.startswith("--workspace="):
            workspace_name = value.removeprefix("--workspace=")
        elif value in {"-h", "--help"}:
            show_help = True
        else:
            pi_args.append(value)
        index += 1
    return LaunchRequest(workspace_name, check_remote, phone_mode, show_help, tuple(pi_args))


def resolve_installation(package_root: str | Path, install_root: str | Path) -> Installation:
    requested_install = Path(install_root).expanduser()
    if requested_install.is_symlink():
        raise TSPiHostError(f"installation root cannot be a symbolic link: {requested_install}")
    if not requested_install.is_dir():
        raise TSPiHostError(f"installation root is not a directory: {requested_install}")
    root = requested_install.resolve()
    package_home = root / ".pi" / "packages" / "ts-agent"
    releases_root = package_home / "releases"
    current = package_home / "current"
    if not current.is_symlink():
        raise TSPiHostError(
            f"no installed TS Agent release: {current}\n"
            "TSPi: install a validated release before starting a research workspace"
        )
    try:
        active = current.resolve(strict=True)
        releases = releases_root.resolve(strict=True)
    except OSError as exc:
        raise TSPiHostError(f"current TS Agent release is unavailable: {current}: {exc}") from exc
    expected = Path(package_root).expanduser().resolve()
    if active != expected:
        raise TSPiHostError(f"launcher package does not match the active release: {expected}")
    if active.parent != releases:
        raise TSPiHostError(f"current TS Agent release escaped the release store: {active}")
    _validate_release_identity(active)
    runtime_home = root / ".agents" / "runtime" / "transition-state-workflow"
    return Installation(
        root=root,
        package_root=active,
        workspaces_root=root / "workspaces",
        remote_config_default=root / ".pi" / "remote.toml",
        notification_config_default=root / ".pi" / "notifications.toml",
        runtime_home=runtime_home,
        runtime_manifest=runtime_home / "env.json",
        env_root=root / ".agents" / "envs" / "transition-state-workflow",
        process_cache_root=root / ".pi" / "runtime-cache",
    )


def _validate_release_identity(root: Path) -> None:
    manifest_path = root / ".ts-agent-release.json"
    package_path = root / "package.json"
    for path, label in ((manifest_path, "installation manifest"), (package_path, "package manifest")):
        if path.is_symlink() or not path.is_file():
            raise TSPiHostError(f"current TS Agent release has no valid {label}: {path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TSPiHostError(f"current TS Agent release metadata is invalid: {exc}") from exc
    manifest_package = manifest.get("package") if isinstance(manifest, dict) else None
    if (
        manifest.get("schema_version") != "ts-agent-release/1"
        or manifest.get("release_id") != root.name
        or not isinstance(manifest_package, dict)
        or package.get("name") != PACKAGE_NAME
        or manifest_package.get("name") != package.get("name")
        or manifest_package.get("version") != package.get("version")
    ):
        raise TSPiHostError(f"current TS Agent release identity is invalid: {root}")


def configure_runtime_environment(installation: Installation) -> None:
    os.environ.pop(ENV_OVERRIDE, None)
    os.environ.pop(DISABLE_REEXEC, None)
    os.environ["TS_AGENT_RUNTIME_HOME"] = str(installation.runtime_home)
    os.environ["TS_AGENT_RUNTIME_MANIFEST"] = str(installation.runtime_manifest)
    os.environ["TS_AGENT_ENV_ROOT"] = str(installation.env_root)


def prepare_workspace(installation: Installation, workspace_name: str) -> Path:
    if not WORKSPACE_NAME.fullmatch(workspace_name):
        raise TSPiHostError(
            f"invalid workspace name: {workspace_name}\n"
            "TSPi: use 1-80 letters, digits, dots, underscores, or hyphens; start with a letter or digit"
        )
    container = installation.workspaces_root
    if container.is_symlink():
        raise TSPiHostError(f"workspace container cannot be a symbolic link: {container}")
    container.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not container.is_dir():
        raise TSPiHostError(f"workspace container is not a directory: {container}")
    requested = container / workspace_name
    if requested.is_symlink():
        raise TSPiHostError(f"workspace cannot be a symbolic link: {requested}")
    if requested.exists() and not requested.is_dir():
        raise TSPiHostError(f"workspace path is not a directory: {requested}")
    requested.mkdir(mode=0o700, exist_ok=True)
    workspace = requested.resolve()
    if workspace.parent != container.resolve():
        raise TSPiHostError(f"resolved workspace escaped the installation workspace container: {workspace}")
    pi_root = workspace / ".pi"
    sessions = pi_root / "sessions"
    if pi_root.is_symlink() or sessions.is_symlink():
        raise TSPiHostError(f"workspace Pi state paths cannot be symbolic links: {workspace}")
    sessions.mkdir(parents=True, exist_ok=True, mode=0o700)
    pi_root.chmod(0o700)
    sessions.chmod(0o700)
    _configure_workspace_pi_settings(pi_root / "settings.json")
    return workspace


def _configure_workspace_pi_settings(path: Path) -> None:
    if path.is_symlink():
        raise TSPiHostError(f"workspace Pi settings cannot be a symbolic link: {path}")
    try:
        settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise TSPiHostError(f"invalid workspace Pi settings: {path}: {exc}") from exc
    if not isinstance(settings, dict):
        raise TSPiHostError(f"workspace Pi settings must contain a JSON object: {path}")
    if settings.get("quietStartup") is True:
        return
    settings["quietStartup"] = True
    _atomic_write_json(path, settings)


def _atomic_write_json(path: Path, value: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def configure_remote(installation: Installation) -> None:
    configured = os.environ.get("TS_REMOTE_CONFIG")
    if not configured and installation.remote_config_default.is_file():
        configured = str(installation.remote_config_default)
        os.environ["TS_REMOTE_CONFIG"] = configured
    if not configured:
        os.environ.pop("TS_REMOTE_CONFIG", None)
        os.environ["TS_REMOTE_DISPLAY_TARGET"] = "not configured"
        return
    path = _require_config_file(configured, "TS_REMOTE_CONFIG")
    try:
        with path.open("rb") as handle:
            config = tomllib.load(handle)
        profile_name = config.get("default_profile")
        profiles = config.get("profiles", {})
        profile = profiles.get(profile_name, {}) if isinstance(profiles, dict) else {}
        if not isinstance(profile, dict):
            raise ValueError("default profile must be a table")
        host = profile.get("ssh_host", profile_name or "configured")
        scheduler = str(profile.get("scheduler", "torque")).title()
    except (OSError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise TSPiHostError(f"invalid remote configuration: {path}: {exc}") from exc
    os.environ["TS_REMOTE_CONFIG"] = str(path)
    os.environ["TS_REMOTE_DISPLAY_TARGET"] = f"{host} · {scheduler}"


def configure_notifications(installation: Installation) -> None:
    configured = os.environ.get("TS_NOTIFICATION_CONFIG")
    if not configured and installation.notification_config_default.is_file():
        configured = str(installation.notification_config_default)
        os.environ["TS_NOTIFICATION_CONFIG"] = configured
    if not configured:
        os.environ.pop("TS_NOTIFICATION_CONFIG", None)
        os.environ["TS_NOTIFICATION_DISPLAY_TARGET"] = "not configured"
        return
    path = _require_config_file(configured, "TS_NOTIFICATION_CONFIG")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise TSPiHostError(f"TS_NOTIFICATION_CONFIG must not be accessible by group or others: {path}")
    try:
        with path.open("rb") as handle:
            config = tomllib.load(handle)
        if set(config) != {"notifications"}:
            raise ValueError("expected only [notifications]")
        notifications = config["notifications"]
        if not isinstance(notifications, dict) or set(notifications) != {"email"}:
            raise ValueError("expected only [notifications.email]")
        email = notifications["email"]
        if not isinstance(email, dict) or set(email) != NOTIFICATION_FIELDS:
            raise ValueError("notifications.email fields must be enabled, recipient, and clawemail_root")
        enabled = email["enabled"]
        recipient = email["recipient"]
        clawemail_root = email["clawemail_root"]
        if not isinstance(enabled, bool):
            raise ValueError("notifications.email.enabled must be true or false")
        if not isinstance(recipient, str) or len(recipient) > 320 or not EMAIL_ADDRESS.fullmatch(recipient):
            raise ValueError("notifications.email.recipient must be one email address")
        if not isinstance(clawemail_root, str) or not clawemail_root.startswith("/"):
            raise ValueError("notifications.email.clawemail_root must be an absolute path")
    except (KeyError, OSError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise TSPiHostError(f"invalid notification configuration: {path}: {exc}") from exc
    os.environ["TS_NOTIFICATION_CONFIG"] = str(path)
    os.environ["TS_NOTIFICATION_DISPLAY_TARGET"] = recipient if enabled else "disabled"


def _require_config_file(value: str, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or not os.access(path, os.R_OK):
        raise TSPiHostError(f"invalid {label}: {path}")
    return path.resolve()


def check_remote(installation: Installation) -> int:
    configured = os.environ.get("TS_REMOTE_CONFIG")
    if not configured:
        print(f"TSPi: remote configuration is missing: {installation.remote_config_default}", file=sys.stderr)
        return 1
    completed = subprocess.run(
        [sys.executable, str(installation.package_root / "scripts" / "ts_compute.py"), "remote-diagnostic", "--mode", "status"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = None
    if completed.returncode == 0 and isinstance(payload, dict) and payload.get("ok") is True:
        print(f"TSPi: remote check passed ({os.environ['TS_REMOTE_DISPLAY_TARGET']})")
        return 0
    print(f"TSPi: remote check failed ({os.environ['TS_REMOTE_DISPLAY_TARGET']})", file=sys.stderr)
    if completed.stdout.strip():
        print(completed.stdout.rstrip(), file=sys.stderr)
    if completed.stderr.strip():
        print(completed.stderr.rstrip(), file=sys.stderr)
    return 1


def configure_process_environment(installation: Installation, workspace: Path, workspace_name: str) -> None:
    os.environ["TS_PACKAGE_ROOT"] = str(installation.package_root)
    os.environ["TS_WORKSPACE_ROOT"] = str(workspace)
    python_cache = installation.process_cache_root / "python" / workspace_name
    pytest_cache = installation.process_cache_root / "pytest" / workspace_name
    for path in (installation.process_cache_root, python_cache.parent, pytest_cache.parent, python_cache, pytest_cache):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
    os.environ["PYTHONPYCACHEPREFIX"] = str(python_cache)
    cache_option = f"--cache-dir={pytest_cache}"
    existing = os.environ.get("PYTEST_ADDOPTS", "")
    os.environ["PYTEST_ADDOPTS"] = f"{existing} {cache_option}".strip()


def acquire_root_agent_lock(workspace: Path, *, observer_on_contention: bool = False) -> int | None:
    lock_path = workspace / ".pi" / "root-agent.lock"
    if lock_path.is_symlink():
        raise TSPiHostError(f"Root Agent lock cannot be a symbolic link: {lock_path}")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise TSPiHostError(f"Root Agent lock must be a regular file: {lock_path}")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            if observer_on_contention:
                os.close(descriptor)
                return None
            raise TSPiHostError(
                f"another Root Agent already owns workspace {workspace}\n"
                "TSPi: choose another --workspace name or stop the existing Root Agent"
            ) from exc
        payload = f"pid={os.getpid()}\nstarted_at={_local_timestamp()}\n".encode("ascii")
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.write(descriptor, payload)
        os.fsync(descriptor)
        os.set_inheritable(descriptor, True)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _local_timestamp() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


def _resolve_pi_binary() -> Path:
    requested = os.environ.get("PI_BIN", "/home/iaw/.npm-global/bin/pi")
    candidate = shutil.which(requested) if not Path(requested).is_absolute() else requested
    if not candidate:
        raise TSPiHostError(f"Pi executable not found: {requested}", exit_code=127)
    path = Path(candidate).expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise TSPiHostError(f"Pi executable not found: {requested}", exit_code=127)
    return path


def build_pi_command(
    installation: Installation,
    workspace: Path,
    request: LaunchRequest,
) -> list[str]:
    pi_args = list(request.pi_args)
    phone_extension: list[str] = []
    if request.phone_mode:
        os.environ["TS_PHONE_MODE"] = "bridge"
        os.environ["TS_PHONE_WORKSPACE_ID"] = str(request.workspace_name)
        phone_extension = ["-e", str(installation.package_root / "extensions" / "ts-phone-bridge" / "index.ts")]
        pi_args = ["--continue"] if os.environ.get("TS_PHONE_ACCESS_MODE") == "controller" else []
    package = installation.package_root
    return [
        str(_resolve_pi_binary()),
        "--no-extensions",
        "--no-skills",
        "--skill",
        str(package / "skills" / "transition-state-workflow"),
        "--no-themes",
        "--theme",
        str(package / "themes" / "ts-theme.json"),
        "--no-prompt-templates",
        "-e",
        str(package / "extensions" / "ts-workflow-control" / "index.ts"),
        "-e",
        str(package / "extensions" / "ts-workflow-ui" / "index.ts"),
        "-e",
        str(package / "extensions" / "ts-workflow-review" / "index.ts"),
        "-e",
        str(package / "extensions" / "ts-workflow-compute" / "index.ts"),
        "-e",
        str(package / "extensions" / "ts-workflow-artifacts" / "index.ts"),
        *phone_extension,
        "--approve",
        "--session-dir",
        str(workspace / ".pi" / "sessions"),
        *pi_args,
    ]


def exec_pi(command: list[str], workspace: Path) -> NoReturn:
    os.chdir(workspace)
    os.execve(command[0], command, dict(os.environ))


def launch(argv: list[str], *, package_root: str | Path, install_root: str | Path) -> int:
    request = parse_launch_request(argv)
    if request.show_help:
        print(USAGE, end="")
        return 0
    if request.check_remote and request.phone_mode:
        raise TSPiHostError("--check-remote cannot be combined with phone mode", exit_code=2)
    if request.phone_mode and request.pi_args:
        raise TSPiHostError("--phone does not accept Pi arguments", exit_code=2)
    installation = resolve_installation(package_root, install_root)
    configure_runtime_environment(installation)
    try:
        python = ensure_runtime_python(installation.package_root, required=True)
        if python is None:
            raise RuntimeEnvironmentError("managed TS Python runtime could not be selected")
        bind_runtime_process_environment(python)
    except RuntimeEnvironmentError as exc:
        raise TSPiHostError(str(exc)) from exc
    configure_remote(installation)
    if request.check_remote:
        return check_remote(installation)
    if not request.workspace_name:
        raise TSPiHostError(f"a research workspace is required\n{USAGE}", exit_code=2)
    configure_notifications(installation)
    workspace = prepare_workspace(installation, request.workspace_name)
    configure_process_environment(installation, workspace, request.workspace_name)
    _lock_descriptor = acquire_root_agent_lock(workspace, observer_on_contention=request.phone_mode)
    if _lock_descriptor is None:
        workspace_manifest = workspace / "workspace.json"
        if workspace_manifest.is_symlink() or not workspace_manifest.is_file():
            raise TSPiHostError(
                "the controller is still preparing this workspace; retry the phone observer after it starts"
            )
        os.environ["TS_PHONE_ACCESS_MODE"] = "observer"
        print(
            f"TSPi: workspace {request.workspace_name} is already controlled; starting a read-only phone observer",
            file=sys.stderr,
        )
    else:
        if request.phone_mode:
            os.environ["TS_PHONE_ACCESS_MODE"] = "controller"
        from ts_workspace.bootstrap import WorkspaceBootstrapError, bootstrap_workspace

        try:
            bootstrap_workspace(workspace)
        except WorkspaceBootstrapError as exc:
            raise TSPiHostError(str(exc)) from exc
    command = build_pi_command(installation, workspace, request)
    exec_pi(command, workspace)


def main(
    argv: list[str] | None = None,
    *,
    package_root: str | Path | None = None,
    install_root: str | Path,
) -> int:
    package = Path(package_root).resolve() if package_root else Path(__file__).resolve().parents[1]
    try:
        return launch(list(sys.argv[1:] if argv is None else argv), package_root=package, install_root=install_root)
    except TSPiHostError as exc:
        print(f"TSPi: {exc}", file=sys.stderr)
        return exc.exit_code
    except (OSError, ValueError) as exc:
        print(f"TSPi: startup failed: {exc}", file=sys.stderr)
        return 1
