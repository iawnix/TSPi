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
import threading
from datetime import datetime, timezone
from pathlib import Path

try:
    from ._credentials import provision_service_credentials
    from ._installation_metadata import read_installation_metadata
    from ._terminal_ui import Spinner, ask_text as ask, ask_yes_no, failure, field, note, section, success, title
    from .install_from_github import validate_ref, validate_repo
    from .install_phone import DEFAULT_PHONE_REPO, activate_phone, prepare_phone
    from .install_release import validate_install_root
except ImportError:
    from _credentials import provision_service_credentials
    from _installation_metadata import read_installation_metadata
    from _terminal_ui import Spinner, ask_text as ask, ask_yes_no, failure, field, note, section, success, title
    from install_from_github import validate_ref, validate_repo
    from install_phone import DEFAULT_PHONE_REPO, activate_phone, prepare_phone
    from install_release import validate_install_root


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "git@github.com:iawnix/TSPi.git"
PROGRESS_PREFIX = "@@tspi-progress@@"
MINIMUM_NODE_VERSION = (22, 19, 0)


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
    checks.append({"key": "npm", "label": "npm", "ok": npm_ok, "required": False, "detail": npm_version})

    conda = shutil.which("mamba") or shutil.which("conda")
    conda_ok, conda_version = _command_output([conda, "--version"]) if conda else (False, "not found")
    if not conda_ok:
        conda_version += " (needed when the managed base runtime must be created)"
    checks.append({"key": "conda", "label": "Conda/Mamba", "ok": conda_ok, "required": False, "detail": conda_version})
    return checks


def show_preflight(checks: list[dict[str, object]]) -> None:
    section("System check")
    for check in checks:
        tone = "success" if check["ok"] else ("danger" if check["required"] else "warning")
        state = "ready" if check["ok"] else "unavailable"
        field(str(check["label"]), f"{state} - {check['detail']}", tone=tone)


def require_preflight(checks: list[dict[str, object]], *, with_phone: bool = False) -> None:
    required = {"python", "git", "node"}
    if with_phone:
        required.add("npm")
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

    section("Source and destination")
    args.install_root = args.install_root or ask("Installation directory", str(Path.home() / ".local/share/tspi"))
    args.tspi_ref = ask("TSPi Git branch, tag, or commit", args.tspi_ref)
    field("Repository", args.tspi_repo)

    section("Components")
    if not args.with_web and not args.without_web:
        args.with_web = ask_yes_no("Install TS Web", True)
        args.without_web = not args.with_web
    if args.with_phone is None:
        args.with_phone = ask_yes_no("Install TS Phone for phone access and shared terminal sessions", True)
    if args.with_phone:
        args.phone_ref = ask("TS Phone Git branch, tag, or commit", args.phone_ref)
        if not (Path(args.install_root) / ".pi/ts-phone/server.env").exists():
            args.phone_port = int(ask("TS Phone port", str(args.phone_port)))
    if not args.with_render:
        args.with_render = ask_yes_no("Install molecular rendering support", False)

    section("Runtime and services")
    args.conda_root = args.conda_root or ask("Conda root (blank for auto-detect)", detect_conda_root())
    args.service_scope = args.service_scope or ("user" if ask_yes_no("Configure systemd user services", True) else "none")
    if args.service_scope != "none":
        args.enable_services = ask_yes_no("Enable services", True)
        args.start_services = ask_yes_no("Start services now", True)
        if args.with_web:
            args.web_service = ask_yes_no("Run TS Web as a service", False)
    return args


def show_install_plan(args: argparse.Namespace, installation: dict[str, str | None]) -> None:
    components = ["Agent"]
    if args.with_web and not args.without_web:
        components.append("Web")
    if args.with_phone:
        components.append("Phone")
    if args.with_render:
        components.append("Molecular rendering")
    service_details = args.service_scope
    if args.service_scope != "none":
        actions = []
        if args.enable_services:
            actions.append("enable")
        if args.start_services:
            actions.append("start")
        service_details += f" ({', '.join(actions)})" if actions else " (configure only)"

    section("Installation plan")
    operation = {"install": "Fresh install", "update": "Update existing installation", "restore": "Restore removed application"}[
        str(installation["operation"])
    ]
    field("Operation", operation, tone="accent")
    if installation["release_id"]:
        field("Current release", installation["release_id"])
    field("Installation root", args.install_root, tone="accent")
    field("TSPi revision", args.tspi_ref)
    field("Components", ", ".join(components), tone="success")
    field("Conda root", args.conda_root or "auto-detect")
    field("Services", service_details, tone="success" if args.service_scope != "none" else "muted")


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
    args.with_web = not args.without_web
    if not args.install_root:
        raise ValueError("--install-root is required in non-interactive mode")
    args.install_root = str(validate_install_root(Path(args.install_root)))
    if args.web_service and args.without_web:
        raise ValueError("--web-service requires TS Web")
    args.service_scope = args.service_scope or "none"
    if args.start_services:
        args.enable_services = True
    if args.service_scope == "system" and os.geteuid() != 0:
        raise ValueError("system services require root; choose --service-scope user")
    if args.service_scope != "none" and shutil.which("systemctl") is None:
        raise ValueError("service configuration requires systemctl; choose --service-scope none")


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
                    temporary.unlink()
                    try:
                        log_root.rmdir()
                    except OSError:
                        pass
                    activity.succeed("TSPi package installed")
                    return result
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        failure_log = log_root / f"install-failure-{stamp}.log"
        os.replace(temporary, failure_log)
        details = [line.strip() for line in stderr_lines if line.strip() and not line.startswith(PROGRESS_PREFIX)]
        summary = details[-1] if details else f"installer process exited with status {returncode}"
        raise RuntimeError(f"{summary}\nDiagnostic log: {failure_log}")
    except BaseException:
        activity.fail("TSPi package installation failed")
        if temporary.exists():
            temporary.unlink()
        raise


