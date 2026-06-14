"""CLI adapter for ChemGate workspace validation."""

from __future__ import annotations

import argparse
from pathlib import Path

from transition_state_workflow.util.cli import CLIBase, CLIResult

from .workspace import validate_ts_workspace_contract


class ValidateWorkspaceCLI(CLIBase):
    """Workspace contract validator command-line interface."""

    description = "Validate a tssearch_<system> workspace."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--source", required=True, type=Path, help="tssearch workspace root.")
        parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
        parser.add_argument("--strict", action="store_true", help="Exit nonzero on warnings as well as errors.")

    def execute(self, args: argparse.Namespace) -> CLIResult:
        payload = validate_ts_workspace_contract(args.source)
        exit_code = 0
        if payload["summary"]["errors"]:
            exit_code = 1
        elif args.strict and payload["summary"]["warnings"]:
            exit_code = 1
        return CLIResult(exit_code=exit_code, payload=payload, pretty=args.pretty)


def main(argv: list[str] | None = None) -> int:
    """Run the workspace contract validator command-line interface."""

    return ValidateWorkspaceCLI().main(argv)


__all__ = ["ValidateWorkspaceCLI", "main"]
