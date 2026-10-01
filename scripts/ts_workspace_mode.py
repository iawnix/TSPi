#!/usr/bin/env python3
"""Create a canonical Research Agent workspace for Host/Pi integrations.

This command is deliberately separate from ``ts_workspace.py``.  The latter
owns the retired ResearchMap storage tooling and must not be used as a
workspace producer by the Native Pi Host.  This entrypoint writes only the
``workspace_manifest.json`` protocol and its mode-owned directories.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from _bootstrap import bootstrap_python_package

bootstrap_python_package(ROOT, workspace_from_argv=True)

from ts_agent.runtime.workspace_mode import (  # noqa: E402
    WorkspaceModeError,
    admit_research_workspace,
    initialize_workspace,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ts_workspace_mode")
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
