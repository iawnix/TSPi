from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ts_backends.ase_neb import prepare_ase_neb
from ts_backends.base import BackendTask
from ts_backends.xtb import prepare_xtb_opt
from ts_remote import job_lifecycle


def test_generic_runner_text_records_status_and_quoted_command() -> None:
    config = job_lifecycle.RemoteJobConfig(
        node_id="n001",
        login_host="login",
        compute_host="compute",
        remote_dir="/remote/n001",
        command=["xtb", "input file.xyz", "--opt"],
        environment={"OMP_NUM_THREADS": "4"},
    )

    text = job_lifecycle.remote_runner_text(config)

    assert "export OMP_NUM_THREADS=4" in text
    assert "xtb 'input file.xyz' --opt > remote_job.stdout 2> remote_job.stderr" in text
    assert '"state":"running"' in text
    assert '"state":"$state"' in text


def test_generic_runner_rejects_unsafe_environment_key() -> None:
    config = job_lifecycle.RemoteJobConfig(
        node_id="n001",
        login_host="login",
        compute_host="compute",
        remote_dir="/remote/n001",
        command=["true"],
        environment={"BAD-KEY": "1"},
    )

    with pytest.raises(ValueError, match="invalid shell environment key"):
        job_lifecycle.remote_runner_text(config)


def test_submit_async_stages_inputs_runner_receipt_and_launches_background_job(monkeypatch, tmp_path: Path) -> None:
    xyz = tmp_path / "input.xyz"
    xyz.write_text("1\nh\nH 0 0 0\n", encoding="utf-8")
    calls: list[list[str]] = []
    staged_receipt: dict[str, object] = {}

    def fake_run(argv, check):
        calls.append(list(argv))
        if argv[0] == "scp" and argv[-2].endswith("remote_receipt.json"):
            staged_receipt.update(json.loads(Path(argv[-2]).read_text(encoding="utf-8")))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    config = job_lifecycle.RemoteJobConfig(
        node_id="n001",
        login_host="login",
        compute_host="compute",
        remote_dir="/remote/n001",
        command=["xtb", "input.xyz", "--opt"],
        input_paths=(xyz,),
        output_dir=tmp_path / "pulled",
        expected_artifacts=("xtbopt.xyz", "xtb.out"),
    )

    receipt = job_lifecycle.submit_async(config)

    assert receipt.node_id == "n001"
    assert receipt.host == "compute"
    assert receipt.receipt_path == "/remote/n001/remote_receipt.json"
    assert staged_receipt["receipt_path"] == "/remote/n001/remote_receipt.json"
    assert json.loads(receipt.metadata["expected_artifacts"]) == ["xtbopt.xyz", "xtb.out"]
    assert calls[0] == ["ssh", "login", "mkdir", "-p", "/remote/n001"]
    assert [call[-1] for call in calls if call[0] == "scp"] == [
        "login:/remote/n001/input.xyz",
        "login:/remote/n001/run_remote_job.sh",
        "login:/remote/n001/remote_receipt.json",
    ]
    assert calls[-2] == ["ssh", "login", "chmod", "+x", "/remote/n001/run_remote_job.sh"]
    assert calls[-1][:2] == ["ssh", "login"]
    assert calls[-1][2].startswith("ssh compute ")
    assert "nohup bash ./run_remote_job.sh" in calls[-1][2]
    assert "remote_runner.stdout" in calls[-1][2]
    assert "remote_pid.txt" in calls[-1][2]
    assert "remote_pid.txt.lock" in calls[-1][2]
    assert 'kill -0 "$pid"' in calls[-1][2]


def test_submit_async_rejects_staging_basename_collision(tmp_path: Path) -> None:
    left = tmp_path / "left" / "same.dat"
    right = tmp_path / "right" / "same.dat"
    left.parent.mkdir()
    right.parent.mkdir()
    left.write_text("left", encoding="utf-8")
    right.write_text("right", encoding="utf-8")
    config = job_lifecycle.RemoteJobConfig(
        node_id="n001",
        login_host="login",
        compute_host="compute",
        remote_dir="/remote/n001",
        command=["true"],
        input_paths=(left, right),
    )

    with pytest.raises(ValueError, match="basename collision"):
        job_lifecycle.submit_async(config)


