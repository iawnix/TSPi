#!/usr/bin/env python3
"""JSONL entrypoint for the first party chemistry extension.

The extension owns chemistry implementations; the Host owns process
isolation and Research State registration. This adapter only prepares a
bounded task or runs deterministic analysis and never writes canonical state.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
for source in (
    ROOT / "packages" / "tspi-provider-runtime",
    ROOT / "packages" / "tspi-foundation",
    ROOT / "packages" / "research-state",
    ROOT / "packages" / "research-compute",
    ROOT / "extensions" / "chemical" / "providers",
):
    sys.path.insert(0, str(source))

from tspi_provider_runtime.protocol import ProviderRequest
from tspi_provider_runtime.runner import run_jsonl_provider


def _task(request: ProviderRequest):
    from chemical_runtime.backends.base import BackendTask
    inputs = request.inputs.get("inputs", request.inputs.get("input_paths", {}))
    if not isinstance(inputs, dict):
        raise ValueError("chemical compute inputs must be an object keyed by role")
    node_id = request.inputs.get("node_id", "provider_task")
    task_type = request.inputs.get("task_type", request.parameters.get("task_type"))
    if not isinstance(node_id, str) or not node_id:
        raise ValueError("chemical compute node_id is required")
    if not isinstance(task_type, str) or not task_type:
        raise ValueError("chemical compute task_type is required")
    settings = request.parameters.get("settings", request.parameters)
    if not isinstance(settings, dict):
        raise ValueError("chemical compute settings must be an object")
    return BackendTask(
        node_id=node_id, task_type=task_type, work_dir=str(request.inputs.get("work_dir", ".")),
        inputs={str(key): str(value) for key, value in inputs.items()},
        settings={str(key): str(value) for key, value in settings.items()},
    )


def _prepare(request: ProviderRequest) -> dict[str, Any]:
    from chemical_runtime.backends.crest import prepare_crest
    from chemical_runtime.backends.gaussian import prepare_gaussian
    from chemical_runtime.backends.pyscf import prepare_pyscf
    from chemical_runtime.backends.xtb import prepare_xtb
    handlers = {"xtb": prepare_xtb, "crest": prepare_crest, "gaussian": prepare_gaussian, "pyscf": prepare_pyscf}
    prepared = handlers[request.provider_id](_task(request))
    return {"backend": prepared.backend, "node_id": prepared.node_id, "command": prepared.command,
            "input_paths": prepared.input_paths, "expected_artifacts": prepared.expected_artifacts,
            "environment": prepared.environment, "activation_script": prepared.activation_script}


def handle(request: ProviderRequest) -> dict[str, Any]:
    if request.provider_id in {"xtb", "crest", "gaussian", "pyscf"}:
        result = _prepare(request)
    elif request.provider_id == "chemical.analysis":
        from chemical_compute_provider import chemical_compute_provider
        root = request.context.get("workspace_root")
        if not isinstance(root, str) or not root.startswith("/"):
            raise ValueError("chemical analysis requires an absolute workspace_root context")
        result = chemical_compute_provider.run_analysis(Path(root), request.inputs.get("request", request.inputs))
    elif request.provider_id == "artifact_seed":
        from chemical_runtime.structures.seed import generate_smiles_seed
        result = generate_smiles_seed(str(request.inputs.get("smiles", "")),
                                      charge=int(request.parameters.get("charge", 0)),
                                      multiplicity=int(request.parameters.get("multiplicity", 1)),
                                      optimization=str(request.parameters.get("optimization", "none")))
    else:
        raise ValueError(f"unsupported chemical provider: {request.provider_id}")
    return {"status": "succeeded", "result": result, "outputs": [],
            "provenance": {"provider_id": request.provider_id, "request_id": request.request_id,
                           "operation": request.operation, "version": request.version}, "diagnostics": []}


if __name__ == "__main__":
    raise SystemExit(run_jsonl_provider(handle))
