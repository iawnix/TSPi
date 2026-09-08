"""Python lifecycle host for one installed TSPi Root Agent process."""

from __future__ import annotations

import fcntl
import argparse
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
    PACKAGE_ROOT_OVERRIDE,
    RuntimeEnvironmentError,
    bind_runtime_process_environment,
    ensure_runtime_python,
    package_root_from_file,
)
from .session_guard import (
    CONTRACT as SESSION_GUARD_CONTRACT,
    SessionGuardError,
    acquire_directory_guard,
    acquire_session_guard,
    assert_no_unguarded_writers,
    select_session,
    verify_session_writer,
)


PACKAGE_NAME = "@iawnix/ts-agent"
SUITE_PACKAGE_NAME = "@iawnix/tspi"
WORKSPACE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
SESSION_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,158}[A-Za-z0-9])?$")
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
NOTIFICATION_FIELDS = {"enabled", "recipient", "clawemail_root"}
EMAIL_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+$")


class TSPiHostError(RuntimeError):
    def __init__(self, message: str, *, exit_code: int = 1, code: str | None = None):
        super().__init__(message)
        self.exit_code = exit_code
        self.code = code


@dataclass(frozen=True)
class LaunchRequest:
    workspace_name: str | None
    check_remote: bool
    phone_mode: bool
    phone_worker: bool
    lifecycle_preflight: bool
    lifecycle_guard: bool
    session_id: str | None
    session_name: str | None
    model: str | None
    phone_access: str | None
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
Use --phone --phone-access observer explicitly for a separate read-only assistant.
Continue an exact conversation with --session-id <id>, or the latest with -c.
An occupied workspace/session is a conflict, never an automatic mode downgrade.
Managed sessions cannot switch, resume, or fork in-process; exit and reopen.
TSPi loads only the validated Package selected by .pi/packages/tspi/current.
Package development runs separately in the authored checkout.
"""


def parse_launch_request(argv: list[str]) -> LaunchRequest:
    check_remote = False
    phone_mode = False
    phone_worker = "--phone-worker" in argv
    lifecycle_preflight = "--lifecycle-preflight" in argv
    lifecycle_guard = "--lifecycle-guard" in argv
    show_help = False
    workspace_name: str | None = None
    session_id: str | None = None
    session_name: str | None = None
    model: str | None = None
    phone_access: str | None = None
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
            phone_worker = True
        elif value == "--lifecycle-preflight":
            lifecycle_preflight = True
        elif value == "--lifecycle-guard":
            lifecycle_guard = True
        elif value == "--workspace":
            index += 1
            if index >= len(argv) or not argv[index]:
                raise TSPiHostError("--workspace requires a name", exit_code=2)
            workspace_name = argv[index]
        elif value.startswith("--workspace="):
            workspace_name = value.removeprefix("--workspace=")
        elif value in {"--session-id", "--phone-access"} or (phone_worker and value in {"--name", "--model"}):
            index += 1
            if index >= len(argv) or not argv[index]:
                raise TSPiHostError(f"{value} requires a value", exit_code=2)
            if value == "--session-id":
                session_id = argv[index]
            elif value == "--name":
                session_name = argv[index]
            elif value == "--model":
                model = argv[index]
            else:
                phone_access = argv[index]
        elif value.startswith("--session-id="):
            session_id = value.removeprefix("--session-id=")
        elif phone_worker and value.startswith("--name="):
            session_name = value.removeprefix("--name=")
        elif phone_worker and value.startswith("--model="):
            model = value.removeprefix("--model=")
        elif value.startswith("--phone-access="):
            phone_access = value.removeprefix("--phone-access=")
        elif value in {"-h", "--help"}:
            show_help = True
        else:
            pi_args.append(value)
        index += 1
    return LaunchRequest(
        workspace_name=workspace_name,
        check_remote=check_remote,
        phone_mode=phone_mode,
        phone_worker=phone_worker,
        lifecycle_preflight=lifecycle_preflight,
        lifecycle_guard=lifecycle_guard,
        session_id=session_id,
        session_name=session_name,
        model=model,
        phone_access=phone_access,
        show_help=show_help,
        pi_args=tuple(pi_args),
    )


def resolve_installation(package_root: str | Path, install_root: str | Path) -> Installation:
    requested_install = Path(install_root).expanduser()
    if requested_install.is_symlink():
        raise TSPiHostError(f"installation root cannot be a symbolic link: {requested_install}")
    if not requested_install.is_dir():
        raise TSPiHostError(f"installation root is not a directory: {requested_install}")
    root = requested_install.resolve()
    package_home = root / ".pi" / "packages" / "tspi"
    releases_root = package_home / "releases"
    current = package_home / "current"
    if not current.is_symlink():
        raise TSPiHostError(
            f"no selected TSPi Package release: {current}\n"
            "TSPi: install a validated Package before starting a research workspace"
        )
    try:
        suite_root = current.resolve(strict=True)
        releases = releases_root.resolve(strict=True)
    except OSError as exc:
        raise TSPiHostError(f"selected TSPi Package is unavailable: {current}: {exc}") from exc
    if suite_root.parent != releases:
        raise TSPiHostError(f"selected TSPi Package escaped the release store: {suite_root}")
    expected_agent = Path(package_root).expanduser().resolve()
    selected_agent = suite_root / "agent"
    if selected_agent.is_symlink() or not selected_agent.is_dir():
        raise TSPiHostError(f"selected TSPi Package has no regular Agent component: {selected_agent}")
    if selected_agent.resolve() != expected_agent:
        raise TSPiHostError(f"launcher Agent does not match the selected TSPi Package: {expected_agent}")
    _validate_suite_identity(suite_root, expected_agent)
    runtime_home = root / ".agents" / "runtime" / "transition-state-workflow"
    return Installation(
        root=root,
        package_root=expected_agent,
        workspaces_root=root / "workspaces",
        remote_config_default=root / ".pi" / "remote.toml",
        notification_config_default=root / ".pi" / "notifications.toml",
        runtime_home=runtime_home,
        runtime_manifest=runtime_home / "env.json",
        env_root=root / ".agents" / "envs" / "transition-state-workflow",
        process_cache_root=root / ".pi" / "runtime-cache",
    )


def _validate_suite_identity(suite_root: Path, agent_root: Path) -> None:
    manifest_path = suite_root / ".tspi-package-release.json"
    package_path = agent_root / "package.json"
    for path, label in ((manifest_path, "Package manifest"), (package_path, "Agent package manifest")):
        if path.is_symlink() or not path.is_file():
            raise TSPiHostError(f"selected TSPi Package has no valid {label}: {path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TSPiHostError(f"selected TSPi Package metadata is invalid: {exc}") from exc
    suite_package = manifest.get("package") if isinstance(manifest, dict) else None
    components = manifest.get("components") if isinstance(manifest, dict) else None
    agent = components.get("agent") if isinstance(components, dict) else None
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {"schema_version", "release_id", "package", "components", "archive", "created_at_utc"}
        or manifest.get("schema_version") != "tspi-package-release/2"
        or manifest.get("release_id") != suite_root.name
        or not isinstance(suite_package, dict)
        or suite_package.get("name") != SUITE_PACKAGE_NAME
        or not isinstance(agent, dict)
        or not isinstance(package, dict)
        or package.get("name") != PACKAGE_NAME
        or suite_package.get("version") != package.get("version")
        or agent.get("version") != package.get("version")
    ):
        raise TSPiHostError(f"selected TSPi Package identity is invalid: {suite_root}")


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


def resolve_existing_workspace(installation: Installation, workspace_name: str) -> Path:
    if not WORKSPACE_NAME.fullmatch(workspace_name):
        raise TSPiHostError(f"invalid workspace name: {workspace_name}", exit_code=2)
    container = installation.workspaces_root
    requested = container / workspace_name
    if container.is_symlink() or requested.is_symlink() or not requested.is_dir():
        raise TSPiHostError(f"workspace is unavailable: {requested}")
    workspace = requested.resolve()
    if workspace.parent != container.resolve():
        raise TSPiHostError(f"resolved workspace escaped the installation workspace container: {workspace}")
    return workspace


def lifecycle_preflight(
    workspace: Path,
    *,
    root_agent_active: bool | None = None,
    session_writers_active: bool = False,
) -> dict[str, object]:
    from ts_agent.workspace.operational import operational_snapshot

    if root_agent_active is None:
        root_agent_active = inspect_root_agent_lock(workspace)
    snapshot = operational_snapshot(workspace)
    integrity_sections = [
        key
        for key in (
            "activity_integrity_findings",
            "operational_integrity_findings",
            "calculation_attempt_integrity_findings",
        )
        if snapshot.get(key)
    ]
    if integrity_sections:
        raise TSPiHostError(
            "workspace operational state cannot be verified for deletion: "
            + ", ".join(integrity_sections)
        )
    attempts = snapshot.get("calculation_attempts", [])
    remote_calculations = sum(
        1
        for row in attempts
        if isinstance(row, dict)
        and isinstance(row.get("job_id"), str)
        and bool(row["job_id"])
        and row.get("terminal") is not True
    )
    pending = snapshot.get("pending_controls", [])
    unresolved = snapshot.get("unresolved_controls", [])
    return {
        "schema_version": "ts-phone-project-preflight/2",
        "workspace_root": str(workspace),
        "root_agent_active": root_agent_active,
        "session_writers_active": session_writers_active,
        "session_guard_contract": SESSION_GUARD_CONTRACT,
        "remote_calculations": remote_calculations,
        "unresolved_remote_effects": sum(
            len(value) if isinstance(value, list) else 1
            for value in (pending, unresolved)
        ),
    }


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
    os.environ[PACKAGE_ROOT_OVERRIDE] = str(installation.package_root)
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


def inspect_root_agent_lock(workspace: Path) -> bool:
    """Report lock ownership without creating or modifying the lock file."""

    pi_root = workspace / ".pi"
    if pi_root.is_symlink():
        raise TSPiHostError(f"workspace Pi state path cannot be a symbolic link: {pi_root}")
    lock_path = pi_root / "root-agent.lock"
    if lock_path.is_symlink():
        raise TSPiHostError(f"Root Agent lock cannot be a symbolic link: {lock_path}")
    flags = os.O_RDONLY | os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags)
    except FileNotFoundError:
        return False
    try:
        _validate_root_agent_lock(descriptor, lock_path)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    finally:
        os.close(descriptor)


def acquire_lifecycle_guard(workspace: Path) -> int | None:
    """Hold the Root Agent lock while the Phone Host performs a mutation."""

    pi_root = workspace / ".pi"
    if pi_root.is_symlink():
        raise TSPiHostError(f"workspace Pi state path cannot be a symbolic link: {pi_root}")
    pi_root.mkdir(mode=0o700, exist_ok=True)
    if not pi_root.is_dir():
        raise TSPiHostError(f"workspace Pi state path is not a directory: {pi_root}")
    descriptor = _open_root_agent_lock(pi_root / "root-agent.lock")
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
            return None
        _validate_root_agent_lock(descriptor, pi_root / "root-agent.lock")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def acquire_root_agent_lock(workspace: Path, *, observer_on_contention: bool = False) -> int | None:
    lock_path = workspace / ".pi" / "root-agent.lock"
    descriptor = _open_root_agent_lock(lock_path)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            if observer_on_contention:
                os.close(descriptor)
                return None
            raise TSPiHostError(
                f"another Root Agent already owns workspace {workspace}\n"
                "TSPi: choose another --workspace name or stop the existing Root Agent",
                code="session_writer_active",
            ) from exc
        _validate_root_agent_lock(descriptor, lock_path)
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


def _open_root_agent_lock(lock_path: Path) -> int:
    if lock_path.is_symlink():
        raise TSPiHostError(f"Root Agent lock cannot be a symbolic link: {lock_path}")
    flags = os.O_RDWR | os.O_CREAT | os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        _validate_root_agent_lock(descriptor, lock_path)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _validate_root_agent_lock(descriptor: int, lock_path: Path) -> None:
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode):
        raise TSPiHostError(f"Root Agent lock must be a regular file: {lock_path}")
    current = lock_path.lstat()
    if lock_path.parent.is_symlink() or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
        raise TSPiHostError(f"Root Agent lock changed while opening: {lock_path}")


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
    *,
    session_args: list[str] | None = None,
) -> list[str]:
    pi_args = list(request.pi_args)
    phone_extension: list[str] = []
    if request.phone_mode or request.phone_worker:
        os.environ["TS_PHONE_MODE"] = "bridge"
        os.environ["TS_PHONE_WORKSPACE_ID"] = str(request.workspace_name)
        phone_extension = ["-e", str(installation.package_root / "extensions" / "ts-phone-bridge" / "index.ts")]
        if request.phone_worker:
            os.environ["TS_PHONE_WORKER"] = "1"
            pi_args = ["--mode", "rpc", "--session-id", str(request.session_id)]
            if request.session_name:
                pi_args.extend(["--name", request.session_name])
            if request.model:
                pi_args.extend(["--model", request.model])
        else:
            pi_args = ["--continue"] if os.environ.get("TS_PHONE_ACCESS_MODE") == "controller" else []
    if session_args is not None:
        pi_args = session_args
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
    if "--session-writer-check" in argv:
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--session-writer-check", action="store_true", required=True)
        parser.add_argument("--workspace", required=True)
        parser.add_argument("--session-id", required=True)
        parser.add_argument("--phone-access", required=True, choices=("controller", "observer"))
        parser.add_argument("--writer-pid", required=True, type=int)
        options = parser.parse_args(argv)
        installation = resolve_installation(package_root, install_root)
        workspace = resolve_existing_workspace(installation, options.workspace)
        try:
            verify_session_writer(installation.root, workspace, options.session_id, options.phone_access, options.writer_pid)
        except SessionGuardError as exc:
            raise TSPiHostError(str(exc)) from exc
        print(json.dumps({"session_guard_contract": SESSION_GUARD_CONTRACT, "verified": True,
            "workspace_root": str(workspace), "session_id": options.session_id,
            "access_mode": options.phone_access, "pid": options.writer_pid}))
        return 0
    if argv == ["--session-host-capabilities"]:
        resolve_installation(package_root, install_root)
        print(json.dumps({"session_guard_contract": SESSION_GUARD_CONTRACT}))
        return 0
    request = parse_launch_request(argv)
    if request.show_help:
        print(USAGE, end="")
        return 0
    if request.phone_mode and request.phone_worker:
        raise TSPiHostError("--phone and --phone-worker cannot be combined", exit_code=2)
    lifecycle_operation = request.lifecycle_preflight or request.lifecycle_guard
    if request.lifecycle_preflight and request.lifecycle_guard:
        raise TSPiHostError("lifecycle preflight and guard modes cannot be combined", exit_code=2)
    if lifecycle_operation and (request.check_remote or request.phone_mode or request.phone_worker or request.pi_args):
        raise TSPiHostError("a lifecycle operation cannot be combined with another operation", exit_code=2)
    if request.check_remote and (request.phone_mode or request.phone_worker):
        raise TSPiHostError("--check-remote cannot be combined with phone mode", exit_code=2)
    if request.phone_worker and request.pi_args:
        raise TSPiHostError("phone mode does not accept additional Pi arguments", exit_code=2)
    if request.phone_access is not None and (
        not (request.phone_mode or request.phone_worker)
        or request.phone_access not in {"controller", "observer"}
    ):
        raise TSPiHostError("--phone-access requires --phone and controller or observer", exit_code=2)
    if request.phone_worker:
        if not request.session_id or not SESSION_ID.fullmatch(request.session_id):
            raise TSPiHostError("--phone-worker requires a valid --session-id", exit_code=2)
        if request.phone_access not in {"controller", "observer"}:
            raise TSPiHostError("--phone-worker requires --phone-access controller or observer", exit_code=2)
        if request.session_name is not None and (
            not 1 <= len(request.session_name) <= 120
            or request.session_name.strip() != request.session_name
            or any(ord(character) < 32 or ord(character) == 127 for character in request.session_name)
        ):
            raise TSPiHostError("--name is invalid", exit_code=2)
        if request.model is not None and not MODEL_ID.fullmatch(request.model):
            raise TSPiHostError("--model is invalid", exit_code=2)
    installation = resolve_installation(package_root, install_root)
    configure_runtime_environment(installation)
    try:
        python = ensure_runtime_python(installation.package_root, required=True)
        if python is None:
            raise RuntimeEnvironmentError("managed TS Python runtime could not be selected")
        bind_runtime_process_environment(python)
    except RuntimeEnvironmentError as exc:
        raise TSPiHostError(str(exc)) from exc
    if lifecycle_operation:
        if not request.workspace_name:
            raise TSPiHostError(f"a research workspace is required\n{USAGE}", exit_code=2)
        workspace = resolve_existing_workspace(installation, request.workspace_name)
        guard_descriptor = None
        directory_descriptor = None
        writers_active = False
        try:
            try:
                directory_descriptor = acquire_directory_guard(installation.root, workspace, exclusive=True)
                assert_no_unguarded_writers(workspace)
                if request.lifecycle_guard:
                    guard_descriptor = acquire_lifecycle_guard(workspace)
            except SessionGuardError:
                writers_active = True
            preflight = lifecycle_preflight(
                workspace,
                root_agent_active=False if guard_descriptor is not None else None,
                session_writers_active=writers_active,
            )
            if request.lifecycle_guard:
                preflight = {
                    **preflight,
                    "schema_version": "ts-phone-project-guard/1",
                    "guard_acquired": guard_descriptor is not None,
                }
            print(json.dumps(preflight, sort_keys=True), flush=True)
            if guard_descriptor is not None:
                sys.stdin.buffer.read(1)
        finally:
            if guard_descriptor is not None:
                os.close(guard_descriptor)
            if directory_descriptor is not None:
                os.close(directory_descriptor)
        return 0
    configure_remote(installation)
    if request.check_remote:
        return check_remote(installation)
    if not request.workspace_name:
        raise TSPiHostError(f"a research workspace is required\n{USAGE}", exit_code=2)
    configure_notifications(installation)
    if not WORKSPACE_NAME.fullmatch(request.workspace_name):
        raise TSPiHostError("invalid workspace name")
    workspace = installation.workspaces_root / request.workspace_name
    mode = request.phone_access or "controller"
    descriptors: list[int] = []
    try:
        descriptors.append(acquire_directory_guard(installation.root, workspace))
        workspace = (
            resolve_existing_workspace(installation, request.workspace_name)
            if mode == "observer"
            else prepare_workspace(installation, request.workspace_name)
        )
        configure_process_environment(installation, workspace, request.workspace_name)
        assert_no_unguarded_writers(workspace)
        if mode == "controller":
            descriptors.append(acquire_root_agent_lock(workspace))
            from ts_agent.workspace.bootstrap import WorkspaceBootstrapError, bootstrap_workspace

            try:
                bootstrap_workspace(workspace)
            except WorkspaceBootstrapError as exc:
                raise TSPiHostError(str(exc)) from exc
        elif not (workspace / "workspace.json").is_file():
            raise TSPiHostError("workspace bootstrap must finish before starting an observer")
        arguments = list(request.pi_args)
        if request.session_id:
            arguments.extend(["--session-id", request.session_id])
        session_id, arguments = select_session(
            workspace, arguments, default_continue=request.phone_mode and mode == "controller"
        )
        descriptors.append(acquire_session_guard(installation.root, workspace, session_id, mode))
        os.environ["TS_SESSION_GUARD"] = SESSION_GUARD_CONTRACT
        os.environ["TS_SESSION_ID"] = session_id
        os.environ["TS_SESSION_WRITER_PID"] = str(os.getpid())
        if not request.phone_worker:
            os.environ.pop("TS_PHONE_WORKER", None)
            os.environ.pop("TS_PHONE_LAUNCH_ID", None)
        if request.phone_mode or request.phone_worker:
            os.environ["TS_PHONE_ACCESS_MODE"] = mode
        if request.phone_worker:
            arguments = ["--mode", "rpc", *arguments]
            if request.session_name:
                arguments.extend(["--name", request.session_name])
            if request.model:
                arguments.extend(["--model", request.model])
        command = build_pi_command(installation, workspace, request, session_args=arguments)
        exec_pi(command, workspace)
    except SessionGuardError as exc:
        raise TSPiHostError(str(exc), code=exc.code) from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def main(
    argv: list[str] | None = None,
    *,
    package_root: str | Path | None = None,
    install_root: str | Path,
) -> int:
    package = Path(package_root).resolve() if package_root else package_root_from_file(__file__)
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        return launch(arguments, package_root=package, install_root=install_root)
    except TSPiHostError as exc:
        print(f"TSPi: {exc}", file=sys.stderr)
        if "--phone-worker" in arguments and exc.code is not None:
            print(json.dumps({"type": "tspi.startup_error", "code": exc.code}), file=sys.stderr, flush=True)
        return exc.exit_code
    except (OSError, ValueError) as exc:
        print(f"TSPi: startup failed: {exc}", file=sys.stderr)
        return 1
