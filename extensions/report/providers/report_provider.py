#!/usr/bin/env python3
"""First party report Provider."""
from __future__ import annotations
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "packages" / "tspi-runtime"), str(ROOT / "packages" / "research-state"), str(ROOT / "packages" / "research-memory"), str(ROOT / "packages" / "research-compute"), str(Path(__file__).resolve().parent)]
from tspi_runtime.providers.runner import run_jsonl_provider
from report_lib import build_final_report, build_report_package

def handle(request):
    inputs, parameters = request.inputs, request.parameters
    root = Path(inputs.get("workspace_root", "")); output = Path(inputs.get("output_path", "")) if inputs.get("output_path") else None
    if not root.is_absolute(): raise ValueError("report provider requires an absolute workspace_root")
    if parameters.get("package", True):
        package_dir = output or root / "reports" / str(parameters.get("package_name", "final-report"))
        value = build_report_package(root, package_dir, exclude_activity_refs=parameters.get("exclude_activity_refs", []), asset_artifact_ids=inputs.get("asset_artifact_ids", []))
        outputs = [{"role": "report", "path": value["package_dir"]}, {"role": "artifact", "path": value["report"]}]
    else:
        text = build_final_report(root)
        if output: output.write_text(text, encoding="utf-8")
        value = {"report": str(output) if output else text}; outputs = [{"role": "report", "path": str(output)}] if output else []
    return {"status": "succeeded", "result": value, "outputs": outputs, "provenance": {"provider_id": request.provider_id, "request_id": request.request_id}, "diagnostics": []}

if __name__ == "__main__": raise SystemExit(run_jsonl_provider(handle))
