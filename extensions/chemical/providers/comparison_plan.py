"""Deterministic method/environment/task planning for chemistry comparisons.

The planner is deliberately side effect free.  It only describes work; the
caller submits each ready job to ``compute_run`` and records the resulting
Attempt and Artifact provenance there.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


_METHODS = {
    "cf22d/6-31g": {
        "name": "CF22D/6-31G",
        "capability": {"opt": "pyscf.opt", "sp": "pyscf.sp"},
        "backend": "pyscf",
    },
    "gfn2-xtb": {
        "name": "GFN2-xTB",
        "capability": {"opt": "xtb.opt", "sp": "xtb.sp"},
        "backend": "xtb",
    },
    "m062x/6-31g": {
        "name": "M062X/6-31G",
        "capability": {"opt": "gaussian", "sp": "gaussian"},
        "backend": "gaussian",
    },
}


def _canonical_method(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        value = value.get("method", value.get("name"))
    if not isinstance(value, str) or not value.strip():
        raise ValueError("comparison method must be a non-empty string")
    key = re.sub(r"\s+", "", value.strip().lower())
    key = key.replace("–", "-").replace("—", "-")
    aliases = {
        "cf22d/6-31g": "cf22d/6-31g",
        "cf22d6-31g": "cf22d/6-31g",
        "gfn2-xtb": "gfn2-xtb",
        "gfn2xtb": "gfn2-xtb",
        "m062x/6-31g": "m062x/6-31g",
        "m062x6-31g": "m062x/6-31g",
    }
    try:
        return dict(_METHODS[aliases[key]])
    except KeyError as exc:
        raise ValueError(f"unsupported comparison method: {value}") from exc


def _stable_job_id(method: str, environment: str, step: str, geometry: str) -> str:
    payload = json.dumps(
        {"method": method, "environment": environment, "step": step, "geometry": geometry},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "job_" + hashlib.sha256(payload).hexdigest()[:24]


def _readiness_value(readiness: Mapping[str, Any] | None, capability: str, environment: str) -> bool:
    if readiness is None:
        return True
    # Accept either {"capability@environment": bool},
    # {capability: {environment: bool}}, or a catalog-like mapping.
    direct = readiness.get(f"{capability}@{environment}")
    if isinstance(direct, bool):
        return direct
    by_capability = readiness.get(capability)
    if isinstance(by_capability, Mapping):
        value = by_capability.get(environment)
        if isinstance(value, bool):
            return value
        if isinstance(value, Mapping):
            return value.get("ready") is True or value.get("state") in {"ready", "available"}
    if isinstance(by_capability, Mapping) and "environments" in by_capability:
        value = by_capability["environments"].get(environment)
        return value is True or isinstance(value, Mapping) and value.get("ready") is True
    return True


def build_comparison_plan(
    *,
    methods: Sequence[Any] | None = None,
    environments: Sequence[Any] | None = None,
    input_artifact: str | Mapping[str, Any] | None = None,
    readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable opt/sp matrix without touching workspace state."""

    selected_methods = [_canonical_method(item) for item in (methods or ("CF22D/6-31G", "GFN2-xTB", "M062X/6-31G"))]
    if not selected_methods:
        raise ValueError("comparison plan requires at least one method")
    selected_environments = list(environments or ("local",))
    if not selected_environments or any(not isinstance(item, str) or not item.strip() for item in selected_environments):
        raise ValueError("comparison environments must contain non-empty strings")
    selected_environments = list(dict.fromkeys(item.strip() for item in selected_environments))
    if isinstance(input_artifact, Mapping):
        artifact_id = input_artifact.get("artifact_id")
        input_ref = dict(input_artifact)
    else:
        artifact_id = input_artifact
        input_ref = {"artifact_id": input_artifact} if input_artifact is not None else {}
    if artifact_id is None or not isinstance(artifact_id, str) or not artifact_id.startswith("art_"):
        raise ValueError("input_artifact must be an artifact id")

    jobs: list[dict[str, Any]] = []
    opt_ids: dict[tuple[str, str], str] = {}
    for method in selected_methods:
        for environment in selected_environments:
            for step in ("opt", "sp"):
                capability = method["capability"][step]
                job_id = _stable_job_id(method["name"], environment, step, str(artifact_id or ""))
                if step == "opt":
                    inputs = [{"input_role": "geometry", **input_ref}] if input_ref else []
                    depends_on: list[str] = []
                    opt_ids[(method["name"], environment)] = job_id
                    parameters: dict[str, Any] = {}
                    if method["backend"] == "gaussian":
                        parameters["route"] = f"# M062X/6-31G Opt"
                else:
                    parent = opt_ids[(method["name"], environment)]
                    inputs = [{"input_role": "geometry", "from_job_id": parent, "output_role": "optimized_geometry"}]
                    depends_on = [parent]
                    parameters = {}
                    if method["backend"] == "gaussian":
                        parameters["route"] = "# M062X/6-31G SP"
                ready = _readiness_value(readiness, capability, environment)
                if step == "sp":
                    parent_job = next(item for item in jobs if item["job_id"] == parent)
                    ready = ready and parent_job["status"] == "ready"
                    blocked_reason = (
                        "dependency_unavailable"
                        if parent_job["status"] != "ready"
                        else "capability_or_environment_unavailable"
                    )
                else:
                    blocked_reason = "capability_or_environment_unavailable"
                jobs.append({
                    "job_id": job_id,
                    "method": method["name"],
                    "capability": capability,
                    "capability_version": "1",
                    "backend": method["backend"],
                    "environment": environment,
                    "step": step,
                    "parameters": parameters,
                    "input_artifacts": inputs,
                    "depends_on": depends_on,
                    "status": "ready" if ready else "blocked",
                    **({"blocked_reason": blocked_reason} if not ready else {}),
                })
    return {
        "schema_version": "chemical_computation_plan/1",
        "methods": [method["name"] for method in selected_methods],
        "environments": selected_environments,
        "jobs": jobs,
    }
