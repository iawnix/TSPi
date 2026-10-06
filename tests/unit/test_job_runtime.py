from __future__ import annotations

from pathlib import Path
import sys
import time

import pytest

from job_runtime import JobOutput, JobRuntime, JobSpec, JobState, LocalProcessPlatform


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
