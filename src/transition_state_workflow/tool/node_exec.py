#!/usr/bin/env python3
"""Run an engine command from a node-scoped output directory."""

from __future__ import annotations

import argparse
from pathlib import Path

from transition_state_workflow.tools.node_exec import (
    NodeExecutionRequest,
    dry_run_payload,
    environment_for_node,
    render_command,
    run_node_command,
    timestamp,
    write_metadata,
)
from transition_state_workflow.util.cli import CLIBase, CLIResult, CliError
from transition_state_workflow.util.node_layout import resolve_node_layout


def build_parser() -> argparse.ArgumentParser:
    """Build the node execution CLI parser."""

    return NodeExecCLI().build_parser()


command_text = render_command


class NodeExecCLI(CLIBase):
    """Run a node-scoped command through the ChemTool execution boundary."""

    description = __doc__

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--workspace", required=True, type=Path, help="tssearch_<system> workspace root")
        parser.add_argument("--node-id", required=True, help="Existing node id under nodes/")
        parser.add_argument(
            "--metadata-name",
            default="run_metadata.txt",
            help="Metadata file to write under nodes/<node_id>/outputs/",
        )
        parser.add_argument("--dry-run", action="store_true", help="Print resolved cwd/env/command without executing")
        parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to execute, usually after --")

    def execute(self, args: argparse.Namespace) -> CLIResult:
        command = tuple(args.command[1:] if args.command and args.command[0] == "--" else args.command)
        if not command:
            raise CliError("missing command; pass it after --")

        if args.dry_run:
            layout = resolve_node_layout(args.workspace, args.node_id)
            return CLIResult(payload=dry_run_payload(layout, command), pretty=True)
        result = run_node_command(
            NodeExecutionRequest(
                workspace=args.workspace,
                node_id=args.node_id,
                command=command,
                metadata_name=args.metadata_name,
            )
        )
        return CLIResult(exit_code=result.returncode)


def main(argv: list[str] | None = None) -> int:
    return NodeExecCLI().main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
