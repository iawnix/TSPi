from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from cluster_mcp.config import (
    AppConfig,
    AuditSettings,
    AuthSettings,
    HTTPSettings,
    SchedulerSettings,
    SoftwareProfile,
    WorkspaceSettings,
    load_config,
)
from cluster_mcp.errors import ConfigurationError, SecurityError
from cluster_mcp.service import ClusterService
from cluster_mcp.ts_jobs import validate_ts_submission_request
from ts_remote.mcp import (
    MCP_CLIENT_MODE,
    MCPClientError,
    MCPConnectionSettings,
    TSClusterMCPClient,
    SDKToolCaller,
    _structured_result,
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


def _service(
    tmp_path: Path,
    scheduler_type=_Scheduler,
    *,
    software: dict[str, SoftwareProfile] | None = None,
) -> ClusterService:
    tmp_path.mkdir(parents=True, exist_ok=True)
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
    if software is None:
        activation = tmp_path / "activate_gaussian16.sh"
        activation.write_text("export PATH=/opt/gaussian/g16:$PATH\n", encoding="utf-8")
        software = {
            "gaussian": SoftwareProfile(
                name="gaussian",
                description="Gaussian 16",
                command=("/opt/gaussian/bin/gaussian16-run",),
                activation_script=activation,
                default_queue="workq",
                allowed_queues=("workq",),
                environment={"GAUSSIAN16_DEFER_SCRATCH": "1"},
            )
        }
    config = AppConfig(
        source_path=tmp_path / "config.toml",
        workspace=WorkspaceSettings(root=root, min_free_bytes=0),
        scheduler=SchedulerSettings(allowed_queues=("workq",), gpu_queues=()),
        audit=AuditSettings(enabled=False, path=root / ".cluster_mcp" / "audit.jsonl"),
        auth=AuthSettings(required=True, principals_file=auth_file),
        http=HTTPSettings(),
        software=software,
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
    request["execution"]["environment"]["GAUSSIAN16_DEFER_SCRATCH"] = "0"

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
    assert submission.environment["GAUSSIAN16_DEFER_SCRATCH"] == "1"
    assert submission.metadata["kind"] == "ts_calculation"
    assert submission.metadata["software_profile"] == "gaussian"
    assert submission.body_lines[0].startswith("source ")
    assert submission.body_lines[1].startswith("exec /usr/bin/env bash -- ")

    record = service.get_ts_submission(str(request["submission_id"]), include_history=True)
    assert record["state"] == "submitted"
    assert record["scheduler"]["state"] == "F"


def test_example_config_registers_same_name_gaussian_profile() -> None:
    config = load_config(Path(__file__).resolve().parents[1] / "cluster_mcp" / "config.example.toml")

    profile = config.software["gaussian"]
    assert profile.name == "gaussian"
    assert profile.activation_script is not None
    assert profile.environment == {"GAUSSIAN16_DEFER_SCRATCH": "1"}


def test_gaussian_ts_submission_requires_registered_server_profile(tmp_path: Path) -> None:
    service = _service(tmp_path, software={})
    request = _request(service)

    with pytest.raises(ConfigurationError, match="requires a matching server software profile"):
        service.submit_ts_job(request)

    assert service.scheduler.submissions == []
    with pytest.raises(SecurityError, match="Unknown TS submission"):
        service.ts_submissions.get(str(request["submission_id"]))


def test_gaussian_ts_profile_checks_activation_and_queue_before_reservation(tmp_path: Path) -> None:
    missing_activation = tmp_path / "missing-activation.sh"
    profile = SoftwareProfile(
        name="gaussian",
        description="Gaussian 16",
        command=("/opt/gaussian/bin/gaussian16-run",),
        activation_script=missing_activation,
        default_queue="workq",
        allowed_queues=("workq",),
    )
    service = _service(tmp_path, software={"gaussian": profile})
    request = _request(service)

    with pytest.raises(ConfigurationError, match="Activation script.*missing"):
        service.submit_ts_job(request)
    assert service.scheduler.submissions == []

    activation = tmp_path / "activation.sh"
    activation.write_text("export PATH=/opt/gaussian/g16:$PATH\n", encoding="utf-8")
    restricted = SoftwareProfile(
        name="gaussian",
        description="Gaussian 16",
        command=("/opt/gaussian/bin/gaussian16-run",),
        activation_script=activation,
        default_queue="fat",
        allowed_queues=("fat",),
    )
    service = _service(tmp_path / "queue-case", software={"gaussian": restricted})
    request = _request(service, submission_id="tsjob_calc_queue_000001")
    with pytest.raises(SecurityError, match="not allowed in queue"):
        service.submit_ts_job(request)
    assert service.scheduler.submissions == []


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


def test_mcp_error_result_preserves_safe_server_detail() -> None:
    result = SimpleNamespace(
        is_error=True,
        structured_content=None,
        content=[SimpleNamespace(text="Unknown TS submission: tsjob_missing Bearer top-secret")],
    )

    with pytest.raises(MCPClientError, match="Unknown TS submission") as raised:
        _structured_result(result)

    assert "top-secret" not in str(raised.value)
    assert "Bearer [REDACTED]" in str(raised.value)


def test_authenticated_sdk_client_applies_configured_http_timeout(monkeypatch) -> None:
    httpx2 = pytest.importorskip("httpx2")
    mcp = pytest.importorskip("mcp")
    from mcp.client import streamable_http

    observed: dict[str, object] = {}

    class FakeHTTPClient:
        def __init__(self, **kwargs) -> None:
            observed["http"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, _error_type, _error, _traceback) -> None:
            return None

    class FakeMCPClient:
        def __init__(self, target, **kwargs) -> None:
            observed["target"] = target
            observed["mcp"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, _error_type, _error, _traceback) -> None:
            return None

        async def call_tool(self, name, arguments):
            observed["tool"] = (name, arguments)
            return SimpleNamespace(
                is_error=False,
                structured_content={"result": {"ok": True}},
            )

    monkeypatch.setattr(httpx2, "AsyncClient", FakeHTTPClient)
    monkeypatch.setattr(mcp, "Client", FakeMCPClient)
    monkeypatch.setattr(
        streamable_http,
        "streamable_http_client",
        lambda endpoint, *, http_client: (endpoint, http_client),
    )
    caller = SDKToolCaller(
        MCPConnectionSettings(
            "http://127.0.0.1:8765/mcp",
            token="x" * 32,
            timeout_seconds=73,
        )
    )

    assert caller.call_tool("probe", {}) == {"ok": True}
    assert observed["http"] == {
        "headers": {"Authorization": "Bearer " + "x" * 32},
        "timeout": 73,
    }
    assert observed["mcp"]["read_timeout_seconds"] == 73


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
    assert capabilities["software"]["software"][0]["name"] == "gaussian"
    assert capabilities["software"]["software"][0]["activation_script_exists"] is True
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


def test_mcp_sdk_authenticated_http_transport_round_trip(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("mcp")
    uvicorn = pytest.importorskip("uvicorn")
    from cluster_mcp.http_transport import (
        ClientNetworkAllowlistMiddleware,
        transport_security_settings,
    )
    from cluster_mcp.server import create_server

    token = "authenticated-http-test-token-value-1234567890"
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = int(listener.getsockname()[1])

    service = _service(tmp_path)
    http = replace(
        service.config.http,
        port=port,
        public_url=f"http://127.0.0.1:{port}/mcp",
    )
    config = replace(service.config, http=http)
    monkeypatch.setenv("CLUSTER_MCP_HTTP_TOKEN", token)
    mcp_server = create_server(
        config,
        principal="pi-ts",
        auth_method="http-bearer",
        transport="streamable-http",
    )
    app = mcp_server.streamable_http_app(
        host=http.host,
        streamable_http_path=http.path,
        stateless_http=http.stateless,
        json_response=http.json_response,
        transport_security=transport_security_settings(http),
    )
    app = ClientNetworkAllowlistMiddleware(app, http.allowed_client_networks)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(
        target=lambda: asyncio.run(server.serve(sockets=[listener])),
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)

    try:
        assert server.started
        caller = SDKToolCaller(
            MCPConnectionSettings(
                f"http://127.0.0.1:{port}/mcp",
                token=token,
                timeout_seconds=5,
            )
        )
        capabilities = TSClusterMCPClient(caller).capabilities()
        assert capabilities["server"] == "cluster-mcp"
        assert capabilities["authentication"]["principal"] == "pi-ts"
        assert MCP_CLIENT_MODE == "legacy"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()

    assert not thread.is_alive()
