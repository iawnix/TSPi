from __future__ import annotations

from pathlib import Path
import sys
import time

import pytest

from research_agent.jobs import JobOutput, JobRuntime, JobSpec, JobState, LocalProcessPlatform, TorqueSSHPlatform, platforms_from_config
from research_agent.jobs.local import _process_state
from research_agent.application.execution import _spec


def _runtime() -> JobRuntime:
    return JobRuntime({"local": LocalProcessPlatform()})


def _wait(runtime: JobRuntime, receipt):
    for _ in range(100):
        status = runtime.job_status(receipt)
        if status.state not in {JobState.RUNNING, JobState.SUBMITTED}:
            return status
        time.sleep(0.01)
    raise AssertionError("job did not reach a terminal state")


def test_arbitrary_argv_job_collects_declared_output(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    runtime = _runtime()
    spec = JobSpec(
        command=(sys.executable, "-c", "from pathlib import Path; Path('result.txt').write_text('ok')"),
        cwd=work,
        outputs=(JobOutput("result.txt", required=True, media_type="text/plain"),),
    )

    receipt = runtime.job_start(spec)
    status = _wait(runtime, receipt)
    collected = runtime.job_collect(receipt)

    assert status.state is JobState.SUCCEEDED
    assert collected["outputs"] == [{
        "path": "result.txt",
        "required": True,
        "exists": True,
        "size": 2,
        "sha256": "2689367b205c16ce32ed4200942b8b8b1e262dfc70d9bc9fbc77c49699a4f1df",
    }]


def test_job_probe_reports_missing_cwd_or_inputs_without_execution(tmp_path: Path) -> None:
    runtime = _runtime()
    spec = JobSpec(command=(sys.executable, "-c", "raise SystemExit(99)"), cwd=tmp_path / "missing")

    probe = runtime.job_probe(spec)

    assert probe["platform"] == "local"
    assert probe["cwd_exists"] is False


def test_output_paths_cannot_escape_job_cwd(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="stay below cwd"):
        JobSpec(command=(sys.executable,), cwd=tmp_path, outputs=(JobOutput("../outside"),))


def test_job_runtime_preserves_research_identity_without_domain_parsing(tmp_path: Path) -> None:
    runtime = _runtime()
    request = JobSpec(
        command=(sys.executable, "-c", "print('raw evidence')"),
        cwd=tmp_path,
        workspace_id="ws_demo",
        job_id="job_demo",
    )

    receipt = runtime.job_start(request)
    status = _wait(runtime, receipt)

    assert status.state is JobState.SUCCEEDED
    assert receipt.job_id == "job_demo"
    assert receipt.workspace_id == "ws_demo"
    assert runtime.job_collect(receipt)["job_id"] == "job_demo"


def test_job_config_wires_remote_environment_into_runtime(tmp_path: Path) -> None:
    config = tmp_path / "job.toml"
    config.write_text(
        """default_environment = \"local\"\n
[environments.local]
kind = \"local\"

[environments.cluster]
kind = \"remote\"
ssh_host = \"compute.example\"
ssh_config = \"/tmp/ssh-config\"
scheduler = \"torque\"
remote_root = \"/scratch/coragent\"
""",
        encoding="utf-8",
    )
    platforms, default = platforms_from_config(config)
    assert default == "local"
    assert isinstance(platforms["local"], LocalProcessPlatform)
    assert isinstance(platforms["cluster"], TorqueSSHPlatform)
    assert "remote" not in platforms
    assert platforms["cluster"].host == "compute.example"


def test_job_spec_separates_execution_target_from_process_environment(tmp_path: Path) -> None:
    spec = _spec(tmp_path, {
        "job_id": "job_target",
        "command": [sys.executable, "-c", "pass"],
        "environment": "cluster_1w",
        "env": {"SCIENTIFIC_RUNTIME": "configured"},
    })
    assert spec.env == {"SCIENTIFIC_RUNTIME": "configured"}


def test_process_state_reports_missing_pid_without_treating_it_as_alive() -> None:
    assert _process_state(2**31 - 1) is None
