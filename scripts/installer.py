#!/usr/bin/env python3
"""Public install/uninstall routing and immutable source selection."""
from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def module(name: str):
    return importlib.import_module(f"{__package__}.{name}" if __package__ else name)


def source_options(argv: list[str]):
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--source", choices=("local", "github"), default=None)
    parser.add_argument("--source-root")
    parser.add_argument("--research-agent-repo", default=os.environ.get("RESEARCH_AGENT_INSTALL_REPO", "https://github.com/iawnix/TSPi.git"))
    parser.add_argument("--research-agent-ref", default=os.environ.get("RESEARCH_AGENT_INSTALL_REF", "main"))
    parser.add_argument("--research-agent-commit", help=argparse.SUPPRESS)
    options, remaining = parser.parse_known_args(argv)
    if options.research_agent_commit is not None:
        parser.error("--research-agent-commit is reserved for the selected source")
    if options.source == "github" and options.source_root:
        parser.error("--source-root is only supported with --source local")
    options.source = options.source or ("local" if options.source_root else "github")
    if options.source == "local" and any(arg == "--research-agent-ref" or arg.startswith("--research-agent-ref=") for arg in argv):
        parser.error("--research-agent-ref selects a GitHub revision; local source uses its current HEAD")
    return options, remaining


def local_source(path: str | None, *, allow_dirty: bool) -> tuple[Path, str]:
    root = Path(path).expanduser() if path else ROOT
    if root.is_symlink() or not root.is_dir():
        raise ValueError("local source must be a physical Git checkout")
    root = root.resolve()
    source = module("install_from_github")
    if Path(source.run(["git", "rev-parse", "--show-toplevel"], cwd=root)).resolve() != root:
        raise ValueError("--source-root must be the top level of its Git checkout")
    commit = source.run(["git", "rev-parse", "--verify", "HEAD^{commit}"], cwd=root)
    source.validate_commit(commit)
    if not allow_dirty and source.run(["git", "status", "--porcelain"], cwd=root):
        raise ValueError("local checkout has uncommitted changes; commit them or use --allow-dirty for local validation")
    return root, commit


def run_selected(root: Path, commit: str, options, component: str, remaining: list[str]) -> int:
    script = "install_link_relay.py" if component == "relay" else "install_wizard.py"
    command = [sys.executable, "-B", str(root / "scripts" / script), *remaining, "--source-root", str(root)]
    if component != "relay":
        command.extend([
            "--research-agent-repo", options.research_agent_repo,
            "--research-agent-ref", options.research_agent_ref if options.source == "github" else commit,
            "--research-agent-commit", commit,
        ])
    return subprocess.run(command, env={**os.environ, "RESEARCH_AGENT_INSTALL_BOOTSTRAPPED": "1"}, check=False).returncode


def install(argv: list[str]) -> int:
    component = "relay" if argv[:1] == ["relay"] else "agent"
    if component == "relay":
        argv = argv[1:]
    options, remaining = source_options(argv)
    implementation = module("install_link_relay" if component == "relay" else "install_wizard")
    if "--help" in remaining or "-h" in remaining:
        print("Usage: install.sh [relay] [options]\n"
              "Source: --source {local,github} (default: github), --source-root PATH,\n"
              "        --research-agent-repo URL, --research-agent-ref REF\n"
              "Use --dry-run to preview without downloading or installing.\n", flush=True)
        implementation.parse_args(["--help"])
    dry_run = "--dry-run" in remaining
    parse_remaining = [arg for arg in remaining if arg != "--dry-run"] if component == "relay" else remaining
    args = implementation.parse_args(parse_remaining)
    source = module("install_from_github")
    source.validate_repo(options.research_agent_repo)
    source.validate_ref(options.research_agent_ref)
    if component == "agent":
        # Validate configuration inputs before a download; no secrets are copied here.
        module("_install_inputs").apply_config_directory(args)
        module("_install_relay").prepare(args)
        if args.job_config:
            import tomllib
            implementation._validate_job_config(tomllib.loads(Path(args.job_config).expanduser().read_text()))
        implementation.validate_email_options(args)
    if dry_run:
        if component == "agent":
            args.research_agent_repo = options.research_agent_repo
            args.research_agent_ref = options.research_agent_ref
            args.source_root = str(Path(options.source_root or ROOT).expanduser().resolve()) if options.source == "local" else None
            implementation.show_dry_run(args)
        else:
            print(json.dumps({"dry_run": True, "component": "relay", "source": options.source,
                              "install_root": args.install_root, "state_dir": args.state_dir}, indent=2))
        return 0
    if options.source == "local":
        root, commit = local_source(options.source_root, allow_dirty=args.allow_dirty)
        return run_selected(root, commit, options, component, remaining)
    with tempfile.TemporaryDirectory(prefix="research-agent-installer-") as temporary:
        root = Path(temporary) / "source"
        print(f"Preparing ResearchAgent revision {options.research_agent_ref}...", file=sys.stderr)
        commit = source.checkout_github(options.research_agent_repo, options.research_agent_ref, root)
        return run_selected(root, commit, options, component, remaining)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        action = arguments.pop(0) if arguments else "install"
        if action == "install":
            return install(arguments)
        if action == "uninstall":
            relay = arguments[:1] == ["relay"]
            if relay:
                arguments.pop(0)
            if "--help" in arguments or "-h" in arguments:
                print("Usage: uninstall.sh [relay] [options]\n", flush=True)
            return module("uninstall_link_relay" if relay else "uninstall").main(arguments)
        raise ValueError("expected install or uninstall")
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ResearchAgent installer failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
