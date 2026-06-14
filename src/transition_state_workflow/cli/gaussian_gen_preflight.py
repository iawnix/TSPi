#!/usr/bin/env python3
"""CLI for preflighting and optionally repairing Gaussian Gen/GenECP inputs."""

from __future__ import annotations

import argparse
from pathlib import Path

from transition_state_workflow.backends.gaussian import (
    fix_lines,
    link0_end,
    route_indices,
    split_tail,
    warnings_for,
)
from transition_state_workflow.util.cli import CLIBase, CLIResult


class GaussianGenPreflightCLI(CLIBase):
    """Gaussian Gen/GenECP preflight and optional repair command."""

    description = __doc__

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("input", type=Path)
        parser.add_argument("--output", type=Path)
        parser.add_argument("--fix", action="store_true")
        parser.add_argument("--chk")
        parser.add_argument("--nproc", type=int)
        parser.add_argument("--mem")

    def execute(self, args: argparse.Namespace) -> CLIResult:
        lines = args.input.read_text(encoding="utf-8", errors="replace").splitlines()
        warnings = warnings_for(lines)
        result: dict[str, object] = {"warnings": warnings, "fixed": False, "output": None}
        if args.fix:
            output = args.output or args.input.with_suffix(".fixed.gjf")
            chk = args.chk or f"{output.stem}.chk"
            output.write_text("\n".join(fix_lines(lines, chk, args.nproc, args.mem)), encoding="utf-8")
            result["fixed"] = True
            result["output"] = str(output)
        return CLIResult(exit_code=1 if warnings and not args.fix else 0, payload=result, pretty=True)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for compatibility with older imports."""

    return GaussianGenPreflightCLI().build_parser()


def main(argv: list[str] | None = None) -> int:
    return GaussianGenPreflightCLI().main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
