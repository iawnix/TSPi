from __future__ import annotations

from pathlib import Path

from ts_agent.compute.readiness import calculation_readiness
from ts_agent.remote.client import CommandResult


def _remote_config(tmp_path: Path) -> Path:
    ssh_config = tmp_path / "ssh_config"
    ssh_config.write_text("Host fake-login\n  HostName fake-login\n", encoding="utf-8")
    config = tmp_path / "compute.toml"
    config.write_text(
        f'''default_environment = "cluster"

[environments.cluster]
kind = "remote"
ssh_host = "fake-login"
ssh_config = "{ssh_config}"
scheduler = "torque"
remote_root = "/srv/tspi"
allowed_queues = ["batch"]
max_nodes = 1

[environments.cluster.backends.xtb]
command = ["xtb"]
allowed_queues = ["batch"]
''',
        encoding="utf-8",
    )
    return config


class _FakeSSH:
    def __init__(self, platform, *, queue_enabled: bool = True):
        self.platform = platform
        self.queue_enabled = queue_enabled

    def run(self, remote_argv, *, check=True, input_text=None, timeout=None):
        del check, input_text, timeout
        argv = tuple(str(item) for item in remote_argv)
        if argv == ("qstat", "-Qf"):
            enabled = "True" if self.queue_enabled else "False"
            return CommandResult(argv, 0, f"Queue: batch\n enabled = {enabled}\n started = True\n", "")
        return CommandResult(argv, 0, "", "")

    def run_script(self, script, args=(), *, check=True, timeout=None):
        del script, args, check, timeout
        return CommandResult(("bash",), 0, "", "")


def test_remote_readiness_runs_scheduler_and_backend_probes(tmp_path, monkeypatch):
    config = _remote_config(tmp_path)
    monkeypatch.setattr("ts_agent.compute.readiness.SSHClient", _FakeSSH)

    result = calculation_readiness(
        capability_id="xtb.sp",
        environment_id="cluster",
        execution_kind="remote",
        config_path=config,
    )

    row = result["readiness"][0]
    assert row["environment_id"] == "cluster"
    assert row["readiness"]["state"] == "ready"
    assert {check["name"] for check in row["readiness"]["checks"]} >= {
        "ssh",
        "scheduler_commands",
        "scheduler",
        "remote_root",
        "queues",
        "executable",
    }


def test_remote_readiness_reports_queue_gap_without_submitting(tmp_path, monkeypatch):
    config = _remote_config(tmp_path)
    monkeypatch.setattr(
        "ts_agent.compute.readiness.SSHClient",
        lambda platform: _FakeSSH(platform, queue_enabled=False),
    )

    result = calculation_readiness(
        capability_id="xtb.sp",
        environment_id="cluster",
        execution_kind="remote",
        config_path=config,
    )

    readiness = result["readiness"][0]["readiness"]
    assert readiness["state"] == "unavailable"
    assert any(check.get("code") == "queue_unavailable" for check in readiness["checks"])
