#!/usr/bin/env python3
"""Create and admit a canonical research workspace for Host/Pi integrations.

Workspace diagnostics and projection repair are exposed by workspace.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from _bootstrap import bootstrap_python_package

bootstrap_python_package(ROOT, workspace_from_argv=True)

from research_agent.research.workspace import (  # noqa: E402
    WorkspaceModeError,
    admit_research_workspace,
    initialize_workspace,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="workspace_mode")
    parser.add_argument("--root", required=True)
    parser.add_argument("--workspace-id", required=True)
    args = parser.parse_args(argv)
    try:
        manifest = initialize_workspace(args.root, args.workspace_id, "research")
        manifest = admit_research_workspace(args.root)
    except (WorkspaceModeError, OSError, ValueError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
