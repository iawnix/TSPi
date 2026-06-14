"""Argparse registration for the plan-next workspace command."""

from __future__ import annotations

import argparse
from pathlib import Path


def register_plan_next_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Attach the plan-next subcommand to the workspace CLI."""

    plan = subparsers.add_parser(
        "plan-next",
        help="Summarize tree/evidence state into an agent-facing next-action packet.",
    )
    plan.add_argument("--root", required=True, type=Path, help="Workspace directory.")
    plan.add_argument("--max-suggestions", type=int, default=4, help="Maximum decision-card suggestions.")
    plan.add_argument(
        "--write-decision-cards",
        action="store_true",
        help="Materialize suggested decision-card nodes. Default is read-only.",
    )
    plan.add_argument("--force", action="store_true", help="Overwrite existing suggested node templates.")
    plan.add_argument(
        "--alternative-mechanism",
        action="store_true",
        help="After an accepted TS exists, plan a chemically distinct alternative mechanism instead of audit-only mode.",
    )
    plan.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    plan.add_argument("--verbose", action="store_true", help="Write diagnostic logs to stderr.")
    plan.add_argument("--quiet", action="store_true", help="Only write errors to stderr.")


__all__ = ["register_plan_next_parser"]
