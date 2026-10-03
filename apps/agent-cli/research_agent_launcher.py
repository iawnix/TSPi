#!/usr/bin/env python3
"""Launch the installed Research Agent App Server.

 The launcher starts the installation-owned Pi SDK and TSPi Host. It loads one
 owner-only JSON configuration file, validates the installed Runtime binding,
 then replaces itself with Node so signals and exit status belong to the App
 Server process.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONFIG_RELATIVE = Path(".pi/research-agent/server.json")
CONFIG_SCHEMA = "research_agent_server/1"
NODE_SERVER = ROOT / "apps/app-server/server.mjs"


class LauncherError(ValueError):
    """A user-actionable Research Agent launcher configuration error."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-root", required=True, help=argparse.SUPPRESS)
    parser.add_argument(
        "--config",
        default=None,
        help="Research Agent JSON configuration (default: <install-root>/.pi/research-agent/server.json).",
    )
    parser.add_argument("--host", help="HTTP listen host override.")
    parser.add_argument("--port", type=int, help="HTTP listen port override.")
    parser.add_argument("--catalog-root", help="Workspace catalog root override.")
    parser.add_argument("--session-root", help="Durable session root override.")
    parser.add_argument(
        "--write-config",
        action="store_true",
        help="Write the server options to --config, then exit.",
    )
    parser.add_argument("arguments", nargs=argparse.REMAINDER, help="Arguments forwarded to the Node entrypoint after --.")
    return parser


def _load_config(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise LauncherError(
            f"Research Agent config is missing: {path}; create this file with --write-config"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LauncherError(f"Research Agent config is not valid JSON: {path}: {error}") from error
    if not isinstance(value, dict):
        raise LauncherError(f"Research Agent config must be a JSON object: {path}")
    schema = value.get("schema_version")
    if schema != CONFIG_SCHEMA:
        raise LauncherError(f"Research Agent config schema_version must be {CONFIG_SCHEMA!r}: {path}")
    retired = sorted(set(value) & {"runtime_module", "kernel_module", "runtime_options", "kernel_options"})
    if retired:
        raise LauncherError(
            "Research Agent config contains removed Runtime injection fields: " + ", ".join(retired)
        )
    return value


def _private_write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise LauncherError(f"Research Agent config destination is not a regular file: {path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _option_value(cli: object, config: dict[str, object], key: str) -> object:
    return cli if cli is not None else config.get(key)


def _build_environment(args: argparse.Namespace, config: dict[str, object], package_root: Path) -> dict[str, str]:
    environment = dict(os.environ)
    # Keep the installation identity explicit for the Node App Server and its
    # worker children.  The capability host uses this to resolve the
    # installation-owned `.pi/compute.toml` when a service manager does not
    # forward TS_COMPUTE_CONFIG.
    environment["TSPI_INSTALL_ROOT"] = str(Path(args.install_root).expanduser().resolve())
    # The App Server always uses the installation-owned Pi SDK. A caller may
    # not replace the Agent Runtime by injecting a module or source checkout.
    pin_path = package_root / "config" / "pi-source.json"
    try:
        pin = json.loads(pin_path.read_text(encoding="utf-8"))
        commit = pin.get("commit") if isinstance(pin, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LauncherError(f"cannot read installed Pi Runtime descriptor: {pin_path}") from error
    if not isinstance(commit, str) or not commit:
        raise LauncherError(f"installed Pi Runtime descriptor has no commit: {pin_path}")
    source = Path(args.install_root).resolve() / ".pi" / "runtime-cache" / "pi" / commit
    if not source.is_dir() or source.is_symlink():
        raise LauncherError(f"installed Pi Runtime is missing or invalid: {source}")
    configured_source = environment.get("TSPI_PI_RUNTIME_ROOT")
    if configured_source and Path(configured_source).expanduser().resolve() != source.resolve():
        raise LauncherError("TSPI_PI_RUNTIME_ROOT is installation-managed and cannot be overridden")
    environment["TSPI_PI_RUNTIME_ROOT"] = str(source)

    mappings = (
        ("host", "TSP_APP_SERVER_HOST"),
        ("port", "TSP_APP_SERVER_PORT"),
        ("catalog_root", "RESEARCH_AGENT_CATALOG_ROOT"),
        ("session_root", "RESEARCH_AGENT_SESSION_ROOT"),
    )
    for config_key, env_key in mappings:
        value = _option_value(getattr(args, config_key), config, config_key)
        if value is None:
            continue
        if config_key == "port":
            if not isinstance(value, int) or not 0 <= value <= 65535:
                raise LauncherError("port must be an integer between 0 and 65535")
            value = str(value)
        elif not isinstance(value, str) or not value.strip():
            raise LauncherError(f"{config_key} must be a non-empty string")
        environment[env_key] = str(value)
    return environment


def _config_from_args(args: argparse.Namespace) -> dict[str, object]:
    config: dict[str, object] = {"schema_version": CONFIG_SCHEMA}
    for key in (
        "host",
        "port",
        "catalog_root",
        "session_root",
    ):
        value = getattr(args, key)
        if value is not None:
            config[key] = value
    return config


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    package_root = ROOT.resolve()
    install_root = Path(args.install_root).expanduser().resolve()
    config_path = Path(args.config).expanduser().resolve() if args.config else install_root / CONFIG_RELATIVE
    try:
        if args.write_config:
            _private_write(config_path, _config_from_args(args))
            print(config_path)
            return 0
        config = _load_config(config_path) if config_path.exists() or config_path.is_symlink() else {}
        environment = _build_environment(args, config, package_root)
        if not NODE_SERVER.is_file():
            raise LauncherError(f"Research Agent App Server entrypoint is missing: {NODE_SERVER}")
        node = shutil.which("node")
        if not node:
            raise LauncherError("Node.js is required to start the Research Agent App Server")
        forwarded = list(args.arguments)
        if forwarded[:1] == ["--"]:
            forwarded.pop(0)
        os.execvpe(node, [node, str(NODE_SERVER), *forwarded], environment)
    except LauncherError as error:
        print(f"ResearchAgentServer: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"ResearchAgentServer: could not start Node App Server: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
