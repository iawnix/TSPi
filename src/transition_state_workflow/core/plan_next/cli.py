"""Argparse registration for workspace decision-context commands."""

from __future__ import annotations

import argparse
from pathlib import Path


def register_plan_next_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Attach decision-context and the deprecated plan-next alias to the workspace CLI."""

    context = subparsers.add_parser(
        "decision-context",
        help="Summarize tree/evidence state into an agent-facing decision-context packet.",
    )
    _add_decision_context_arguments(context, deprecated_alias=False)

    plan = subparsers.add_parser(
        "plan-next",
        help="Deprecated alias for decision-context; reports state and constraints only.",
    )
    _add_decision_context_arguments(plan, deprecated_alias=True)


def _add_decision_context_arguments(parser: argparse.ArgumentParser, *, deprecated_alias: bool) -> None:
    parser.set_defaults(decision_context_alias="plan-next" if deprecated_alias else "decision-context")
    parser.add_argument("--root", required=True, type=Path, help="Workspace directory.")
    parser.add_argument(
        "--max-suggestions",
        type=int,
        default=4,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--write-decision-cards",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--force", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--alternative-mechanism",
        action="store_true",
        help="After an accepted TS exists, report context for a chemically distinct alternative mechanism.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    parser.add_argument("--verbose", action="store_true", help="Write diagnostic logs to stderr.")
    parser.add_argument("--quiet", action="store_true", help="Only write errors to stderr.")


__all__ = ["register_plan_next_parser"]
