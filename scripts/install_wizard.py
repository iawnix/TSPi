#!/usr/bin/env python3
"""Interactive installer and service configurator for a TSPi installation."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from .install_from_github import validate_ref, validate_repo
    from .install_phone import DEFAULT_PHONE_REPO, activate_phone, prepare_phone
except ImportError:
    from install_from_github import validate_ref, validate_repo
    from install_phone import DEFAULT_PHONE_REPO, activate_phone, prepare_phone


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "https://github.com/iawnix/TSPi.git"


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    marker = "Y/n" if default else "y/N"
    value = input(f"{prompt} [{marker}]: ").strip().lower()
    return default if not value else value in {"y", "yes"}


def detect_conda_root() -> str:
    configured = os.environ.get("CONDA_EXE")
    if configured:
        return str(Path(configured).expanduser().resolve().parent.parent)
    conda = shutil.which("conda")
    return str(Path(conda).resolve().parent.parent) if conda else ""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-root")
    parser.add_argument("--tspi-repo", default=DEFAULT_REPO)
    parser.add_argument("--tspi-ref", default=os.environ.get("TSPI_INSTALL_REF", "main"))
    phone = parser.add_mutually_exclusive_group()
    phone.add_argument("--with-phone", dest="with_phone", action="store_true", help="Fetch and build TS Phone from GitHub.")
    phone.add_argument("--without-phone", dest="with_phone", action="store_false", help="Skip TS Phone installation.")
    parser.set_defaults(with_phone=None)
    parser.add_argument("--phone-repo", default=DEFAULT_PHONE_REPO)
    parser.add_argument("--phone-ref", default="main", help="TS Phone branch, tag, or full commit SHA.")
    parser.add_argument("--phone-port", type=int, default=22113, help="Port for a new Phone configuration.")
    parser.add_argument("--with-web", action="store_true")
    parser.add_argument("--without-web", action="store_true")
    parser.add_argument("--with-render", action="store_true")
    parser.add_argument("--conda-root")
    parser.add_argument("--service-scope", choices=("none", "user", "system"))
    parser.add_argument("--enable-services", action="store_true")
    parser.add_argument("--start-services", action="store_true")
    parser.add_argument("--web-service", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def interactive_options(args: argparse.Namespace) -> argparse.Namespace:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError("interactive installation requires a TTY; use --non-interactive")
    print("TSPi Installer\n==============")
    args.install_root = args.install_root or ask("Installation directory", str(Path.home() / ".local/share/tspi"))
    args.tspi_ref = ask("TSPi Git branch, tag, or commit", args.tspi_ref)
    if not args.with_web and not args.without_web:
        args.with_web = ask_yes_no("Install TS Web", True)
        args.without_web = not args.with_web
    if args.with_phone is None:
        args.with_phone = ask_yes_no("Install TS Phone for phone access and shared terminal sessions", True)
    if args.with_phone:
        args.phone_ref = ask("TS Phone Git branch, tag, or commit", args.phone_ref)
        if not (Path(args.install_root) / ".pi/ts-phone/server.env").exists():
            args.phone_port = int(ask("TS Phone port", str(args.phone_port)))
    args.conda_root = args.conda_root or ask("Conda root (blank for auto-detect)", detect_conda_root())
    args.service_scope = args.service_scope or ("user" if ask_yes_no("Configure systemd user services", True) else "none")
    if args.service_scope != "none":
        args.enable_services = ask_yes_no("Enable services", True)
        args.start_services = ask_yes_no("Start services now", True)
        if args.with_web:
            args.web_service = ask_yes_no("Run TS Web as a service", False)
    return args


def validate_options(args: argparse.Namespace) -> None:
    validate_repo(args.tspi_repo)
    validate_ref(args.tspi_ref)
    if args.with_phone:
        validate_repo(args.phone_repo)
        validate_ref(args.phone_ref)
        if not 1 <= args.phone_port <= 65535:
            raise ValueError("--phone-port must be between 1 and 65535")
    if args.with_web and args.without_web:
        raise ValueError("--with-web and --without-web are mutually exclusive")
    if not args.install_root:
        raise ValueError("--install-root is required in non-interactive mode")
    root = Path(args.install_root).expanduser()
    if not root.is_absolute():
        raise ValueError("--install-root must be absolute")
    if root.resolve() in {Path("/"), Path.home(), Path.home().parent}:
        raise ValueError("--install-root must name a dedicated installation directory")
    if any(ord(char) < 32 or char in {'"', "\\"} for char in str(root)):
        raise ValueError("--install-root cannot contain control characters, double quotes, or backslashes")
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise ValueError("--install-root must use a physical directory path")
    args.install_root = str(root.resolve())
    if args.web_service and args.without_web:
        raise ValueError("--web-service requires TS Web")
    args.service_scope = args.service_scope or "none"
    if args.start_services:
        args.enable_services = True
    if args.service_scope == "system" and os.geteuid() != 0:
        raise ValueError("system services require root; choose --service-scope user")


def run_install(args: argparse.Namespace, phone_release: Path | None = None) -> dict[str, object]:
    print(f"TSPi: building and installing {args.tspi_ref}", file=sys.stderr, flush=True)
    command = [sys.executable, str(ROOT / "scripts/install_from_github.py"), "--repo", args.tspi_repo,
               "--ref", args.tspi_ref, "--install-root", args.install_root, "--json"]
    command.append("--without-web" if args.without_web else "--with-web")
    if args.with_render:
        command.append("--with-render")
    if args.conda_root:
        command.extend(["--conda-root", args.conda_root])
    if phone_release is not None:
        command.extend(["--phone-server-root", str(phone_release)])
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "TSPi installation failed")
    return json.loads(completed.stdout)


def write_private(path: Path, content: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"refusing to replace unsafe file: {path}")
        path.chmod(0o600)
        return
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def configure_phone(args: argparse.Namespace) -> Path | None:
    if not args.with_phone:
        return None
    root = Path(args.install_root)
    state = root / ".pi/ts-phone-state"
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    (root / "workspaces").mkdir(mode=0o700, exist_ok=True)
    values = {
        "TS_PHONE_HOST": "127.0.0.1",
        "TS_PHONE_PORT": str(args.phone_port),
        "TS_PHONE_TSPI": root / "TSPi",
        "TS_PHONE_WORKSPACES": root / "workspaces",
        "TS_PHONE_STATE_DIR": state,
        "TS_PHONE_BRIDGE_SOCKET": state / "bridge.sock",
        "TS_PHONE_BRIDGE_SECRET_FILE": state / "bridge.secret",
        "TS_PHONE_COMMAND_TIMEOUT_MS": "30000",
        "TS_PHONE_SHUTDOWN_TIMEOUT_MS": "10000",
        "TS_PHONE_BRIDGE_HEARTBEAT_TIMEOUT_MS": "45000",
        "TS_PHONE_BRIDGE_MAX_RECORD_BYTES": "8388608",
        "TS_PHONE_MAX_BODY_BYTES": "131072",
        "TS_PHONE_EVENT_JOURNAL_SIZE": "1000",
        "TS_PHONE_EVENT_JOURNAL_MAX_BYTES": "33554432",
    }
    config = root / ".pi/ts-phone/server.env"
    write_private(config, "".join(f"{key}={json.dumps(str(value), ensure_ascii=False)}\n" for key, value in values.items()))
    return config


def prepare_runtime_dirs(root: Path) -> None:
    for relative in (
        ".pi/runtime-cache",
        ".pi/session-host",
        ".agents/runtime",
        ".agents/envs",
        ".pi/ts-web-state",
    ):
        directory = root / relative
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)


def phone_unit(args: argparse.Namespace) -> str:
    root = Path(args.install_root)
    renderer = (root / ".pi/packages/tspi/current/agent/apps/host/service.mjs").resolve()
    result = subprocess.run([shutil.which("node") or "node", str(renderer), "--install-root", str(root)],
                            text=True, capture_output=True, check=True)
    if "[Service]\n" not in result.stdout or "ExecStart=" not in result.stdout:
        raise RuntimeError("Phone service renderer did not produce a service unit")
    search_path = os.environ.get("PATH", os.defpath)
    if any(ord(char) < 32 for char in search_path):
        raise ValueError("PATH cannot contain control characters")
    environment = json.dumps("PATH=" + search_path.replace("%", "%%"), ensure_ascii=False)
    return result.stdout.replace("[Service]\n", f"[Service]\nEnvironment={environment}\n", 1)


def web_unit(args: argparse.Namespace) -> str:
    root = Path(args.install_root)
    return f"""[Unit]
