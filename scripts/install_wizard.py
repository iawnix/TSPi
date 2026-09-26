#!/usr/bin/env python3
"""Interactive installer and service configurator for a TSPi installation."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import pwd
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    from ._credentials import provision_service_credentials
    from ._installation_metadata import read_installation_metadata, read_workspace_root, write_workspace_root
    from ._terminal_ui import (
        Spinner,
        ask_text as ask,
        ask_secret,
        ask_yes_no,
        failure,
        field,
        note,
        section,
        success,
        title,
    )
    from .install_from_github import install_uninstaller, validate_commit, validate_ref, validate_repo
    from .install_release import validate_install_root
    from .model_icons import install_model_icon_font
except ImportError:
    from _credentials import provision_service_credentials
    from _installation_metadata import read_installation_metadata, read_workspace_root, write_workspace_root
    from _terminal_ui import (
        Spinner,
        ask_text as ask,
        ask_secret,
        ask_yes_no,
        failure,
        field,
        note,
        section,
        success,
        title,
    )
    from install_from_github import install_uninstaller, validate_commit, validate_ref, validate_repo
    from install_release import validate_install_root
    from model_icons import install_model_icon_font


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "git@github.com:iawnix/TSPi.git"
PROGRESS_PREFIX = "@@tspi-progress@@"
MINIMUM_NODE_VERSION = (22, 19, 0)
EMAIL_PROVIDERS = {"clawemail", "smtp"}
SMTP_PRESETS = {
    "163": "smtp.163.com",
    "qq": "smtp.qq.com",
    "custom": None,
}
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
WEB_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,100}$")
SERVICE_CONFIG_SCHEMA = "tspi-service/1"
SERVICE_CONFIG_RELATIVE = Path(".pi/tspi/service.json")
PI_AGENT_CONFIG_FILES = ("models.json", "auth.json")
PI_AGENT_CONFIG_MAX_BYTES = 2 * 1024 * 1024


def detect_conda_root() -> str:
    configured = os.environ.get("CONDA_EXE")
    if configured:
        return str(Path(configured).expanduser().resolve().parent.parent)
    conda = shutil.which("mamba") or shutil.which("conda")
    return str(Path(conda).resolve().parent.parent) if conda else ""


def _command_output(command: list[str]) -> tuple[bool, str]:
    try:
        completed = subprocess.run(command, text=True, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, str(error)
    output = (completed.stdout or completed.stderr).strip().splitlines()
    return completed.returncode == 0, output[0] if output else "unavailable"


def collect_preflight() -> list[dict[str, object]]:
    python_ok = sys.version_info >= (3, 11)
    checks: list[dict[str, object]] = [
        {
            "key": "python",
            "label": "Python",
            "ok": python_ok,
            "required": True,
            "detail": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        }
    ]
    git = shutil.which("git")
    git_ok, git_version = _command_output([git, "--version"]) if git else (False, "not found")
    checks.append({"key": "git", "label": "Git", "ok": git_ok, "required": True, "detail": git_version})

    node = shutil.which("node")
    node_ok, node_version = _command_output([node, "-p", "process.versions.node"]) if node else (False, "not found")
    try:
        node_ok = node_ok and tuple(int(part) for part in node_version.split(".")) >= MINIMUM_NODE_VERSION
    except ValueError:
        node_ok = False
    node_detail = node_version if node_ok else f"{node_version} (requires >=22.19.0)"
    checks.append({"key": "node", "label": "Node.js", "ok": node_ok, "required": True, "detail": node_detail})

    npm = shutil.which("npm")
    npm_ok, npm_version = _command_output([npm, "--version"]) if npm else (False, "not found")
    checks.append({"key": "npm", "label": "npm", "ok": npm_ok, "required": True, "detail": npm_version})

    conda = shutil.which("mamba") or shutil.which("conda")
    conda_ok, conda_version = _command_output([conda, "--version"]) if conda else (False, "not found")
    if not conda_ok:
        conda_version += " (needed when the managed base runtime must be created)"
    checks.append({"key": "conda", "label": "Conda/Mamba", "ok": conda_ok, "required": True, "detail": conda_version})
    return checks


def show_preflight(checks: list[dict[str, object]], *, require_conda: bool = True) -> None:
    section("System check")
    for check in checks:
        required = bool(check["required"]) and (require_conda or check["key"] != "conda")
        tone = "success" if check["ok"] else ("danger" if required else "warning")
        state = "ready" if check["ok"] else "unavailable"
        field(str(check["label"]), f"{state} - {check['detail']}", tone=tone)


def require_preflight(checks: list[dict[str, object]], *, require_conda: bool = True) -> None:
    required = {"python", "git", "node", "npm", "conda"}
    if not require_conda:
        required.remove("conda")
    failed = [str(check["label"]) for check in checks if check["key"] in required and not check["ok"]]
    if failed:
        raise RuntimeError("missing or unsupported installation prerequisites: " + ", ".join(failed))


def inspect_installation(root: Path) -> dict[str, str | None]:
    package_home = root / ".pi/packages/tspi"
    state_path = package_home / "install-state.json"
    try:
        metadata = read_installation_metadata(root)
    except ValueError as error:
        raise RuntimeError(str(error)) from error
    if not metadata["state_present"]:
        if metadata["owned"]:
            return {"operation": "restore", "release_id": None}
        tspi_like = [root / "TSPi", package_home]
        if any(path.exists() or path.is_symlink() for path in tspi_like):
            raise RuntimeError(
                f"installation-like files exist without trusted package state in {root}; "
                "choose a dedicated empty directory or remove the stale files"
            )
        return {"operation": "install", "release_id": None}

    release_id = metadata["release_id"]
    if not isinstance(release_id, str):
        raise RuntimeError(f"installed package state is invalid: {state_path}")
    release = package_home / "releases" / release_id
    current = package_home / "current"
    if (
        not release.is_dir()
        or release.is_symlink()
        or not current.is_symlink()
        or current.resolve() != release.resolve()
    ):
        raise RuntimeError(f"installed package selection is inconsistent: {state_path}")
    return {"operation": "update", "release_id": release_id}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-root")
    parser.add_argument("--workspace-root", help="Absolute directory containing named research workspaces.")
    parser.add_argument("--tspi-repo", default=DEFAULT_REPO)
    parser.add_argument("--tspi-ref", default=os.environ.get("TSPI_INSTALL_REF", "main"))
    parser.add_argument("--tspi-commit", help=argparse.SUPPRESS)
    web = parser.add_mutually_exclusive_group()
    web.add_argument("--with-web", dest="with_web", action="store_true", help="Install TS Web.")
    web.add_argument("--without-web", dest="with_web", action="store_false", help="Skip TS Web installation.")
    parser.set_defaults(with_web=None)
    icons = parser.add_mutually_exclusive_group()
    icons.add_argument(
        "--with-model-icons",
        dest="with_model_icons",
        action="store_true",
        help="Install the optional TSPi model icon font.",
    )
    icons.add_argument(
        "--without-model-icons",
        dest="with_model_icons",
        action="store_false",
        help="Do not install the optional TSPi model icon font.",
    )
    parser.set_defaults(with_model_icons=None)
    parser.add_argument("--web-port", type=int, help="TS Web HTTP port.")
    parser.add_argument("--web-host", default="127.0.0.1", help="TS Web listen address.")
    parser.add_argument("--allow-remote", action="store_true", help="Allow TS Web to listen on a non-loopback address.")
    parser.add_argument("--web-auth-token-file", help="TS Web token file (must be inside the installation root).")
    parser.add_argument(
        "--web-auth-token",
        help="Explicit TS Web token (8-100 URL-safe characters; prefer --web-auth-token-file for secrets).",
    )
    parser.add_argument("--compute-config", help="Unified compute.toml to install as .pi/compute.toml.")
    parser.add_argument("--probe-remote", action="store_true", help="Run the remote doctor and fail if the configured environment is not ready.")
    parser.add_argument("--conda-root")
    parser.add_argument("--service-scope", choices=("none", "user", "system"))
    parser.add_argument("--service-user", help="Unix account used by systemd services (required for system scope).")
    parser.add_argument("--phone-access", choices=("disabled", "link"), help="TS Phone access mode.")
    parser.add_argument("--link-url", default=os.environ.get("TSPI_LINK_URL"), help="TSPi Link Relay HTTPS origin.")
    parser.add_argument("--link-enrollment-code", help="Single-use Host enrollment code issued by TSPi Link Relay.")
    parser.add_argument("--enable-services", action="store_true")
    parser.add_argument("--start-services", action="store_true")
    email = parser.add_argument_group("email notifications")
    email.add_argument("--email-binding", choices=sorted(EMAIL_PROVIDERS))
    email.add_argument("--email-preset", choices=sorted(SMTP_PRESETS))
    email.add_argument("--email-host", help="SMTP hostname; required with --email-preset custom.")
    email.add_argument("--email-recipient")
    email.add_argument(
        "--email-address",
        "--email-username",
        dest="email_username",
        help="SMTP sender email address (email-username is a compatibility alias).",
    )
    email.add_argument("--email-port", type=int)
    email.add_argument("--email-security", choices=("ssl", "starttls"))
    email.add_argument("--clawemail-root")
    password = email.add_mutually_exclusive_group()
    password.add_argument("--email-password-env")
    password.add_argument("--email-password-file")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def interactive_options(args: argparse.Namespace) -> argparse.Namespace:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError("interactive installation requires a TTY; use --non-interactive")

    section("Source and destination")
    args.install_root = args.install_root or ask("Installation directory", str(Path.home() / ".local/share/tspi"))
    args.workspace_root = args.workspace_root or ask(
        "Workspace root",
        str(read_workspace_root(Path(args.install_root).expanduser())),
    )
    field("Repository", args.tspi_repo)
    field("Requested revision", args.tspi_ref)
    if args.tspi_commit:
        field("Resolved commit", args.tspi_commit)

    section("Core")
    field("Agent", "required", tone="success")
    field("Scientific runtime", "required", tone="success")
    field("Molecular rendering", "required", tone="success")
    field("Pi App Server runtime", "required", tone="success")

    section("Optional components")
    if args.with_web is None:
        args.with_web = ask_yes_no("Install TS Web", True)
    if args.with_web:
        args.web_port = _ask_int("TS Web port", args.web_port or 8766, minimum=1, maximum=65535)
        args.web_host = ask("TS Web listen address", args.web_host or "127.0.0.1")
        if args.web_host not in {"127.0.0.1", "::1", "localhost"}:
            args.allow_remote = ask_yes_no("Allow remote TS Web clients", False)
        if args.web_auth_token is None and ask_yes_no("Use a custom TS Web access token", False):
            args.web_auth_token = _ask_web_auth_token()
    if args.with_model_icons is None:
        args.with_model_icons = ask_yes_no("Install TSPi model icon font", True)
    section("Compute backends")
    args.compute_config = ask(
        "Compute backend TOML path (blank preserves existing configuration)",
        args.compute_config or "",
    ).strip() or None
    section("Phone connection")
    existing_link = _existing_link_configuration(Path(args.install_root))
    if args.phone_access is None:
        args.phone_access = "link" if ask_yes_no("Enable TS Phone through TSPi Link Relay", existing_link is not None) else "disabled"
    if args.phone_access == "link":
        args.link_url = ask(
            "TSPi Link Relay URL",
            args.link_url or (existing_link[0] if existing_link else ""),
        ).strip()
        token_exists = (Path(args.install_root) / ".pi/app-server-host/host.token").is_file()
        enrolled_for_url = token_exists and existing_link is not None and args.link_url.rstrip("/") == existing_link[0]
        if not enrolled_for_url and args.link_enrollment_code is None:
            # The package/runtime installation can take longer than the
            # Relay's short-lived enrollment window. Ask for the code only
            # after that work completes, immediately before redemption.
            args._defer_link_enrollment = True
    section("Runtime and services")
    args.conda_root = args.conda_root or ask("Conda root (blank for auto-detect)", detect_conda_root())
    if args.service_scope is None:
        configure_systemd = ask_yes_no(
            "Install App Server and selected component service units",
            True,
        )
        args.service_scope = "user" if configure_systemd else "none"
    if args.service_scope == "system" and not args.service_user:
        args.service_user = os.environ.get("SUDO_USER") or ask("Service user", "")
    if args.service_scope != "none":
        args.enable_services = ask_yes_no("Enable services", True)
        args.start_services = ask_yes_no("Start services now", True)
    configure_email_interactively(args)
    return args


def _load_existing_menu_defaults(args: argparse.Namespace) -> None:
    """Load persisted values so reopening the installer is an edit operation."""

    root = Path(args.install_root).expanduser()
    if args.workspace_root is None:
        args.workspace_root = str(read_workspace_root(root))
    if args.with_web is None:
        args.with_web = (root / "TSWeb").exists() or not (root / ".pi/packages/tspi/install-state.json").is_file()
    if args.web_port is None:
        args.web_port = 8766
    if args.with_model_icons is None:
        marker = root / ".pi/tspi/model-icons.json"
        try:
            document = json.loads(marker.read_text(encoding="utf-8"))
            args.with_model_icons = bool(document.get("enabled")) if isinstance(document, dict) else False
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            args.with_model_icons = not (root / ".pi/packages/tspi/install-state.json").is_file()
    if args.phone_access is None:
        args.phone_access = "link" if _existing_link_configuration(root) else "disabled"
    if args.link_url is None:
        existing_link = _existing_link_configuration(root)
        args.link_url = existing_link[0] if existing_link else None
    service_config = root / ".pi/tspi/service.json"
    if args.service_scope is None:
        try:
            document = json.loads(service_config.read_text(encoding="utf-8"))
            scope = document.get("scope") if isinstance(document, dict) else None
            args.service_scope = scope if scope in {"none", "user", "system"} else None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            args.service_scope = None
    if args.service_scope is None:
        args.service_scope = "none"
    if args.service_scope == "system" and not args.service_user:
        unit = Path("/etc/systemd/system/ts-app-server-tspi.service")
        try:
            for line in unit.read_text(encoding="utf-8").splitlines():
                if line.startswith("User=") and line.removeprefix("User=").strip():
                    args.service_user = line.removeprefix("User=").strip()
                    break
        except OSError:
            pass
    if args.service_scope != "none" and not args.enable_services:
        args.enable_services = True
    if args.service_scope != "none" and not args.start_services:
        args.start_services = False
    _load_existing_email_defaults(args, root)


def _load_existing_email_defaults(args: argparse.Namespace, root: Path) -> None:
    config = root / ".pi/notifications.toml"
    try:
        document = tomllib.loads(config.read_text(encoding="utf-8"))
        email = document.get("notifications", {}).get("email", {})
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, AttributeError):
        return
    if not isinstance(email, dict) or not email.get("enabled"):
        return
    provider = email.get("provider", "smtp")
    if provider == "clawemail":
        args.email_binding = "clawemail"
        args.email_recipient = email.get("recipient")
        args.clawemail_root = email.get("clawemail_root")
        return
    args.email_binding = "smtp"
    args.email_recipient = email.get("recipient")
    args.email_preset = email.get("preset", "qq")
    args.email_host = email.get("host")
    args.email_port = email.get("port", 465)
    args.email_security = email.get("security", "ssl")
    args.email_username = email.get("username")
    args.email_password_env = email.get("password_env")
    args.email_password_file = email.get("password_file")


def _menu_choice(args: argparse.Namespace) -> str:
    root = Path(args.install_root)
    section("Installer menu")
    field("Installation", args.install_root, tone="accent")
    field("Workspace", args.workspace_root or "not set")
    field("TS Web", "enabled" if args.with_web else "disabled")
    field("Phone", "Link Relay" if args.phone_access == "link" else "disabled")
    field("Services", args.service_scope or "none")
    field("Email", args.email_binding or ("configured" if (root / ".pi/notifications.toml").is_file() else "not configured"))
    print()
    print("  1) Installation and workspace")
    print("  2) TS Web")
    print("  3) Compute backends")
    print("  4) Phone connection")
    print("  5) Runtime and services")
    print("  6) Email notifications")
    print("  7) Model icon font")
    print("  8) Review and install")
    print("  9) Quit")
    return ask("Select a configuration area", "8").strip()


def _configure_menu_web(args: argparse.Namespace) -> None:
    args.with_web = ask_yes_no("Install TS Web", bool(args.with_web))
    if not args.with_web:
        args.web_port = None
        args.web_auth_token = None
        args.allow_remote = False
        return
    args.web_port = _ask_int("TS Web port", args.web_port or 8766, minimum=1, maximum=65535)
    args.web_host = ask("TS Web listen address", args.web_host or "127.0.0.1")
    if args.web_host not in {"127.0.0.1", "::1", "localhost"}:
        args.allow_remote = ask_yes_no("Allow remote TS Web clients", bool(args.allow_remote))
    else:
        args.allow_remote = False
    if ask_yes_no("Replace the TS Web access token", False):
        args.web_auth_token = _ask_web_auth_token()


def _ask_int(
    prompt: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """Read a bounded integer without aborting the interactive wizard."""

    while True:
        raw = ask(prompt, str(default)).strip()
        try:
            value = int(raw)
        except ValueError:
            note("Please enter a whole number.", tone="warning")
            continue
        if minimum is not None and value < minimum:
            note(f"Please enter a number of at least {minimum}.", tone="warning")
            continue
        if maximum is not None and value > maximum:
            note(f"Please enter a number no greater than {maximum}.", tone="warning")
            continue
        return value


def _configure_menu_phone(args: argparse.Namespace) -> None:
    enabled = ask_yes_no("Enable TS Phone through TSPi Link Relay", args.phone_access == "link")
    if not enabled:
        args.phone_access = "disabled"
        args.link_url = None
        args.link_enrollment_code = None
        args._defer_link_enrollment = False
        return
    args.phone_access = "link"
    existing_link = _existing_link_configuration(Path(args.install_root))
    args.link_url = ask("TSPi Link Relay URL", args.link_url or (existing_link[0] if existing_link else "")).strip()
    token_file = Path(args.install_root) / ".pi/app-server-host/host.token"
    enrolled_for_url = token_file.is_file() and existing_link is not None and args.link_url.rstrip("/") == existing_link[0]
    if not enrolled_for_url:
        args.link_enrollment_code = None
        # Enrollment is deliberately collected after the potentially long
        # package installation, so a valid code cannot expire mid-install.
        args._defer_link_enrollment = True
    else:
        args.link_enrollment_code = None
        args._defer_link_enrollment = False


def _configure_menu_runtime(args: argparse.Namespace) -> None:
    args.conda_root = ask("Conda root (blank for auto-detect)", args.conda_root or detect_conda_root()).strip()
    current_scope = args.service_scope or "none"
    while True:
        scope = ask("Service scope (none, user, or system)", current_scope).strip().lower()
        if scope in {"none", "user", "system"}:
            args.service_scope = scope
            break
        note("Choose none, user, or system.", tone="warning")
    if args.service_scope == "system" and not args.service_user:
        args.service_user = os.environ.get("SUDO_USER") or ask("Service user", "")
    if args.service_scope == "none":
        args.enable_services = False
        args.start_services = False
    else:
        args.enable_services = ask_yes_no("Enable services", bool(args.enable_services))
        args.start_services = ask_yes_no("Start services now", bool(args.start_services))


def _initialize_interactive_menu(args: argparse.Namespace) -> None:
    """Initialize interactive defaults once for the lifetime of one wizard run."""

    if getattr(args, "_installer_menu_initialized", False):
        return
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError("interactive installation requires a TTY; use --non-interactive")
    args.install_root = args.install_root or ask("Installation directory", str(Path.home() / ".local/share/tspi"))
    args.install_root = str(Path(args.install_root).expanduser())
    _load_existing_menu_defaults(args)
    if args.phone_access == "link" and not _link_host_enrolled_for_url(args):
        # Do not collect a ten-minute enrollment code before a long runtime
        # installation. It is requested in the finalization phase instead.
        args.link_enrollment_code = None
        args._defer_link_enrollment = True
    args._installer_menu_initialized = True


def interactive_menu_options(args: argparse.Namespace) -> argparse.Namespace:
    """Collect configuration through a repeatable menu before installation."""

    _initialize_interactive_menu(args)
    while True:
        choice = _menu_choice(args)
        if choice in {"8", ""}:
            return args
        if choice == "9":
            args._installer_cancelled = True
            return args
        if choice == "1":
            args.workspace_root = ask("Workspace root", args.workspace_root or str(read_workspace_root(Path(args.install_root))))
        elif choice == "2":
            _configure_menu_web(args)
        elif choice == "3":
            args.compute_config = ask(
                "Compute backend TOML path (blank preserves existing configuration)",
                args.compute_config or "",
            ).strip() or None
        elif choice == "4":
            _configure_menu_phone(args)
        elif choice == "5":
            _configure_menu_runtime(args)
        elif choice == "6":
            configure_email_interactively(args, force=True)
        elif choice == "7":
            args.with_model_icons = ask_yes_no("Install TSPi model icon font", bool(args.with_model_icons))
        else:
            note("Choose a menu number from 1 to 9.", tone="warning")


def configure_email_interactively(args: argparse.Namespace, *, force: bool = False) -> None:
    if args.email_binding is not None and not force:
        return
    args.__dict__.pop("_email_password", None)
    args.__dict__.pop("_clear_email", None)
    root = Path(args.install_root)
    existing = root / ".pi" / "notifications.toml"
    prompt = "Reconfigure email notifications" if existing.is_file() else "Configure email notifications"
    if not ask_yes_no(prompt, False):
        if force and existing.is_file() and ask_yes_no("Disable email notifications", False):
            args.email_binding = None
            _clear_email_options(args)
            args._clear_email = True
        return
    args.email_binding = ask("Email binding (smtp or clawemail)", getattr(args, "email_binding", None) or "smtp").lower()
    args.email_recipient = _ask_email_address("Notification recipient", getattr(args, "email_recipient", None) or "")
    if args.email_binding == "clawemail":
        _clear_smtp_options(args)
        args.clawemail_root = ask("ClawEmail installation root", getattr(args, "clawemail_root", None) or "")
        return
    args.clawemail_root = None
    args.email_preset = ask("SMTP mailbox preset (163, qq, or custom)", getattr(args, "email_preset", None) or "qq").lower()
    if args.email_preset == "custom":
        args.email_host = ask("SMTP hostname", getattr(args, "email_host", None) or "")
    elif args.email_preset in SMTP_PRESETS:
        args.email_host = None
    args.email_port = _ask_int(
        "SMTP port",
        getattr(args, "email_port", None) or 465,
        minimum=1,
        maximum=65535,
    )
    args.email_security = ask("SMTP security (ssl or starttls)", getattr(args, "email_security", None) or "ssl").lower()
    args.email_username = _ask_email_address("SMTP sender email address", getattr(args, "email_username", None) or "")
    if ask_yes_no("Read SMTP authorization code from an environment variable", False):
        args.email_password_env = ask("Password environment variable", "TSPI_EMAIL_PASSWORD")
        args.email_password_file = None
        return
    default_password_file = root / ".pi" / "email" / "smtp-password"
    args.email_password_env = None
    args.email_password_file = ask("SMTP authorization-code file", getattr(args, "email_password_file", None) or str(default_password_file))
    password_path = Path(args.email_password_file).expanduser()
    if not password_path.exists() or ask_yes_no("Replace the SMTP authorization code", False):
        password = _read_secret("SMTP authorization code (hidden)").strip()
        if not password:
            raise ValueError("SMTP authorization code must not be empty")
        args._email_password = password


def _clear_smtp_options(args: argparse.Namespace) -> None:
    for name in ("email_preset", "email_host", "email_username", "email_port", "email_security", "email_password_env", "email_password_file"):
        setattr(args, name, None)


def _clear_email_options(args: argparse.Namespace) -> None:
    args.email_recipient = None
    args.clawemail_root = None
    _clear_smtp_options(args)


def _ask_email_address(prompt: str, default: str = "") -> str:
    while True:
        value = ask(prompt, default)
        try:
            _validate_email_address(value, prompt)
        except ValueError:
            note("Please enter a complete email address, for example sender@example.com.", tone="warning")
            continue
        return value


def show_install_plan(args: argparse.Namespace, installation: dict[str, str | None]) -> None:
    section("Installation plan")
    operation = {
        "install": "Fresh install",
        "update": "Update existing installation",
        "restore": "Restore removed application",
    }[str(installation["operation"])]
    field("Operation", operation, tone="accent")
    if installation["release_id"]:
        field("Current release", installation["release_id"])
    field("Installation root", args.install_root, tone="accent")
    field("TSPi revision", args.tspi_ref)
    if args.tspi_commit:
        field("Resolved commit", args.tspi_commit)
    field("Workspace root", args.workspace_root)
    field("Conda root", args.conda_root or "auto-detect")
    if args.service_scope == "system":
        field("Installation owner", f"{args.service_user} (private package/runtime/state tree)", tone="warning")
    field("Phone access", "TSPi Link Relay" if args.phone_access == "link" else "disabled", tone="success" if args.phone_access == "link" else "muted")
    if args.phone_access == "link":
        field("TSPi Link Relay", args.link_url, tone="success")
        if getattr(args, "_defer_link_enrollment", False):
            field("Host enrollment", "request after core installation", tone="warning")
        field("Phone tool access", "same Agent and tools as terminal", tone="success")
    field(
        "Model icon font",
        "install optional TSPi font" if args.with_model_icons else "use Nerd Font/Unicode fallback",
        tone="success" if args.with_model_icons else "muted",
    )

    root = Path(args.install_root)
    section("Core")
    field("Agent", f"install - {root / 'TSPi'}", tone="success")
    field("Scientific runtime", "install and verify", tone="success")
    field("Molecular rendering", "install and verify (xyzrender, Matplotlib)", tone="success")
    field("Pi App Server", "install pinned runtime and verify", tone="success")
    field("Local backend policy", "core Python/runtime only; native tools must be selected explicitly", tone="muted")
    field("Compute backend config", args.compute_config or "preserve <install>/.pi/compute.toml if present", tone="muted")
    field("Remote readiness", "probe during installation" if args.probe_remote else "not probed", tone="success" if args.probe_remote else "muted")
    field(
        "App Server service",
        _service_plan(args),
        tone="success" if args.service_scope != "none" else "muted",
    )

    section("Email notifications")
    if args.email_binding is None:
        if getattr(args, "_clear_email", False):
            configuration = "disable existing"
        else:
            configuration = (
                "preserve existing"
                if (Path(args.install_root) / ".pi/notifications.toml").is_file()
                else "not configured"
            )
        field("Configuration", configuration, tone="muted")
    elif args.email_binding == "clawemail":
        field("Provider", "ClawEmail", tone="success")
        field("Recipient", args.email_recipient)
        field("ClawEmail root", args.clawemail_root)
    else:
        field("Provider", f"SMTP ({args.email_preset})", tone="success")
        field("Recipient", args.email_recipient)
        field("Username", args.email_username)
        credential = args.email_password_env or args.email_password_file
        field("Credential", credential)

    section("TS Web")
    field(
        "Install",
        "yes" if args.with_web else "no",
        tone="success" if args.with_web else "muted",
    )
    if args.with_web:
        field("Launcher", root / "TSWeb")
        field("Listen", f"http://{args.web_host}:{args.web_port}")
        field("Workspace root", args.workspace_root)
        field("State directory", root / ".pi/ts-web-state")
        token_path = Path(args.web_auth_token_file).expanduser() if args.web_auth_token_file else root / ".pi/ts-web/auth.token"
        field("HTTP token", _planned_credential(token_path))
        field(
            "Service",
            _service_plan(args),
            tone="success" if args.service_scope != "none" else "muted",
        )
    note("Press Enter/Y to install, N to return to the configuration menu, or choose 9 to quit.")


def _planned_credential(path: Path) -> str:
    action = "validate and preserve" if path.exists() or path.is_symlink() else "create"
    return f"{path} ({action}, mode 0600)"


def _ask_web_auth_token() -> str | None:
    """Read a custom token without delaying validation until installation."""

    while True:
        value = _read_secret("TS Web access token (8-100 URL-safe characters; blank generates one)").strip()
        if not value:
            return None
        if WEB_TOKEN_PATTERN.fullmatch(value):
            return value
        note(
            "Token must contain 8-100 URL-safe characters: A-Z, a-z, 0-9, _ or -.",
            tone="warning",
        )


def _read_secret(prompt: str) -> str:
    """Use visible masked input on a TTY and retain injectable getpass in tests."""

    if sys.stdin.isatty() and sys.stdout.isatty():
        return ask_secret(prompt)
    return getpass.getpass(prompt + ": ")


def _service_plan(args: argparse.Namespace, *, template: bool = False) -> str:
    if args.service_scope == "none":
        return "not configured"
    actions = ["configure"]
    if args.enable_services:
        actions.append("enable")
    if args.start_services:
        actions.append("start")
    return f"{args.service_scope} ({', '.join(actions)})"


def validate_options(args: argparse.Namespace) -> None:
    validate_repo(args.tspi_repo)
    validate_ref(args.tspi_ref)
    if args.tspi_commit:
        validate_commit(args.tspi_commit)
    if not args.install_root:
        raise ValueError("--install-root is required in non-interactive mode")
    args.install_root = str(validate_install_root(Path(args.install_root)))
    if args.compute_config:
        source = Path(args.compute_config).expanduser()
        if not source.is_absolute() or source.is_symlink() or not source.is_file():
            raise ValueError("--compute-config must be an existing absolute regular file")
        try:
            parsed_compute = tomllib.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise ValueError(f"invalid compute TOML configuration: {source}: {error}") from error
        _validate_compute_config(parsed_compute)
    if args.workspace_root is None:
        args.workspace_root = str(read_workspace_root(Path(args.install_root)))
    args.workspace_root = str(_validate_workspace_root(args.workspace_root, Path(args.install_root)))
    existing_link = _existing_link_configuration(Path(args.install_root))
    if args.phone_access is None:
        args.phone_access = "link" if existing_link is not None else "disabled"
    if args.link_url is None and existing_link is not None:
        args.link_url = existing_link[0]
    if args.with_web is None:
        args.with_web = True
    if args.with_model_icons is None:
        args.with_model_icons = False
    if args.web_auth_token is not None:
        if not args.with_web:
            raise ValueError("--web-auth-token requires --with-web")
        if WEB_TOKEN_PATTERN.fullmatch(args.web_auth_token) is None:
            raise ValueError("--web-auth-token must contain 8 to 100 URL-safe characters")
    if not args.with_web and args.web_port is not None:
        raise ValueError("--web-port requires --with-web")
    if args.with_web:
        if args.web_port is None:
            args.web_port = 8766
        if not 1 <= args.web_port <= 65535:
            raise ValueError("--web-port must be between 1 and 65535")
        if not isinstance(args.web_host, str) or not args.web_host.strip() or len(args.web_host) > 255 or any(ord(c) < 32 or c.isspace() for c in args.web_host):
            raise ValueError("--web-host must be a non-empty address")
        loopback = args.web_host in {"127.0.0.1", "::1", "localhost"}
        if not loopback and not args.allow_remote:
            raise ValueError("non-loopback --web-host requires --allow-remote")
        if args.web_auth_token_file:
            token_path = Path(args.web_auth_token_file).expanduser()
            root = Path(args.install_root).resolve()
            if not token_path.is_absolute() or token_path.is_symlink() or root not in token_path.resolve().parents:
                raise ValueError("--web-auth-token-file must be an absolute path inside the installation root")
    elif args.allow_remote:
        raise ValueError("--allow-remote requires --with-web")
    args.service_scope = args.service_scope or "none"
    if args.service_scope == "none" and (args.enable_services or args.start_services):
        raise ValueError("--enable-services and --start-services require a service scope")
    if args.start_services:
        args.enable_services = True
    if args.service_scope == "system" and os.geteuid() != 0:
        raise ValueError("system services require root; choose --service-scope user")
    if args.service_scope == "system":
        if not args.service_user or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}", args.service_user):
            raise ValueError("--service-user is required for system services")
        try:
            service_account = pwd.getpwnam(args.service_user)
        except KeyError as exc:
            raise ValueError(f"service user does not exist: {args.service_user}") from exc
        install_path = Path(args.install_root).resolve()
        service_home = Path(service_account.pw_dir).resolve()
        if service_home == Path("/") or service_home in install_path.parents or install_path == service_home:
            if service_account.pw_uid != os.getuid():
                raise ValueError("system service installation under another user's home is not supported; use /opt or /var/lib")
    if args.service_scope == "user" and args.service_user:
        current_user = pwd.getpwuid(os.getuid()).pw_name
        if args.service_user != current_user:
            raise ValueError("--service-user is only supported with --service-scope system")
    if args.phone_access == "link":
        args.link_url = _validate_link_url(args.link_url)
        token_file = Path(args.install_root) / ".pi/app-server-host/host.token"
        enrolled_for_url = token_file.is_file() and existing_link is not None and existing_link[0] == args.link_url
        if not enrolled_for_url and not args.link_enrollment_code and not getattr(args, "_defer_link_enrollment", False):
            raise ValueError("--link-enrollment-code is required when enrolling a new TSPi Host")
    elif args.link_url or args.link_enrollment_code:
        raise ValueError("--link-url and --link-enrollment-code require --phone-access link")
    if args.service_scope != "none" and shutil.which("systemctl") is None:
        raise ValueError("service configuration requires systemctl; choose --service-scope none")
    validate_email_options(args)


def _validate_workspace_root(value: object, install_root: Path) -> Path:
    requested = Path(value).expanduser() if isinstance(value, str) and value else install_root / "workspaces"
    if not requested.is_absolute():
        raise ValueError("--workspace-root must be absolute")
    if requested.is_symlink():
        raise ValueError("--workspace-root cannot be a symbolic link")
    resolved = requested.resolve()
    install = install_root.resolve()
    home = Path.home().resolve()
    if (
        resolved.parent == Path("/")
        or resolved == home
        or resolved in home.parents
        or resolved == install
        or resolved in install.parents
    ):
        raise ValueError("--workspace-root must be a dedicated directory")
    for protected in (install / ".pi", install / ".agents"):
        if resolved == protected or protected in resolved.parents:
            raise ValueError("--workspace-root cannot be inside installation control or runtime state")
    if resolved.exists() and not resolved.is_dir():
        raise ValueError("--workspace-root must be a directory")
    return resolved


def configure_workspace_root(args: argparse.Namespace) -> dict[str, str]:
    root = Path(args.install_root).resolve()
    requested = Path(args.workspace_root)
    if requested.is_symlink():
        raise ValueError(f"workspace root cannot be a symbolic link: {requested}")
    workspace_root = requested.resolve()
    workspace_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not workspace_root.is_dir():
        raise ValueError(f"workspace root is not a directory: {workspace_root}")
    workspace_root.chmod(0o700)
    config = write_workspace_root(root, workspace_root)
    return {"status": "configured", "path": str(config), "workspace_root": str(workspace_root)}


def configure_service_runtime(args: argparse.Namespace) -> dict[str, str | None]:
    """Persist the service scope and socket runtime selected by the installer."""

    root = Path(args.install_root).resolve()
    scope = args.service_scope or "none"
    if scope == "none":
        runtime_dir: str | None = None
    elif scope == "system":
        runtime_dir = "/run/tspi"
    else:
        service_user = getattr(args, "service_user", None) or pwd.getpwuid(os.getuid()).pw_name
        service_uid = pwd.getpwnam(service_user).pw_uid
        runtime_parent = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{service_uid}"
        runtime_dir = str(Path(runtime_parent) / "tspi")
    document = {
        "schema_version": SERVICE_CONFIG_SCHEMA,
        "scope": scope,
        "runtime_dir": runtime_dir,
    }
    destination = root / SERVICE_CONFIG_RELATIVE
    _write_private_config_bytes(
        (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        destination,
    )
    return {"status": "configured", "path": str(destination), "scope": scope, "runtime_dir": runtime_dir}


def _existing_link_configuration(root: Path) -> tuple[str, str] | None:
    manifest = root / ".pi/app-server-host/link.json"
    if not manifest.is_file() or manifest.is_symlink():
        return None
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema_version") != "tspi-link/1":
        return None
    relay_url = value.get("relay_url")
    host_id = value.get("host_id")
    if not isinstance(relay_url, str) or not isinstance(host_id, str):
        return None
    return relay_url, host_id


def _link_host_enrolled_for_url(args: argparse.Namespace) -> bool:
    """Return whether this install already has a Host token for the Relay."""

    if args.phone_access != "link" or not isinstance(args.link_url, str):
        return False
    root = Path(args.install_root)
    existing = _existing_link_configuration(root)
    token_file = root / ".pi/app-server-host/host.token"
    return token_file.is_file() and existing is not None and existing[0] == args.link_url.rstrip("/")


def _validate_link_url(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError("--link-url must be a TSPi Link Relay origin")
    try:
        parsed = urllib.parse.urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("--link-url must be a TSPi Link Relay origin") from exc
    loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
    if not parsed.hostname or (parsed.scheme != "https" and not (loopback and parsed.scheme == "http")):
        raise ValueError("--link-url must use HTTPS except on loopback")
    if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("--link-url must contain only scheme, host, and port")
    return value.rstrip("/")


def validate_email_options(args: argparse.Namespace) -> None:
    values = (
        args.email_preset,
        args.email_host,
        args.email_recipient,
        args.email_username,
        args.email_port,
        args.email_security,
        args.clawemail_root,
        args.email_password_env,
        args.email_password_file,
    )
    if args.email_binding is None:
        if any(value is not None for value in values):
            raise ValueError("email options require --email-binding")
        return
    if args.email_binding not in EMAIL_PROVIDERS:
        raise ValueError("--email-binding must be smtp or clawemail")
    _validate_email_address(args.email_recipient, "--email-recipient")
    if args.email_binding == "clawemail":
        clawemail_path = Path(args.clawemail_root).expanduser() if isinstance(args.clawemail_root, str) else None
        if (
            clawemail_path is None
            or not clawemail_path.is_absolute()
            or clawemail_path.is_symlink()
            or not clawemail_path.is_dir()
        ):
            raise ValueError("--clawemail-root must be an existing absolute non-symbolic-link directory")
        _validate_clawemail_install(clawemail_path)
        if any(
            value is not None
            for value in (args.email_preset, args.email_host, args.email_username, args.email_port, args.email_security, args.email_password_env, args.email_password_file)
        ):
            raise ValueError("SMTP-only email options cannot be used with ClawEmail")
        return

    if args.email_preset not in SMTP_PRESETS:
        raise ValueError("--email-preset must be 163, qq, or custom for SMTP")
    if args.email_preset == "custom":
        _validate_smtp_host(args.email_host, "--email-host")
    elif args.email_host is not None:
        expected_host = SMTP_PRESETS[args.email_preset]
        if args.email_host != expected_host:
            raise ValueError(f"--email-host must be {expected_host} for preset {args.email_preset}")
    if args.email_port is None:
        args.email_port = 465
    if not isinstance(args.email_port, int) or isinstance(args.email_port, bool) or not 1 <= args.email_port <= 65535:
        raise ValueError("--email-port must be between 1 and 65535")
    args.email_security = args.email_security or "ssl"
    if args.email_security not in {"ssl", "starttls"}:
        raise ValueError("--email-security must be ssl or starttls")
    _validate_email_address(args.email_username, "--email-username")
    if (args.email_password_env is None) == (args.email_password_file is None):
        raise ValueError("SMTP requires exactly one of --email-password-env or --email-password-file")
    if args.email_password_env is not None and not ENV_NAME.fullmatch(args.email_password_env):
        raise ValueError("--email-password-env must be an environment variable name")
    if args.email_password_file is not None:
        password_path = Path(args.email_password_file).expanduser()
        if not password_path.is_absolute() or password_path.is_symlink():
            raise ValueError("--email-password-file must be an absolute non-symbolic-link path")
        if not password_path.exists() and not hasattr(args, "_email_password"):
            raise ValueError("--email-password-file must exist for non-interactive installation")
        if password_path.exists():
            if not password_path.is_file() or stat.S_IMODE(password_path.stat().st_mode) != 0o600:
                raise ValueError("--email-password-file must be a regular file with mode 0600")
    if hasattr(args, "_email_password") and args.email_password_env is not None:
        raise ValueError("an interactive SMTP password must use a password file")


def _validate_email_address(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or any(character.isspace() for character in value):
        raise ValueError(f"{label} must be one email address")
    if value.count("@") != 1:
        raise ValueError(f"{label} must be one email address")
    local, domain = value.split("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError(f"{label} must be one email address")


def _validate_smtp_host(value: object, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 255
        or any(character.isspace() or ord(character) < 32 for character in value)
        or "/" in value
        or "@" in value
    ):
        raise ValueError(f"{label} must be a hostname")


def _validate_clawemail_install(root: Path) -> None:
    skill_file = root / "SKILL.md"
    manager = root / "bin/clawemail-manager"
    state = root / ".clawemail"
    if (
        not skill_file.is_file()
        or skill_file.is_symlink()
        or "name: clawemail" not in skill_file.read_text(encoding="utf-8")[:2048]
    ):
        raise ValueError("--clawemail-root does not contain a ClawEmail skill")
    if not manager.is_file() or manager.is_symlink() or not os.access(manager, os.X_OK):
        raise ValueError("--clawemail-root does not contain an executable clawemail-manager")
    if state.is_symlink() or not state.is_dir():
        raise ValueError("--clawemail-root does not contain a physical .clawemail state directory")
    for path, label in ((state / "skill.json", "settings"), (state / "mail-cli.json", "authentication")):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"ClawEmail {label} file is missing or unsafe: {path}")
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise ValueError(f"ClawEmail {label} file must have mode 0600: {path}")


def configure_notification_config(args: argparse.Namespace) -> dict[str, str]:
    """Write installation-owned notification configuration without exposing secrets."""

    root = Path(args.install_root).expanduser().resolve()
    config_path = root / ".pi" / "notifications.toml"
    if getattr(args, "_clear_email", False):
        if config_path.is_symlink():
            raise ValueError(f"notification file cannot be a symbolic link: {config_path}")
        config_path.unlink(missing_ok=True)
        return {"status": "disabled", "path": str(config_path)}
    if args.email_binding is None:
        return {
            "status": "preserved" if config_path.is_file() else "not_configured",
            "path": str(config_path),
        }

    if args.email_binding == "clawemail":
        content = "\n".join(
            [
                "[notifications.email]",
                "enabled = true",
                f"recipient = {_toml_string(args.email_recipient)}",
                f"clawemail_root = {_toml_string(str(Path(args.clawemail_root).expanduser()))}",
                "",
            ]
        )
        _write_private_text(config_path, content)
        return {"status": "configured", "binding": "clawemail", "path": str(config_path)}

    password_file: Path | None = None
    if args.email_password_file is not None:
        password_file = Path(args.email_password_file).expanduser()
        if hasattr(args, "_email_password"):
            _write_private_text(password_file, f"{args._email_password}\n")
        _validate_private_secret_file(password_file)

    lines = [
        "[notifications.email]",
        "enabled = true",
        "provider = \"smtp\"",
        f"preset = {_toml_string(args.email_preset)}",
        f"port = {args.email_port}",
        f"security = {_toml_string(args.email_security)}",
        f"recipient = {_toml_string(args.email_recipient)}",
        f"username = {_toml_string(args.email_username)}",
    ]
    if args.email_preset == "custom":
        lines.append(f"host = {_toml_string(args.email_host)}")
    if args.email_password_env is not None:
        lines.append(f"password_env = {_toml_string(args.email_password_env)}")
        credential = args.email_password_env
        env_path = root / ".pi" / "email" / "service.env"
        value = os.environ.get(args.email_password_env)
        if value:
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            _write_private_text(env_path, f'{args.email_password_env}="{escaped}"\n')
    else:
        assert password_file is not None
        lines.append(f"password_file = {_toml_string(str(password_file.resolve()))}")
        credential = str(password_file.resolve())
    lines.append("")
    _write_private_text(config_path, "\n".join(lines))
    return {
        "status": "configured",
        "binding": "smtp",
        "preset": args.email_preset,
        "credential": credential,
        "environment_file": str(root / ".pi" / "email" / "service.env") if args.email_password_env else None,
        "path": str(config_path),
    }


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _ensure_private_directory(path: Path) -> None:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_dir():
            raise ValueError(f"private directory must be a physical directory: {path}")
    else:
        path.mkdir(mode=0o700, parents=True)
    path.chmod(0o700)


def _write_private_text(path: Path, content: str) -> None:
    if path.is_symlink():
        raise ValueError(f"notification file cannot be a symbolic link: {path}")
    _ensure_private_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".notification-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _validate_private_secret_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"--email-password-file must be a regular file: {path}")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError(f"--email-password-file must have mode 0600: {path}")
    try:
        value = path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError as error:
        raise ValueError(f"--email-password-file must contain text: {path}") from error
    if not value:
        raise ValueError(f"--email-password-file must not be empty: {path}")


def _copy_private_config(source_value: str, destination: Path, *, kind: str) -> dict[str, str]:
    source = Path(source_value).expanduser()
    if not source.is_absolute() or source.is_symlink() or not source.is_file():
        raise ValueError(f"--{kind}-config must be an existing absolute regular file")
    try:
        with source.open("rb") as handle:
            raw = handle.read()
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("configuration is too large")
            parsed = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"invalid {kind} TOML configuration: {source}: {error}") from error
    if kind == "compute":
        _validate_compute_config(parsed)
    elif kind == "remote":
        _validate_remote_config(parsed, source.parent)
    elif kind == "local":
        table = parsed.get("backends", parsed.get("local", parsed))
        if not isinstance(table, dict):
            raise ValueError("local config must contain a [backends] table")
        for name, entry in table.items():
            activation = None
            command = entry
            if isinstance(entry, dict):
                command = entry.get("command")
                activation = entry.get("activation_script")
            if not isinstance(name, str) or not isinstance(command, str) or not command.strip():
                raise ValueError("local backend commands must be non-empty strings")
            if activation is not None:
                activation_path = Path(activation).expanduser() if isinstance(activation, str) else None
                if (
                    activation_path is None
                    or not activation_path.is_absolute()
                    or activation_path.is_symlink()
                    or not activation_path.is_file()
                    or not os.access(activation_path, os.R_OK)
                ):
                    raise ValueError(f"local backend {name!r} activation_script must be an absolute readable regular file")
    _write_private_config_bytes(raw, destination)
    return {"status": "configured", "path": str(destination), "source": str(source)}


def _validate_compute_config(parsed: dict[str, object]) -> None:
    """Validate the shared environment shape before installing it."""
    environments = parsed.get("environments")
    default = parsed.get("default_environment")
    if not isinstance(environments, dict) or not environments or not isinstance(default, str) or default not in environments:
        raise ValueError("compute config must define default_environment and at least one environment")
    for name, environment in environments.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name):
            raise ValueError(f"invalid compute environment name: {name!r}")
        if not isinstance(environment, dict) or environment.get("kind") not in {"local", "remote"}:
            raise ValueError(f"compute environment {name!r} must declare kind=local or kind=remote")
        backends = environment.get("backends", {})
        if not isinstance(backends, dict):
            raise ValueError(f"compute environment {name!r} backends must be a table")
        for backend, item in backends.items():
            if not isinstance(backend, str) or not isinstance(item, dict):
                raise ValueError(f"compute environment {name!r} has an invalid backend binding")
            command = item.get("command")
            valid_command = isinstance(command, str) and bool(command.strip()) if environment["kind"] == "local" else (
                isinstance(command, list) and bool(command) and all(isinstance(value, str) and value for value in command)
            )
            if not valid_command:
                expected = "string" if environment["kind"] == "local" else "string array"
                raise ValueError(f"compute environment {name!r} backends.{backend}.command must be a {expected}")
            activation = item.get("activation_script")
            if activation is not None and (not isinstance(activation, str) or not activation.startswith("/")):
                raise ValueError(f"compute environment {name!r} backends.{backend}.activation_script must be absolute")
        if environment["kind"] == "remote":
            _validate_remote_config({"default_environment": name, "environments": {name: environment}}, Path("/"))


def _validate_remote_config(parsed: dict[str, object], base: Path) -> None:
    environments = parsed.get("environments")
    default = parsed.get("default_environment")
    if not isinstance(environments, dict) or not environments or not isinstance(default, str) or default not in environments:
        raise ValueError("remote config must define default_environment and at least one environment")
    for name, environment in environments.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name):
            raise ValueError(f"invalid remote environment name: {name!r}")
        if not isinstance(environment, dict) or environment.get("scheduler", "torque") != "torque":
            raise ValueError(f"remote environment {name!r} must use scheduler=torque")
        ssh_host = environment.get("ssh_host")
        if not isinstance(ssh_host, str):
            raise ValueError(f"remote environment {name!r} is missing ssh_host or remote_root")
        if any(character.isspace() for character in ssh_host):
            raise ValueError(f"remote environment {name!r} has an invalid ssh_host")
        remote_root = environment.get("remote_root")
        if not isinstance(remote_root, str):
            raise ValueError(f"remote environment {name!r} is missing ssh_host or remote_root")
        if (
            not remote_root.startswith("/")
            or remote_root == "/"
            or ".." in Path(remote_root).parts
            or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in Path(remote_root).parts[1:])
        ):
            raise ValueError(f"remote environment {name!r} has an invalid remote_root")
        queues = environment.get("allowed_queues")
        if not isinstance(queues, list) or not queues or any(
            not isinstance(queue, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", queue)
            for queue in queues
        ):
            raise ValueError(f"remote environment {name!r} must define allowed_queues")
        for key in ("max_nodes", "connect_timeout_seconds", "command_timeout_seconds"):
            value = environment.get(key, 1 if key == "max_nodes" else (15 if key == "connect_timeout_seconds" else 60))
            maximum = {"max_nodes": None, "connect_timeout_seconds": 300, "command_timeout_seconds": 3600}[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 1
                or (maximum is not None and value > maximum)
            ):
                raise ValueError(f"remote environment {name!r} has an invalid {key}")
        commands = environment.get("commands", {})
        if not isinstance(commands, dict):
            raise ValueError(f"remote environment {name!r} commands must be a table")
        for command_name in ("qsub", "qstat", "qdel", "pbsnodes"):
            command_value = commands.get(command_name, command_name)
            if (
                not isinstance(command_value, str)
                or not command_value
                or any(character.isspace() for character in command_value)
            ):
                raise ValueError(f"remote environment {name!r} has an invalid scheduler command: {command_name}")
        backends = environment.get("backends", {})
        if not isinstance(backends, dict):
            raise ValueError(f"remote environment {name!r} backends must be a table")
        for backend, item in backends.items():
            if not isinstance(backend, str) or not isinstance(item, dict):
                raise ValueError(f"remote environment {name!r} has an invalid backend binding")
            command = item.get("command")
            if not isinstance(command, list) or not command or any(not isinstance(value, str) or not value for value in command):
                raise ValueError(f"remote environment {name!r} backends.{backend} must define command")
            backend_queues = item.get("allowed_queues", queues)
            if not isinstance(backend_queues, list) or not backend_queues or any(
                not isinstance(queue, str) or queue not in queues for queue in backend_queues
            ):
                raise ValueError(f"remote environment {name!r} backends.{backend} has invalid allowed_queues")
            for path_key in ("activation_script", "scratch_root"):
                path_value = item.get(path_key)
                if path_value is not None and (
                    not isinstance(path_value, str)
                    or not path_value.startswith("/")
                    or path_value == "/"
                    or ".." in Path(path_value).parts
                    or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in Path(path_value).parts[1:])
                ):
                    raise ValueError(f"remote environment {name!r} backends.{backend}.{path_key} must be a safe absolute path")
        ssh_config = environment.get("ssh_config")
        if not isinstance(ssh_config, str) or not ssh_config:
            raise ValueError(f"remote environment {name!r} is missing ssh_config")
        ssh_path = Path(os.path.expandvars(os.path.expanduser(ssh_config)))
        if not ssh_path.is_absolute():
            raise ValueError(f"remote environment {name!r} ssh_config must be an absolute path")
        if ssh_path.is_symlink() or not ssh_path.is_file():
            raise ValueError(f"remote environment {name!r} ssh_config is not a regular file: {ssh_path}")


def _write_private_config_bytes(raw: bytes, destination: Path) -> None:
    root = destination.parent
    _ensure_private_directory(root)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=root)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return None


def configure_backend_configs(args: argparse.Namespace) -> dict[str, dict[str, str]]:
    root = Path(args.install_root).expanduser().resolve()
    result: dict[str, dict[str, str]] = {}
    compute_config = getattr(args, "compute_config", None)
    if compute_config:
        result["compute"] = _copy_private_config(
            compute_config,
            root / ".pi" / "compute.toml",
            kind="compute",
        )
        return result
    destination = root / ".pi" / "compute.toml"
    result["compute"] = {"status": "preserved" if destination.is_file() else "not_configured", "path": str(destination)}
    return result


def probe_remote_backend(args: argparse.Namespace, configs: dict[str, dict[str, str]]) -> None:
    if not args.probe_remote:
        return
    compute = configs.get("compute", {})
    if compute.get("status") == "not_configured":
        raise ValueError("--probe-remote requires an installed compute configuration with a remote environment")
    command = [str(Path(args.install_root) / "TSPi"), "--check-remote"]
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"remote environment readiness check failed: {detail or 'unknown error'}")


def run_logged_install(
    command: list[str],
    install_root: Path,
    *,
    show_progress: bool = True,
) -> dict[str, object]:
    install_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    pi_root = install_root / ".pi"
    log_root = pi_root / "logs"
    for directory in (pi_root, log_root):
        if directory.exists() or directory.is_symlink():
            if directory.is_symlink() or not directory.is_dir():
                raise RuntimeError(f"installer log path must be a physical directory: {directory}")
        else:
            directory.mkdir(mode=0o700)
        directory.chmod(0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".install-", suffix=".log", dir=log_root)
    os.chmod(temporary_name, 0o600)
    temporary = Path(temporary_name)
    stderr_lines: list[str] = []
    stdout = ""
    returncode = 1
    activity = Spinner("Starting the TSPi package installation", stream=sys.stderr, enabled=show_progress)
    activity.start()
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as log:
            log.write("TSPi installation diagnostic log\n")
            log.write(f"started_at_utc={datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}\n")
            log.write(f"command={shlex.join(command)}\n\n")
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
            )

            def relay_stderr() -> None:
                assert process.stderr is not None
                for line in process.stderr:
                    stderr_lines.append(line)
                    log.write(line)
                    log.flush()
                    if line.startswith(PROGRESS_PREFIX):
                        activity.update(line.removeprefix(PROGRESS_PREFIX).strip())

            relay = threading.Thread(target=relay_stderr, daemon=True)
            relay.start()
            assert process.stdout is not None
            try:
                stdout = process.stdout.read()
                returncode = process.wait()
            except BaseException:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                relay.join()
                raise
            else:
                relay.join()
            if stdout:
                log.write("\nstdout:\n")
                log.write(stdout)
            log.flush()
            os.fsync(log.fileno())
        if returncode == 0:
            try:
                result = json.loads(stdout)
            except json.JSONDecodeError as error:
                stderr_lines.append(f"installer returned invalid JSON: {error}\n")
            else:
                if not isinstance(result, dict):
                    stderr_lines.append("installer returned a non-object JSON result\n")
                else:
                    _append_log_file(_install_log_path(install_root), temporary)
                    temporary.unlink(missing_ok=True)
                    activity.succeed("TSPi package installed")
                    return result
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        failure_log = log_root / f"install-failure-{stamp}.log"
        _append_log_file(_install_log_path(install_root), temporary)
        os.replace(temporary, failure_log)
        details = [line.strip() for line in stderr_lines if line.strip() and not line.startswith(PROGRESS_PREFIX)]
        summary = details[-1] if details else f"installer process exited with status {returncode}"
        raise RuntimeError(f"{summary}\nDiagnostic log: {failure_log}")
    except BaseException:
        activity.fail("TSPi package installation failed")
        if temporary.exists():
            temporary.unlink()
        raise


def _install_log_path(install_root: Path, *, now: datetime | None = None) -> Path:
    """Return the owner-only, date-addressable installer log path."""

    root = install_root.expanduser().resolve()
    log_root = root / ".pi" / "logs"
    _ensure_private_directory(root / ".pi")
    _ensure_private_directory(log_root)
    current = now or datetime.now()
    return log_root / f"install.{current.strftime('%Y.%m.%d')}.log"


def _append_log_file(destination: Path, source: Path) -> None:
    """Append a temporary run log, separating repeated runs on one date."""

    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise RuntimeError(f"installer log path must be a physical file: {destination}")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination.parent.chmod(0o700)
    existed = destination.exists()
    with destination.open("ab" if existed else "wb") as output, source.open("rb") as input_file:
        if existed and destination.stat().st_size:
            output.write(
                f"\n===== install run {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')} =====\n".encode()
            )
        shutil.copyfileobj(input_file, output)
        output.flush()
        os.fsync(output.fileno())
    os.chmod(destination, 0o600)


def append_install_log(install_root: Path, *lines: str) -> Path:
    """Record final installer state without writing secret values."""

    path = _install_log_path(install_root)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".install-summary-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write("\n".join(lines).rstrip() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _append_log_file(path, temporary)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return path


def run_install(args: argparse.Namespace) -> dict[str, object]:
    command = [
        sys.executable,
        str(ROOT / "scripts/install_from_github.py"),
        "--repo",
        args.tspi_repo,
        "--ref",
        args.tspi_ref,
        "--install-root",
        args.install_root,
        "--progress",
        "--json",
    ]
    if args.tspi_commit:
        command.extend(["--resolved-commit", args.tspi_commit])
    if not args.with_web:
        command.append("--without-web")
    if args.conda_root:
        command.extend(["--conda-root", args.conda_root])
    return run_logged_install(command, Path(args.install_root), show_progress=not args.json)


def collect_deferred_link_enrollment(args: argparse.Namespace) -> None:
    """Collect a short-lived Relay code after the long install phase."""

    if not getattr(args, "_defer_link_enrollment", False):
        return
    if args.phone_access != "link":
        return
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError("a Host enrollment code is required after installation; use --link-enrollment-code with --non-interactive")
    note("Core installation is complete. Generate a fresh Host enrollment code now, then enter it below.", tone="accent")
    args.link_enrollment_code = ask("Host enrollment code").strip()
    if not args.link_enrollment_code:
        raise ValueError("Host enrollment code must not be empty")
    args._defer_link_enrollment = False


def configure_model_icons(args: argparse.Namespace, installed: dict[str, object]) -> dict[str, object]:
    package_root_value = installed.get("package_root")
    if not isinstance(package_root_value, str) or not package_root_value:
        raise RuntimeError("installed package did not report a package root for model icons")
    package_root = Path(package_root_value).expanduser().resolve()
    agent_root = package_root / "agent"
    if not agent_root.is_dir():
        # Keep this compatible with direct package fixtures and older package
        # wrappers that report the Agent root itself.
        agent_root = package_root
    font_home: Path | None = None
    if args.service_scope == "system" and args.service_user:
        try:
            font_home = Path(pwd.getpwnam(args.service_user).pw_dir)
        except KeyError as error:
            raise RuntimeError(f"service user does not exist for model icon font: {args.service_user}") from error
    return install_model_icon_font(
        agent_root,
        Path(args.install_root),
        enabled=bool(args.with_model_icons),
        font_home=font_home,
    )


def snapshot_active_release(root: Path) -> dict[str, object] | None:
    package_home = root / ".pi" / "packages" / "tspi"
    current = package_home / "current"
    state = package_home / "install-state.json"
    if not current.is_symlink() or not state.is_file():
        return None
    launchers = {name: os.readlink(root / name) for name in ("TSPi", "TSWeb") if (root / name).is_symlink()}
    state_bytes = state.read_bytes()
    runtime_manifest: tuple[str, bytes] | None = None
    try:
        state_object = json.loads(state_bytes.decode("utf-8"))
        manifest_path = state_object.get("runtime_manifest") if isinstance(state_object, dict) else None
        if isinstance(manifest_path, str) and Path(manifest_path).is_file():
            runtime_manifest = (manifest_path, Path(manifest_path).read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    model_icon_marker = root / ".pi/tspi/model-icons.json"
    marker_snapshot: bytes | None = None
    if model_icon_marker.is_file() and not model_icon_marker.is_symlink():
        marker_snapshot = model_icon_marker.read_bytes()
    return {
        "current": os.readlink(current),
        "state": state_bytes,
        "launchers": launchers,
        "runtime_manifest": runtime_manifest,
        "model_icon_marker": marker_snapshot,
    }


def _snapshot_file(path: Path) -> dict[str, object]:
    if path.is_symlink():
        return {"kind": "symlink", "target": os.readlink(path)}
    if path.is_file():
        return {
            "kind": "file",
            "content": path.read_bytes(),
            "mode": stat.S_IMODE(path.stat().st_mode),
        }
    if path.exists():
        raise RuntimeError(f"rollback target must be a regular file or absent: {path}")
    return {"kind": "absent"}


def snapshot_install_configuration(root: Path, args: argparse.Namespace) -> dict[str, object]:
    """Capture installer-owned configuration before any install side effect."""

    relative_paths = [
        "TSPi",
        "TSWeb",
        "uninstall.sh",
        ".pi/tspi/workspace-root.json",
        ".pi/tspi/service.json",
        ".pi/app-server-host/server-id",
        ".pi/app-server-host/link.json",
        ".pi/app-server-host/host.token",
        ".pi/ts-web/auth.token",
        ".pi/tspi/model-icons.json",
        ".pi/agent/models.json",
        ".pi/agent/auth.json",
        ".pi/notifications.toml",
        ".pi/email/service.env",
        ".pi/email/smtp-password",
        ".pi/compute.toml",
    ]
    paths = {str(root / relative): _snapshot_file(root / relative) for relative in relative_paths}
    external_password = getattr(args, "email_password_file", None)
    if isinstance(external_password, str):
        password_path = Path(external_password).expanduser()
        if password_path.is_absolute() and password_path != root / ".pi/email/smtp-password":
            paths[str(password_path)] = _snapshot_file(password_path)

    services: dict[str, object] = {}
    if getattr(args, "service_scope", "none") != "none":
        unit_dir = _service_unit_directory(args.service_scope)
        names = ["ts-app-server-tspi.service", "ts-web-tspi.service", "ts-app-server-tspi@.service"]
        for name in names:
            unit_path = unit_dir / name
            services[str(unit_path)] = {
                "file": _snapshot_file(unit_path),
                "status": _service_status(
                    [] if args.service_scope == "system" else ["--user"],
                    args.service_scope,
                    name,
                ),
            }
    releases_root = root / ".pi/packages/tspi/releases"
    release_ids = sorted(
        path.name
        for path in releases_root.iterdir()
        if path.is_dir() and not path.is_symlink()
    ) if releases_root.is_dir() and not releases_root.is_symlink() else []
    workspace_root = Path(args.workspace_root).expanduser().resolve()
    return {
        "files": paths,
        "services": services,
        "service_scope": getattr(args, "service_scope", "none"),
        "release_ids": release_ids,
        "workspace_root": {
            "path": str(workspace_root),
            "existed": workspace_root.exists(),
            "empty": workspace_root.is_dir() and not any(workspace_root.iterdir()),
        },
    }


def _restore_file(path: Path, snapshot: dict[str, object]) -> None:
    kind = snapshot.get("kind")
    if kind == "absent":
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.exists():
            raise RuntimeError(f"rollback target is no longer a regular file: {path}")
        return
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if kind == "symlink":
        target = snapshot.get("target")
        if not isinstance(target, str):
            raise RuntimeError(f"rollback symlink target is invalid: {path}")
        temporary = path.parent / f".{path.name}.rollback.{os.getpid()}"
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(target)
        os.replace(temporary, path)
        return
    if kind != "file" or not isinstance(snapshot.get("content"), bytes):
        raise RuntimeError(f"rollback file snapshot is invalid: {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.rollback.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        mode = snapshot.get("mode", 0o600)
        os.fchmod(descriptor, int(mode) if isinstance(mode, int) else 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(snapshot["content"])
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _make_tree_removable(path: Path) -> None:
    """Restore owner write permissions before removing a read-only release tree."""

    if path.is_symlink() or not path.exists():
        return

    def visit(item: Path) -> None:
        if item.is_symlink() or not item.is_dir():
            return
        mode = stat.S_IMODE(item.lstat().st_mode)
        os.chmod(item, mode | stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        for child in item.iterdir():
            visit(child)

    visit(path)


def restore_install_configuration(root: Path, snapshot: dict[str, object]) -> None:
    files = snapshot.get("files")
    if isinstance(files, dict):
        for raw_path, raw_snapshot in files.items():
            if isinstance(raw_path, str) and isinstance(raw_snapshot, dict):
                _restore_file(Path(raw_path), raw_snapshot)

    services = snapshot.get("services")
    if isinstance(services, dict) and services:
        for raw_path, raw_value in services.items():
            if isinstance(raw_path, str) and isinstance(raw_value, dict):
                file_snapshot = raw_value.get("file")
                if isinstance(file_snapshot, dict):
                    _restore_file(Path(raw_path), file_snapshot)
        service_scope = snapshot.get("service_scope")
        scope = [] if service_scope == "system" else ["--user"]
        # Restore the activation state captured before the transaction. A
        # systemd failure must not hide the original install error.
        try:
            _run_systemctl(scope, "daemon-reload")
            for raw_path, raw_value in services.items():
                if not isinstance(raw_path, str) or not isinstance(raw_value, dict):
                    continue
                status = raw_value.get("status")
                if not isinstance(status, dict):
                    continue
                name = Path(raw_path).name
                enabled = status.get("enabled")
                if enabled in {"enabled", "enabled-runtime"}:
                    _run_systemctl(scope, "enable", name)
                elif enabled in {"disabled", "masked"}:
                    _run_systemctl(scope, "disable", name)
                active = status.get("active")
                if active == "active":
                    _run_systemctl(scope, "restart", name)
                elif active in {"inactive", "failed"}:
                    _run_systemctl(scope, "stop", name)
        except RuntimeError:
            pass

    release_ids = snapshot.get("release_ids")
    releases_root = root / ".pi/packages/tspi/releases"
    if isinstance(release_ids, list) and releases_root.is_dir() and not releases_root.is_symlink():
        original = {item for item in release_ids if isinstance(item, str)}
        for path in releases_root.iterdir():
            if path.name in original or path.is_symlink() or not path.is_dir():
                continue
            _make_tree_removable(path)
            shutil.rmtree(path)

    workspace = snapshot.get("workspace_root")
    if isinstance(workspace, dict) and workspace.get("existed") is False:
        path_value = workspace.get("path")
        if isinstance(path_value, str):
            path = Path(path_value)
            if path.is_dir() and not path.is_symlink() and not any(path.iterdir()):
                path.rmdir()


def restore_active_release(root: Path, snapshot: dict[str, object] | None) -> None:
    if not snapshot:
        return
    package_home = root / ".pi" / "packages" / "tspi"
    current = package_home / "current"
    target = snapshot.get("current")
    if isinstance(target, str):
        temporary = package_home / f".current.rollback.{os.getpid()}"
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(target)
        os.replace(temporary, current)
    state = snapshot.get("state")
    if isinstance(state, bytes):
        descriptor, temporary_name = tempfile.mkstemp(prefix=".install-state.rollback.", dir=package_home)
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(state)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, package_home / "install-state.json")
        finally:
            if descriptor != -1:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
    launchers = snapshot.get("launchers")
    if isinstance(launchers, dict):
        for name, target in launchers.items():
            if not isinstance(name, str) or not isinstance(target, str):
                continue
            path = root / name
            temporary = root / f".{name}.rollback.{os.getpid()}"
            temporary.unlink(missing_ok=True)
            temporary.symlink_to(target)
            os.replace(temporary, path)
    runtime_manifest = snapshot.get("runtime_manifest")
    if isinstance(runtime_manifest, tuple) and len(runtime_manifest) == 2 and isinstance(runtime_manifest[0], str) and isinstance(runtime_manifest[1], bytes):
        manifest_path = Path(runtime_manifest[0])
        if manifest_path.parent.is_dir():
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".{manifest_path.name}.rollback.", dir=manifest_path.parent)
            temporary = Path(temporary_name)
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "wb") as handle:
                    descriptor = -1
                    handle.write(runtime_manifest[1])
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, manifest_path)
            finally:
                if descriptor != -1:
                    os.close(descriptor)
                temporary.unlink(missing_ok=True)
    marker_path = root / ".pi/tspi/model-icons.json"
    marker_snapshot = snapshot.get("model_icon_marker")
    if isinstance(marker_snapshot, bytes):
        marker_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{marker_path.name}.rollback.", dir=marker_path.parent)
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(marker_snapshot)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, marker_path)
        finally:
            if descriptor != -1:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
    elif marker_path.exists() or marker_path.is_symlink():
        marker_path.unlink()


def prepare_app_server_runtime(root: Path) -> Path:
    installer = root / ".pi/packages/tspi/current/agent/scripts/prepare_pi_source.py"
    if installer.is_symlink() or not installer.is_file():
        raise RuntimeError(f"installed App Server runtime installer is unavailable: {installer}")
    completed = subprocess.run(
        [sys.executable, str(installer), "--install", str(root)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"Pi App Server runtime installation failed: {detail}")
    # Prefer the pinned destination, which is deterministic even when npm or
    # git writes diagnostics after the helper's final stdout line.
    source: Path | None = None
    pin_path = root / ".pi/packages/tspi/current/agent/config/pi-source.json"
    try:
        pin = json.loads(pin_path.read_text(encoding="utf-8"))
        commit = pin.get("commit") if isinstance(pin, dict) else None
        if isinstance(commit, str) and commit:
            source = root / ".pi/runtime-cache/pi" / commit
    except (OSError, json.JSONDecodeError):
        pass
    if source is None or not source.is_dir():
        output_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        candidates = [Path(line) for line in reversed(output_lines)]
        source = next((candidate for candidate in candidates if candidate.is_absolute() and candidate.is_dir()), None)
    if source is None or not source.is_absolute() or not source.is_dir():
        raise RuntimeError("Pi App Server runtime installer returned an invalid source path")
    return source


def prepare_runtime_dirs(root: Path) -> None:
    for relative in (
        ".pi/runtime-cache",
        ".agents/runtime",
        ".agents/envs",
        ".pi/agent",
        ".pi/ts-web-state",
        ".pi/ts-web",
        ".pi/app-server-runtime",
        ".pi/app-server-host",
        ".pi/session-guards",
        ".pi/email",
    ):
        directory = root / relative
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise RuntimeError(f"runtime path must be a physical directory: {directory}")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
    ensure_host_identity(root)


def provision_pi_agent_configuration(args: argparse.Namespace) -> dict[str, object]:
    """Seed installation-local Pi state without replacing an existing setup."""

    root = Path(args.install_root).expanduser().resolve()
    service_user = (
        args.service_user
        if args.service_scope == "system"
        else pwd.getpwuid(os.getuid()).pw_name
    )
    account = pwd.getpwnam(service_user)
    source_dir = Path(account.pw_dir) / ".pi" / "agent"
    destination_dir = root / ".pi" / "agent"
    _ensure_private_directory(destination_dir)
    files: dict[str, str] = {}

    for name in PI_AGENT_CONFIG_FILES:
        destination = destination_dir / name
        if _preserve_pi_agent_configuration(destination):
            files[name] = "preserved"
            continue
        raw = _read_pi_agent_configuration(Path(account.pw_dir), name)
        if raw is None:
            files[name] = "not_configured"
            continue
        if _install_new_private_config_bytes(raw, destination):
            files[name] = "imported"
        elif _preserve_pi_agent_configuration(destination):
            # Another installer or the service won the create race. Never
            # replace configuration that appeared after our initial check.
            files[name] = "preserved"
        else:
            raise RuntimeError(f"Pi agent configuration changed while it was being installed: {destination}")

    configured = [status for status in files.values() if status != "not_configured"]
    if not configured:
        status = "not_configured"
    elif "imported" in configured:
        status = "imported"
    else:
        status = "preserved"
    return {
        "status": status,
        "directory": str(destination_dir),
        "source": str(source_dir),
        "files": files,
    }


def _pi_agent_open_flags(*, directory: bool = False) -> int:
    if not hasattr(os, "O_NOFOLLOW") or (directory and not hasattr(os, "O_DIRECTORY")):
        raise RuntimeError("secure Pi configuration import is unavailable on this platform")
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    return flags | (os.O_DIRECTORY if directory else 0)


def _read_pi_agent_configuration(home: Path, name: str) -> bytes | None:
    """Read a bounded source file without following a swapped path component."""

    source = home / ".pi" / "agent" / name
    descriptors: list[int] = []
    try:
        try:
            current = os.open(home, _pi_agent_open_flags(directory=True))
            descriptors.append(current)
            for component in (".pi", "agent"):
                current = os.open(component, _pi_agent_open_flags(directory=True), dir_fd=current)
                descriptors.append(current)
            descriptor = os.open(name, _pi_agent_open_flags(), dir_fd=current)
            descriptors.append(descriptor)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise RuntimeError(
                f"Pi agent configuration source must be a regular file in physical directories: {source}"
            ) from error

        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeError(f"Pi agent configuration source must be a regular file: {source}")
        if info.st_size > PI_AGENT_CONFIG_MAX_BYTES:
            raise RuntimeError(f"Pi agent configuration source is too large: {source}")
        chunks: list[bytes] = []
        size = 0
        while size <= PI_AGENT_CONFIG_MAX_BYTES:
            chunk = os.read(descriptor, min(64 * 1024, PI_AGENT_CONFIG_MAX_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > PI_AGENT_CONFIG_MAX_BYTES:
            raise RuntimeError(f"Pi agent configuration source is too large: {source}")
        return b"".join(chunks)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _preserve_pi_agent_configuration(destination: Path) -> bool:
    """Validate and chmod an existing destination through the opened inode."""

    try:
        descriptor = os.open(destination, _pi_agent_open_flags())
    except FileNotFoundError:
        return False
    except OSError as error:
        raise RuntimeError(f"Pi agent configuration must be a regular file: {destination}") from error
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError(f"Pi agent configuration must be a regular file: {destination}")
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)
    return True


def _install_new_private_config_bytes(raw: bytes, destination: Path) -> bool:
    """Atomically install a new file, without replacing a concurrent writer."""

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination, follow_symlinks=False)
        except FileExistsError:
            return False
        return True
    finally:
        if descriptor != -1:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def ensure_host_identity(root: Path) -> Path:
    state = root / ".pi" / "app-server-host"
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    state.chmod(0o700)
    identity = state / "server-id"
    if identity.is_symlink():
        raise RuntimeError(f"Host identity cannot be a symbolic link: {identity}")
    if identity.exists():
        value = identity.read_text(encoding="ascii").strip()
        if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", value):
            raise RuntimeError(f"Host identity is invalid: {identity}")
        if stat.S_IMODE(identity.stat().st_mode) != 0o600:
            identity.chmod(0o600)
        return identity
    descriptor, temporary_name = tempfile.mkstemp(prefix=".server-id.", dir=state)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            descriptor = -1
            handle.write(str(uuid.uuid4()) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, identity)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return identity


def configure_phone_connection(args: argparse.Namespace) -> dict[str, object]:
    """Enroll the installation Host and write its private TSPi Link files."""

    root = Path(args.install_root).resolve()
    state = root / ".pi/app-server-host"
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    state.chmod(0o700)
    manifest = state / "link.json"
    token_file = state / "host.token"
    if args.phone_access == "disabled":
        manifest.unlink(missing_ok=True)
        token_file.unlink(missing_ok=True)
        return {
            "status": "disabled",
            "manifest": str(manifest),
            "relay_url": None,
            "protocol": "tspi-link.v1",
            "tool_access": "same_as_terminal",
        }

    identity = ensure_host_identity(root)
    host_id = identity.read_text(encoding="ascii").strip()
    existing = _existing_link_configuration(root)
    if args.link_enrollment_code:
        enrollment = _redeem_link_enrollment(args.link_url, args.link_enrollment_code, host_id)
        if enrollment.get("hostId") != host_id or enrollment.get("protocol") != "tspi-link.v1":
            raise RuntimeError("TSPi Link Relay returned a mismatched Host enrollment")
        host_token = enrollment.get("hostToken")
        if not isinstance(host_token, str) or re.fullmatch(r"tsph_[A-Za-z0-9_-]{40,80}", host_token) is None:
            raise RuntimeError("TSPi Link Relay returned an invalid Host token")
        _write_private_text(token_file, host_token + "\n")
    elif not token_file.is_file() or existing is None or existing[0] != args.link_url:
        raise RuntimeError("a Host enrollment code is required for this TSPi Link Relay")

    payload = {
        "schema_version": "tspi-link/1",
        "protocol": "tspi-link.v1",
        "relay_url": args.link_url,
        "host_id": host_id,
    }
    _write_private_text(manifest, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return {
        "status": "configured",
        "manifest": str(manifest),
        "relay_url": args.link_url,
        "host_id": host_id,
        "protocol": "tspi-link.v1",
        "tool_access": "same_as_terminal",
    }


def _redeem_link_enrollment(relay_url: str, code: str, host_id: str) -> dict[str, object]:
    payload = json.dumps({"code": code, "hostId": host_id, "name": "TSPi Host"}, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        urllib.parse.urljoin(relay_url + "/", "v1/enrollments/redeem"),
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read(64 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read(16 * 1024)).get("message", exc.reason)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            detail = exc.reason
        raise RuntimeError(f"TSPi Link Relay rejected Host enrollment ({exc.code}): {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"could not reach TSPi Link Relay at {relay_url}: {exc}") from exc
    if len(raw) > 64 * 1024:
        raise RuntimeError("TSPi Link Relay enrollment response is too large")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("TSPi Link Relay returned invalid enrollment JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("TSPi Link Relay enrollment response must be an object")
    return value


def app_server_unit(args: argparse.Namespace) -> str:
    root = Path(args.install_root)
    workspace_root = Path(args.workspace_root)
    search_path = os.environ.get("PATH", os.defpath)
    if any(ord(char) < 32 for char in search_path):
        raise ValueError("service PATH cannot contain control characters")
    service_user = getattr(args, "service_user", None) or pwd.getpwuid(os.getuid()).pw_name
    service_home = Path(pwd.getpwnam(service_user).pw_dir)
    service_uid = pwd.getpwnam(service_user).pw_uid
    runtime_dir = f"/run/user/{service_uid}" if args.service_scope == "system" else (os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{service_uid}")
    if not Path(runtime_dir).is_absolute():
        raise ValueError("service XDG_RUNTIME_DIR must be an absolute path")
    # Host is an internal service entrypoint. Ordinary users manage this unit
    # through systemctl and never need to invoke the Host process directly.
    command = " ".join((_systemd_quote(root / "TSPi"), "--service-host"))
    wanted_by = "multi-user.target" if args.service_scope == "system" else "default.target"
    runtime_directory = "RuntimeDirectory=tspi\nRuntimeDirectoryMode=0700" if args.service_scope == "system" else ""
    return f"""[Unit]
