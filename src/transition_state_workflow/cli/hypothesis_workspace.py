"""Command-line interface for chemistry-hypothesis TS-search workspaces."""

from __future__ import annotations

import argparse
from pathlib import Path

from transition_state_workflow.base.explorer_registry import register_workspace
from transition_state_workflow.cli.workspace_control import (
    build_workspace_report_payload,
    end_node_from_cli_args,
    register_end_node_parser,
    register_init_workspace_parser,
    register_report_workspace_parser,
    register_start_node_parser,
    register_validate_decision_parser,
    start_node_from_cli_args,
    validate_decision_payload,
)
from transition_state_workflow.core.workspace_state import (
    initialize_ts_hypothesis_workspace_files_from_cli_args,
)
from transition_state_workflow.core.workspace import write_text_file_if_allowed
from transition_state_workflow.util.cli import configure_cli_logging, emit_json
from transition_state_workflow.util.json_io import read_json_object_required


def build_parser() -> argparse.ArgumentParser:
    """Build the TS hypothesis workspace CLI parser."""

    parser = argparse.ArgumentParser(
        description="Control TS-search workspaces through the public five-command contract.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    register_init_workspace_parser(sub)
    register_start_node_parser(sub)
    register_end_node_parser(sub)
    register_report_workspace_parser(sub)
    register_validate_decision_parser(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the TS hypothesis workspace command-line interface."""

    parser = build_parser()
    args = parser.parse_args(argv)
    configure_cli_logging(verbose=getattr(args, "verbose", False), quiet=getattr(args, "quiet", False))
    if args.command == "init_workspace":
        initialize_ts_hypothesis_workspace_from_cli_args(args)
    elif args.command == "start_node":
        start_node_from_cli_args(args)
    elif args.command == "end_node":
        end_node_from_cli_args(args)
    elif args.command == "report_workspace":
        emit_json(
            build_workspace_report_payload(args.root, alternative_mechanism=bool(args.alternative_mechanism)),
            pretty=bool(args.pretty),
        )
    elif args.command == "validate_decision":
        decision = read_json_object_required(args.decision_file)
        emit_json(validate_decision_payload(args.root, decision), pretty=bool(args.pretty))
    else:
        parser.error(f"unsupported command: {args.command}")
    return 0


def initialize_ts_hypothesis_workspace_from_cli_args(args: argparse.Namespace) -> None:
    """Create the root files and CLI-owned explorer launch checklist."""

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

    write_explorer_launch_checklist(
        root,
        workspace_id=workspace_id,
        registry_note=registry_note,
        force=bool(args.force),
    )


def write_explorer_launch_checklist(
    root: Path,
    *,
    workspace_id: str,
    registry_note: str,
    force: bool,
) -> Path:
    """Write the CLI-facing note for opening this workspace in the web explorer."""

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
    target = root / "reports" / "explorer_launch_checklist.md"
    write_text_file_if_allowed(target, explorer_checklist, overwrite_existing=force)
    return target


__all__ = [
    "build_parser",
    "initialize_ts_hypothesis_workspace_from_cli_args",
    "main",
    "write_explorer_launch_checklist",
]


if __name__ == "__main__":
    raise SystemExit(main())
