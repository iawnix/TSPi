#!/usr/bin/env python3
"""Install the standalone TSPi Link Relay service."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path


SERVICE_NAME = "tspi-link-relay.service"
DEFAULT_INSTALL_ROOT = Path("/opt/tspi-link-relay")
DEFAULT_STATE_ROOT = Path("/var/lib/tspi-link-relay")
SERVICE_USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-root", default=str(DEFAULT_INSTALL_ROOT))
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_ROOT))
    parser.add_argument("--public-url", help="HTTPS origin reachable by Hosts and Phones.")
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--service-scope", choices=("system", "user", "none"), default="system")
    parser.add_argument("--service-user", default="tspi-link-relay")
    parser.add_argument("--enable-services", action="store_true")
    parser.add_argument("--start-services", action="store_true")
    parser.add_argument("--source-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--allow-dirty", action="store_true", help="Allow a dirty checkout for local development only.")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--yes", action="store_true", help="Alias for --non-interactive when all options are supplied.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def validate_public_url(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError("--public-url must be a Link Relay origin")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ValueError("--public-url must be a Link Relay origin")
    try:
        parsed = urllib.parse.urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("--public-url must be a Link Relay origin") from exc
    loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
    if not parsed.hostname or (parsed.scheme != "https" and not (loopback and parsed.scheme == "http")):
        raise ValueError("--public-url must use HTTPS except on loopback")
    if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("--public-url must contain only scheme, host, and port")
    return value.rstrip("/")


def validate_options(args: argparse.Namespace) -> None:
    if args.yes:
        args.non_interactive = True
    if args.service_scope != "system":
        # /opt and /var/lib are appropriate for a system service, but should
        # not make a development or user-scoped install fail for permissions.
        if args.install_root == str(DEFAULT_INSTALL_ROOT):
            args.install_root = str(Path.home() / ".local/share/tspi-link-relay")
        if args.state_dir == str(DEFAULT_STATE_ROOT):
            args.state_dir = str(Path.home() / ".local/state/tspi-link-relay")
    args.install_root = str(Path(args.install_root).expanduser().resolve())
    args.state_dir = str(Path(args.state_dir).expanduser().resolve())
    args.source_root = str(Path(args.source_root).expanduser().resolve())
    args.public_url = validate_public_url(args.public_url or "")
    if not 1 <= args.port <= 65535:
        raise ValueError("--port must be between 1 and 65535")
    if (
        not args.listen
        or any(character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F for character in args.listen)
        or "/" in args.listen
    ):
        raise ValueError("--listen must be a host name or IP address")
    if not SERVICE_USER.fullmatch(args.service_user):
        raise ValueError("--service-user has an invalid account name")
    if args.service_scope == "none" and (args.enable_services or args.start_services):
        raise ValueError("service actions require --service-scope user or system")
    if args.start_services:
        args.enable_services = True
    if args.service_scope == "system" and os.geteuid() != 0:
        raise ValueError("system Relay service installation requires root; choose --service-scope user")
    if not (Path(args.source_root) / "services/tspi-link-relay/package.json").is_file():
        raise ValueError("source root does not contain services/tspi-link-relay")
    source_root = Path(args.source_root)
    install_root = Path(args.install_root)
    state_root = Path(args.state_dir)
    if install_root == source_root or source_root in install_root.parents:
        raise ValueError("--install-root cannot be inside the source checkout")
    if state_root == source_root or source_root in state_root.parents:
        raise ValueError("--state-dir cannot be inside the source checkout")
    if state_root == install_root or install_root in state_root.parents or state_root in install_root.parents:
        raise ValueError("--state-dir must be independent from --install-root")
    if args.service_scope != "none" and shutil.which("systemctl") is None:
        raise ValueError("service installation requires systemctl; choose --service-scope none")
    for command in ("node", "npm", "git"):
        if shutil.which(command) is None:
            raise ValueError(f"{command} is required to install TSPi Link Relay")


def ensure_service_user(name: str) -> pwd.struct_passwd:
    try:
        return pwd.getpwnam(name)
    except KeyError:
        useradd = shutil.which("useradd")
        if useradd is None:
            raise ValueError(f"service user does not exist and useradd is unavailable: {name}")
        subprocess.run(
            [useradd, "--system", "--home-dir", "/nonexistent", "--shell", "/usr/sbin/nologin", name],
            check=True,
        )
        try:
            return pwd.getpwnam(name)
        except KeyError as exc:
            raise RuntimeError(f"created service user cannot be resolved: {name}") from exc


def ensure_directory(path: Path, mode: int = 0o700) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError(f"path must be a physical directory: {path}")
    path.mkdir(mode=mode, parents=True, exist_ok=True)
    path.chmod(mode)


def install_release(args: argparse.Namespace) -> tuple[Path, str]:
    source = Path(args.source_root) / "services/tspi-link-relay"
    install_root = Path(args.install_root)
    ensure_directory(install_root, 0o755)
    releases = install_root / "releases"
    ensure_directory(releases, 0o755)
    commit = git_revision(Path(args.source_root), allow_dirty=args.allow_dirty)
    release = releases / commit
    if not release.exists():
        staging = Path(tempfile.mkdtemp(prefix=".install-", dir=releases))
        try:
            shutil.copytree(source, staging / "service")
            subprocess.run(
                ["npm", "ci", "--omit=dev", "--ignore-scripts"],
                cwd=staging / "service",
                check=True,
            )
            staging.chmod(0o755)
            os.replace(staging, release)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    current = install_root / "current"
    temporary = install_root / f".current.{os.getpid()}"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(Path("releases") / commit)
    os.replace(temporary, current)
    return current / "service", commit


def git_revision(source_root: Path, *, allow_dirty: bool) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "--verify", "HEAD"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        value = completed.stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("source root must be a Git checkout") from exc
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("source checkout did not provide a full commit SHA")
    if not allow_dirty:
        dirty = subprocess.run(
            ["git", "-C", str(source_root), "status", "--porcelain"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        ).stdout.strip()
        if dirty:
            raise ValueError("source checkout is dirty; commit changes or pass --allow-dirty for development")
    return value


def prepare_state(args: argparse.Namespace, account: pwd.struct_passwd | None) -> Path:
    state = Path(args.state_dir)
    ensure_directory(state)
    if account is not None and os.geteuid() == 0:
        os.chown(state, account.pw_uid, account.pw_gid)
    return state


def create_enrollment(service_root: Path, state: Path, account: pwd.struct_passwd | None) -> dict[str, object]:
    completed = subprocess.run(
        ["node", str(service_root / "cli.mjs"), "enrollment", "create", "--state", str(state / "relay.db")],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Link Relay enrollment command returned invalid JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get("code"), str):
        raise RuntimeError("Link Relay enrollment command returned an invalid code")
    if account is not None and os.geteuid() == 0:
        for path in (state, *state.iterdir()):
            os.chown(path, account.pw_uid, account.pw_gid)
    return value


def systemd_unit(
    args: argparse.Namespace,
    service_root: Path,
    state: Path,
    account: pwd.struct_passwd | None,
    node: str,
) -> str:
    service_user = account.pw_name if account is not None else None
    wanted_by = "multi-user.target" if args.service_scope == "system" else "default.target"
    user_line = f"User={service_user}\n" if args.service_scope == "system" and service_user else ""
    command = " ".join(
        (
            _systemd_quote(node),
            _systemd_quote(service_root / "cli.mjs"),
            "serve",
            "--state",
            _systemd_quote(state / "relay.db"),
            "--public-url",
            _systemd_quote(args.public_url),
            "--listen",
            _systemd_quote(args.listen),
            "--port",
            str(args.port),
        )
    )
    return f"""[Unit]
