#!/usr/bin/env python3
"""Copy a legacy v2 TS workspace into a new v3 workspace."""

from __future__ import annotations

import argparse
import json
import sys

from ts_workspace.migrate_v2 import MigrationError, migrate_workspace_v2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copy a v2 TS workspace into a new v3 workspace")
    parser.add_argument("--source", required=True, help="existing v2 workspace")
    parser.add_argument("--target", required=True, help="new, non-existing v3 workspace")
    args = parser.parse_args(argv)
    try:
        result = migrate_workspace_v2(args.source, args.target)
    except MigrationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
