"""Lifecycle of the optional installation-owned Link Relay."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    from .link_relay_discovery import discover_link_relay
except ImportError:
    from link_relay_discovery import discover_link_relay

RELAY_MARKER_NAME = "link-relay.json"

def prepare(args: argparse.Namespace) -> None:
    if not args.with_link_relay:
        return
    if args.phone_access == "disabled":
        raise ValueError("--with-link-relay cannot be combined with --phone-access disabled")
    if not args.link_url:
        raise ValueError("--with-link-relay requires --link-url")
    try:
        from .install_link_relay import validate_public_url
    except ImportError:
        from install_link_relay import validate_public_url
    args.link_url = validate_public_url(args.link_url)
    if not 1 <= args.relay_port <= 65535:
        raise ValueError("--relay-port must be between 1 and 65535")
    if args.relay_service_scope == "none" or not args.relay_start_services:
        raise ValueError("an embedded Relay must start to enroll the Host; use install.sh relay for staging")
    args.phone_access = "link"
    args._defer_link_enrollment = True


def enroll_options(args: argparse.Namespace, result: dict[str, object]) -> None:
    if not result.get("host_enrollment_preserved"):
        enrollment = result.get("enrollment")
        if not isinstance(enrollment, dict) or not isinstance(enrollment.get("code"), str):
            raise RuntimeError("Link Relay did not return a Host enrollment code")
        args.link_enrollment_code = enrollment["code"]
    args.link_url = str(result["public_url"])
    if not result.get("reused") and not args.link_enrollment_url and args.relay_listen in {"127.0.0.1", "::1", "localhost"}:
        host = f"[{args.relay_listen}]" if ":" in args.relay_listen else args.relay_listen
        args.link_enrollment_url = f"http://{host}:{args.relay_port}"
    args._defer_link_enrollment = False


def validate(args: argparse.Namespace) -> None:
    if not args.with_link_relay:
        return
    try:
        from . import install_link_relay
    except ImportError:
        import install_link_relay
    relay_root, state_root = _relay_paths(args, Path(args.install_root))
    if discover_link_relay(relay_root) is not None:
        return
    options = install_link_relay.parse_args([
        "--install-root", str(relay_root), "--state-dir", str(state_root),
        "--public-url", args.link_url, "--listen", args.relay_listen,
        "--port", str(args.relay_port), "--service-scope", args.relay_service_scope,
        "--service-user", args.relay_service_user,
        "--source-root", args.source_root or str(Path(__file__).resolve().parents[1]),
    ])
    install_link_relay.validate_options(options)


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
    relay_root = Path(args.link_relay_root).expanduser().resolve() if args.link_relay_root else install_root / "runtimes/link-relay"
    state_root = Path(args.relay_state_dir).expanduser().resolve() if args.relay_state_dir else install_root / "var/state/link-relay"
    return relay_root, state_root


def install(args: argparse.Namespace, install_root: Path) -> tuple[dict[str, object], bool]:
    """Install/reuse a local Relay and return its JSON result and ownership."""
    relay_root, state_root = _relay_paths(args, install_root)
    discovered = discover_link_relay(relay_root)
    if discovered is not None:
        service_root = Path(discovered["service_root"])
        state_db = Path(discovered.get("state", str(state_root / "relay.db")))
        if state_db.name != "relay.db":
            state_db = state_db / "relay.db"
        try:
            from .install_wizard import _existing_link_configuration
        except ImportError:
            from install_wizard import _existing_link_configuration
        existing = _existing_link_configuration(install_root)
        token = install_root / "var/state/host/host.token"
        identity = install_root / "var/state/host/server-id"
        if (not args.link_enrollment_code and existing is not None
                and existing[0] == discovered["relay_url"]
                and token.is_file() and not token.is_symlink()
                and identity.is_file() and identity.read_text().strip() == existing[1]):
            return {
                "ok": True, "service_root": str(service_root), "state_dir": str(state_db.parent),
                "public_url": discovered["relay_url"], "reused": True, "host_enrollment_preserved": True,
            }, False
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
        "--source-root", args.source_root or str(Path(__file__).resolve().parents[1]),
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
    _write_json_private(install_root / "etc" / RELAY_MARKER_NAME, {
        "schema": "coragent-install-link-relay/1",
        "install_root": str(install_root),
        "relay_install_root": str(relay_root),
        "state_dir": str(state_root),
        "service_scope": args.relay_service_scope,
        "owned": True,
    })
    result["install_root"] = str(relay_root)
    result["reused"] = False
    return result, True


def rollback(args: argparse.Namespace, relay_result: dict[str, object]) -> None:
    """Remove a Relay created by this install when Host setup fails."""
    relay_root = relay_result.get("service_root")
    state_dir = relay_result.get("state_dir")
    if not isinstance(relay_root, str) or not isinstance(state_dir, str):
        return
    root = Path(relay_result["install_root"])
    command = [
        sys.executable,
        str(Path(__file__).with_name("uninstall_link_relay.py")),
        "--install-root", str(root),
        "--state-dir", state_dir,
        "--service-scope", args.relay_service_scope,
        "--purge-state", "--non-interactive", "--yes", "--json",
    ]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    (Path(args.install_root) / "etc" / RELAY_MARKER_NAME).unlink(missing_ok=True)
