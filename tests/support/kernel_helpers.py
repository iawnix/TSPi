"""Small helpers for applying canonical ResearchMap ChangeSets in tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ts_agent.research import ResearchKernel


def compile_change(root: str | Path, request: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise TypeError("request must be an object")
    operations = request.get("operations")
    if not isinstance(operations, list) or any(not isinstance(item, dict) for item in operations):
        raise ValueError("request.operations must be a list of objects")
    current = ResearchKernel(root).load()
    canonical = {
        "schema_version": "ts-change-request/1",
        "expected_revision": request.get("expected_revision", current.revision),
        "operations": [dict(item) for item in operations],
    }
    allocated = {
        str(item["type"])[len("create_"):]: item["id"]
        for item in operations
        if isinstance(item.get("type"), str)
        and item["type"].startswith("create_")
        and isinstance(item.get("id"), str)
    }
    return {
        "schema_version": "research-change-preview/1",
        "decision": canonical,
        "allocated_refs": allocated,
        "valid": True,
    }


def apply_compiled_change(root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    return ResearchKernel(root).apply(decision)
