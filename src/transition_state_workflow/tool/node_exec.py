#!/usr/bin/env python3
"""Run an engine command from a node-scoped output directory."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess

from transition_state_workflow.util.cli import emit_json, run_cli
from transition_state_workflow.util.node_layout import NodeLayout, resolve_node_layout
from transition_state_workflow.util.remote_exec import command_text


def timestamp() -> str:
    """Return a UTC ISO timestamp."""

    return datetime.now(timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    """Build the node execution CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path, help="tssearch_<system> workspace root")
    parser.add_argument("--node-id", required=True, help="Existing node id under nodes/")
    parser.add_argument(
        "--metadata-name",
        default="run_metadata.txt",
        help="Metadata file to write under nodes/<node_id>/outputs/",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print resolved cwd/env/command without executing")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to execute, usually after --")
    return parser


def environment_for_node(layout: NodeLayout) -> dict[str, str]:
    """Return child-process environment with node-scoped path hints."""

    env = os.environ.copy()
    env.update(
        {
            "TS_WORKSPACE": str(layout.root),
            "TS_NODE_ID": layout.node_dir.name,
            "TS_NODE_DIR": str(layout.node_dir),
            "TS_NODE_INPUTS": str(layout.inputs),
            "TS_NODE_OUTPUTS": str(layout.outputs),
            "TS_NODE_PARSED": str(layout.parsed),
            "TS_NODE_SCRATCH": str(layout.scratch),
        }
    )
    return env


def write_metadata(path: Path, lines: list[str], *, append: bool = False) -> None:
    """Write simple key-value execution metadata."""

    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as handle:
        for line in lines:
            handle.write(line.rstrip() + "\n")


def _run(argv: list[str] | None) -> int:
    """Run the selected command in nodes/<node_id>/outputs."""

    parser = build_parser()
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("missing command; pass it after --")

    layout = resolve_node_layout(args.workspace, args.node_id)
    env = environment_for_node(layout)
    metadata_path = layout.outputs / args.metadata_name
    metadata_lines = [
        f"start={timestamp()}",
        f"workspace={layout.root}",
        f"node_id={layout.node_dir.name}",
        f"cwd={layout.outputs}",
        f"command={command_text(command)}",
    ]

    if args.dry_run:
        emit_json(
            {
                "cwd": str(layout.outputs),
                "command": command_text(command),
                "env": {
                    "TS_NODE_INPUTS": str(layout.inputs),
                    "TS_NODE_OUTPUTS": str(layout.outputs),
                    "TS_NODE_SCRATCH": str(layout.scratch),
                },
            }
        )
        return 0

    write_metadata(metadata_path, metadata_lines)
    result = subprocess.run(command, cwd=layout.outputs, env=env, check=False)
    write_metadata(
        metadata_path,
        [f"end={timestamp()}", f"status={result.returncode}"],
        append=True,
    )
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    return run_cli(_run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
