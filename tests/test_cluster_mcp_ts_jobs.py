from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from cluster_mcp.config import (
    AppConfig,
    AuditSettings,
    AuthSettings,
    HTTPSettings,
    SchedulerSettings,
    WorkspaceSettings,
)
from cluster_mcp.errors import SecurityError
from cluster_mcp.service import ClusterService
from cluster_mcp.ts_jobs import validate_ts_submission_request
from ts_remote.mcp import (
    MCPClientError,
    MCPConnectionSettings,
    TSClusterMCPClient,
    SDKToolCaller,
    build_ts_job_request,
)


class _Scheduler:
    def __init__(self, owner: str) -> None:
        self.owner = owner
        self.submissions = []
        self.deleted: list[str] = []

    def submit(self, submission):
        self.submissions.append(submission)
        return {
            "job_id": "42001.cluster",
            "queue": submission.queue,
            "name": submission.name,
            "script_sha256": "a" * 64,
            "record_warning": None,
            "gpu_isolation_warning": None,
        }

    def get_job(self, job_id: str, *, include_history: bool = False):
        return {
            "id": job_id,
            "owner": self.owner,
            "state": "F" if include_history else "Q",
            "exit_status": 0 if include_history else None,
        }

    def delete(self, job_id: str):
        self.deleted.append(job_id)
        return {"job_id": job_id, "action": "delete", "accepted": True}


class _FailingScheduler(_Scheduler):
    def submit(self, submission):
        self.submissions.append(submission)
        raise RuntimeError("qsub transport outcome is unknown")


class _FailingDeleteScheduler(_Scheduler):
    def delete(self, job_id: str):
        self.deleted.append(job_id)
        raise RuntimeError("qdel transport outcome is unknown")


class _ServiceCaller:
    def __init__(self, service: ClusterService) -> None:
        self.service = service
        self.calls: list[str] = []

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append(name)
        if name == "cluster_capabilities":
            return self.service.capabilities()
        if name == "ts_ensure_directory":
            return self.service.ensure_ts_directory(str(arguments["path"]))
        if name == "ts_prepare_upload":
            return self.service.prepare_ts_upload(
                str(arguments["path"]),
                size=int(arguments["size"]),
                sha256=str(arguments["sha256"]),
            )
        if name == "upload_chunk":
            return self.service.upload_chunk(
                str(arguments["upload_id"]),
                offset=int(arguments["offset"]),
                data_base64=str(arguments["data_base64"]),
            )
        if name == "finish_upload":
            return self.service.finish_upload(str(arguments["upload_id"]))
        if name == "abort_upload":
            return self.service.abort_upload(str(arguments["upload_id"]))
        if name == "file_info":
            return self.service.file_info(
                str(arguments["path"]),
                include_sha256=bool(arguments.get("include_sha256", False)),
            )
        if name == "download_chunk":
            return self.service.download_chunk(
                str(arguments["path"]),
                offset=int(arguments.get("offset", 0)),
                max_bytes=(int(arguments["max_bytes"]) if arguments.get("max_bytes") is not None else None),
            )
        if name == "ts_submit_job":
            return self.service.submit_ts_job(dict(arguments["request"]))
        if name == "ts_get_submission":
            return self.service.get_ts_submission(
                str(arguments["submission_id"]),
                include_history=bool(arguments.get("include_history", False)),
            )
        if name == "ts_cancel_submission":
            return self.service.cancel_ts_submission(
                str(arguments["submission_id"]),
                confirmation=str(arguments["confirmation"]),
            )
        raise AssertionError(name)


