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
    parser.add_argument("--phone-root", help="Existing ts-phone checkout for server deployment.")
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
    args.tspi_ref = ask("TSPi Git tag or commit", args.tspi_ref)
    if not args.with_web and not args.without_web:
        args.with_web = ask_yes_no("Install TS Web", True)
    if not args.phone_root:
        args.phone_root = ask("Existing ts-phone checkout (blank to skip)", "")
    args.conda_root = args.conda_root or ask("Conda root (blank for auto-detect)", detect_conda_root())
    args.service_scope = args.service_scope or ("user" if ask_yes_no("Configure systemd user services", True) else "none")
    if args.service_scope != "none":
        args.enable_services = ask_yes_no("Enable services", True)
        args.start_services = ask_yes_no("Start services now", True)
        if args.with_web:
            args.web_service = ask_yes_no("Run TS Web as a service", False)
    return args


def validate_options(args: argparse.Namespace) -> None:
    if args.with_web and args.without_web:
        raise ValueError("--with-web and --without-web are mutually exclusive")
    if not args.install_root:
        raise ValueError("--install-root is required in non-interactive mode")
    root = Path(args.install_root).expanduser()
    if not root.is_absolute():
        raise ValueError("--install-root must be absolute")
    args.install_root = str(root)
    if args.phone_root:
        phone = Path(args.phone_root).expanduser().resolve()
        if not (phone / "services/server/dist/index.js").is_file():
            raise ValueError(f"ts-phone server build is missing: {phone}")
        args.phone_root = str(phone)
    args.service_scope = args.service_scope or "none"
    if args.start_services:
        args.enable_services = True
    if args.service_scope == "system" and os.geteuid() != 0:
        raise ValueError("system services require root; choose --service-scope user")


def run_install(args: argparse.Namespace) -> dict[str, object]:
    command = [sys.executable, str(ROOT / "scripts/install_from_github.py"), "--repo", args.tspi_repo,
               "--ref", args.tspi_ref, "--install-root", args.install_root, "--json"]
    command.append("--without-web" if args.without_web else "--with-web")
    if args.with_render:
        command.append("--with-render")
    if args.conda_root:
        command.extend(["--conda-root", args.conda_root])
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
    if not args.phone_root:
        return None
    root = Path(args.install_root)
    state = root / ".pi/ts-phone-state"
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    (root / "workspaces").mkdir(mode=0o700, exist_ok=True)
    values = {
        "TS_PHONE_HOST": "127.0.0.1",
        "TS_PHONE_PORT": "22113",
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
    write_private(config, "".join(f"{key}={value}\n" for key, value in values.items()))
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
    phone = Path(args.phone_root) if args.phone_root else root
    command = phone / "bin/ts-phone-server" if args.phone_root else root / "TSPhoneServer"
    state = root / ".pi/ts-phone-state"
    return f"""[Unit]
Description=TSPi TS Phone Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={phone}
EnvironmentFile={root / '.pi/ts-phone/server.env'}
ExecStart={command}
Restart=on-failure
RestartSec=3s
TimeoutStopSec=20s
KillMode=mixed
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadWritePaths={state}
ReadWritePaths={root / 'workspaces'}
ReadWritePaths={root / '.pi/runtime-cache'}
ReadWritePaths={root / '.pi/session-host'}
ReadWritePaths={root / '.agents/runtime'}
ReadWritePaths={root / '.agents/envs'}
ReadWritePaths=%h/.pi/agent

[Install]
WantedBy=default.target
"""


def web_unit(args: argparse.Namespace) -> str:
    root = Path(args.install_root)
    return f"""[Unit]
Description=TSPi TS Web read-only server
After=network-online.target

[Service]
Type=simple
WorkingDirectory={root}
ExecStart={root / 'TSWeb'} serve --state-dir {root / '.pi/ts-web-state'} --host 127.0.0.1 --port 8766 --provider {root / '.pi/packages/tspi/current/agent/scripts/ts_web_provider.py'} --workspace-root {root / 'workspaces'}
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
                  f"TS Phone: {args.phone_root or 'no'}\nServices: {args.service_scope}")
            if not ask_yes_no("Proceed", True):
                return 0
        installed = run_install(args)
        phone_config = configure_phone(args)
        services = configure_services(args, phone_config)
        result = {"ok": True, "install_root": args.install_root, "release_id": installed.get("release_id"),
                  "commit": installed.get("commit"), "provenance": installed.get("provenance"),
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
