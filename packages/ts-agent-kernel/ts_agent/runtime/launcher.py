"""Lifecycle launcher for one installed TSPi App Server and its clients."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlsplit

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
    SessionGuardError,
    acquire_directory_guard,
    require_guarded_installation,
)


PACKAGE_NAME = "@iawnix/ts-agent"
SUITE_PACKAGE_NAME = "@iawnix/tspi"
SUITE_SCHEMA_VERSIONS = ("tspi-package-release/4",)
WORKSPACE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
SESSION_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,158}[A-Za-z0-9])?$")
APP_SERVER_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
NOTIFICATION_CLAWEMAIL_FIELDS = {"enabled", "recipient", "clawemail_root"}
# Kept for callers that imported the original launcher constant.
NOTIFICATION_FIELDS = NOTIFICATION_CLAWEMAIL_FIELDS
NOTIFICATION_SMTP_FIELDS = {
    "enabled",
    "provider",
    "preset",
    "recipient",
    "from_address",
    "username",
    "password_env",
    "password_file",
    "host",
    "port",
    "security",
}
SMTP_PRESETS = {
    "163": {"host": "smtp.163.com", "port": 465, "security": "ssl"},
    "qq": {"host": "smtp.qq.com", "port": 465, "security": "ssl"},
    "custom": {"host": None, "port": 465, "security": "ssl"},
}
SMTP_SECURITY = {"ssl", "starttls"}
WORKSPACE_ROOT_SCHEMA = "tspi-workspace-root/1"
MODEL_ICON_CONFIG_SCHEMA = "tspi-model-icons/1"
MODEL_ICON_CONFIG_RELATIVE = Path(".pi/tspi/model-icons.json")
SERVICE_CONFIG_SCHEMA = "tspi-service/1"
SERVICE_CONFIG_RELATIVE = Path(".pi/tspi/service.json")
PI_AGENT_SETTINGS_RELATIVE = Path(".pi/agent/settings.json")
TSPI_THEME_RELATIVE = Path("themes/ts-theme.json")
TSPI_THEME_NAME = "ts-theme"
EMAIL_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+$")
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PROXY_VARIABLES = (
    "http_proxy",
    "HTTP_PROXY",
    "https_proxy",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
)
PROXY_SCHEMES = {"http", "https", "socks", "socks5"}
APP_SERVER_SERVICE = "ts-app-server-tspi.service"
HOST_START_TIMEOUT_SECONDS = 15
HOST_READY_TIMEOUT_SECONDS = 10.0
HOST_READY_POLL_SECONDS = 0.1


class TSPiHostError(RuntimeError):
    def __init__(self, message: str, *, exit_code: int = 1, code: str | None = None):
        super().__init__(message)
        self.exit_code = exit_code
        self.code = code


class TSPiHostUnavailableError(TSPiHostError):
    """The installation Host has not created a usable endpoint yet."""


@dataclass(frozen=True)
class LaunchRequest:
    workspace_name: str | None
    check_remote: bool
    session_id: str | None
    continue_latest: bool
    show_help: bool
    pi_args: tuple[str, ...]
    gateway: bool = False
    host: bool = False
    phone_action: str | None = None
    phone_device_id: str | None = None


@dataclass(frozen=True)
class Installation:
    root: Path
    package_root: Path
    workspaces_root: Path
    notification_config_default: Path
    runtime_home: Path
    runtime_manifest: Path
    env_root: Path
    process_cache_root: Path
    compute_config_default: Path | None = None
    model_icons_config: Path | None = None
    service_scope: str = "user"
    host_runtime_dir: Path | None = None


USAGE = """Usage:
  TSPi --workspace <name> [--session-id <id> | -c] [Pi arguments...]
  TSPi --check-remote
  TSPi phone pair
  TSPi phone devices
  TSPi phone revoke <device-id>

Options:
  --workspace <name>   Open a research workspace.
  --session-id <id>   Continue one exact conversation.
  -c, --continue      Continue the latest conversation.
  --check-remote      Check the configured remote compute environment.
  -h, --help          Show this help.

