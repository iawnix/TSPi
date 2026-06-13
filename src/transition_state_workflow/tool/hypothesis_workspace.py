#!/usr/bin/env python3
"""Initialize and maintain chemistry-hypothesis TS-search workspaces."""

from __future__ import annotations

import argparse
from pathlib import Path

from transition_state_workflow.config.state_contract import (
    VALID_EVIDENCE_STATES,
)
from transition_state_workflow.tool.explorer_registry import register_workspace
from transition_state_workflow.gate.finalize import (
    finalize_ts_workspace_node_from_cli_args,
    register_finalize_node_parser,
)
from transition_state_workflow.base.pathway_model import (
    pathway_bind_step_from_cli_args,
    pathway_init_from_cli_args,
    register_pathway_parsers,
)
from transition_state_workflow.tool.plan_next import build_plan_next_packet, register_plan_next_parser
from transition_state_workflow.core.backtrack import (
    record_backtrack_from_cli_args,
    register_record_backtrack_parser,
    register_update_backtrack_parser,
    update_backtrack_from_cli_args,
)
from transition_state_workflow.core.start_node import (
    register_start_node_parser,
    start_ts_workspace_node_from_cli_args,
)
from transition_state_workflow.core.workspace_state import (
    append_ts_workspace_evidence_record_from_cli_args,
    create_ts_branch_decision_artifacts_from_cli_args,
    initialize_ts_hypothesis_workspace_files_from_cli_args,
    write_suggested_decision_cards_from_plan,
    write_text_file_if_allowed,
)
from transition_state_workflow.util.cli import configure_cli_logging, emit_json


def main() -> int:
    """Run the TS hypothesis workspace command-line interface."""

    parser = argparse.ArgumentParser(
        description="Create TS-search hypothesis workspace artifacts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize a tssearch_<system> workspace.")
    init.add_argument("--root", required=True, type=Path, help="Workspace directory.")
    init.add_argument("--system", required=True, help="Short system label.")
    init.add_argument("--charge", required=True, type=int, help="Total charge.")
    init.add_argument("--multiplicity", required=True, type=int, help="Spin multiplicity.")
    init.add_argument("--reaction-class", default="unknown", help="Initial reaction-class hypothesis.")
    init.add_argument(
        "--key-atoms",
        nargs="*",
        default=[],
        help="Reaction-center atom labels or indices.",
    )
    init.add_argument(
        "--bond-change",
        action="append",
        default=[],
        help="Expected bond change as role:atomA-atomB, e.g. breaking:O7-H5.",
    )
    init.add_argument("--force", action="store_true", help="Overwrite existing scaffold files.")
    init.add_argument(
        "--no-explorer-register",
        action="store_true",
        help="Skip registering this workspace in the persistent explorer registry.",
    )
    init.add_argument(
        "--explorer-register",
        action="store_true",
        help="Register this workspace in the persistent explorer registry.",
    )
    init.add_argument(
        "--explorer-registry",
        type=Path,
        default=None,
        help="Explorer registry path. Passing this path also opts into registration.",
    )
    init.add_argument("--verbose", action="store_true", help="Write diagnostic logs to stderr.")
    init.add_argument("--quiet", action="store_true", help="Only write errors to stderr.")

    card = sub.add_parser("decision-card", help="Create templates for one branch node.")
    card.add_argument("--root", required=True, type=Path, help="Workspace directory.")
    card.add_argument("--node-id", required=True, help="Node id under nodes/.")
    card.add_argument("--stage", required=True, help="Workflow stage.")
    card.add_argument("--parent-id", default=None, help="Parent node id.")
    card.add_argument("--pathway-id", default="", help="Optional pathway id for multi-step aggregation.")
    card.add_argument("--step-id", default="", help="Optional elementary step id within --pathway-id.")
    card.add_argument(
        "--input-ref",
        action="append",
        default=[],
        help=(
            "Additional input/dependency node id for multi-input routes such as QST2, "
            "endpoint-pair validation, or IRC reference checks. May be repeated."
        ),
    )
    card.add_argument("--hypothesis", required=True, help="Chemical hypothesis being tested.")
    card.add_argument("--operation", required=True, help="Operation or route chosen for this test.")
    card.add_argument("--force", action="store_true", help="Overwrite existing node templates.")
    card.add_argument("--verbose", action="store_true", help="Write diagnostic logs to stderr.")
    card.add_argument("--quiet", action="store_true", help="Only write errors to stderr.")

    evidence = sub.add_parser("add-evidence", help="Append one evidence registry record.")
    evidence.add_argument("--root", required=True, type=Path, help="Workspace directory.")
    evidence.add_argument("--kind", required=True, help="Evidence kind.")
    evidence.add_argument("--path", required=True, help="Evidence path.")
    evidence.add_argument("--node-id", required=True, help="Node id.")
    evidence.add_argument("--claim", required=True, help="Short source-backed claim.")
    evidence.add_argument(
        "--evidence-state",
        default="prepared",
        choices=sorted(VALID_EVIDENCE_STATES),
        help="How this evidence relates to the current hypothesis.",
    )
    evidence.add_argument("--verbose", action="store_true", help="Write diagnostic logs to stderr.")
    evidence.add_argument("--quiet", action="store_true", help="Only write errors to stderr.")

    register_start_node_parser(sub)
    register_record_backtrack_parser(sub)
    register_update_backtrack_parser(sub)
    register_pathway_parsers(sub)
    register_finalize_node_parser(sub)
    register_plan_next_parser(sub)

    args = parser.parse_args()
    configure_cli_logging(verbose=getattr(args, "verbose", False), quiet=getattr(args, "quiet", False))
    if args.command == "init":
        initialize_ts_hypothesis_workspace_from_cli_args(args)
    elif args.command == "decision-card":
        create_ts_branch_decision_artifacts_from_cli_args(args)
    elif args.command == "add-evidence":
        append_ts_workspace_evidence_record_from_cli_args(args)
    elif args.command == "start-node":
        start_ts_workspace_node_from_cli_args(args)
    elif args.command == "record-backtrack":
        record_backtrack_from_cli_args(args)
    elif args.command == "update-backtrack":
        update_backtrack_from_cli_args(args)
    elif args.command == "pathway-init":
        pathway_init_from_cli_args(args)
    elif args.command == "pathway-bind-step":
        pathway_bind_step_from_cli_args(args)
    elif args.command == "finalize-node":
        finalize_ts_workspace_node_from_cli_args(args)
    elif args.command == "plan-next":
        packet = build_plan_next_packet(
            args.root,
            max_suggestions=args.max_suggestions,
            alternative_mechanism=args.alternative_mechanism,
        )
        if args.write_decision_cards:
            packet["written_decision_cards"] = write_suggested_decision_cards_from_plan(args, packet)
        emit_json(packet, pretty=args.pretty)
    else:
        parser.error(f"unsupported command: {args.command}")
    return 0


