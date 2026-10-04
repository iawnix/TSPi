#!/usr/bin/env python3
"""JSONL entrypoint for the script extension."""

from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for source in (
    ROOT / "packages" / "tspi-provider-runtime",
    ROOT / "packages" / "tspi-foundation",
    ROOT / "packages" / "research-state",
    ROOT / "packages" / "research-compute",
    ROOT / "extensions" / "script" / "providers",
):
    sys.path.insert(0, str(source))

from tspi_provider_runtime.protocol import ProviderRequest
from tspi_provider_runtime.runner import run_jsonl_provider
from research_compute.provider import BackendTask
from script_compute_provider import script_compute_provider


def handle(request: ProviderRequest) -> dict:
    if request.provider_id != "script.bash":
        raise ValueError(f"unsupported script provider: {request.provider_id}")
    if request.operation == "describe":
        result = asdict(script_compute_provider.descriptors()[0])
    elif request.operation == "prepare":
        inputs = request.inputs.get("inputs", request.inputs)
        if not isinstance(inputs, dict):
            raise ValueError("script inputs must be an object")
        task = BackendTask(
            node_id=str(request.inputs.get("node_id", "provider_task")),
            task_type="bash",
            work_dir=str(request.inputs.get("work_dir", ".")),
            inputs={str(key): str(value) for key, value in inputs.items()},
            settings={str(key): _encode(value) for key, value in request.parameters.items()},
            backend="script",
        )
        prepared = script_compute_provider.prepare(task)
        result = {
            "backend": prepared.backend,
            "node_id": prepared.node_id,
            "command": prepared.command,
            "input_paths": prepared.input_paths,
            "expected_artifacts": prepared.expected_artifacts,
        }
    else:
        raise ValueError(f"unsupported script provider operation: {request.operation}")
    return {
        "status": "succeeded",
        "result": result,
        "outputs": [],
        "provenance": {
            "provider_id": request.provider_id,
            "request_id": request.request_id,
            "operation": request.operation,
            "version": request.version,
        },
        "diagnostics": [],
    }


def _encode(value):
    if isinstance(value, (list, dict)):
        import json
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


if __name__ == "__main__":
    raise SystemExit(run_jsonl_provider(handle))