The terminal connects to the installation Host managed by
ts-app-server-tspi.service, starting its configured service when needed. Exiting
the terminal only detaches this client.
"""


def parse_launch_request(argv: list[str]) -> LaunchRequest:
    if argv[:1] == ["phone"]:
        if len(argv) == 2 and argv[1] in {"pair", "devices"}:
            return LaunchRequest(None, False, None, False, False, (), phone_action=argv[1])
        if len(argv) == 3 and argv[1] == "revoke":
            return LaunchRequest(None, False, None, False, False, (), phone_action="revoke", phone_device_id=argv[2])
        raise TSPiHostError("usage: TSPi phone pair|devices|revoke <device-id>", exit_code=2)
    check_remote = False
    show_help = False
    workspace_name: str | None = None
    session_id: str | None = None
    continue_latest = False
    pi_args: list[str] = []
    gateway = False
    host = False
    index = 0
    while index < len(argv):
        value = argv[index]
        if value == "--":
            pi_args.extend(argv[index + 1 :])
            break
        if value == "--check-remote":
            check_remote = True
        elif value == "--standalone":
            raise TSPiHostError(
                "--standalone was removed; use TSPi --workspace <name> to connect to the installation Host",
                exit_code=2,
            )
        elif value in {"--app-server", "--app-client"}:
            raise TSPiHostError(
                f"{value} was removed; use TSPi --workspace <name> to connect to the installation Host",
                exit_code=2,
            )
        elif value == "--gateway":
            gateway = True
        elif value in {"--host", "--service-host"}:
            host = True
        elif value == "--allow-writes":
            raise TSPiHostError("--allow-writes was removed; App Server is the guarded writable Root Agent", exit_code=2)
        elif value in {"--phone", "--phone-worker", "--phone-access"} or value.startswith("--phone-access="):
            raise TSPiHostError(
                f"{value.split('=', 1)[0]} was removed; configure TSPi Link during installation",
                exit_code=2,
            )
        elif value in {
            "--lifecycle-preflight",
            "--lifecycle-guard",
            "--session-host-capabilities",
            "--session-writer-check",
            "--phone-models",
        }:
            raise TSPiHostError(f"{value} was removed with the shared Session Host", exit_code=2)
        elif value == "--workspace":
            index += 1
            if index >= len(argv) or not argv[index]:
                raise TSPiHostError("--workspace requires a name", exit_code=2)
            workspace_name = argv[index]
        elif value.startswith("--workspace="):
            workspace_name = value.removeprefix("--workspace=")
        elif value == "--session-id":
            index += 1
            if index >= len(argv) or not argv[index]:
                raise TSPiHostError(f"{value} requires a value", exit_code=2)
            session_id = argv[index]
        elif value.startswith("--session-id="):
            session_id = value.removeprefix("--session-id=")
        elif value in {"-c", "--continue"}:
            continue_latest = True
        elif value in {"-h", "--help"}:
            show_help = True
        else:
            pi_args.append(value)
        index += 1
    if session_id and continue_latest:
        raise TSPiHostError("--session-id and --continue cannot be combined", exit_code=2)
    return LaunchRequest(
        workspace_name=workspace_name,
        check_remote=check_remote,
        session_id=session_id,
        continue_latest=continue_latest,
        show_help=show_help,
        pi_args=tuple(pi_args),
        gateway=gateway,
        host=host,
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
    runtime_home = root / ".agents" / "runtime" / "tspi"
    service_scope, host_runtime_dir = _configured_service(root)
    return Installation(
        root=root,
        package_root=expected_agent,
        workspaces_root=_configured_workspace_root(root),
        notification_config_default=root / ".pi" / "notifications.toml",
        runtime_home=runtime_home,
        runtime_manifest=runtime_home / "env.json",
        env_root=root / ".agents" / "envs" / "tspi",
        process_cache_root=root / ".pi" / "runtime-cache",
        compute_config_default=root / ".pi" / "compute.toml",
        model_icons_config=root / MODEL_ICON_CONFIG_RELATIVE,
        service_scope=service_scope,
        host_runtime_dir=host_runtime_dir,
    )


def _configured_service(root: Path) -> tuple[str, Path | None]:
    path = root / SERVICE_CONFIG_RELATIVE
    if not path.exists() and not path.is_symlink():
        return "user", None
    if path.is_symlink() or not path.is_file():
        raise TSPiHostError(f"service configuration is unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TSPiHostError(f"service configuration is invalid: {path}: {exc}") from exc
    if not isinstance(value, dict) or set(value) != {"schema_version", "scope", "runtime_dir"}:
        raise TSPiHostError(f"service configuration is invalid: {path}")
    if value.get("schema_version") != SERVICE_CONFIG_SCHEMA:
        raise TSPiHostError(f"service configuration is invalid: {path}")
    scope = value.get("scope")
    runtime_value = value.get("runtime_dir")
    if scope not in {"none", "user", "system"}:
        raise TSPiHostError(f"service configuration is invalid: {path}")
    if scope == "none":
        if runtime_value is not None:
            raise TSPiHostError(f"service configuration is invalid: {path}")
        return scope, None
    if not isinstance(runtime_value, str) or not runtime_value.startswith("/") or "\x00" in runtime_value:
        raise TSPiHostError(f"service configuration is invalid: {path}")
    runtime_dir = Path(runtime_value)
    if runtime_dir == Path("/") or runtime_dir.is_symlink():
        raise TSPiHostError(f"service runtime directory is invalid: {runtime_dir}")
    return scope, runtime_dir


def _configured_workspace_root(root: Path) -> Path:
    config_path = root / ".pi/tspi/workspace-root.json"
    if not config_path.exists() and not config_path.is_symlink():
        return root / "workspaces"
    if config_path.is_symlink() or not config_path.is_file():
        raise TSPiHostError(f"workspace root configuration is unsafe: {config_path}")
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TSPiHostError(f"workspace root configuration is invalid: {config_path}: {exc}") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "workspace_root"}
        or value.get("schema_version") != WORKSPACE_ROOT_SCHEMA
        or not isinstance(value.get("workspace_root"), str)
    ):
        raise TSPiHostError(f"workspace root configuration is invalid: {config_path}")
    requested = Path(value["workspace_root"]).expanduser()
    if not requested.is_absolute() or requested.is_symlink():
        raise TSPiHostError(f"configured workspace root must be an absolute physical path: {requested}")
    resolved = requested.resolve()
    home = Path.home().resolve()
    if (
        resolved.parent == Path("/")
        or resolved == home
        or resolved in home.parents
        or resolved == root
        or resolved in root.parents
    ):
        raise TSPiHostError(f"configured workspace root must be a dedicated directory: {resolved}")
    for protected in (root / ".pi", root / ".agents"):
        if resolved == protected or protected in resolved.parents:
            raise TSPiHostError(f"configured workspace root overlaps installation state: {resolved}")
    return resolved


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
        or manifest.get("schema_version") not in SUITE_SCHEMA_VERSIONS
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


def normalize_proxy_environment() -> None:
    """Make inherited proxy variables acceptable to Node's Undici client.

    Undici requires an absolute proxy URL, while shell profiles commonly use
    ``host:port``. Normalize that shorthand and discard malformed values so a
    stale proxy setting cannot prevent Pi from starting at all.
    """

    for variable in PROXY_VARIABLES:
        value = os.environ.get(variable)
        if not value:
            continue
        normalized = value.strip()
        if "://" not in normalized:
            normalized = f"http://{normalized}"
        try:
            parsed = urlsplit(normalized)
            valid = (
                parsed.scheme.lower() in PROXY_SCHEMES
                and bool(parsed.hostname)
                and not any(character.isspace() for character in normalized)
            )
            if valid:
                # Accessing port validates malformed numeric ports as well.
                _ = parsed.port
        except ValueError:
            valid = False
        if valid:
            if normalized != value:
                os.environ[variable] = normalized
                print(f"TSPi: normalized {variable} to an HTTP proxy URL", file=sys.stderr)
        else:
            os.environ.pop(variable, None)
            print(f"TSPi: ignoring invalid {variable} proxy setting", file=sys.stderr)


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
        raise TSPiHostError(
            f"workspace is unavailable: {requested}\n"
            "Create it first with TSPi --workspace <name>.\n"
            "If this installation was upgraded unsuccessfully, rerun install.sh."
        )
    workspace = requested.resolve()
    if workspace.parent != container.resolve():
        raise TSPiHostError(f"resolved workspace escaped the installation workspace container: {workspace}")
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


def _configure_agent_pi_settings(installation: Installation) -> None:
    """Register the release theme for Pi's experimental client.

    The Host client creates its TUI from the installation-wide agent directory,
    rather than from the legacy extension entrypoint. Keep this registration
    additive so user model/provider settings and explicitly selected custom
    themes remain untouched.
    """

    installation_pi = installation.root / ".pi"
    if installation_pi.is_symlink():
        raise TSPiHostError(f"Pi agent settings parent cannot be a symbolic link: {installation_pi}")
    agent_root = installation.root / PI_AGENT_SETTINGS_RELATIVE.parent
    if agent_root.is_symlink():
        raise TSPiHostError(f"Pi agent settings directory cannot be a symbolic link: {agent_root}")
    if not agent_root.exists():
        try:
            agent_root.mkdir(mode=0o700, parents=True)
        except OSError as exc:
            raise TSPiHostError(f"Pi agent settings directory is unavailable: {agent_root}: {exc}") from exc
    if not agent_root.is_dir():
        raise TSPiHostError(f"Pi agent settings path is not a directory: {agent_root}")

    theme_path = installation.package_root / TSPI_THEME_RELATIVE
    if theme_path.is_symlink() or not theme_path.is_file():
        raise TSPiHostError(f"selected Package TSPi theme is unavailable: {theme_path}")
    try:
        theme_document = json.loads(theme_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TSPiHostError(f"selected Package TSPi theme is invalid: {theme_path}: {exc}") from exc
    if not isinstance(theme_document, dict) or theme_document.get("name") != TSPI_THEME_NAME:
        raise TSPiHostError(f"selected Package TSPi theme is invalid: {theme_path}")

    path = installation.root / PI_AGENT_SETTINGS_RELATIVE
    if path.is_symlink():
        raise TSPiHostError(f"Pi agent settings cannot be a symbolic link: {path}")
    if path.exists() and not path.is_file():
        raise TSPiHostError(f"Pi agent settings must be a regular file: {path}")
    try:
        settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TSPiHostError(f"invalid Pi agent settings: {path}: {exc}") from exc
    if not isinstance(settings, dict):
        raise TSPiHostError(f"Pi agent settings must contain a JSON object: {path}")

    themes = settings.get("themes", [])
    if not isinstance(themes, list) or any(not isinstance(theme, str) for theme in themes):
        raise TSPiHostError(f"Pi agent settings themes must be an array of strings: {path}")
    theme_value = str(theme_path)
    changed = False
    if theme_value not in themes:
        themes = [*themes, theme_value]
        settings["themes"] = themes
        changed = True

    selected_theme = settings.get("theme")
    if selected_theme is not None and not isinstance(selected_theme, str):
        raise TSPiHostError(f"Pi agent setting 'theme' must be a string: {path}")
    if selected_theme in {None, "dark", "light"}:
        if selected_theme != TSPI_THEME_NAME:
            settings["theme"] = TSPI_THEME_NAME
            changed = True

    if changed:
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
    configured = os.environ.get("TS_COMPUTE_CONFIG")
    if not configured:
        if installation.compute_config_default and installation.compute_config_default.is_file():
            configured = str(installation.compute_config_default)
    if not configured:
        os.environ.pop("TS_COMPUTE_CONFIG", None)
        os.environ["TS_REMOTE_DISPLAY_TARGET"] = "not configured"
        return
    path = _require_config_file(configured, "TS_COMPUTE_CONFIG")
    try:
        with path.open("rb") as handle:
            config = tomllib.load(handle)
        environment_name = config.get("default_environment")
        environments = config.get("environments", {})
        environment = environments.get(environment_name, {}) if isinstance(environments, dict) else {}
        if isinstance(environment, dict) and environment.get("kind") == "local" and isinstance(environments, dict):
            remote_environments = [
                item for item in environments.values()
                if isinstance(item, dict) and item.get("kind") == "remote"
            ]
            environment = remote_environments[0] if remote_environments else environment
        if not isinstance(environment, dict):
            raise ValueError("default environment must be a table")
        host = environment.get("ssh_host", environment_name or "configured")
        scheduler = str(environment.get("scheduler", "torque")).title()
    except (OSError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise TSPiHostError(f"invalid remote configuration: {path}: {exc}") from exc
    os.environ["TS_COMPUTE_CONFIG"] = str(path)
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
        if not isinstance(email, dict):
            raise ValueError("notifications.email must be a table")
        email = _normalize_notification_provider(email)
        enabled = email["enabled"]
        recipient = email["recipient"]
        if not isinstance(enabled, bool):
            raise ValueError("notifications.email.enabled must be true or false")
        if not isinstance(recipient, str) or len(recipient) > 320 or not EMAIL_ADDRESS.fullmatch(recipient):
            raise ValueError("notifications.email.recipient must be one email address")
        provider = email.get("provider", "clawemail")
        if provider == "clawemail":
            expected = set(NOTIFICATION_CLAWEMAIL_FIELDS)
            if "provider" in email:
                expected.add("provider")
            if set(email) != expected:
                raise ValueError(
                    "notifications.email fields must be enabled, recipient, and clawemail_root"
                )
            clawemail_root = email["clawemail_root"]
            if not isinstance(clawemail_root, str) or not clawemail_root.startswith("/"):
                raise ValueError("notifications.email.clawemail_root must be an absolute path")
        elif provider == "smtp":
            if set(email) - NOTIFICATION_SMTP_FIELDS:
                unknown = ", ".join(sorted(set(email) - NOTIFICATION_SMTP_FIELDS))
                raise ValueError(f"unknown notifications.email fields: {unknown}")
            required = {"enabled", "provider", "preset", "recipient", "username"}
            missing = required - set(email)
            if missing:
                raise ValueError(
                    "notifications.email is missing fields: " + ", ".join(sorted(missing))
                )
            preset = email["preset"]
            if not isinstance(preset, str) or preset.lower() not in SMTP_PRESETS:
                raise ValueError("notifications.email.preset must be 163, qq, or custom")
            username = email["username"]
            if not isinstance(username, str) or not EMAIL_ADDRESS.fullmatch(username):
                raise ValueError("notifications.email.username must be one email address")
            from_address = email.get("from_address", username)
            if not isinstance(from_address, str) or not EMAIL_ADDRESS.fullmatch(from_address):
                raise ValueError("notifications.email.from_address must be one email address")
            password_env = email.get("password_env")
            password_file = email.get("password_file")
            if (password_env is None) == (password_file is None):
                raise ValueError(
                    "notifications.email must set exactly one of password_env or password_file"
                )
            if password_env is not None and (
                not isinstance(password_env, str) or not ENV_NAME.fullmatch(password_env)
            ):
                raise ValueError("notifications.email.password_env must be an environment variable name")
            if password_file is not None:
                if not isinstance(password_file, str) or not password_file.startswith("/"):
                    raise ValueError("notifications.email.password_file must be an absolute path")
                secret_path = Path(password_file).expanduser()
                if secret_path.is_symlink() or not secret_path.is_file():
                    raise ValueError("notifications.email.password_file must be a regular file")
                if stat.S_IMODE(secret_path.stat().st_mode) & 0o077:
                    raise ValueError("notifications.email.password_file must have mode 0600")
            defaults = SMTP_PRESETS[preset.lower()]
            host = email.get("host", defaults["host"])
            if (
                not isinstance(host, str)
                or not host
                or len(host) > 255
                or any(character.isspace() for character in host)
                or "/" in host
                or "@" in host
            ):
                raise ValueError("notifications.email.host must be a hostname")
            if preset.lower() != "custom" and host != defaults["host"]:
                raise ValueError(
                    f"notifications.email.host must be {defaults['host']} for preset {preset.lower()}"
                )
            port = email.get("port", defaults["port"])
            if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
                raise ValueError("notifications.email.port must be an integer from 1 to 65535")
            security = email.get("security", defaults["security"])
            if not isinstance(security, str) or security.lower() not in SMTP_SECURITY:
                raise ValueError("notifications.email.security must be ssl or starttls")
        else:
            raise ValueError("notifications.email.provider must be clawemail or smtp")
    except (KeyError, OSError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise TSPiHostError(f"invalid notification configuration: {path}: {exc}") from exc
    os.environ["TS_NOTIFICATION_CONFIG"] = str(path)
    os.environ["TS_NOTIFICATION_DISPLAY_TARGET"] = recipient if enabled else "disabled"


def _normalize_notification_provider(email: dict) -> dict:
    """Accept the transitional installer key while retaining one canonical schema."""
    if "binding" not in email:
        return email
    if "provider" in email:
        raise ValueError("notifications.email cannot set both provider and binding")
    normalized = dict(email)
    normalized["provider"] = normalized.pop("binding")
    return normalized


def _require_config_file(value: str, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or not os.access(path, os.R_OK):
        raise TSPiHostError(f"invalid {label}: {path}")
    return path.resolve()


def check_remote(installation: Installation) -> int:
    configured = os.environ.get("TS_COMPUTE_CONFIG")
    if not configured:
        expected = installation.compute_config_default or installation.root / ".pi" / "compute.toml"
        print(f"TSPi: remote configuration is missing: {expected}", file=sys.stderr)
        return 1
    completed = subprocess.run(
        [sys.executable, str(installation.package_root / "scripts" / "ts_compute.py"), "remote-diagnostic", "--mode", "doctor"],
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


def configure_model_icon_environment(installation: Installation) -> bool:
    """Enable the optional model icon font when its installer marker is valid."""
    if "TSPI_ICON_STYLE" in os.environ:
        return False
    marker = installation.model_icons_config
    if marker is None or marker.is_symlink() or not marker.is_file():
        return False
    try:
        document = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != MODEL_ICON_CONFIG_SCHEMA
        or document.get("enabled") is not True
    ):
        return False
    font_value = document.get("font_path")
    digest_value = document.get("sha256")
    if not isinstance(font_value, str) or not isinstance(digest_value, str):
        return False
    font_path = Path(font_value).expanduser()
    if not font_path.is_absolute() or font_path.is_symlink() or not font_path.is_file():
        return False
    try:
        digest = hashlib.sha256(font_path.read_bytes()).hexdigest()
    except OSError:
        return False
    if digest != digest_value:
        return False
    os.environ["TSPI_ICON_STYLE"] = "tspi"
    return True


def configure_process_environment(installation: Installation, workspace: Path, workspace_name: str) -> None:
    os.environ[PACKAGE_ROOT_OVERRIDE] = str(installation.package_root)
    os.environ["TSPI_INSTALL_ROOT"] = str(installation.root)
    os.environ["TS_WORKSPACE_ROOT"] = str(workspace)
    os.environ["PI_CODING_AGENT_DIR"] = str(installation.root / ".pi" / "agent")
    _configure_agent_pi_settings(installation)
    if installation.compute_config_default and installation.compute_config_default.is_file():
        os.environ["TS_COMPUTE_CONFIG"] = str(installation.compute_config_default)
    else:
        os.environ.pop("TS_COMPUTE_CONFIG", None)
    python_cache = installation.process_cache_root / "python" / workspace_name
    pytest_cache = installation.process_cache_root / "pytest" / workspace_name
    for path in (installation.process_cache_root, python_cache.parent, pytest_cache.parent, python_cache, pytest_cache):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
    os.environ["PYTHONPYCACHEPREFIX"] = str(python_cache)
    cache_option = f"--cache-dir={pytest_cache}"
    existing = os.environ.get("PYTEST_ADDOPTS", "")
    os.environ["PYTEST_ADDOPTS"] = f"{existing} {cache_option}".strip()


def configure_host_process_environment(installation: Installation) -> None:
    """Configure the installation-wide environment used by the Host process."""
    os.environ[PACKAGE_ROOT_OVERRIDE] = str(installation.package_root)
    os.environ["TSPI_INSTALL_ROOT"] = str(installation.root)
    os.environ["TS_WORKSPACE_ROOT"] = str(installation.workspaces_root)
    os.environ["TSPI_WORKSPACE_ROOT"] = str(installation.workspaces_root)
    os.environ["PI_CODING_AGENT_DIR"] = str(installation.root / ".pi" / "agent")
    from .link import LinkError, configure_link_environment

    try:
        configure_link_environment(installation.root)
    except LinkError as exc:
        raise TSPiHostError(str(exc)) from exc
    python_cache = installation.process_cache_root / "python" / "host"
    pytest_cache = installation.process_cache_root / "pytest" / "host"
    for path in (installation.process_cache_root, python_cache.parent, pytest_cache.parent, python_cache, pytest_cache):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
    os.environ["PYTHONPYCACHEPREFIX"] = str(python_cache)
    cache_option = f"--cache-dir={pytest_cache}"
    existing = os.environ.get("PYTEST_ADDOPTS", "")
    os.environ["PYTEST_ADDOPTS"] = f"{existing} {cache_option}".strip()


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


def build_host_server_command(installation: Installation, request: LaunchRequest) -> list[str]:
    """Build the one installation-wide Pi App Server command."""
    for option in ("--directory", "--server-id", "--session-dir", "--workspace"):
        if _has_cli_option(request.pi_args, option):
            raise TSPiHostError(f"{option} is managed by the TSPi Host launcher", exit_code=2)
    host_workspace, state_root = _prepare_host_state(installation)
    server_id = _host_server_id(installation, create=True)
    socket_directory = _host_socket_directory(installation, create=True)
    command = [
        _node_binary(),
        str(_app_server_entry(installation)),
        "server",
        "--workspace",
        str(host_workspace),
        "--directory",
        str(socket_directory),
        "--server-id",
        server_id,
        "--session-dir",
        str(state_root / "sessions"),
    ]
    command.extend(request.pi_args)
    return command


def resolve_host_socket(installation: Installation) -> Path:
    """Resolve the one installation Host endpoint without hiding invalid state."""
    server_id = _host_server_id(installation, create=False)
    socket_path = _host_socket_directory(installation, create=False) / f"{server_id}.sock"
    try:
        socket_mode = socket_path.stat().st_mode
    except FileNotFoundError as exc:
        raise TSPiHostUnavailableError("TSPi Host is not running") from exc
    except OSError as exc:
        raise TSPiHostError(f"cannot inspect TSPi Host endpoint: {socket_path}: {exc}") from exc
    if not stat.S_ISSOCK(socket_mode):
        raise TSPiHostError(f"TSPi Host endpoint is not a Unix socket: {socket_path}")
    return socket_path


def ensure_host_running(installation: Installation) -> Path:
    """Return the Host socket, starting the configured service when absent."""
    try:
        return resolve_host_socket(installation)
    except TSPiHostUnavailableError:
        pass

    if installation.service_scope == "none":
        raise TSPiHostError(
            "TSPi Host service is disabled; configure a systemd service before opening a workspace"
        )

    systemctl = shutil.which("systemctl")
    if systemctl is None:
        raise TSPiHostError(
            f"TSPi Host is not running and systemctl is unavailable; start {APP_SERVER_SERVICE}"
        )
    scope = [] if installation.service_scope == "system" else ["--user"]
    command = [systemctl, *scope, "start", APP_SERVER_SERVICE]
    try:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=HOST_START_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise TSPiHostError(f"timed out starting {APP_SERVER_SERVICE}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "systemctl returned no diagnostic"
        raise TSPiHostError(f"could not start {APP_SERVER_SERVICE}: {detail}")

    deadline = time.monotonic() + HOST_READY_TIMEOUT_SECONDS
    while True:
        try:
            return resolve_host_socket(installation)
        except TSPiHostUnavailableError:
            if time.monotonic() >= deadline:
                break
            time.sleep(HOST_READY_POLL_SECONDS)
    raise TSPiHostError(
        f"{APP_SERVER_SERVICE} started but the Host did not become ready within "
        f"{HOST_READY_TIMEOUT_SECONDS:g} seconds; inspect it with systemctl {' '.join(scope + ['status', APP_SERVER_SERVICE])}"
    )


def build_host_client_command(
    installation: Installation,
    request: LaunchRequest,
    *,
    socket_path: Path | None = None,
) -> list[str]:
    """Build a terminal client command connected to the installation Host."""
    endpoint = socket_path or resolve_host_socket(installation)
    command = [
        _node_binary(),
        str(_app_server_entry(installation)),
        "client",
        "--directory",
        str(endpoint.parent),
        "--connect",
        f"unix://{endpoint}",
    ]
    if request.session_id:
        command.extend(["--session-id", request.session_id])
    elif request.continue_latest:
        command.append("--continue")
    command.extend(request.pi_args)
    return command


def build_gateway_command(
    installation: Installation,
    request: LaunchRequest,
    *,
    socket_path: Path | None = None,
) -> list[str]:
    """Build a browser adapter attached to an existing installation Host session."""
    if not request.session_id:
        raise TSPiHostError("--gateway requires --session-id", exit_code=2)
    endpoint = socket_path or resolve_host_socket(installation)
    command = [
        _node_binary(),
        str(_app_server_entry(installation)),
        "gateway",
        "--workspace",
        str(installation.workspaces_root / request.workspace_name),
        "--connect",
        f"unix://{endpoint}",
        "--session-id",
        request.session_id,
    ]
    command.extend(request.pi_args)
    return command


def _node_binary() -> str:
    node = shutil.which("node")
    if not node:
        raise TSPiHostError("Node.js executable not found", exit_code=127)
    return node


def _app_server_entry(installation: Installation) -> Path:
    entry = installation.package_root / "apps" / "app-server" / "pi-app-server.mjs"
    if entry.is_symlink() or not entry.is_file():
        raise TSPiHostError("selected Package has no native Pi App Server entrypoint")
    return entry


def _prepare_host_state(installation: Installation) -> tuple[Path, Path]:
    state_root = installation.root / ".pi" / "app-server-host"
    host_workspace = state_root / "workspace"
    # The native Host uses its private workspace as a real Pi workspace.  Keep
    # its local `.pi` directory present before acquiring the Root Agent lock;
    # otherwise a fresh installation fails before the App Server can start.
    installation_pi = installation.root / ".pi"
    # The installation's .pi directory is part of the immutable package
    # surface under the systemd Host sandbox.  Installation already creates
    # it with owner-only permissions, so only validate it here; attempting
    # mkdir/chmod on an existing directory fails with EROFS when ProtectSystem
    # is strict.  Runtime-owned children remain mutable below.
    if installation_pi.is_symlink():
        raise TSPiHostError(f"Host state path cannot be a symbolic link: {installation_pi}")
    if not installation_pi.exists():
        try:
            installation_pi.mkdir(mode=0o700, parents=True)
        except OSError as exc:
            raise TSPiHostError(f"Host state path is not a directory: {installation_pi}") from exc
    if not installation_pi.is_dir():
        raise TSPiHostError(f"Host state path is not a directory: {installation_pi}")
    if stat.S_IMODE(installation_pi.stat().st_mode) != 0o700:
        raise TSPiHostError(f"Host state path must be owner-only: {installation_pi}")
    for path in (
        state_root,
        host_workspace,
        host_workspace / ".pi",
        state_root / "sessions",
    ):
        if path.is_symlink():
            raise TSPiHostError(f"Host state path cannot be a symbolic link: {path}")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not path.is_dir():
            raise TSPiHostError(f"Host state path is not a directory: {path}")
        path.chmod(0o700)
    workspaces_root = installation.workspaces_root
    if workspaces_root.is_symlink():
        raise TSPiHostError(f"workspace container cannot be a symbolic link: {workspaces_root}")
    workspaces_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not workspaces_root.is_dir():
        raise TSPiHostError(f"workspace container is not a directory: {workspaces_root}")
    workspaces_root.chmod(0o700)
    return host_workspace, state_root


def _host_server_id(installation: Installation, *, create: bool) -> str:
    host_workspace, state_root = _prepare_host_state(installation)
    path = state_root / "server-id"
    if create and not path.exists() and not path.is_symlink():
        value = str(uuid.uuid4())
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                handle.write(value + "\n")
                handle.flush()
                os.fsync(handle.fileno())
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError as exc:
        raise TSPiHostUnavailableError("TSPi Host is not initialized") from exc
    except OSError as exc:
        raise TSPiHostError(f"cannot read TSPi Host identity: {path}: {exc}") from exc
    with os.fdopen(descriptor, "r", encoding="ascii") as handle:
        info = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or info.st_size > 64
        ):
            raise TSPiHostError(f"Host identity must be an owner-only regular file: {path}")
        server_id = handle.read(65).strip()
    if not APP_SERVER_ID.fullmatch(server_id):
        raise TSPiHostError(f"invalid Host identity: {path}")
    return server_id


def _private_socket_directory(
    identity_root: Path,
    *,
    create: bool,
    configured_runtime_dir: Path | None = None,
) -> Path:
    configured = os.environ.get("TSPI_APP_SERVER_RUNTIME_DIR", "").strip()
    if not configured and configured_runtime_dir is not None:
        configured = str(configured_runtime_dir)
    if configured:
        base = Path(configured).expanduser()
        if not base.is_absolute():
            raise TSPiHostError("TSPI_APP_SERVER_RUNTIME_DIR must be absolute")
        bases = [base]
    else:
        xdg = os.environ.get("XDG_RUNTIME_DIR", "").strip()
        candidate = Path(xdg) if xdg else Path(f"/run/user/{os.getuid()}")
        bases = []
        if candidate.is_dir():
            bases.append(candidate / "tspi")
        bases.append(Path(tempfile.gettempdir()) / f"tspi-{os.getuid()}")
    key = hashlib.sha256(os.fsencode(identity_root.resolve())).hexdigest()[:16]
    last_error: OSError | None = None
    for base in bases:
        directory = base / key
        longest_socket = directory / f"server-{'0' * 36}-{'0' * 12}.sock"
        if len(os.fsencode(longest_socket)) >= 108:
            if configured:
                raise TSPiHostError(
                    f"App Server runtime directory is too long for Unix sockets: {directory}; "
                    "set TSPI_APP_SERVER_RUNTIME_DIR to a shorter private directory"
                )
            continue
        try:
            for path in (base, directory):
                if path.is_symlink():
                    raise TSPiHostError(f"App Server runtime directory cannot be a symbolic link: {path}")
                if create:
                    path.mkdir(mode=0o700, parents=True, exist_ok=True)
                if path.exists():
                    info = path.stat()
                    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                        raise TSPiHostError(f"App Server runtime directory must be owned by the current user: {path}")
                    if create:
                        path.chmod(0o700)
            return directory
        except OSError as exc:
            if configured:
                raise TSPiHostError(f"cannot prepare App Server runtime directory: {base}: {exc}") from exc
            last_error = exc
    detail = f": {last_error}" if last_error else ""
    raise TSPiHostError(f"cannot prepare a private App Server runtime directory{detail}")


def _host_socket_directory(installation: Installation, *, create: bool) -> Path:
    host_workspace, _state_root = _prepare_host_state(installation)
    return _private_socket_directory(
        host_workspace,
        create=create,
        configured_runtime_dir=installation.host_runtime_dir,
    )


def _has_cli_option(arguments: tuple[str, ...], option: str) -> bool:
    return any(value == option or value.startswith(f"{option}=") for value in arguments)


def exec_pi(command: list[str], workspace: Path) -> NoReturn:
    os.chdir(workspace)
    os.execve(command[0], command, dict(os.environ))


def launch_terminal(installation: Installation, request: LaunchRequest, workspace: Path) -> NoReturn:
    """Attach Pi's native TUI to the installation Host without owning session state."""
    if request.session_id and not SESSION_ID.fullmatch(request.session_id):
        raise TSPiHostError("invalid session identity", exit_code=2)
    os.environ["TSPI_SESSION_CWD"] = str(workspace)
    socket_path = ensure_host_running(installation)
    exec_pi(build_host_client_command(installation, request, socket_path=socket_path), workspace)