Description=TSPi installation Host (all workspaces)
After=network-online.target

[Service]
Type=simple
WorkingDirectory={_systemd_value(root)}
ExecStart={command}
Environment={_systemd_quote('PATH=' + search_path)}
Environment={_systemd_quote('HOME=' + str(service_home))}
Environment={_systemd_quote('XDG_RUNTIME_DIR=' + runtime_dir)}
Environment={_systemd_quote('PI_CODING_AGENT_DIR=' + str(root / '.pi/agent'))}
Environment=TSPI_SYSTEMD_HOST=1
Environment={_systemd_quote('TSPI_WORKSPACE_ROOT=' + str(workspace_root))}
Environment={_systemd_quote('TSPI_APP_SERVER_RUNTIME_DIR=' + ('/run/tspi' if args.service_scope == 'system' else str(Path(runtime_dir) / 'tspi')))}
Environment=TSPI_SERVER_EXTENSIONS=tspi-server-tools
{f'User={_systemd_value(service_user)}' if args.service_scope == 'system' else ''}
{f'Group={_systemd_value(args.service_group)}' if getattr(args, 'service_group', None) and args.service_scope == 'system' else ''}
{_notification_environment_directive(args)}
{runtime_directory}
Restart=on-failure
RestartSec=3s
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadWritePaths={_systemd_quote(root / '.pi/runtime-cache')}
ReadWritePaths={_systemd_quote(root / '.pi/app-server-host')}
ReadWritePaths={_systemd_quote(Path('/run/tspi') if args.service_scope == 'system' else Path(runtime_dir) / 'tspi')}
ReadWritePaths={_systemd_quote(root / '.pi/session-guards')}
ReadWritePaths={_systemd_quote(root / '.pi/agent')}
ReadWritePaths={_systemd_quote(Path(runtime_dir) / 'tspi')}
ReadWritePaths={_systemd_quote(workspace_root)}

