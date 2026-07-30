#!/usr/bin/env python3
"""Create bounded local email drafts without sending or network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ts_workspace.io import write_json  # noqa: E402

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
REQUEST_KEYS = {"schema_version", "summary_ref", "draft_ref", "recipients", "subject", "body"}


def main() -> int:
    parser = argparse.ArgumentParser(prog="ts_email")
    sub = parser.add_subparsers(dest="command", required=True)
    draft = sub.add_parser("draft", help="Write one local email draft artifact.")
    draft.add_argument("--root", required=True)
    draft.add_argument("--request-file", required=True)
    draft.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        result = create_draft(Path(args.root), Path(args.request_file))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else result["draft_ref"])
    return 0


def create_draft(root: Path, request_file: Path) -> dict[str, Any]:
    workspace = root.resolve(strict=True)
    if not workspace.is_dir():
        raise ValueError("workspace root must be a directory")
    request = json.loads(request_file.read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise ValueError("email draft request must be an object")
    unknown = sorted(set(request) - REQUEST_KEYS)
    if unknown:
        raise ValueError(f"email draft request contains unknown fields: {', '.join(unknown)}")
    if request.get("schema_version") != "ts-email-draft/1":
        raise ValueError("email draft request schema_version must be ts-email-draft/1")

    summary_ref, summary_path = _workspace_path(workspace, request.get("summary_ref"), must_exist=True)
    if not summary_ref.endswith("/email_summary.md"):
        raise ValueError("summary_ref must select a generated email_summary.md")
    context_path = summary_path.with_name("report_context.json")
    if not context_path.is_file():
        raise ValueError("email_summary.md must have a sibling report_context.json")
    draft_ref, draft_path = _workspace_path(workspace, request.get("draft_ref"), must_exist=False)
    if draft_path.suffix.lower() != ".json":
        raise ValueError("draft_ref must end in .json")

    recipients = _recipients(request.get("recipients"))
    subject = _bounded_text(request.get("subject"), "subject", 300)
    body = _bounded_text(request.get("body"), "body", 20_000)
    summary_bytes = summary_path.read_bytes()
    artifact = {
        "schema_version": "ts-email-draft/1",
        "recipients": recipients,
        "subject": subject,
        "body": body,
        "summary_ref": summary_ref,
        "summary_sha256": hashlib.sha256(summary_bytes).hexdigest(),
        "delivery": {"status": "draft_only", "send_available": False},
    }
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(draft_path, artifact)
    return {
        "operation": "draft",
        "state": "drafted",
        "summary_ref": summary_ref,
        "draft_ref": draft_ref,
        "recipients": recipients,
        "subject": subject,
        "artifact_refs": [draft_ref],
        "external_side_effects": False,
    }


def _workspace_path(workspace: Path, value: Any, *, must_exist: bool) -> tuple[str, Path]:
    ref = _bounded_text(value, "workspace ref", 4096).replace("\\", "/")
    parts = ref.split("/")
    if not ref.startswith("reports/") or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("email artifacts must use a safe reports/ workspace-relative path")
    path = workspace.joinpath(*parts)
    current = workspace
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"email artifact path contains a symbolic link: {ref}")
        if not current.exists():
            break
    if path.exists() != must_exist:
        state = "does not exist" if must_exist else "already exists"
        raise ValueError(f"email artifact {state}: {ref}")
    return ref, path


def _recipients(value: Any) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise ValueError("recipients must contain 1-20 explicit email addresses")
    recipients = [_bounded_text(item, f"recipients[{index}]", 320) for index, item in enumerate(value)]
    if len(set(recipients)) != len(recipients):
        raise ValueError("recipients contains duplicates")
    invalid = [item for item in recipients if EMAIL_RE.fullmatch(item) is None]
    if invalid:
        raise ValueError(f"invalid explicit email recipient: {invalid[0]}")
    return recipients


def _bounded_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    text = value.strip()
    if len(text) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters")
    return text


if __name__ == "__main__":
    raise SystemExit(main())