def _service(tmp_path: Path, scheduler_type=_Scheduler) -> ClusterService:
    root = tmp_path / "cluster"
    auth_file = tmp_path / "auth.toml"
    auth_file.write_text(
        """
[principals.pi-ts]
enabled = true
scopes = ["cluster:read", "files:read", "files:write", "ts:read", "ts:submit", "ts:control"]
workspace_prefix = "pi-ts"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    auth_file.chmod(0o600)
    config = AppConfig(
        source_path=tmp_path / "config.toml",
        workspace=WorkspaceSettings(root=root, min_free_bytes=0),
        scheduler=SchedulerSettings(allowed_queues=("workq",), gpu_queues=()),
        audit=AuditSettings(enabled=False, path=root / ".cluster_mcp" / "audit.jsonl"),
        auth=AuthSettings(required=True, principals_file=auth_file),
        http=HTTPSettings(),
        software={},
    )
    service = ClusterService(config, principal="pi-ts", auth_method="local")
    service.initialize()
    service.scheduler = scheduler_type(service.actor)
    return service


def _request(service: ClusterService, *, submission_id: str = "tsjob_calc_000001") -> dict[str, object]:
    workdir = service.policy.root / "runs" / submission_id
    outputs = workdir / "outputs"
    outputs.mkdir(parents=True)
    script = workdir / "run.sh"
    source = workdir / "candidate.gjf"
    script.write_text("#!/usr/bin/env bash\nset -euo pipefail\ng16 candidate.gjf\n", encoding="utf-8")
    source.write_text("#p hf/3-21g sp\n\nprobe\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")

    def manifest(path: Path) -> dict[str, object]:
        payload = path.read_bytes()
        return {
            "path": path.relative_to(service.policy.root).as_posix(),
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    workdir_ref = workdir.relative_to(service.policy.root).as_posix()
    return {
        "schema_version": "ts-cluster-job/1",
        "submission_id": submission_id,
        "intent_id": "calc_n001_optfreq_001",
        "intent_digest": "sha256:" + "1" * 64,
        "node_id": "n001",
        "backend": "gaussian",
        "script_path": script.relative_to(service.policy.root).as_posix(),
        "workdir": workdir_ref,
        "input_manifest": [manifest(script), manifest(source)],
        "expected_artifacts": [f"{workdir_ref}/outputs/candidate.log"],
        "execution": {
            "queue": "workq",
            "nodes": 1,
            "ncpus": 4,
            "memory": "8gb",
            "walltime": "01:00:00",
            "ngpus": 0,
            "mpiprocs": None,
            "ompthreads": 4,
            "host": None,
            "place": None,
            "environment": {"OMP_STACKSIZE": "1G"},
            "gpu_devices": [],
        },
    }


def test_ts_submission_is_manifest_bound_and_idempotent(tmp_path: Path) -> None:
    service = _service(tmp_path)
    request = _request(service)

    first = service.submit_ts_job(request)
    second = service.submit_ts_job(request)

    assert first["state"] == "submitted"
    assert first["intent_digest"] == request["intent_digest"]
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert len(service.scheduler.submissions) == 1
    submission = service.scheduler.submissions[0]
    assert submission.environment["TS_CLUSTER_SUBMISSION_ID"] == request["submission_id"]
    assert submission.environment["TS_CLUSTER_INTENT_DIGEST"] == request["intent_digest"]
    assert submission.metadata["kind"] == "ts_calculation"

    record = service.get_ts_submission(str(request["submission_id"]), include_history=True)
    assert record["state"] == "submitted"
    assert record["scheduler"]["state"] == "F"


def test_ts_submission_rejects_rebinding_and_changed_inputs(tmp_path: Path) -> None:
    service = _service(tmp_path)
    request = _request(service)
    service.submit_ts_job(request)

    changed = json.loads(json.dumps(request))
    changed["execution"]["walltime"] = "02:00:00"
    with pytest.raises(SecurityError, match="different request"):
        service.submit_ts_job(changed)

    other = _request(service, submission_id="tsjob_calc_000002")
    source = service.policy.root / str(other["input_manifest"][1]["path"])
    source.write_text("changed after manifest\n", encoding="utf-8")
    with pytest.raises(SecurityError, match="size changed|digest changed"):
        service.submit_ts_job(other)
    with pytest.raises(SecurityError, match="Unknown TS submission"):
        service.ts_submissions.get(str(other["submission_id"]))


def test_ambiguous_scheduler_result_blocks_automatic_resubmission(tmp_path: Path) -> None:
    service = _service(tmp_path, _FailingScheduler)
    request = _request(service)

    with pytest.raises(RuntimeError, match="outcome is unknown"):
        service.submit_ts_job(request)
    record = service.ts_submissions.get(str(request["submission_id"]))
    assert record["state"] == "ambiguous"

    with pytest.raises(SecurityError, match="automatic resubmission is forbidden"):
        service.submit_ts_job(request)
    assert len(service.scheduler.submissions) == 1


def test_known_job_id_survives_post_qsub_persistence_failure(tmp_path: Path) -> None:
    service = _service(tmp_path)
    request = _request(service)

    def fail_ownership(*args, **kwargs):
        raise RuntimeError("ownership persistence failed after qsub")

    service.ownership.record = fail_ownership
    with pytest.raises(RuntimeError, match="ownership persistence failed"):
        service.submit_ts_job(request)

    record = service.get_ts_submission(str(request["submission_id"]))
    assert record["state"] == "ambiguous"
    assert record["job_id"] == "42001.cluster"
    assert record["scheduler"]["state"] == "Q"

    confirmation = f"{request['submission_id']}:{record['job_id']}"
    cancelled = service.cancel_ts_submission(
        str(request["submission_id"]),
        confirmation=confirmation,
    )
    assert cancelled["state"] == "cancelled"
    assert service.scheduler.deleted == ["42001.cluster"]


def test_ts_cancellation_requires_submission_and_job_binding(tmp_path: Path) -> None:
    service = _service(tmp_path)
    request = _request(service)
    submitted = service.submit_ts_job(request)

    with pytest.raises(SecurityError, match="submission_id:job_id"):
        service.cancel_ts_submission(str(request["submission_id"]), confirmation=submitted["job_id"])

    confirmation = f"{request['submission_id']}:{submitted['job_id']}"
    first = service.cancel_ts_submission(str(request["submission_id"]), confirmation=confirmation)
    second = service.cancel_ts_submission(str(request["submission_id"]), confirmation=confirmation)
    assert first["state"] == "cancelled"
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert service.scheduler.deleted == [submitted["job_id"]]


def test_ambiguous_cancellation_blocks_automatic_qdel_replay(tmp_path: Path) -> None:
    service = _service(tmp_path, _FailingDeleteScheduler)
    request = _request(service)
    submitted = service.submit_ts_job(request)
    confirmation = f"{request['submission_id']}:{submitted['job_id']}"

    with pytest.raises(RuntimeError, match="qdel transport outcome is unknown"):
        service.cancel_ts_submission(
            str(request["submission_id"]),
            confirmation=confirmation,
        )
    assert service.ts_submissions.get(str(request["submission_id"]))["state"] == "cancellation_ambiguous"

    with pytest.raises(SecurityError, match="automatic cancellation replay is forbidden"):
        service.cancel_ts_submission(
            str(request["submission_id"]),
            confirmation=confirmation,
        )
    assert service.scheduler.deleted == [submitted["job_id"]]


def test_pi_file_scope_cannot_overwrite_manifest_inputs(tmp_path: Path) -> None:
    service = _service(tmp_path)
    request = _request(service)
    source = request["input_manifest"][1]

    with pytest.raises(SecurityError, match="not authorized"):
        service.start_upload(
            str(source["path"]),
            size=int(source["size"]),
            sha256=str(source["sha256"]),
            overwrite=True,
        )


def test_ts_scope_is_not_granted_to_unauthenticated_legacy_clients(tmp_path: Path) -> None:
    request = validate_ts_submission_request(
        {
            "schema_version": "ts-cluster-job/1",
            "submission_id": "tsjob_calc_legacy",
            "intent_id": "calc_legacy",
            "intent_digest": "sha256:" + "2" * 64,
            "node_id": "n001",
            "backend": "xtb",
            "script_path": "runs/job/run.sh",
            "workdir": "runs/job",
            "input_manifest": [
                {"path": "runs/job/run.sh", "size": 1, "sha256": "3" * 64}
            ],
            "expected_artifacts": ["runs/job/outputs/result.out"],
            "execution": {
                "queue": "workq",
                "nodes": 1,
                "ncpus": 1,
                "memory": "1gb",
                "walltime": "00:10:00",
                "ngpus": 0,
                "mpiprocs": None,
                "ompthreads": None,
                "host": None,
                "place": None,
                "environment": {},
                "gpu_devices": [],
            },
        }
    )
    root = tmp_path / "legacy"
    config = AppConfig(
        source_path=tmp_path / "config.toml",
        workspace=WorkspaceSettings(root=root, min_free_bytes=0),
        scheduler=SchedulerSettings(),
        audit=AuditSettings(enabled=False, path=root / "audit.jsonl"),
        auth=AuthSettings(required=False, principals_file=None),
        http=HTTPSettings(),
        software={},
    )
    service = ClusterService(config)
    assert "ts:submit" not in service.session_principal.scopes
    assert request["submission_id"] == "tsjob_calc_legacy"


def test_ts_mcp_client_upload_submit_status_and_download(tmp_path: Path) -> None:
    service = _service(tmp_path)
    caller = _ServiceCaller(service)
    client = TSClusterMCPClient(caller)
    workdir = "runs/tsjob_client_000001"
    client.ensure_directory(f"{workdir}/outputs")

    local = tmp_path / "local"
    local.mkdir()
    script = local / "run.sh"
    source = local / "candidate.gjf"
    script.write_text("#!/usr/bin/env bash\nset -euo pipefail\ng16 candidate.gjf\n", encoding="utf-8")
    source.write_text("#p hf/3-21g sp\n\nprobe\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")
    script_remote = f"{workdir}/run.sh"
    source_remote = f"{workdir}/candidate.gjf"

    first_upload = client.upload_file(script, script_remote, chunk_bytes=7)
    second_upload = client.upload_file(script, script_remote, chunk_bytes=7)
    client.upload_file(source, source_remote, chunk_bytes=11)
    assert first_upload["replayed"] is False
    assert second_upload["replayed"] is True

    execution = {
        "queue": "workq",
        "nodes": 1,
        "ncpus": 4,
        "memory": "8gb",
        "walltime": "01:00:00",
        "ngpus": 0,
        "mpiprocs": None,
        "ompthreads": 4,
        "host": None,
        "place": None,
        "environment": {},
        "gpu_devices": [],
    }
    request = build_ts_job_request(
        submission_id="tsjob_client_000001",
        intent_id="calc_n001_client_001",
        intent_digest="sha256:" + "5" * 64,
        node_id="n001",
        backend="gaussian",
        workdir=workdir,
        script_path=script_remote,
        input_files={script_remote: script, source_remote: source},
        expected_artifacts=[f"{workdir}/outputs/candidate.log"],
        execution=execution,
    )
    receipt = client.submit(request)
    assert receipt.scheduler_id == "42001.cluster"
    assert receipt.metadata["submission_id"] == request["submission_id"]
    assert client.status("tsjob_client_000001", include_history=True)["scheduler"]["state"] == "F"

    tail = client.read_tail(source_remote, max_bytes=16)
    assert tail["data"] == source.read_bytes()[-16:]
    assert tail["size"] == source.stat().st_size

    downloaded = tmp_path / "downloaded.gjf"
    result = client.download_file(source_remote, downloaded, expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    assert downloaded.read_bytes() == source.read_bytes()
    assert result["size"] == source.stat().st_size
    assert "file_info" in caller.calls
    assert "start_upload" not in caller.calls
    assert caller.calls.count("ts_prepare_upload") == 3

    refused = tmp_path / "wrong-digest.gjf"
    with pytest.raises(MCPClientError, match="source SHA-256"):
        client.download_file(source_remote, refused, expected_sha256="0" * 64)
    assert not refused.exists()


def test_mcp_connection_settings_require_tls_and_strong_token() -> None:
    assert MCPConnectionSettings("http://127.0.0.1:8765/mcp").validated().endpoint.endswith("/mcp")
    with pytest.raises(MCPClientError, match="require HTTPS"):
        MCPConnectionSettings("http://cluster.example/mcp").validated()
    with pytest.raises(MCPClientError, match="at least 32"):
        MCPConnectionSettings("https://cluster.example/mcp", token="short").validated()


def test_cluster_mcp_script_resolves_bundled_package_outside_checkout(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(root / "scripts" / "ts_cluster_mcp.py"), "--help"],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "serve" in completed.stdout
    assert "check" in completed.stdout


def test_mcp_sdk_in_memory_transport_exposes_ts_tools(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("mcp")
    from cluster_mcp.server import create_server

    service = _service(tmp_path)
    server = create_server(service.config, principal="pi-ts", auth_method="local")
    caller = SDKToolCaller(
        MCPConnectionSettings("http://127.0.0.1:8765/mcp"),
        server=server,
    )
    client = TSClusterMCPClient(caller)

    capabilities = client.capabilities()
    assert capabilities["server"] == "cluster-mcp"
    assert "ts:submit" in capabilities["authentication"]["scopes"]
    client.ensure_directory("sdk-smoke/outputs")
    assert (service.policy.root / "sdk-smoke" / "outputs").is_dir()

    monkeypatch.setenv("CLUSTER_MCP_HTTP_TOKEN", "x" * 32)
    http_server = create_server(
        service.config,
        principal="pi-ts",
        auth_method="http-bearer",
        transport="streamable-http",
    )
    assert http_server is not None