def run_install(args: argparse.Namespace, phone_release: Path | None = None) -> dict[str, object]:
    command = [sys.executable, str(ROOT / "scripts/install_from_github.py"), "--repo", args.tspi_repo,
               "--ref", args.tspi_ref, "--install-root", args.install_root, "--progress", "--json"]
    command.append("--without-web" if args.without_web else "--with-web")
    if args.with_render:
        command.append("--with-render")
    if args.conda_root:
        command.extend(["--conda-root", args.conda_root])
    if phone_release is not None:
        command.extend(["--phone-server-root", str(phone_release)])
    return run_logged_install(command, Path(args.install_root), show_progress=not args.json)


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
ExecStart={root / 'TSWeb'} --provider {root / '.pi/packages/tspi/current/agent/scripts/ts_web_provider.py'} serve --state-dir {root / '.pi/ts-web-state'} --auth-token-file {root / '.pi/ts-web/auth.token'} --host 127.0.0.1 --port 8766 --workspace-root {root / 'workspaces'}
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
        interactive = not args.non_interactive
        if interactive:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise RuntimeError("interactive installation requires a TTY; use --non-interactive")
            title("TSPi Installer", "Configure a reproducible TSPi installation.")
        checks = collect_preflight()
        if interactive:
            show_preflight(checks)
        require_preflight(checks)
        if not args.non_interactive:
            args = interactive_options(args)
        validate_options(args)
        require_preflight(checks, with_phone=bool(args.with_phone))
        installation = inspect_installation(Path(args.install_root))
        if not args.non_interactive:
            show_install_plan(args, installation)
            if not args.yes and not ask_yes_no("Proceed with installation", True):
                note("Installation cancelled.", tone="warning")
                return 0
        phone_release = None
        if args.with_phone:
            with Spinner("Preparing TS Phone", stream=sys.stderr, enabled=not args.json) as activity:
                phone_release = prepare_phone(
                    Path(args.install_root),
                    args.phone_repo,
                    args.phone_ref,
                    progress=activity.update,
                )
                activity.succeed("TS Phone release prepared")
        installed = run_install(args, phone_release)
        with Spinner("Finalizing installation", stream=sys.stderr, enabled=not args.json) as activity:
            phone = activate_phone(Path(args.install_root), phone_release) if phone_release is not None else None
            activity.update("Provisioning service credentials")
            credentials = provision_service_credentials(
                Path(args.install_root),
                with_phone=bool(args.with_phone),
                with_web=bool(args.with_web),
            )
            activity.update("Writing service configuration")
            phone_config = configure_phone(args)
            activity.update("Configuring services")
            services = configure_services(args, phone_config)
            activity.update("Verifying the installed release")
            verified = inspect_installation(Path(args.install_root))
            activity.succeed("Installation finalized")
        result = {"ok": True, "operation": installation["operation"], "install_root": args.install_root,
                  "release_id": installed.get("release_id"),
                  "commit": installed.get("commit"), "provenance": installed.get("provenance"),
                  "phone": phone, "uninstaller": installed.get("uninstaller"),
                  "phone_config": str(phone_config) if phone_config else None, "services": services,
                  "credentials": credentials,
                  "verified_release": verified["release_id"]}
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            success("Installation complete")
            section("Installed")
            field("Installation root", args.install_root, tone="accent")
            field("Release", installed.get("release_id") or "package")
            field("TSPi commit", installed.get("commit") or "unknown")
            if phone:
                field("TS Phone commit", phone.get("commit") or "unknown")
            for name, credential in credentials.items():
                label = {
                    "phone_http": "Phone HTTP token",
                    "phone_bridge": "Phone bridge secret",
                    "web_http": "Web HTTP token",
                }[name]
                field(label, f"{credential['path']} ({credential['status']})")
            field("Services", ", ".join(services) if services else "not configured")
            field("Uninstaller", installed.get("uninstaller") or "not installed")
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        failure(f"TSPi installation failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
