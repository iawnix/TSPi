#!/usr/bin/env python3
"""Build a final report from a validated workspace."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ts_runtime import ensure_runtime_python, seed_workspace_root_from_argv

seed_workspace_root_from_argv()
ensure_runtime_python(ROOT)

from ts_report import build_final_report, build_report_package


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output")
    parser.add_argument("--package-dir", help="Write final_report.md, report_context.json, assets/, and email_summary.md.")
    parser.add_argument("--exclude-activity-ref", action="append", default=[], help="Exclude the caller's in-flight report activity from the snapshot.")
    parser.add_argument("--json", action="store_true", help="Print the report package result as JSON.")
    args = parser.parse_args()
    if args.package_dir:
        result = build_report_package(
            args.root,
            args.package_dir,
            exclude_activity_refs=args.exclude_activity_ref,
        )
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else result["report"])
        return 0
    text = build_final_report(args.root)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