[Install]
WantedBy={wanted_by}
"""


def web_unit(args: argparse.Namespace) -> str:
    root = Path(args.install_root)
    workspace_root = Path(args.workspace_root)
    working_directory = _systemd_value(root)
    wanted_by = "multi-user.target" if args.service_scope == "system" else "default.target"
    command_values: list[object] = [
        root / "TSWeb",
        "--provider",
        root / ".pi/packages/tspi/current/agent/scripts/ts_web_provider.py",
        "serve",
        "--state-dir",
        root / ".pi/ts-web-state",
        "--auth-token-file",
            Path(args.web_auth_token_file).expanduser() if args.web_auth_token_file else root / ".pi/ts-web/auth.token",
        "--host",
        args.web_host,
    ]
    if args.allow_remote:
        command_values.append("--allow-remote")
    command_values.extend(("--port", str(args.web_port), "--workspace-root", workspace_root))
    command = " ".join(_systemd_quote(value) for value in command_values)
    return f"""[Unit]
Description=TSPi TS Web read-only server
After=network-online.target

[Service]
Type=simple
WorkingDirectory={working_directory}
ExecStart={command}
{f'User={_systemd_value(args.service_user)}' if args.service_scope == 'system' else ''}
{f'Group={_systemd_value(args.service_group)}' if getattr(args, 'service_group', None) and args.service_scope == 'system' else ''}
{f'Environment={_systemd_quote("HOME=" + str(pwd.getpwnam(args.service_user).pw_dir))}' if args.service_scope == 'system' else ''}
Restart=on-failure
RestartSec=3s
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadWritePaths={_systemd_quote(root / '.pi/ts-web-state')}
ReadWritePaths={_systemd_quote(root / '.pi/ts-web')}
ReadOnlyPaths={_systemd_quote(workspace_root)}