def test_poll_parses_status_sections(monkeypatch) -> None:
    stdout = """__PID__
123
__STATUS__
{"state":"completed","pid":123,"exit_status":0}
__PS__

__FILES__
-rw-r--r-- 1 iaw iaw 10 Jun 24 remote_status.json
"""

    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    config = job_lifecycle.RemoteJobConfig(
        node_id="n001",
        login_host="login",
        compute_host="compute",
        remote_dir="/remote/n001",
        command=["true"],
    )

    status = job_lifecycle.poll(config)

    assert status.state == "completed"
    assert status.pid == "123"
    assert status.exit_status == 0
    assert status.files == ["-rw-r--r-- 1 iaw iaw 10 Jun 24 remote_status.json"]


def test_poll_reports_missing_remote_dir(monkeypatch) -> None:
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 3, stdout="", stderr="missing")

    monkeypatch.setattr(subprocess, "run", fake_run)
    config = job_lifecycle.RemoteJobConfig(
        node_id="n001",
        login_host="login",
        compute_host="compute",
        remote_dir="/remote/missing",
        command=["true"],
    )

    assert job_lifecycle.poll(config).state == "missing_remote_dir"


def test_kill_binds_remote_pid_before_signalling(monkeypatch) -> None:
    calls: list[list[str]] = []
    config = job_lifecycle.RemoteJobConfig(
        node_id="n001",
        login_host="login",
        compute_host="compute",
        remote_dir="/remote/n001",
        command=["true"],
    )
    observed = job_lifecycle.RemoteJobStatus(
        node_id="n001",
        host="compute",
        remote_dir="/remote/n001",
        state="killed",
        pid="123",
    )
    monkeypatch.setattr(job_lifecycle, "_run", lambda argv, _dry_run: calls.append(list(argv)))
    monkeypatch.setattr(job_lifecycle, "poll", lambda _config: observed)

    result = job_lifecycle.kill(config, expected_pid="123")

    assert result == observed
    remote_command = calls[0][-1]
    assert "expected_pid=123" in remote_command
    assert '"$pid" != "$expected_pid"' in remote_command
    assert "remote PID changed before cancellation" in remote_command


def test_fetch_uses_expected_artifacts_and_can_tolerate_missing(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, check):
        calls.append(list(argv))
        if argv[-2] == "login:/remote/n001/missing.out":
            raise subprocess.CalledProcessError(1, argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    config = job_lifecycle.RemoteJobConfig(
        node_id="n001",
        login_host="login",
        compute_host="compute",
        remote_dir="/remote/n001",
        command=["true"],
        output_dir=tmp_path,
        expected_artifacts=("ok.out", "missing.out"),
    )

    assert job_lifecycle.fetch(config, tolerate_missing=True) == ["ok.out"]
    assert [call[-2] for call in calls] == ["login:/remote/n001/ok.out", "login:/remote/n001/missing.out"]


def test_backend_prepared_tasks_feed_generic_remote_config(tmp_path: Path) -> None:
    xyz = tmp_path / "candidate.xyz"
    reactant = tmp_path / "reactant.xyz"
    product = tmp_path / "product.xyz"
    for path in [xyz, reactant, product]:
        path.write_text("1\nh\nH 0 0 0\n", encoding="utf-8")

    xtb = prepare_xtb_opt(
        BackendTask(
            node_id="n010",
            work_dir="nodes/n010",
            inputs={"xyz": str(xyz)},
            settings={"charge": "0", "uhf": "0"},
        )
    )
    xtb_remote = job_lifecycle.config_from_prepared_task(
        xtb,
        login_host="login",
        compute_host="compute",
        remote_dir="/remote/n010",
        output_dir=tmp_path / "xtb-pulled",
    )

    assert xtb_remote.command == ["xtb", "candidate.xyz", "--opt", "--chrg", "0", "--uhf", "0"]
    assert xtb_remote.input_paths == (xyz,)
    assert xtb_remote.expected_artifacts == ("xtbopt.xyz", "xtb.out")

    neb = prepare_ase_neb(
        BackendTask(
            node_id="n011",
            work_dir="nodes/n011",
            inputs={"reactant": str(reactant), "product": str(product)},
            settings={"images": "5"},
        )
    )
    neb_remote = job_lifecycle.config_from_prepared_task(
        neb,
        login_host="login",
        compute_host="compute",
        remote_dir="/remote/n011",
    )

    assert neb_remote.command[-2:] == ["reactant.xyz", "product.xyz"]
    assert neb_remote.input_paths == (reactant, product)
    assert neb_remote.expected_artifacts == ("neb.traj", "neb_summary.json")