Description=TSPi TS Web read-only server
After=network-online.target

[Service]
Type=simple
WorkingDirectory={root}
ExecStart={root / 'TSWeb'} --provider {root / '.pi/packages/tspi/current/agent/scripts/ts_web_provider.py'} serve --state-dir {root / '.pi/ts-web-state'} --host 127.0.0.1 --port 8766 --workspace-root {root / 'workspaces'}
Restart=on-failure
RestartSec=3s
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadWritePaths={root / '.pi/ts-web-state'}
ReadWritePaths={root / 'workspaces'}

[Install]
WantedBy=default.target
"""


def configure_services(args: argparse.Namespace, phone_config: Path | None) -> list[str]:
    if args.service_scope == "none":
        return []
    units: list[tuple[str, str]] = []
    if phone_config:
        units.append(("ts-phone-tspi.service", phone_unit(args)))
    if args.web_service:
        units.append(("ts-web-tspi.service", web_unit(args)))
    if not units:
        return []
    prepare_runtime_dirs(Path(args.install_root))
    unit_dir = Path("/etc/systemd/system") if args.service_scope == "system" else Path.home() / ".config/systemd/user"
    unit_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
    names: list[str] = []
    scope = [] if args.service_scope == "system" else ["--user"]
    for name, _ in units:
        unit = unit_dir / name
        if unit.is_symlink():
            raise ValueError(f"service unit is a symbolic link: {unit}")
        if unit.exists():
            existing = unit.read_text(encoding="utf-8")
            root = str(Path(args.install_root)).replace("%", "%%")
            bindings = dict(line.split("=", 1) for line in existing.splitlines() if "=" in line)
            same_root = bindings.get("WorkingDirectory", "").strip('"') == root
            same_config = bindings.get("EnvironmentFile", "").strip('"') == f"{root}/.pi/ts-phone/server.env"
            if not same_root and not same_config:
                raise ValueError(f"service {name} belongs to another installation: {unit}")
    for name, content in units:
        (unit_dir / name).write_text(content, encoding="utf-8")
        (unit_dir / name).chmod(0o644)
        names.append(name)
    subprocess.run(["systemctl", *scope, "daemon-reload"], check=True)
    if args.enable_services:
        for name in names:
            subprocess.run(["systemctl", *scope, "enable", name], check=True)
    if args.start_services:
        for name in names:
            subprocess.run(["systemctl", *scope, "restart", name], check=True)
    return names


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if not args.non_interactive:
            args = interactive_options(args)
        validate_options(args)
        if not args.yes and not args.non_interactive:
            print(f"\nInstallation: {args.install_root}\nTSPi ref: {args.tspi_ref}\n"
                  f"TS Web: {'yes' if args.with_web and not args.without_web else 'no'}\n"
                  f"TS Phone: {args.phone_ref if args.with_phone else 'no'}\nServices: {args.service_scope}")
            if not ask_yes_no("Proceed", True):
                return 0
        phone_release = prepare_phone(Path(args.install_root), args.phone_repo, args.phone_ref) if args.with_phone else None
        installed = run_install(args, phone_release)
        phone = activate_phone(Path(args.install_root), phone_release) if phone_release is not None else None
        phone_config = configure_phone(args)
        services = configure_services(args, phone_config)
        result = {"ok": True, "install_root": args.install_root, "release_id": installed.get("release_id"),
                  "commit": installed.get("commit"), "provenance": installed.get("provenance"),
                  "phone": phone, "uninstaller": installed.get("uninstaller"),
                  "phone_config": str(phone_config) if phone_config else None, "services": services}
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("\nInstallation complete")
            for key, value in result.items():
                if value is not None:
                    print(f"{key}: {value}")
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"TSPi installer failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
