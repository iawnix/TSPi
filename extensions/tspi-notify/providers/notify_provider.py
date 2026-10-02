#!/usr/bin/env python3
"""First party notification Provider with durable receipt semantics."""
from __future__ import annotations
from pathlib import Path
import json, sys
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "packages" / "tspi-runtime"), str(ROOT / "packages" / "research-state"), str(ROOT / "packages" / "research-memory"), str(ROOT / "packages" / "research-compute"), str(ROOT / "extensions" / "tspi-report" / "providers"), str(Path(__file__).resolve().parent)]
from tspi_runtime.providers.runner import run_jsonl_provider
from notify_lib import notify_user

def handle(request):
    root = Path(request.inputs.get("workspace_root", ""))
    if not root.is_absolute(): raise ValueError("notify provider requires an absolute workspace_root")
    request_file = root / ".provider-notify-request.json"
    request_file.write_text(json.dumps({**request.parameters, **request.inputs.get("notification", {})}), encoding="utf-8")
    try: value = notify_user(root, request_file)
    finally: request_file.unlink(missing_ok=True)
    return {"status": "succeeded", "result": value, "outputs": [{"role": "receipt", "path": value.get("receipt_ref", "")}], "provenance": {"provider_id": request.provider_id, "request_id": request.request_id}, "diagnostics": []}

if __name__ == "__main__": raise SystemExit(run_jsonl_provider(handle))