[Install]
WantedBy={wanted_by}
"""


def _notification_environment_directive(args: argparse.Namespace) -> str:
    root = Path(args.install_root)
    config = root / ".pi" / "notifications.toml"
    if not config.is_file():
        return ""
    try:
        raw = tomllib.loads(config.read_text(encoding="utf-8"))
        email = raw.get("notifications", {}).get("email", {})
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, AttributeError):
        return ""
    if isinstance(email, dict) and isinstance(email.get("password_env"), str):
        return f"EnvironmentFile=-{_systemd_value(root / '.pi/email/service.env')}"
    return ""


def _systemd_quote(value: object) -> str:
    escaped = _systemd_value(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _systemd_value(value: object) -> str:
    text = str(value)
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise ValueError("systemd values cannot contain control characters")
    return text.replace("%", "%%")


def _selected_service_names(args: argparse.Namespace) -> list[str]:
    names = ["ts-app-server-tspi.service"]
    if args.with_web:
        names.append("ts-web-tspi.service")
    return names


def _service_unit_directory(scope: str) -> Path:
    return Path("/etc/systemd/system") if scope == "system" else Path.home() / ".config/systemd/user"


def _service_working_directory(content: str) -> str | None:
    for line in content.splitlines():
        key, separator, raw_value = line.partition("=")
        if separator and key.strip() == "WorkingDirectory":
            value = raw_value.strip()
            if value.startswith('"'):
                try:
                    decoded = json.loads(value)
                except json.JSONDecodeError:
                    return None
                return decoded if isinstance(decoded, str) else None
            return value
    return None


def validate_service_ownership(args: argparse.Namespace) -> None:
    if args.service_scope == "none":
        return
    unit_dir = _service_unit_directory(args.service_scope)
    expected_root = str(Path(args.install_root)).replace("%", "%%")
    names = [*_selected_service_names(args)]
    if "ts-web-tspi.service" not in names:
        names.append("ts-web-tspi.service")
    names.append("ts-app-server-tspi@.service")
    for name in names:
        unit = unit_dir / name
        if unit.is_symlink():
            raise ValueError(f"service unit is a symbolic link: {unit}")
        if not unit.exists():
            continue
        if not unit.is_file():
            raise ValueError(f"service unit is not a regular file: {unit}")
        working_directory = _service_working_directory(unit.read_text(encoding="utf-8"))
        if working_directory != expected_root:
            owner = working_directory or "unknown"
            raise ValueError(
                f"service {name} belongs to another installation ({owner}): {unit}; "
                "uninstall that installation or remove the stale unit before retrying"
            )


def verify_service_units(args: argparse.Namespace, units: list[tuple[str, str]]) -> None:
    analyzer = shutil.which("systemd-analyze")
    if analyzer is None:
        raise RuntimeError("service configuration requires systemd-analyze to verify generated units")
    with tempfile.TemporaryDirectory(prefix="tspi-systemd-verify-") as temporary:
        unit_root = Path(temporary)
        unit_paths: list[Path] = []
        for name, content in units:
            path = unit_root / name
            path.write_text(content, encoding="utf-8")
            unit_paths.append(path)
        dependency_units = ["basic.target", "network-online.target"]
        if args.service_scope == "system":
            dependency_units.extend(["sysinit.target", "local-fs.target"])
        for name in dependency_units:
            (unit_root / name).write_text("[Unit]\nDescription=TSPi verification dependency\n", encoding="utf-8")
        environment = dict(os.environ)
        environment["SYSTEMD_UNIT_PATH"] = str(unit_root)
        if args.service_scope == "user" and not environment.get("XDG_RUNTIME_DIR"):
            runtime = unit_root / "runtime"
            runtime.mkdir(mode=0o700)
            environment["XDG_RUNTIME_DIR"] = str(runtime)
        scope = "--system" if args.service_scope == "system" else "--user"
        completed = subprocess.run(
            [analyzer, scope, "--man=no", "verify", *(str(path) for path in unit_paths)],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(f"generated systemd service validation failed: {detail}")


def configure_services(args: argparse.Namespace) -> list[dict[str, str]]:
    if args.service_scope == "none":
        return []
    validate_service_ownership(args)
    units: list[tuple[str, str]] = [
        ("ts-app-server-tspi.service", app_server_unit(args)),
    ]
    if args.with_web:
        units.append(("ts-web-tspi.service", web_unit(args)))
    prepare_runtime_dirs(Path(args.install_root))
    align_service_ownership(args)
    verify_service_units(args, units)
    unit_dir = _service_unit_directory(args.service_scope)
    unit_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
    names: list[str] = []
    scope = [] if args.service_scope == "system" else ["--user"]
    if not args.with_web:
        stale_web = unit_dir / "ts-web-tspi.service"
        if stale_web.exists() or stale_web.is_symlink():
            if stale_web.is_symlink() or not stale_web.is_file():
                raise ValueError(f"optional web service unit is not a regular file: {stale_web}")
            for action in ("stop", "disable"):
                _run_systemctl(scope, action, stale_web.name)
            stale_web.unlink()
    for name, content in units:
        (unit_dir / name).write_text(content, encoding="utf-8")
        (unit_dir / name).chmod(0o644)
        names.append(name)
    template_unit = unit_dir / "ts-app-server-tspi@.service"
    if template_unit.exists() or template_unit.is_symlink():
        if template_unit.is_symlink() or not template_unit.is_file():
            raise ValueError(f"template service unit is not a regular file: {template_unit}")
        # A template unit is not an invocable systemd unit. Stop every
        # concrete instance before removing it, otherwise an old per-workspace
        # Host can continue writing session state after the unified Host starts.
        scope = [] if args.service_scope == "system" else ["--user"]
        for instance in app_server_service_instances(scope):
            _run_systemctl(scope, "disable", "--now", instance)
        template_unit.unlink()
    _run_systemctl(scope, "daemon-reload")
    managed_names = names
    if args.enable_services:
        for name in managed_names:
            _run_systemctl(scope, "enable", name)
    if args.start_services:
        for name in managed_names:
            _run_systemctl(scope, "restart", name)
    services = [_service_status(scope, args.service_scope, name) for name in names]
    return services


def align_service_ownership(args: argparse.Namespace) -> None:
    """Make the private installation usable by the selected system service user."""
    if args.service_scope != "system":
        return
    root = Path(args.install_root)
    account = pwd.getpwnam(args.service_user)
    # Release stores are owner-only too, so state-only chown would leave the
    # service unable to traverse or execute the selected package.
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"installation root must be a physical directory: {root}")
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        os.chown(current_path, account.pw_uid, account.pw_gid)
        for name in [*directories, *files]:
            child = current_path / name
            if not child.is_symlink():
                os.chown(child, account.pw_uid, account.pw_gid)
    workspace_root = Path(args.workspace_root)
    if workspace_root.is_symlink() or not workspace_root.is_dir():
        raise ValueError(f"workspace root must be a physical directory: {workspace_root}")
    current = workspace_root.stat()
    if current.st_uid not in {account.pw_uid, os.getuid()}:
        raise ValueError(
            f"workspace root is owned by another account: {workspace_root}; "
            f"make it accessible to {args.service_user} before installing the system service"
        )
    os.chown(workspace_root, account.pw_uid, account.pw_gid)


def app_server_service_instances(scope: list[str]) -> list[str]:
    """Return loaded concrete instances of the retired per-workspace unit."""
    completed = subprocess.run(
        ["systemctl", *scope, "list-units", "--all", "--plain", "--no-legend", "ts-app-server-tspi@*.service"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        return []
    instances: list[str] = []
    for line in completed.stdout.splitlines():
        name = line.split(None, 1)[0] if line.strip() else ""
        if name.startswith("ts-app-server-tspi@") and name.endswith(".service") and "/" not in name:
            instances.append(name)
    return instances


def _run_systemctl(scope: list[str], *arguments: str) -> None:
    completed = subprocess.run(
        ["systemctl", *scope, *arguments],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        command = " ".join(("systemctl", *scope, *arguments))
        raise RuntimeError(f"{command} failed: {detail or f'exit status {completed.returncode}'}")


def _service_status(scope: list[str], scope_name: str, name: str) -> dict[str, str]:
    values: dict[str, str] = {"name": name, "scope": scope_name}
    for key, action in (("enabled", "is-enabled"), ("active", "is-active")):
        completed = subprocess.run(
            ["systemctl", *scope, action, name],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        values[key] = (completed.stdout or completed.stderr).strip() or "unknown"
    return values


def build_component_summary(
    args: argparse.Namespace,
    installed: dict[str, object],
    app_server_runtime: Path,
    services: list[dict[str, str]],
    credentials: dict[str, dict[str, str]],
    backend_configs: dict[str, dict[str, str]] | None = None,
    phone_connection: dict[str, object] | None = None,
    model_icons: dict[str, object] | None = None,
    model_configuration: dict[str, object] | None = None,
) -> dict[str, object]:
    root = Path(args.install_root)
    workspace_root = Path(args.workspace_root)
    runtime = (
        installed.get("runtime")
        if isinstance(installed.get("runtime"), dict)
        else {}
    )
    probe = runtime.get("runtime_probe") if isinstance(runtime.get("runtime_probe"), dict) else {}
    modules = probe.get("modules") if isinstance(probe.get("modules"), dict) else {}
    commands = probe.get("commands") if isinstance(probe.get("commands"), dict) else {}
    service_by_name = {item["name"]: item for item in services}
    server_id_path = root / ".pi/app-server-host/server-id"
    try:
        server_id = server_id_path.read_text(encoding="ascii").strip() if server_id_path.is_file() else None
    except (OSError, UnicodeDecodeError):
        server_id = None
    return {
        "agent": {
            "status": "ready",
            "launcher": str(root / "TSPi"),
        },
        "runtime": {
            "status": "ready",
            "environment": runtime.get("env_prefix"),
            "python": runtime.get("python_executable"),
            "manifest": runtime.get("manifest_path"),
        },
        "render": {
            "status": "ready",
            "xyzrender": commands.get("xyzrender"),
            "matplotlib": modules.get("matplotlib"),
        },
        "app_server": {
            "status": "configured" if args.service_scope == "none" else _service_readiness(service_by_name.get("ts-app-server-tspi.service"), probed=args.start_services),
            "runtime": str(app_server_runtime),
            "service": service_by_name.get("ts-app-server-tspi.service"),
            "server_id": str(server_id_path),
            "server_uuid": server_id,
            "server_id_path": str(server_id_path),
            "link_url": args.link_url if args.phone_access == "link" else "not configured",
            "workspace_root": str(workspace_root),
            "start": "systemctl "
            + ("" if args.service_scope == "system" else "--user ")
            + "start ts-app-server-tspi.service",
        },
        "phone": phone_connection or {
            "status": "disabled",
            "manifest": str(root / ".pi/app-server-host/link.json"),
            "relay_url": args.link_url,
            "protocol": "tspi-link.v1",
            "tool_access": "same_as_terminal",
        },
        "model_icons": model_icons or {
            "status": "disabled",
            "enabled": False,
            "config_path": str(root / ".pi/tspi/model-icons.json"),
        },
        "models": model_configuration or {
            "status": "not_configured",
            "directory": str(root / ".pi/agent"),
            "files": {},
        },
        "web": (
            {
                "status": "configured" if args.service_scope == "none" else _service_readiness(service_by_name.get("ts-web-tspi.service"), probed=args.start_services),
                "launcher": str(root / "TSWeb"),
                "url": f"http://{args.web_host}:{args.web_port}",
                "state_directory": str(root / ".pi/ts-web-state"),
                "workspace_root": str(workspace_root),
                "credential": credentials.get("web_http"),
                "service": service_by_name.get("ts-web-tspi.service"),
            }
            if args.with_web
            else None
        ),
        "compute": backend_configs.get("compute") if backend_configs else {
            "status": "preserved" if (root / ".pi/compute.toml").is_file() else "not_configured",
            "path": str(root / ".pi/compute.toml"),
        },
    }


def _service_readiness(service: object, *, probed: bool) -> str:
    if not isinstance(service, dict):
        return "not_probed"
    active = service.get("active")
    if active == "active":
        return "running"
    return "failed" if probed and active != "active" else "configured"


def show_installed_summary(
    args: argparse.Namespace,
    installed: dict[str, object],
    components: dict[str, object],
    credentials: dict[str, dict[str, str]],
) -> None:
    root = Path(args.install_root)
    section("Installation")
    field("Installation root", root, tone="accent")
    field("Release", installed.get("release_id") or "package")
    field("TSPi commit", installed.get("commit") or "unknown")
    field("Workspace root", args.workspace_root)
    field("Uninstaller", installed.get("uninstaller") or "not installed")
    field("Install log", _install_log_path(root))

    runtime = components["runtime"]
    render = components["render"]
    assert isinstance(runtime, dict) and isinstance(render, dict)
    section("Core")
    field("Agent", f"ready - {root / 'TSPi'}", tone="success")
    field(
        "Scientific runtime",
        f"ready - {runtime.get('environment') or 'verified'}",
        tone="success",
    )
    renderer = (
        render.get("xyzrender")
        if isinstance(render.get("xyzrender"), dict)
        else {}
    )
    matplotlib = (
        render.get("matplotlib")
        if isinstance(render.get("matplotlib"), dict)
        else {}
    )
    render_detail = renderer.get("path") or "xyzrender verified"
    if matplotlib.get("version"):
        render_detail = f"{render_detail}; Matplotlib {matplotlib['version']}"
    field("Molecular rendering", f"ready - {render_detail}", tone="success")
    model_icons = components.get("model_icons")
    if isinstance(model_icons, dict):
        icon_status = str(model_icons.get("status", "disabled"))
        icon_enabled = bool(model_icons.get("enabled"))
        icon_detail = model_icons.get("font_path") or model_icons.get("config_path") or "not configured"
        field(
            "Model icon font",
            f"{icon_status} - {icon_detail}",
            tone="success" if icon_enabled else "muted",
        )
    models = components.get("models")
    if isinstance(models, dict):
        model_status = str(models.get("status", "not_configured"))
        field(
            "Pi model configuration",
            f"{model_status} - {models.get('directory', root / '.pi/agent')}",
            tone="success" if model_status in {"imported", "preserved"} else "warning",
        )

    app_server = components["app_server"]
    assert isinstance(app_server, dict)
    section("Pi App Server")
    app_status = str(app_server.get("status", "not_probed"))
    field("Status", app_status, tone="success" if app_status in {"running", "configured"} else "warning")
    field("Runtime", app_server["runtime"])
    field("Manual start", app_server["start"])
    field("Server ID", app_server.get("server_uuid") or f"not initialized - {app_server['server_id_path']}")
    field("TSPi Link Relay", app_server.get("link_url", "not configured"))
    field("Workspace root", app_server["workspace_root"])
    _show_service(app_server.get("service"))
    note("One Host serves all workspaces below the workspace root. The terminal and TS Phone attach once and switch projects.")

    section("TS Web")
    web = components["web"]
    if not isinstance(web, dict):
        field("Status", "not installed", tone="muted")
    else:
        web_status = str(web.get("status", "not_probed"))
        field("Status", web_status, tone="success" if web_status in {"running", "configured"} else "warning")
        field("Launcher", web["launcher"])
        field("URL", web["url"])
        field("State directory", web["state_directory"])
        _show_service(web.get("service"))
        _show_credential("HTTP token", credentials["web_http"], reveal=True)

    note("TS Phone is a separate App Server client and is no longer installed as a local service.")
    note("Phone pairing uses a short-lived TSPi Link code; it is distinct from the TS Web HTTP token.")
    phone = components.get("phone")
    if isinstance(phone, dict):
        field("Phone connection manifest", phone.get("manifest", "not configured"))
        field("Phone tool access", phone.get("tool_access", "same_as_terminal"))
    if isinstance(web, dict):
        note("Token values are not printed. Read the owner-only TS Web token file when pairing a browser.")

    compute = components.get("compute")
    if isinstance(compute, dict):
        section("Compute backends")
        field("Unified config", compute.get("path", "not configured"))
        field("Status", compute.get("status", "not configured"), tone="success" if compute.get("status") in {"configured", "preserved"} else "warning")


def _show_service(value: object) -> None:
    if not isinstance(value, dict):
        field("Service", "not configured", tone="muted")
        return
    detail = (
        f"{value.get('name')} "
        f"({value.get('scope')}, {value.get('enabled')}, {value.get('active')})"
    )
    tone = "success" if value.get("active") == "active" else "warning"
    field("Service", detail, tone=tone)


def _show_credential(label: str, credential: dict[str, str], *, reveal: bool) -> None:
    path = credential["path"]
    field(label, f"{path} ({credential['status']}, mode {credential['mode']})")
    if reveal:
        field("Read token", shlex.join(["cat", "--", path]))


def _prepare_installation(args: argparse.Namespace, checks: list[dict[str, object]]) -> dict[str, str | None]:
    """Validate the selected configuration and describe the pending operation.

    This stage is intentionally read-only. Rollback snapshots and installation
    side effects are deferred until the user confirms the displayed plan.
    """

    validate_options(args)
    if not args.conda_root:
        require_preflight(checks)
    installation = inspect_installation(Path(args.install_root))
    validate_service_ownership(args)
    return installation


def _interactive_prepare_installation(
    args: argparse.Namespace,
    checks: list[dict[str, object]],
) -> tuple[argparse.Namespace, dict[str, str | None] | None]:
    """Keep the configuration menu open until the plan is accepted or quit."""

    while True:
        args = interactive_menu_options(args)
        if getattr(args, "_installer_cancelled", False):
            note("Installation cancelled. No changes were made.", tone="warning")
            return args, None
        try:
            installation = _prepare_installation(args, checks)
        except (OSError, RuntimeError, ValueError) as error:
            note(f"Configuration needs attention: {error}", tone="warning")
            note("Returning to the installer menu so you can correct it.", tone="muted")
            continue
        show_install_plan(args, installation)
        if args.yes or ask_yes_no("Proceed with installation", True):
            return args, installation
        note("No changes applied. Returning to installer menu.", tone="warning")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    previous_release: dict[str, object] | None = None
    previous_configuration: dict[str, object] | None = None
    installation_root: Path | None = None
    try:
        interactive = not args.non_interactive
        if interactive:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise RuntimeError("interactive installation requires a TTY; use --non-interactive")
            if os.environ.get("TSPI_INSTALL_BOOTSTRAPPED") != "1":
                title("TSPi Installer", "Configure a reproducible TSPi installation.")
        checks = collect_preflight()
        if interactive:
            show_preflight(checks, require_conda=False)
        require_preflight(checks, require_conda=False)
        if interactive:
            args, installation = _interactive_prepare_installation(args, checks)
            if installation is None:
                return 0
        else:
            installation = _prepare_installation(args, checks)

        installation_root = Path(args.install_root)
        previous_release = snapshot_active_release(installation_root)
        previous_configuration = snapshot_install_configuration(installation_root, args)
        install_uninstaller(Path(args.install_root), ROOT)
        installed = run_install(args)
        collect_deferred_link_enrollment(args)
        with Spinner("Finalizing installation", stream=sys.stderr, enabled=not args.json) as activity:
            activity.update("Importing Pi model configuration")
            model_configuration = provision_pi_agent_configuration(args)
            activity.update("Configuring the model icon font")
            model_icons = configure_model_icons(args, installed)
            activity.update("Configuring the workspace root")
            workspace_config = configure_workspace_root(args)
            activity.update("Recording the App Server service scope")
            service_config = configure_service_runtime(args)
            activity.update("Installing the Pi App Server runtime")
            app_server_runtime = prepare_app_server_runtime(Path(args.install_root))
            ensure_host_identity(Path(args.install_root))
            activity.update("Writing the Phone connection manifest")
            phone_connection = configure_phone_connection(args)
            activity.update("Provisioning service credentials")
            credentials = provision_service_credentials(
                Path(args.install_root),
                with_web=bool(args.with_web),
                web_token_path=Path(args.web_auth_token_file).expanduser() if args.web_auth_token_file else None,
                web_token_value=args.web_auth_token,
            )
            activity.update("Configuring email notifications")
            notifications = configure_notification_config(args)
            activity.update("Installing backend configuration")
            backend_configs = configure_backend_configs(args)
            activity.update("Checking the remote backend")
            probe_remote_backend(args, backend_configs)
            activity.update("Configuring services")
            services = configure_services(args)
            activity.update("Verifying the installed release")
            verified = inspect_installation(Path(args.install_root))
            activity.succeed("Installation finalized")
        components = build_component_summary(
            args,
            installed,
            app_server_runtime,
            services,
            credentials,
            backend_configs,
            phone_connection,
            model_icons,
            model_configuration,
        )
        if args.start_services:
            failed_services = [
                str(item.get("name"))
                for item in services
                if item.get("active") in {"failed", "inactive", "unknown"}
            ]
            if failed_services:
                raise RuntimeError("started services are not running: " + ", ".join(failed_services))
        result = {
            "ok": True,
            "operation": installation["operation"],
            "install_root": args.install_root,
            "release_id": installed.get("release_id"),
            "commit": installed.get("commit"),
            "provenance": installed.get("provenance"),
            "components": components,
            "uninstaller": installed.get("uninstaller"),
            "services": services,
            "credentials": credentials,
            "notifications": notifications,
            "backend_configs": backend_configs,
            "workspace_config": workspace_config,
            "service_config": service_config,
            "phone_connection": phone_connection,
            "model_icons": model_icons,
            "model_configuration": model_configuration,
            "verified_release": verified["release_id"],
            "install_log": str(_install_log_path(Path(args.install_root))),
        }
        append_install_log(
            Path(args.install_root),
            "TSPi installer final summary",
            f"completed_at_utc={datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}",
            f"operation={installation['operation']}",
            f"install_root={args.install_root}",
            f"workspace_root={args.workspace_root}",
            f"release_id={installed.get('release_id') or ''}",
            f"commit={installed.get('commit') or ''}",
            f"with_web={bool(args.with_web)}",
            f"service_scope={args.service_scope}",
            f"compute_config={backend_configs.get('compute', {}).get('status', 'not_configured')}",
            f"phone_manifest={phone_connection.get('manifest', '') if isinstance(phone_connection, dict) else ''}",
            f"model_icons={model_icons.get('status', 'unknown') if isinstance(model_icons, dict) else 'unknown'}",
            f"model_configuration={model_configuration.get('status', 'unknown') if isinstance(model_configuration, dict) else 'unknown'}",
            f"web_token_file={credentials.get('web_http', {}).get('path', '') if isinstance(credentials.get('web_http'), dict) else ''}",
            "status=success",
        )
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            success("Installation complete")
            show_installed_summary(args, installed, components, credentials)
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        if installation_root is not None and previous_release is not None:
            try:
                restore_active_release(installation_root, previous_release)
            except (OSError, RuntimeError, ValueError) as rollback_error:
                error = RuntimeError(f"{error}; release rollback failed: {rollback_error}")
        if installation_root is not None and previous_configuration is not None:
            try:
                restore_install_configuration(installation_root, previous_configuration)
            except (OSError, RuntimeError, ValueError) as rollback_error:
                error = RuntimeError(f"{error}; configuration rollback failed: {rollback_error}")
        if installation_root is not None:
            try:
                append_install_log(
                    installation_root,
                    "TSPi installer failure",
                    f"failed_at_utc={datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}",
                    f"install_root={installation_root}",
                    f"error={error}",
                    "status=failure",
                )
            except (OSError, RuntimeError, ValueError):
                pass
        failure(f"TSPi installation failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
