#!/usr/bin/env python3
"""Install TSPi with one installation-owned configuration directory.

This is a thin, non-interactive front end over ``install_wizard.py``.  It is
intended for repeatable workstation installs: compute.toml, Pi model files,
SMTP credentials, Web settings, and the installation-owned Link Relay are
selected from one directory instead of being entered through several menus.
The Relay is installed locally by default when Phone access is enabled; pass
``--without-link-relay`` to reuse an externally managed Relay.
Secrets are copied into the private installation state before the wizard is
run and are never printed or embedded in release metadata.
"""

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
    from .link_relay_discovery import discover_link_relay
except ImportError:
    from link_relay_discovery import discover_link_relay


DEFAULT_INSTALL_ROOT = Path("/home/iaw/ResearchAgent")
DEFAULT_CONFIG_ROOT = Path("/home/iaw/DATA/tspi_install_config")
DEFAULT_RELAY_URL = "https://tsphone.iawnix.xyz"
RELAY_MARKER_NAME = "link-relay.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-root", default=str(DEFAULT_INSTALL_ROOT))
    parser.add_argument("--workspace-root")
    parser.add_argument("--config-dir", default=str(DEFAULT_CONFIG_ROOT))
    parser.add_argument("--source-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--tspi-repo", default="git@github.com:iawnix/TSPi.git")
    parser.add_argument("--tspi-ref", default=os.environ.get("TSPI_INSTALL_REF", "main"))
    parser.add_argument("--with-web", action="store_true", default=True)
    parser.add_argument("--without-web", action="store_false", dest="with_web")
    parser.add_argument("--web-host", default="127.0.0.1")
    parser.add_argument("--web-port", type=int, default=8766)
    parser.add_argument("--service-scope", choices=("none", "user", "system"), default="user")
    parser.add_argument("--link-relay-root")
    parser.add_argument("--relay-state-dir")
    parser.add_argument("--link-url", default=os.environ.get("TSPI_LINK_URL", DEFAULT_RELAY_URL))
    parser.add_argument("--link-enrollment-url", default=os.environ.get("TSPI_LINK_ENROLLMENT_URL"))
    parser.add_argument("--link-enrollment-code")
    parser.add_argument("--phone-access", choices=("auto", "disabled", "link"), default="auto")
    relay = parser.add_mutually_exclusive_group()
    relay.add_argument("--with-link-relay", dest="with_link_relay", action="store_true")
    relay.add_argument("--without-link-relay", dest="with_link_relay", action="store_false")
    parser.set_defaults(with_link_relay=None)
    parser.add_argument("--relay-listen", default="127.0.0.1")
    parser.add_argument("--relay-port", type=int, default=8788)
    parser.add_argument("--relay-service-scope", choices=("none", "user", "system"), default="user")
    parser.add_argument("--relay-service-user", default="tspi-link-relay")
    parser.add_argument("--relay-enable-services", action="store_true", default=True)
    parser.add_argument("--relay-no-enable-services", action="store_false", dest="relay_enable_services")
    parser.add_argument("--relay-start-services", action="store_true", default=True)
    parser.add_argument("--relay-no-start-services", action="store_false", dest="relay_start_services")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow a dirty source checkout for local installation.")
    parser.add_argument("--probe-remote", action="store_true")
    parser.add_argument("--no-start-services", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _regular_file(path: Path, label: str, *, private: bool = False) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file: {path}")
    if private and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError(f"{label} must be mode 0600: {path}")
    return path


def _copy_private(source: Path, destination: Path) -> None:
    _regular_file(source, "SMTP password", private=True)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination.parent.chmod(0o700)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        with source.open("rb") as src, temporary.open("wb") as dst:
            os.chmod(temporary, 0o600)
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _phone_options(args: argparse.Namespace) -> tuple[str, str | None, str | None]:
    if args.phone_access == "disabled":
        return "disabled", None, None
    relay = discover_link_relay(args.link_relay_root)
    url = args.link_url or (relay or {}).get("relay_url")
    if args.phone_access == "link" and not url:
        raise ValueError("--phone-access link requires --link-url or a discoverable Link Relay")
    if not url:
        return "disabled", None, None
    existing_manifest = Path(args.install_root).expanduser() / ".pi/app-server-host/link.json"
    existing_token = Path(args.install_root).expanduser() / ".pi/app-server-host/host.token"
    if not args.link_enrollment_code and not (existing_manifest.is_file() and existing_token.is_file()):
        raise ValueError(
            "Link Relay is enabled but no Host enrollment code was supplied; "
            "use --link-enrollment-code or install the Host for an existing link manifest"
        )
    return "link", url, args.link_relay_root or (relay or {}).get("root")


def _relay_requested(args: argparse.Namespace) -> bool:
    if args.with_link_relay is not None:
        return args.with_link_relay
    return args.phone_access != "disabled" and not args.link_enrollment_code


def _write_json_private(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            os.chmod(temporary, 0o600)
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _relay_paths(args: argparse.Namespace, install_root: Path) -> tuple[Path, Path]:
    relay_root = Path(args.link_relay_root).expanduser().resolve() if args.link_relay_root else install_root / ".pi/link-relay"
    state_root = Path(args.relay_state_dir).expanduser().resolve() if args.relay_state_dir else install_root / ".pi/link-relay-state"
    return relay_root, state_root


def _relay_install(args: argparse.Namespace, install_root: Path) -> tuple[dict[str, object], bool]:
    """Install/reuse a local Relay and return its JSON result and ownership."""
    relay_root, state_root = _relay_paths(args, install_root)
    discovered = discover_link_relay(relay_root)
    if discovered is not None:
        service_root = Path(discovered["service_root"])
        state_db = Path(discovered.get("state", str(state_root / "relay.db")))
        if state_db.name != "relay.db":
            state_db = state_db / "relay.db"
        completed = subprocess.run(
            ["node", str(service_root / "cli.mjs"), "enrollment", "create", "--state", str(state_db)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        enrollment = json.loads(completed.stdout)
        if not isinstance(enrollment, dict) or not isinstance(enrollment.get("code"), str):
            raise RuntimeError("existing Link Relay returned an invalid enrollment code")
        return {
            "ok": True,
            "service_root": str(service_root),
            "state_dir": str(state_db.parent),
            "public_url": discovered["relay_url"],
            "enrollment": enrollment,
            "reused": True,
        }, False

    relay_script = Path(__file__).with_name("install_link_relay.py")
    command = [
        sys.executable,
        str(relay_script),
        "--install-root", str(relay_root),
        "--state-dir", str(state_root),
        "--public-url", args.link_url,
        "--listen", args.relay_listen,
        "--port", str(args.relay_port),
        "--service-scope", args.relay_service_scope,
        "--service-user", args.relay_service_user,
        "--source-root", args.source_root,
        "--non-interactive", "--yes", "--json",
    ]
    if args.allow_dirty:
        command.append("--allow-dirty")
    if args.relay_enable_services and args.relay_service_scope != "none":
        command.append("--enable-services")
    if args.relay_start_services and args.relay_service_scope != "none":
        command.append("--start-services")
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "Link Relay installation failed")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Link Relay installer returned invalid JSON") from exc
    if not isinstance(result, dict) or not isinstance(result.get("enrollment"), dict):
        raise RuntimeError("Link Relay installer did not return enrollment metadata")
    _write_json_private(install_root / ".pi" / RELAY_MARKER_NAME, {
        "schema": "tspi-install-link-relay/1",
        "install_root": str(install_root),
        "relay_install_root": str(relay_root),
        "state_dir": str(state_root),
        "service_scope": args.relay_service_scope,
        "owned": True,
    })
    result["reused"] = False
    return result, True


def _rollback_relay(args: argparse.Namespace, relay_result: dict[str, object]) -> None:
    """Remove a Relay created by this install when Host setup fails."""
    relay_root = relay_result.get("service_root")
    state_dir = relay_result.get("state_dir")
    if not isinstance(relay_root, str) or not isinstance(state_dir, str):
        return
    root = Path(relay_root)
    if root.name == "service" and root.parent.name == "current":
        root = root.parent.parent
    command = [
        sys.executable,
        str(Path(__file__).with_name("uninstall_link_relay.py")),
        "--install-root", str(root),
        "--state-dir", state_dir,
        "--service-scope", args.relay_service_scope,
        "--purge-state", "--non-interactive", "--yes", "--json",
    ]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def build_command(args: argparse.Namespace, config: Path, install_root: Path) -> list[str]:
    compute = _regular_file(config / "compute.toml", "compute.toml")
    # The installer writes both files with mode 0600 in the destination.  A
    # source inventory may be readable by the owner group while it is being
    # staged; the source directory itself is still required to be physical.
    models = _regular_file(config / "models.json", "models.json")
    auth = _regular_file(config / "auth.json", "auth.json")
    password = _regular_file(config / "smtp-password", "smtp-password", private=True)
    if args.workspace_root:
        workspace = Path(args.workspace_root).expanduser().resolve()
    else:
        workspace = install_root / "workspaces"

    phone, link_url, relay_root = _phone_options(args)
    target_password = install_root / ".pi" / "email" / "smtp-password"
    _copy_private(password, target_password)

    command = [
        sys.executable,
        str(Path(__file__).with_name("install_wizard.py")),
        "--source-root",
        args.source_root,
        "--tspi-repo",
        args.tspi_repo,
        "--tspi-ref",
        args.tspi_ref,
        "--install-root",
        str(install_root),
        "--workspace-root",
        str(workspace),
        "--compute-config",
        str(compute),
        "--agent-config-dir",
        str(config),
        "--with-web" if args.with_web else "--without-web",
        "--web-host",
        args.web_host,
        "--web-port",
        str(args.web_port),
        "--service-scope",
        args.service_scope,
        "--email-binding",
        "smtp",
        "--email-preset",
        "qq",
        "--email-recipient",
        "iawhaha@163.com",
        "--email-address",
        "1558901061@qq.com",
        "--email-password-file",
        str(target_password),
        "--phone-access",
        phone,
        "--non-interactive",
        "--yes",
    ]
    if link_url:
        command.extend(["--link-url", link_url])
    if relay_root:
        command.extend(["--link-relay-root", relay_root])
    if args.link_enrollment_code:
        command.extend(["--link-enrollment-code", args.link_enrollment_code])
    if args.link_enrollment_url:
        command.extend(["--link-enrollment-url", args.link_enrollment_url])
    if args.probe_remote:
        command.append("--probe-remote")
    if not args.no_start_services:
        command.extend(["--enable-services", "--start-services"])
    if args.json:
        command.append("--json")
    # Validate the source files here so a failed wizard never writes a partial
    # Pi configuration from an unrelated home directory.
    _regular_file(models, "models.json")
    _regular_file(auth, "auth.json")
    return command


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    relay_result: dict[str, object] | None = None
    relay_owned = False
    try:
        config = Path(args.config_dir).expanduser().resolve()
        install_root = Path(args.install_root).expanduser().resolve()
        if config.is_symlink() or not config.is_dir():
            raise ValueError(f"configuration directory must be a physical directory: {config}")
        if _relay_requested(args):
            if args.phone_access == "disabled":
                raise ValueError("--with-link-relay requires --phone-access link or auto")
            relay_result, relay_owned = _relay_install(args, install_root)
            enrollment = relay_result.get("enrollment")
            if not isinstance(enrollment, dict) or not isinstance(enrollment.get("code"), str):
                raise RuntimeError("Link Relay did not return a Host enrollment code")
            args.link_enrollment_code = enrollment["code"]
            args.link_url = str(relay_result.get("public_url") or args.link_url)
            args.link_relay_root = str(relay_result.get("service_root", "")).removesuffix("/current/service")
            if not args.link_enrollment_url and args.relay_listen in {"127.0.0.1", "::1", "localhost"}:
                host = f"[{args.relay_listen}]" if ":" in args.relay_listen else args.relay_listen
                args.link_enrollment_url = f"http://{host}:{args.relay_port}"
        command = build_command(args, config, install_root)
        result = subprocess.run(command, check=False)
        if result.returncode != 0 and relay_owned:
            _rollback_relay(args, relay_result or {})
            marker = install_root / ".pi" / RELAY_MARKER_NAME
            marker.unlink(missing_ok=True)
        return result.returncode
    except (OSError, ValueError) as exc:
        if relay_owned and relay_result is not None:
            _rollback_relay(args, relay_result)
        print(f"configured TSPi installation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