def launch(argv: list[str], *, package_root: str | Path, install_root: str | Path) -> int:
    request = parse_launch_request(argv)
    if request.show_help:
        print(USAGE, end="")
        return 0
    if request.host and "--service-host" not in argv and os.environ.get("TSPI_SYSTEMD_HOST") != "1":
        try:
            service_scope, _runtime_dir = _configured_service(Path(install_root).expanduser().resolve())
        except TSPiHostError:
            service_scope = "user"
        scope = [] if service_scope == "system" else ["--user"]
        raise TSPiHostError(
            "TSPi Host is managed by systemd; use:\n"
            f"  systemctl {' '.join(scope + ['start', APP_SERVER_SERVICE])}\n"
            f"  systemctl {' '.join(scope + ['status', APP_SERVER_SERVICE])}",
            exit_code=2,
        )
    normalize_proxy_environment()
    if (request.host or request.gateway) and request.check_remote:
        raise TSPiHostError("App Server modes cannot be combined with another launch mode", exit_code=2)
    if request.host and request.gateway:
        raise TSPiHostError("--host and --gateway cannot be combined", exit_code=2)
    if request.host and (request.workspace_name or request.session_id or request.continue_latest):
        raise TSPiHostError("--host does not accept workspace or session selection", exit_code=2)
    if request.check_remote and (request.workspace_name or request.session_id or request.continue_latest):
        raise TSPiHostError("--check-remote does not accept workspace or session selection", exit_code=2)
    if request.gateway and not request.workspace_name:
        raise TSPiHostError("--gateway requires --workspace", exit_code=2)
    if request.gateway and not request.session_id:
        raise TSPiHostError("--gateway requires --session-id", exit_code=2)
    installation = resolve_installation(package_root, install_root)
    os.environ["TSPI_INSTALL_ROOT"] = str(installation.root)
    configure_model_icon_environment(installation)
    try:
        require_guarded_installation(installation.root)
    except SessionGuardError as exc:
        raise TSPiHostError(str(exc), code=exc.code) from exc

    if request.phone_action:
        from .link import (
            LinkError,
            create_phone_pairing,
            format_devices,
            format_pairing,
            list_phone_devices,
            revoke_phone_device,
        )

        try:
            if request.phone_action == "pair":
                print(format_pairing(create_phone_pairing(installation.root)), end="")
            elif request.phone_action == "devices":
                print(format_devices(list_phone_devices(installation.root)), end="")
            else:
                assert request.phone_device_id is not None
                revoke_phone_device(installation.root, request.phone_device_id)
                print(f"Revoked Phone device {request.phone_device_id}")
        except LinkError as exc:
            raise TSPiHostError(str(exc)) from exc
        return 0

    default_client = not (request.host or request.gateway or request.check_remote)
    if default_client:
        if not request.workspace_name:
            raise TSPiHostError(f"a research workspace is required\n{USAGE}", exit_code=2)
        # Bootstrap imports jsonschema and the scientific kernel. Select the
        # installation-owned runtime before importing those modules; the
        # user's shell environment must not determine TSPi's dependencies.
        configure_runtime_environment(installation)
        try:
            python = ensure_runtime_python(installation.package_root, required=True)
            if python is None:
                raise RuntimeEnvironmentError("managed TS Python runtime could not be selected")
            bind_runtime_process_environment(python)
        except RuntimeEnvironmentError as exc:
            raise TSPiHostError(str(exc)) from exc
        configure_remote(installation)
        configure_notifications(installation)
        workspace = prepare_workspace(installation, request.workspace_name)
        from ts_agent.workspace.bootstrap import WorkspaceBootstrapError, bootstrap_workspace

        try:
            bootstrap_workspace(workspace)
        except WorkspaceBootstrapError as exc:
            raise TSPiHostError(str(exc)) from exc
        configure_process_environment(installation, workspace, request.workspace_name)
        launch_terminal(installation, request, workspace)

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
    if request.host:
        configure_notifications(installation)
        host_workspace, _state_root = _prepare_host_state(installation)
        configure_host_process_environment(installation)
        descriptors: list[int] = []
        try:
            descriptors.append(acquire_directory_guard(installation.root, host_workspace))
            descriptors.append(acquire_root_agent_lock(host_workspace))
            exec_pi(build_host_server_command(installation, request), host_workspace)
        except SessionGuardError as exc:
            raise TSPiHostError(str(exc), code=exc.code) from exc
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)
    if request.gateway:
        workspace = resolve_existing_workspace(installation, request.workspace_name)
        configure_process_environment(installation, workspace, request.workspace_name)
        # The gateway attaches through the same native client session lookup
        # as the TUI. Bind the requested workspace explicitly so an ID shared
        # by multiple projects cannot resolve against the Host's private cwd.
        os.environ["TSPI_SESSION_CWD"] = str(workspace)
        socket_path = ensure_host_running(installation)
        exec_pi(build_gateway_command(installation, request, socket_path=socket_path), workspace)
    raise TSPiHostError(f"a research workspace is required\n{USAGE}", exit_code=2)


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
        return exc.exit_code
    except (OSError, ValueError) as exc:
        print(f"TSPi: startup failed: {exc}", file=sys.stderr)
        return 1
