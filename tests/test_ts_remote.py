from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from ts_remote.client import CommandResult
from ts_remote.config import load_config
from ts_remote.diagnostics import MODES, _doctor, diagnose
from ts_remote.errors import (
    RemoteConfigurationError,
    RemoteError,
    RemotePreSubmitError,
    RemoteSubmissionAmbiguous,
)
from ts_remote.lifecycle import _parse_record, _submit_script, collect, status, submit
from ts_remote.models import RemoteJobConfig, RemoteResources, TransferRecord
from ts_remote.torque import parse_records, render_job_script, scheduler_semantics
from ts_remote.transfer import upload_verified


def test_remote_diagnostic_modes_exclude_redundant_cluster_alias() -> None:
    assert MODES == {"status", "doctor", "queues", "nodes"}
    with pytest.raises(RemoteError, match="unsupported ts_remote diagnostic mode: cluster"):
        diagnose("cluster")


def _profile(tmp_path: Path):
    ssh_config = tmp_path / "ssh_config"
    ssh_config.write_text("Host test-login\n  HostName login.test\n", encoding="utf-8")
    config = tmp_path / "remote.toml"
    config.write_text(
        f'''default_profile = "cluster"

[profiles.cluster]
ssh_host = "test-login"
ssh_config = "{ssh_config}"
scheduler = "torque"
remote_root = "/remote/ts"
allowed_queues = ["batch"]
max_nodes = 1

[profiles.cluster.commands]
qsub = "/opt/torque/bin/qsub"
qstat = "/opt/torque/bin/qstat"
qdel = "/opt/torque/bin/qdel"
pbsnodes = "/opt/torque/bin/pbsnodes"

[profiles.cluster.software.gaussian]
command = ["/opt/g16/g16"]
activation_script = "/opt/g16/activate.sh"
allowed_queues = ["batch"]
requires_gpu = false
''',
        encoding="utf-8",
    )
    return load_config(config).profile("cluster")


def _job(tmp_path: Path) -> RemoteJobConfig:
    source = tmp_path / "candidate.gjf"
    source.write_text("#P HF/STO-3G\n", encoding="utf-8")
    return RemoteJobConfig(
        submission_id="tsjob_ws_0123456789abcdef01234567_calc_1_0123456789abcdef",
        intent_id="calc_1",
        intent_digest="sha256:" + "a" * 64,
        node_id="node_1",
        backend="gaussian",
        profile=_profile(tmp_path),
        remote_dir="/remote/ts/workspaces/ws_0123456789abcdef01234567/runs/node_1/calc_1",
        resources=RemoteResources(
            queue="batch",
            nodes=1,
            ncpus=8,
            memory="16gb",
            walltime="04:00:00",
            ompthreads=8,
        ),
        command=("g16", "candidate.gjf"),
        input_paths=(source,),
        expected_artifacts=("candidate.log",),
        output_dir=tmp_path / "outputs",
        stdout_name="candidate.log",
    )


def test_remote_job_rejects_noncanonical_calculation_ids(tmp_path: Path) -> None:
    invalid = replace(
        _job(tmp_path),
        intent_id="calc_test",
        remote_dir="/remote/ts/workspaces/ws_0123456789abcdef01234567/runs/node_1/calc_test",
    )

    with pytest.raises(RemoteConfigurationError, match="calculation Attempt ID"):
        render_job_script(invalid)


def _executable_job(
    tmp_path: Path,
    *,
    activation_body: str,
    scratch_root: Path,
) -> tuple[RemoteJobConfig, Path]:
    remote_root = tmp_path / "remote"
    remote_dir = remote_root / "workspaces/ws_0123456789abcdef01234567/runs/node_1/calc_1"
    remote_dir.mkdir(parents=True)
    (remote_dir / "candidate.gjf").write_text("#P HF/STO-3G\n", encoding="utf-8")
    activation = tmp_path / "activate.sh"
    activation.write_text(activation_body, encoding="utf-8")
    executable = tmp_path / "fake-g16"
    executable.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'test "$GAUSS_SCRDIR" = "$TMPDIR"\n'
        'test -f "$GAUSS_SCRDIR/activation.marker"\n'
        'printf "%s\\n" "$GAUSS_SCRDIR"\n',
        encoding="utf-8",
    )
    executable.chmod(0o755)
    base = _job(tmp_path)
    software = replace(
        base.profile.software["gaussian"],
        command=(str(executable),),
        activation_script=str(activation),
        scratch_root=str(scratch_root),
    )
    profile = replace(
        base.profile,
        remote_root=str(remote_root),
        software={"gaussian": software},
    )
    return replace(
        base,
        profile=profile,
        remote_dir=str(remote_dir),
        input_paths=(remote_dir / "candidate.gjf",),
    ), remote_dir


