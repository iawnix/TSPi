"""Real user units exercise Job ownership, credentials and resource limits."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from research_agent.jobs import JobSpec, JobState, LocalProcessPlatform
from research_agent.jobs.local import manager_environment


def manager(*args, check=False):
    return subprocess.run(["systemctl", "--user", *args], env=manager_environment(),
                          capture_output=True, text=True, check=check, timeout=10)


def wait_file(path):
    for _ in range(200):
        if path.is_file():
            return
        time.sleep(.02)
    raise AssertionError("missing fixture result: " + str(path))


def cleanup(unit):
    if unit:
        manager("stop", unit)
        for _ in range(100):
            if manager("show", "-p", "LoadState", "--value", unit).stdout.strip() == "not-found":
                return
            time.sleep(.02)
        raise AssertionError("test service was not removed: " + unit)


def test_local_job_scrubs_credentials_and_enforces_resources_and_scratch(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURE_PROVIDER_CREDENTIAL", "must-not-enter-job")
    monkeypatch.setenv("PYTHONPATH", "/fixture/control-plane")
    cwd = tmp_path / "job"
    cwd.mkdir()
    command = [sys.executable, "-c", """import json,os,time
from pathlib import Path
Path('environment.json').write_text(json.dumps({k:os.environ.get(k) for k in
    ['FIXTURE_PROVIDER_CREDENTIAL','PYTHONPATH','TMPDIR','GAUSS_SCRDIR','OMP_NUM_THREADS']}))
while not Path('release').exists():time.sleep(.02)
"""]
    platform = LocalProcessPlatform(supervisor="systemd", platform_name="lab")
    unit = None
    try:
        receipt = platform.start(JobSpec(command=tuple(command), cwd=cwd,
            env={"GAUSS_SCRDIR": "{scratch}"}, metadata={"resources": {"cpus": 1, "memory_mb": 128},
                "execution_binding": {"binding": {"scratch_root": str(tmp_path / "scratch")}}}))
        unit = receipt.metadata["systemd_unit"]
        assert receipt.platform == "lab"
        wait_file(cwd / "environment.json")
        env = json.loads((cwd / "environment.json").read_text())
        assert env["FIXTURE_PROVIDER_CREDENTIAL"] is None
        assert env["PYTHONPATH"] is None
        assert env["GAUSS_SCRDIR"] == env["TMPDIR"] == receipt.metadata["scratch_path"]
        assert Path(env["TMPDIR"]).is_relative_to(tmp_path / "scratch")
        assert env["OMP_NUM_THREADS"] == "1"
        assert int(manager("show", "-p", "MemoryMax", "--value", unit, check=True).stdout.strip()) == 128 * 1024 * 1024
        assert manager("show", "-p", "CPUQuotaPerSecUSec", "--value", unit, check=True).stdout.strip() == "1s"
        (cwd / "release").touch()
        for _ in range(100):
            status = platform.status(receipt)
            if status.state != JobState.RUNNING:
                break
            time.sleep(.02)
        assert status.state == JobState.SUCCEEDED
    finally:
        cleanup(unit)


def test_host_unit_stop_does_not_kill_its_separately_owned_job(tmp_path):
    parent_unit = "research-agent-test-host-" + uuid.uuid4().hex + ".service"
    job_unit = None
    cwd = tmp_path / "job"
    cwd.mkdir()
    parent_script = tmp_path / "parent.py"
    child_command = [sys.executable, "-c", """from pathlib import Path
import time
Path('started').touch()
while not Path('release').exists():time.sleep(.02)
Path('result.txt').write_text('survived host stop')
"""]
    parent_script.write_text(
        "import sys,json,time\nfrom pathlib import Path\n"
        + "sys.path[:0] = " + repr(sys.path) + "\n"
        + "from research_agent.jobs import LocalProcessPlatform,JobSpec\n"
        + "receipt=LocalProcessPlatform(supervisor='systemd').start(JobSpec(command=" + repr(tuple(child_command))
        + ",cwd=Path(" + repr(str(cwd)) + "),timeout_seconds=20))\n"
        + "Path(" + repr(str(tmp_path / "parent-receipt.json")) + ").write_text(json.dumps(receipt.__dict__))\n"
        + "time.sleep(60)\n")
    try:
        subprocess.run(["systemd-run", "--user", "--collect", "--quiet", "--unit=" + parent_unit,
            "--property=Type=exec", "--property=ProtectSystem=strict", "--property=ProtectHome=read-only",
            "--property=PrivateTmp=true", "--property=ReadWritePaths=" + str(tmp_path),
            "--property=WorkingDirectory=" + str(tmp_path), "--", sys.executable, str(parent_script)],
            env=manager_environment(), capture_output=True, text=True, check=True, timeout=15)
        wait_file(tmp_path / "parent-receipt.json")
        receipt = LocalProcessPlatform.receipt_from_disk(cwd / "receipt.json")
        job_unit = receipt.metadata["systemd_unit"]
        wait_file(cwd / "started")
        cgroup = Path(f"/proc/{receipt.pid}/cgroup").read_text()
        assert job_unit in cgroup and parent_unit not in cgroup
        manager("stop", parent_unit, check=True)
        recovered = LocalProcessPlatform(supervisor="systemd")
        assert recovered.status(receipt).state == JobState.RUNNING
        (cwd / "release").touch()
        for _ in range(100):
            status = recovered.status(receipt)
            if status.state != JobState.RUNNING:
                break
            time.sleep(.02)
        assert status.state == JobState.SUCCEEDED
        assert (cwd / "result.txt").read_text() == "survived host stop"
    finally:
        if job_unit is None and (cwd / "receipt.json").is_file():
            job_unit = json.loads((cwd / "receipt.json").read_text()).get("metadata", {}).get("systemd_unit")
        try:
            cleanup(job_unit)
        finally:
            cleanup(parent_unit)
