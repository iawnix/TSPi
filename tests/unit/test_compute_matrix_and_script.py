from __future__ import annotations

import json
from pathlib import Path

import pytest

from comparison_plan import build_comparison_plan
from research_compute.capabilities import resolve_capability, validate_capability_parameters
from research_compute.provider import BackendTask, resolve_compute_provider


def test_comparison_plan_has_one_opt_and_sp_per_method_environment() -> None:
    plan = build_comparison_plan(
        methods=["CF22D/6-31G", "GFN2-xTB", "M062X/6-31G"],
        environments=["local", "cluster"],
        input_artifact="art_" + "a" * 64,
    )
    assert plan["schema_version"] == "chemical_computation_plan/1"
    assert len(plan["jobs"]) == 12
    for job in plan["jobs"]:
        if job["step"] == "opt":
            assert job["depends_on"] == []
        else:
            parent = next(
                candidate for candidate in plan["jobs"]
                if candidate["job_id"] == job["depends_on"][0]
            )
            assert parent["method"] == job["method"]
            assert parent["environment"] == job["environment"]
            assert parent["step"] == "opt"
            assert job["input_artifacts"][0]["output_role"] == "optimized_geometry"
    gaussian = next(job for job in plan["jobs"] if job["method"] == "M062X/6-31G" and job["step"] == "opt")
    assert gaussian["capability"] == "gaussian"
    assert gaussian["parameters"]["route"] == "# M062X/6-31G Opt"


def test_comparison_plan_blocks_only_unready_cell() -> None:
    plan = build_comparison_plan(
        methods=["GFN2-xTB"],
        environments=["local", "cluster"],
        input_artifact="art_" + "b" * 64,
        readiness={"xtb.opt@cluster": False},
    )
    states = {(job["environment"], job["step"]): job["status"] for job in plan["jobs"]}
    assert states["cluster", "opt"] == "blocked"
    assert states["cluster", "sp"] == "blocked"
    assert states["local", "opt"] == "ready"


def test_script_capability_preserves_array_parameters_and_uses_bash() -> None:
    descriptor = resolve_capability("script.bash")
    parameters = validate_capability_parameters(
        descriptor,
        {"args": ["--mode", "production"], "output_manifest": ["script_result.json", "summary.txt"]},
    )
    provider = resolve_compute_provider("script")
    prepared = provider.prepare(
        BackendTask(
            node_id="node_1",
            task_type="bash",
            work_dir=".",
            inputs={"script": "inputs/run.sh"},
            settings={
                "args": json.dumps(parameters["args"]),
                "output_manifest": json.dumps(parameters["output_manifest"]),
            },
            backend="script",
        )
    )
    assert prepared.command == ["/bin/bash", "inputs/run.sh", "--mode", "production"]
    assert prepared.expected_artifacts == ["script_result.json", "summary.txt"]


def test_script_output_manifest_rejects_paths() -> None:
    provider = resolve_compute_provider("script")
    with pytest.raises(ValueError, match="basenames"):
        provider.prepare(
            BackendTask(
                node_id="node_1",
                task_type="bash",
                work_dir=".",
                inputs={"script": "run.sh"},
                settings={"output_manifest": json.dumps(["../result.json", "script_result.json"])},
                backend="script",
            )
        )
