"""Small file IO helpers for workspace state files."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def compact_id_time() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp.replace(path)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        json.dump(row, handle, sort_keys=True)
        handle.write("\n")


def append_markdown(path: Path, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = "" if path.exists() and path.stat().st_size else "# Knowledge Base\n\n"
    with path.open("a", encoding="utf-8") as handle:
        if prefix:
            handle.write(prefix)
        handle.write(f"## {title}\n\n{body.strip()}\n\n")


def sha256_json(data: Any) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()