Description=TSPi Link Relay
After=network-online.target

[Service]
Type=simple
WorkingDirectory={_systemd_quote(service_root)}
ExecStart={command}
{user_line}Restart=on-failure
RestartSec=3s
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadWritePaths={_systemd_quote(state)}

[Install]
WantedBy={wanted_by}
"""


def _systemd_quote(value: str | Path) -> str:
    text = str(value)
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in text):
        raise ValueError("systemd paths and arguments cannot contain control characters")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def service_directory(scope: str) -> Path:
    if scope == "system":
        return Path("/etc/systemd/system")
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd/user"


def configure_service(args: argparse.Namespace, service_root: Path, state: Path, account: pwd.struct_passwd | None) -> dict[str, object] | None:
    if args.service_scope == "none":
        return None
    directory = service_directory(args.service_scope)
    ensure_directory(directory, 0o755)
    unit = directory / SERVICE_NAME
    node = shutil.which("node")
    if node is None:
        raise ValueError("node is required to configure the Link Relay service")
    unit.write_text(systemd_unit(args, service_root, state, account, node), encoding="utf-8")
    unit.chmod(0o644)
    scope = [] if args.service_scope == "system" else ["--user"]
    subprocess.run(["systemctl", *scope, "daemon-reload"], check=True)
    if args.enable_services:
        subprocess.run(["systemctl", *scope, "enable", SERVICE_NAME], check=True)
    if args.start_services:
        subprocess.run(["systemctl", *scope, "restart", SERVICE_NAME], check=True)
    return {"name": SERVICE_NAME, "scope": args.service_scope, "unit": str(unit)}


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def interactive_options(args: argparse.Namespace) -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError("interactive Link Relay installation requires a TTY")
    args.public_url = ask("TSPi Link Relay public URL", args.public_url or "")
    args.listen = ask("Listen address", args.listen)
    args.port = int(ask("Listen port", str(args.port)))
    args.install_root = ask("Installation directory", args.install_root)
    args.state_dir = ask("State directory", args.state_dir)
    args.enable_services = ask("Enable service", "y").lower() not in {"n", "no"}
    args.start_services = ask("Start service now", "y").lower() not in {"n", "no"}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if not args.non_interactive:
            interactive_options(args)
        validate_options(args)
        account = ensure_service_user(args.service_user) if args.service_scope == "system" else None
        if account is not None and account.pw_uid == 0:
            raise ValueError("TSPi Link Relay must not run as root")
        service_root, commit = install_release(args)
        state = prepare_state(args, account)
        enrollment = create_enrollment(service_root, state, account)
        service = configure_service(args, service_root, state, account)
        result = {
            "ok": True,
            "service": service,
            "service_root": str(service_root),
            "state_dir": str(state),
            "public_url": args.public_url,
            "commit": commit,
            "enrollment": enrollment,
        }
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else format_result(result))
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"TSPi Link Relay installation failed: {exc}", file=sys.stderr)
        return 1


def format_result(result: dict[str, object]) -> str:
    enrollment = result["enrollment"]
    code = enrollment.get("code") if isinstance(enrollment, dict) else None
    return (
        "TSPi Link Relay installed.\n"
        f"Public URL: {result['public_url']}\n"
        f"Host enrollment code: {code}\n"
        "Use this code once in the local TSPi installer."
    )


if __name__ == "__main__":
    raise SystemExit(main())