def initialize_ts_hypothesis_workspace_from_cli_args(args: argparse.Namespace) -> None:
    """Create the root v2 files for a chemistry-hypothesis TS workspace."""

    root = initialize_ts_hypothesis_workspace_files_from_cli_args(args)

    registry_note = "explorer registration skipped (--no-explorer-register)"
    workspace_id = ""
    should_register = (bool(args.explorer_register) or args.explorer_registry is not None) and not args.no_explorer_register
    if should_register:
        registry_file, workspace_id = register_workspace(
            root,
            display_name=args.system,
            registry_path=args.explorer_registry,
        )
        registry_note = f"registered as `{workspace_id}` in `{registry_file}`"

    skill_scripts = Path(__file__).resolve().parents[3] / "scripts"
    explorer_checklist = f"""# Explorer Monitoring Checklist

This workspace is monitored by the persistent explorer service; one service
watches every registered TS search. Status: {registry_note}.

1. Ensure the persistent service is running (start once, keep it running):

```bash
python {skill_scripts / "ts_explorer_server.py"} serve --host 127.0.0.1 --port 8765
```

With no arguments it serves the persistent registry and hot-reloads it, so
newly initialized workspaces appear without a restart.

2. Open this workspace:

```text
http://127.0.0.1:8765/  (select `{workspace_id or root.name}` in the workspace list)
```

3. Validate before trusting the explorer view as evidence:

```bash
python {skill_scripts / "ts_validate_workspace.py"} --source {root} --pretty
```
"""
    write_text_file_if_allowed(root / "reports" / "explorer_launch_checklist.md", explorer_checklist, overwrite_existing=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