def test_remote_profile_is_installation_owned_and_strict(tmp_path: Path) -> None:
    profile = _profile(tmp_path)

    assert profile.ssh_host == "test-login"
    assert profile.scheduler == "torque"
    assert profile.software["gaussian"].command == ("/opt/g16/g16",)
    assert profile.software["gaussian"].scratch_root is None

    invalid = tmp_path / "invalid.toml"
    invalid.write_text(
        '''default_profile = "cluster"
[profiles.cluster]
ssh_host = "test-login"
ssh_config = "missing"
scheduler = "slurm"
remote_root = "/"
allowed_queues = ["batch"]
max_nodes = 1
''',
        encoding="utf-8",
    )
    with pytest.raises(RemoteConfigurationError):
        load_config(invalid)


@pytest.mark.parametrize("scratch_root", ["/", "relative/scratch"])
def test_remote_profile_rejects_unsafe_scratch_roots(tmp_path: Path, scratch_root: str) -> None:
    profile = _profile(tmp_path)
    gaussian = replace(profile.software["gaussian"], scratch_root=scratch_root)

    with pytest.raises(RemoteConfigurationError, match="scratch_root must be a non-root absolute POSIX path"):
        replace(profile, software={"gaussian": gaussian}).validate()


def test_scheduler_commands_default_to_remote_path_lookup(tmp_path: Path) -> None:
    ssh_config = tmp_path / "ssh_config"
    ssh_config.write_text("Host test-login\n  HostName login.test\n", encoding="utf-8")
    config = tmp_path / "remote.toml"
    config.write_text(
        f'''default_profile = "cluster"

[profiles.cluster]
ssh_host = "test-login"
ssh_config = "{ssh_config}"
scheduler = "torque"
remote_root = "/remote/ts"
allowed_queues = ["batch"]
max_nodes = 1

[profiles.cluster.software.xtb]
command = ["xtb"]
allowed_queues = ["batch"]
requires_gpu = false
''',
        encoding="utf-8",
    )

    commands = load_config(config).profile("cluster").commands

    assert commands.qsub == "qsub"
    assert commands.qstat == "qstat"
    assert commands.qdel == "qdel"
    assert commands.pbsnodes == "pbsnodes"


def test_torque_script_owns_resources_activation_and_program_status(tmp_path: Path) -> None:
    script = render_job_script(_job(tmp_path))

    assert "#PBS -S /bin/bash" in script
    assert "#PBS -q batch" in script
    assert "#PBS -l nodes=1:ppn=8" in script
    assert "#PBS -l mem=16gb" in script
    assert 'scratch_base=${TMPDIR:-/tmp}' in script
    assert 'export GAUSS_SCRDIR="$ts_remote_scratch_dir"' in script
    assert "source /opt/g16/activate.sh 2>> remote_job.stderr" in script
    assert script.index("source /opt/g16/activate.sh") < script.index("set -u")
    assert '"phase":"activation"' in script
    assert 'exit "$activation_rc"' in script
    assert "/opt/g16/g16 < candidate.gjf > candidate.log" in script
    assert '"phase":"scratch_setup"' in script
    assert '"phase":"program"' in script
    assert "trap cleanup_scratch EXIT" in script
    assert "ts-remote-program-status/1" in script
    assert "program_state=completed" in script


