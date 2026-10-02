#!/usr/bin/env python3
"""Launch the installed Research Agent App Server.

The launcher is deliberately separate from the legacy ``TSPi`` Host.  It
loads one owner-only JSON configuration file, validates the module boundary,
then replaces itself with Node so signals and exit status belong to the App
Server process.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[2]
CONFIG_RELATIVE = Path(".pi/research-agent/server.json")
CONFIG_SCHEMA = "research_agent_server/1"
NODE_SERVER = ROOT / "apps/research-agent-app-server/server.mjs"


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
    parser.add_argument("--runtime-module", help="Module exporting create_runtime().")
    parser.add_argument("--kernel-module", help="Optional module exporting create_kernel().")
    parser.add_argument("--host", help="HTTP listen host override.")
    parser.add_argument("--port", type=int, help="HTTP listen port override.")
    parser.add_argument("--catalog-root", help="Workspace catalog root override.")
    parser.add_argument("--session-root", help="Durable session root override.")
    parser.add_argument("--runtime-options", help="Opaque runtime options passed to create_runtime().")
    parser.add_argument("--kernel-options", help="Opaque kernel options passed to create_kernel().")
    parser.add_argument(
        "--write-config",
        action="store_true",
        help="Write the supplied module and server options to --config, then exit.",
    )
    parser.add_argument("arguments", nargs=argparse.REMAINDER, help="Arguments forwarded to the Node entrypoint after --.")
    return parser


def _module_specifier(value: object, *, field: str, package_root: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LauncherError(f"{field} must be a non-empty module path or package specifier")
    value = value.strip()
    if value.startswith("file:"):
        return value
    # Bare package names are resolved by Node's normal module resolver.  Paths
    # are converted to file URLs so spaces and platform-specific characters do
    # not change import semantics.
    if value.startswith(".") or value.startswith("/"):
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = package_root / path
        path = path.resolve()
        if not path.is_file() or path.is_symlink():
            raise LauncherError(f"{field} does not name a regular module file: {path}")
        return "file://" + quote(str(path))
    return value


def _load_config(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise LauncherError(
            f"Research Agent config is missing: {path}; provide --runtime-module or create this file with --write-config"
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
    runtime = _option_value(args.runtime_module, config, "runtime_module")
    environment = dict(os.environ)
    # Keep the installation identity explicit for the Node App Server and its
    # worker children.  The capability host uses this to resolve the
    # installation-owned `.pi/compute.toml` when a service manager does not
    # forward TS_COMPUTE_CONFIG.
    environment["TSPI_INSTALL_ROOT"] = str(Path(args.install_root).expanduser().resolve())
    if runtime is None and not environment.get("RESEARCH_AGENT_RUNTIME_MODULE"):
        raise LauncherError(
            "runtime_module is required; configure --runtime-module, RESEARCH_AGENT_RUNTIME_MODULE, or the server JSON file"
        )
    if runtime is not None:
        environment["RESEARCH_AGENT_RUNTIME_MODULE"] = _module_specifier(
            runtime, field="runtime_module", package_root=package_root
        )

    kernel = _option_value(args.kernel_module, config, "kernel_module")
    if kernel is not None:
        environment["RESEARCH_AGENT_KERNEL_MODULE"] = _module_specifier(
            kernel, field="kernel_module", package_root=package_root
        )

    # The standalone ResearchAgentServer runtime must load the explicitly pinned Pi
    # source prepared by the installation. It must never fall back to ~/.pi.
    pin_path = package_root / "config" / "pi-source.json"
    if not environment.get("RESEARCH_AGENT_PI_SOURCE") and not environment.get("TSPI_PI_SOURCE"):
        try:
            pin = json.loads(pin_path.read_text(encoding="utf-8"))
            commit = pin.get("commit") if isinstance(pin, dict) else None
            if isinstance(commit, str) and commit:
                source = Path(args.install_root).resolve() / ".pi" / "runtime-cache" / "pi" / commit
                if source.is_dir() and not source.is_symlink():
                    environment["RESEARCH_AGENT_PI_SOURCE"] = str(source)
                    environment["TSPI_PI_SOURCE"] = str(source)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass

    mappings = (
        ("host", "TSP_APP_SERVER_HOST"),
        ("port", "TSP_APP_SERVER_PORT"),
        ("catalog_root", "RESEARCH_AGENT_CATALOG_ROOT"),
        ("session_root", "RESEARCH_AGENT_SESSION_ROOT"),
        ("runtime_options", "RESEARCH_AGENT_RUNTIME_OPTIONS"),
        ("kernel_options", "RESEARCH_AGENT_KERNEL_OPTIONS"),
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
        "runtime_module",
        "kernel_module",
        "host",
        "port",
        "catalog_root",
        "session_root",
        "runtime_options",
        "kernel_options",
    ):
        value = getattr(args, key)
        if value is not None:
            config[key] = value
    if "runtime_module" not in config:
        raise LauncherError("--write-config requires --runtime-module")
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