def test_generated_gaussian_script_shares_and_cleans_configured_scratch(tmp_path: Path) -> None:
    scratch_root = tmp_path / "scratch"
    scratch_root.mkdir()
    config, remote_dir = _executable_job(
        tmp_path,
        scratch_root=scratch_root,
        activation_body=(
            'test -d "$GAUSS_SCRDIR"\n'
            'printf "activated\\n" > "$GAUSS_SCRDIR/activation.marker"\n'
            'export TMPDIR=/tmp/activation-overrode-scratch\n'
            'export GAUSS_SCRDIR=/tmp/activation-overrode-scratch\n'
            "return 0\n"
        ),
    )
    script = remote_dir / "job.pbs"
    script.write_text(render_job_script(config), encoding="utf-8")

    completed = subprocess.run(
        ["bash", str(script)],
        cwd=remote_dir,
        env={**os.environ, "PBS_JOBID": "123.cluster"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    status_record = json.loads((remote_dir / "program_status.json").read_text(encoding="utf-8"))
    assert status_record["state"] == "completed"
    assert status_record["phase"] == "program"
    assert status_record["exit_status"] == 0
    scratch_path = Path((remote_dir / "candidate.log").read_text(encoding="utf-8").strip())
    assert scratch_path.parent == scratch_root
    assert not scratch_path.exists()
    assert list(scratch_root.iterdir()) == []


def test_generated_gaussian_script_records_activation_failure_and_cleans_scratch(tmp_path: Path) -> None:
    scratch_root = tmp_path / "scratch"
    scratch_root.mkdir()
    config, remote_dir = _executable_job(
        tmp_path,
        scratch_root=scratch_root,
        activation_body='printf "activation failed\\n" >&2\nreturn 7\n',
    )
    script = remote_dir / "job.pbs"
    script.write_text(render_job_script(config), encoding="utf-8")

    completed = subprocess.run(
        ["bash", str(script)],
        cwd=remote_dir,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 7
    status_record = json.loads((remote_dir / "program_status.json").read_text(encoding="utf-8"))
    assert status_record["state"] == "failed"
    assert status_record["phase"] == "activation"
    assert status_record["exit_status"] == 7
    assert "activation failed" in (remote_dir / "remote_job.stderr").read_text(encoding="utf-8")
    assert not (remote_dir / "candidate.log").exists()
    assert list(scratch_root.iterdir()) == []


def test_generated_gaussian_script_records_unavailable_scratch_root(tmp_path: Path) -> None:
    scratch_root = tmp_path / "missing-scratch"
    config, remote_dir = _executable_job(
        tmp_path,
        scratch_root=scratch_root,
        activation_body="return 0\n",
    )
    script = remote_dir / "job.pbs"
    script.write_text(render_job_script(config), encoding="utf-8")

    completed = subprocess.run(
        ["bash", str(script)],
        cwd=remote_dir,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode != 0
    status_record = json.loads((remote_dir / "program_status.json").read_text(encoding="utf-8"))
    assert status_record["state"] == "failed"
    assert status_record["phase"] == "scratch_setup"
    assert status_record["exit_status"] != 0
    assert not (remote_dir / "candidate.log").exists()


def test_torque_parser_and_terminal_c_do_not_imply_program_failure() -> None:
    records = parse_records(
        """Job Id: 207100.cluster.hpc
    Job_Name = calc_1
    job_state = C
    Resource_List.walltime = 04:00:00
""",
        "Job Id",
    )

    assert records["207100.cluster.hpc"]["job_state"] == "C"
    assert records["207100.cluster.hpc"]["Resource_List.walltime"] == "04:00:00"
    assert scheduler_semantics("C", None) == ("completed", "not_run", None)
    assert scheduler_semantics("C", 1) == ("failed", "failed", "remote_program_failed")


def test_program_status_remains_authoritative_after_qstat_history_expires(tmp_path: Path) -> None:
    config = _job(tmp_path)

    class Client:
        def read_text(self, _path, *, check=True, max_bytes=0):
            del check, max_bytes
            return (
                '{"schema_version":"ts-remote-program-status/1",'
                '"state":"completed","exit_status":0}'
            )

        def run(self, argv, *, check=True):
            del argv, check
            return CommandResult(("ssh",), 153, "", "Unknown Job Id")

    observed = status(config, "207100.cluster.hpc", client=Client())

    assert observed.state == "completed"
    assert observed.program_status == "completed"
    assert observed.exit_status == 0
    assert observed.scheduler_query_error == "Unknown Job Id"


@pytest.mark.parametrize(
    ("phase", "error_class"),
    [
        ("scratch_setup", "remote_scratch_failed"),
        ("activation", "remote_activation_failed"),
        ("program", "remote_program_failed"),
    ],
)
def test_program_failure_phase_maps_to_specific_remote_error(
    tmp_path: Path,
    phase: str,
    error_class: str,
) -> None:
    config = _job(tmp_path)

    class Client:
        def read_text(self, _path, *, check=True, max_bytes=0):
            del check, max_bytes
            return json.dumps(
                {
                    "schema_version": "ts-remote-program-status/1",
                    "state": "failed",
                    "exit_status": 7,
                    "phase": phase,
                }
            )

        def run(self, argv, *, check=True):
            del check
            return CommandResult(tuple(argv), 153, "", "Unknown Job Id")

    observed = status(config, "207100.cluster.hpc", client=Client())

    assert observed.state == "failed"
    assert observed.program_status == "failed"
    assert observed.exit_status == 7
    assert observed.error_class == error_class


def test_status_rejects_scheduler_record_for_a_different_job(tmp_path: Path) -> None:
    config = _job(tmp_path)

    class Client:
        def read_text(self, _path, *, check=True, max_bytes=0):
            del check, max_bytes
            return ""

        def run(self, argv, *, check=True):
            del check
            return CommandResult(
                tuple(argv),
                0,
                "Job Id: 207999.cluster.hpc\n    job_state = R\n",
                "",
            )

    with pytest.raises(RemoteError, match="requested job ID"):
        status(config, "207100.cluster.hpc", client=Client())


def test_collection_verifies_remote_and_local_hash_without_scheduler_query(tmp_path: Path) -> None:
    config = _job(tmp_path)
    payload = b"Normal termination of Gaussian 16\n"
    digest = hashlib.sha256(payload).hexdigest()

    class Client:
        def run(self, argv, *, check=True):
            del check
            if argv[0] == "sha256sum":
                return CommandResult(tuple(argv), 0, f"{digest}  candidate.log\n", "")
            if argv[0] == "wc":
                return CommandResult(tuple(argv), 0, f"{len(payload)} candidate.log\n", "")
            raise AssertionError(f"unexpected remote command: {argv}")

        def download(self, _remote_path, destination):
            destination.write_bytes(payload)
            return CommandResult(("scp",), 0, "", "")

    downloaded, manifest = collect(
        config,
        ["candidate.log"],
        tmp_path / "collected",
        client=Client(),
    )

    assert downloaded == ["candidate.log"]
    assert manifest[0]["sha256"] == f"sha256:{digest}"
    assert (tmp_path / "collected/candidate.log").read_bytes() == payload


def test_submit_script_uses_atomic_lock_and_durable_scheduler_outputs() -> None:
    script = _submit_script()

    assert "mkdir -- \"$lock\"" in script
    assert "state=started" in script
    assert ".ts-remote/qsub.stdout" in script
    assert ".ts-remote/qsub.stderr" in script
    assert "state=accepted" in script
    assert "state=rejected" in script
    assert '"$qsub_command" "$script_name"' in script


def test_submit_rejects_remote_path_escape_before_any_ssh_action(tmp_path: Path) -> None:
    config = replace(_job(tmp_path), remote_dir="/tmp/outside")

    class Client:
        def __getattr__(self, name):
            raise AssertionError(f"SSH action must not occur: {name}")

    with pytest.raises(RemotePreSubmitError) as captured:
        submit(config, client=Client())

    assert captured.value.phase == "pre_submit_preparation"
    assert "outside the configured remote_root" in str(captured.value.cause)


def test_submit_reconciles_durable_receipt_after_ssh_disconnect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _job(tmp_path)
    script_digest = hashlib.sha256(render_job_script(config).encode("utf-8")).hexdigest()

    class Client:
        def run_script(self, *_args, **_kwargs):
            raise TimeoutError("SSH disconnected after request start")

    monkeypatch.setattr("ts_remote.lifecycle.ensure_directory", lambda *_args: None)
    monkeypatch.setattr(
        "ts_remote.lifecycle.upload_verified",
        lambda _client, source, remote_dir, name: TransferRecord(
            remote_path=f"{remote_dir}/{name}",
            size=source.stat().st_size,
            sha256="sha256:" + "a" * 64,
        ),
    )
    monkeypatch.setattr(
        "ts_remote.lifecycle.read_submission_record",
        lambda *_args, **_kwargs: {
            "schema_version": "ts-remote-submission/1",
            "submission_id": config.submission_id,
            "state": "accepted",
            "script_sha256": script_digest,
            "job_id": "207100.cluster.hpc",
            "updated_at": "2026-08-12T00:00:00Z",
        },
    )

    receipt = submit(config, client=Client())

    assert receipt.scheduler_id == "207100.cluster.hpc"
    assert receipt.script_sha256 == script_digest


def test_submit_disconnect_without_durable_record_is_ambiguous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _job(tmp_path)

    class Client:
        def run_script(self, *_args, **_kwargs):
            raise TimeoutError("SSH disconnected after request start")

    monkeypatch.setattr("ts_remote.lifecycle.ensure_directory", lambda *_args: None)
    monkeypatch.setattr(
        "ts_remote.lifecycle.upload_verified",
        lambda _client, source, remote_dir, name: TransferRecord(
            remote_path=f"{remote_dir}/{name}",
            size=source.stat().st_size,
            sha256="sha256:" + "a" * 64,
        ),
    )
    monkeypatch.setattr(
        "ts_remote.lifecycle.read_submission_record",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("record missing")),
    )

    with pytest.raises(RemoteSubmissionAmbiguous) as captured:
        submit(config, client=Client())

    assert captured.value.record["phase"] == "submit_request_started"
    assert "SSH disconnected" in str(captured.value.record["error"])
    assert "record missing" in str(captured.value.record["reconciliation_error"])


def test_control_records_reject_duplicate_fields() -> None:
    with pytest.raises(Exception, match="duplicate fields"):
        _parse_record("state=started\nstate=accepted\n")


def test_control_records_reject_invalid_field_names() -> None:
    with pytest.raises(Exception, match="invalid data"):
        _parse_record("State=started\n")


def test_control_records_accept_versioned_submission_receipt() -> None:
    record = _parse_record(
        "\n".join(
            [
                "schema_version=ts-remote-submission/1",
                "submission_id=tsjob_ws_0123456789abcdef01234567_calc_1_0123456789abcdef",
                "state=accepted",
                f"script_sha256={'a' * 64}",
                "qsub_exit=0",
                "job_id=207217[3].cluster.hpc",
                "updated_at=2026-08-12T11:23:53Z",
            ]
        )
    )

    assert record["schema_version"] == "ts-remote-submission/1"
    assert record["state"] == "accepted"
    assert record["job_id"] == "207217[3].cluster.hpc"


def test_upload_publishes_without_overwriting_remote_target(tmp_path: Path) -> None:
    source = tmp_path / "input.xyz"
    source.write_bytes(b"1\ninput\nH 0 0 0\n")

    class Client:
        def __init__(self):
            self.files = {}

        def upload(self, local, remote):
            self.files[remote] = local.read_bytes()
            return CommandResult(("scp",), 0, "", "")

        def run(self, argv, *, check=True):
            del check
            path = argv[-1]
            if argv[0] == "sha256sum":
                payload = self.files.get(path)
                if payload is None:
                    return CommandResult(tuple(argv), 1, "", "missing")
                digest = hashlib.sha256(payload).hexdigest()
                return CommandResult(tuple(argv), 0, f"{digest}  {path}\n", "")
            if argv[0] == "ln":
                source_path, destination = argv[-2:]
                if destination in self.files:
                    return CommandResult(tuple(argv), 1, "", "exists")
                self.files[destination] = self.files[source_path]
                return CommandResult(tuple(argv), 0, "", "")
            if argv[0] == "rm":
                self.files.pop(path, None)
                return CommandResult(tuple(argv), 0, "", "")
            raise AssertionError(argv)

    client = Client()
    record = upload_verified(client, source, "/remote/ts/run", "input.xyz")

    assert client.files["/remote/ts/run/input.xyz"] == source.read_bytes()
    assert not any(".upload-" in path for path in client.files)
    assert record.remote_path == "/remote/ts/run/input.xyz"


def test_collection_refuses_to_overwrite_local_artifact(tmp_path: Path) -> None:
    config = _job(tmp_path)
    destination = tmp_path / "collected/candidate.log"
    destination.parent.mkdir()
    destination.write_text("existing\n", encoding="utf-8")

    with pytest.raises(RemoteError, match="already exists"):
        collect(config, ["candidate.log"], destination.parent, client=object())

    assert destination.read_text(encoding="utf-8") == "existing\n"


def test_doctor_is_unhealthy_when_storage_or_software_is_unavailable(tmp_path: Path) -> None:
    profile = _profile(tmp_path)

    class Client:
        def run(self, argv, *, check=True):
            del check
            if argv[:2] == ["test", "-d"]:
                return CommandResult(tuple(argv), 1, "", "not writable")
            return CommandResult(tuple(argv), 0, "/opt/g16/g16\n", "")

        def run_script(self, _script, _args, *, check=True):
            del check
            return CommandResult(("ssh",), 0, "", "")

    checks = _doctor(Client(), profile)

    assert checks["remote_root_writable"] is False
    assert checks["software"]["gaussian"]["command_available"] is True
    assert checks["ok"] is False
