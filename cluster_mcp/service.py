"""Application service that enforces authorization before backend operations."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import stat
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .audit import AuditLogger
from .auth import AuthRegistry, Principal
from .config import AppConfig, SoftwareProfile
from .errors import ConfigurationError, SchedulerError, SecurityError
from .models import (
    JobSubmission,
    ResourceRequest,
    validate_arguments,
    validate_environment,
    validate_job_id,
    validate_job_name,
)
from .ownership import JobOwnershipStore
from .runner import CommandRunner
from .schedulers import OpenPBSBackend, TorqueBackend
from .security import WorkspacePolicy, current_username, sha256_regular_file
from .software import SoftwareRegistry
from .storage import StorageService
from .ts_jobs import (
    TSSubmissionStore,
    validate_ts_submission_id,
    validate_ts_submission_request,
)


class ClusterService:
    def __init__(
        self,
        config: AppConfig,
        *,
        principal: str | None = None,
        auth_method: str = "none",
        system: bool = False,
    ) -> None:
        self.config = config
        self.actor = current_username()
        self.auth_registry = AuthRegistry(config.auth, config.workspace.root)
        self.auth_context = self.auth_registry.authenticate(
            principal, auth_method=auth_method, system=system
        )
        self.session_principal = self.auth_registry.current(self.auth_context)
        self.scheduler_policy = WorkspacePolicy(config.workspace.root)
        visible_root = config.workspace.root
        if self.session_principal.workspace_prefix is not None:
            visible_root /= self.session_principal.workspace_prefix
        self.policy = WorkspacePolicy(visible_root)
        self.storage = StorageService(replace(config.workspace, root=visible_root), self.policy)
        self.runner = CommandRunner(
            timeout_seconds=config.scheduler.command_timeout_seconds,
            max_output_bytes=config.scheduler.max_command_output_bytes,
        )
        backend_class = OpenPBSBackend if config.scheduler.backend == "openpbs" else TorqueBackend
        self.scheduler = backend_class(config.scheduler, self.scheduler_policy, self.runner)
        self.software = SoftwareRegistry(config.software)
        self.audit = AuditLogger(
            enabled=config.audit.enabled,
            path=config.audit.path,
            actor=self.actor,
            principal=self.auth_context.principal,
            auth_method=self.auth_context.auth_method,
            session_id=self.auth_context.session_id,
        )
        self.script_snapshot_root = config.workspace.root / ".cluster_mcp" / "script_snapshots"
        self.ownership = JobOwnershipStore(
            config.workspace.root / ".cluster_mcp" / "job_ownership.sqlite3"
        )
        self.ts_submissions = TSSubmissionStore(
            config.workspace.root / ".cluster_mcp" / "ts_submissions.sqlite3"
        )

    def initialize(self) -> None:
        self.scheduler_policy.initialize()
        self._initialize_principal_workspace()
        self.storage.initialize()
        self.scheduler.initialize()
        self.script_snapshot_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.ownership.initialize()
        self.ts_submissions.initialize()
        self.software.load_entry_points()

    def _initialize_principal_workspace(self) -> None:
        prefix = self.session_principal.workspace_prefix
        if prefix is None:
            return
        current = self.scheduler_policy.root
        for part in prefix.parts:
            current /= part
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                current.mkdir(mode=0o700)
                metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise SecurityError("Principal workspace path must contain only directories")
            os.chmod(current, 0o700)

    def _require_any(self, *scopes: str) -> Principal:
        try:
            principal = self.auth_registry.require_any(self.auth_context, *scopes)
            if principal.workspace_prefix != self.session_principal.workspace_prefix:
                raise SecurityError("Client authorization changed; reconnect before continuing")
            return principal
        except SecurityError:
            self.audit.write(
                "auth.authorization_denied",
                success=False,
                details={"required_any": list(scopes)},
            )
            raise

    def capabilities(self) -> dict[str, Any]:
        self._require_any("cluster:read")
        transport = "streamable-http" if self.auth_context.auth_method == "http-bearer" else "stdio"
        software = self.software.describe()
        return {
            "server": "cluster-mcp",
            "version": __version__,
            "transport": transport,
            "actor": self.actor,
            "scheduler": self.config.scheduler.backend,
            "workspace": str(self.policy.root),
            "authentication": self.auth_registry.details(self.auth_context),
            "allowed_queues": list(self.config.scheduler.allowed_queues),
            "gpu_queues": list(self.config.scheduler.gpu_queues),
            "max_nodes": self.config.scheduler.max_nodes,
            "job_submission_enabled": self.config.scheduler.allow_submission,
            "job_control_enabled": self.config.scheduler.allow_job_control,
            "other_user_queries_enabled": self.config.scheduler.allow_other_users,
            "file_transfer": {
                "max_upload_bytes": self.config.workspace.max_upload_bytes,
                "max_chunk_bytes": self.config.workspace.max_chunk_bytes,
                "base64_chunked": True,
            },
            "software": software,
            "security_notes": [
                "All file paths are relative to the authenticated principal workspace.",
                "PBS commands are executed as argv without a shell.",
                "Job control is restricted to the server operating-system user.",
                "GPU IDs are manually bound because PBS does not isolate devices here.",
                (
                    "HTTP access requires TLS, a bearer token, and a direct-client IP allowlist."
                    if transport == "streamable-http"
                    else "Stdio remote access is authenticated by an SSH forced command."
                ),
            ],
        }

    def list_queues(self) -> dict[str, Any]:
        self._require_any("cluster:read")
        return {"queues": self.scheduler.list_queues()}

    def list_nodes(self) -> dict[str, Any]:
        self._require_any("cluster:read")
        return {"nodes": self.scheduler.list_nodes()}

    def list_jobs(self, owner: str | None = None) -> dict[str, Any]:
        principal = self._require_any("jobs:read", "jobs:read:own")
        selected_owner = owner or self.actor
        if "jobs:read" not in principal.scopes and selected_owner != self.actor:
            raise SecurityError("Client may only query its own submitted jobs")
        if selected_owner != self.actor and not self.config.scheduler.allow_other_users:
            raise SecurityError("Querying other users' jobs is disabled")
        if not selected_owner or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
            for character in selected_owner
        ):
            raise SecurityError("Invalid job owner name")
        jobs = self.scheduler.list_jobs(selected_owner)
        if "jobs:read" not in principal.scopes:
            owned = self.ownership.filter_owned(
                [str(job.get("id", "")) for job in jobs], principal=principal.name
            )
            jobs = [job for job in jobs if job.get("id") in owned]
        return {"owner": selected_owner, "jobs": jobs}

    def get_job(self, job_id: str, *, include_history: bool = False) -> dict[str, Any]:
        principal = self._require_any("jobs:read", "jobs:read:own")
        job = self.scheduler.get_job(validate_job_id(job_id), include_history=include_history)
        if job.get("owner") != self.actor and not self.config.scheduler.allow_other_users:
            raise SecurityError("The requested job is not owned by the server user")
        selected_job_id = str(job.get("id", job_id))
        job_principal = self.ownership.principal_for(selected_job_id)
        if "jobs:read" not in principal.scopes and job_principal != principal.name:
            raise SecurityError("Client may only query its own submitted jobs")
        if job_principal is not None:
            job["mcp_principal"] = job_principal
        return job

    def _require_owned_active_job(self, job_id: str, principal: Principal) -> dict[str, Any]:
        job = self.scheduler.get_job(validate_job_id(job_id), include_history=False)
        if job.get("owner") != self.actor:
            raise SecurityError("Job control is restricted to jobs owned by the server user")
        if "jobs:control" not in principal.scopes:
            selected_job_id = str(job.get("id", job_id))
            if self.ownership.principal_for(selected_job_id) != principal.name:
                raise SecurityError("Client may only control its own submitted jobs")
        return job

    def _require_ts_active_job(self, job_id: str) -> dict[str, Any]:
        job = self.scheduler.get_job(validate_job_id(job_id), include_history=False)
        if job.get("owner") != self.actor:
            raise SecurityError("TS job control is restricted to jobs owned by the server user")
        return job

    def control_job(
        self, action: str, job_id: str, *, confirmation: str | None = None
    ) -> dict[str, Any]:
        principal = self._require_any("jobs:control", "jobs:control:own")
        validated = validate_job_id(job_id)
        job = self._require_owned_active_job(validated, principal)
        if action == "hold":
            result = self.scheduler.hold(validated)
        elif action == "release":
            result = self.scheduler.release(validated)
        elif action == "delete":
            if confirmation != validated:
                raise SecurityError(
                    "Deleting a job requires confirmation equal to the exact job_id"
                )
            result = self.scheduler.delete(validated)
        else:
            raise SecurityError("Unsupported job control action")
        self.audit.write(
            f"job.{action}",
            success=True,
            details={"job_id": validated, "previous_state": job.get("state")},
        )
        return result

    def alter_job_walltime(self, job_id: str, walltime: str) -> dict[str, Any]:
        principal = self._require_any("jobs:control", "jobs:control:own")
        validated = validate_job_id(job_id)
        job = self._require_owned_active_job(validated, principal)
        result = self.scheduler.alter_walltime(validated, walltime)
        self.audit.write(
            "job.alter_walltime",
            success=True,
            details={
                "job_id": validated,
                "previous_state": job.get("state"),
                "walltime": result["walltime"],
            },
        )
        return result

    def _resources(
        self,
        *,
        nodes: int,
        ncpus: int,
        memory: str,
        walltime: str,
        ngpus: int,
        mpiprocs: int | None,
        ompthreads: int | None,
        host: str | None,
        place: str | None,
    ) -> ResourceRequest:
        return ResourceRequest(
            nodes=nodes,
            ncpus=ncpus,
            memory=memory,
            walltime=walltime,
            ngpus=ngpus,
            mpiprocs=mpiprocs,
            ompthreads=ompthreads,
            host=host,
            place=place,
        ).validate(max_nodes=self.config.scheduler.max_nodes)

    def _submission(
        self,
        *,
        name: str,
        queue: str,
        workdir: str,
        body_lines: tuple[str, ...],
        environment: dict[str, str] | None,
        gpu_devices: list[int] | None,
        metadata: dict[str, Any],
        nodes: int,
        ncpus: int,
        memory: str,
        walltime: str,
        ngpus: int,
        mpiprocs: int | None,
        ompthreads: int | None,
        host: str | None,
        place: str | None,
    ) -> JobSubmission:
        selected_workdir = self.policy.require_directory(workdir)
        return JobSubmission(
            name=validate_job_name(name),
            queue=queue,
            workdir=str(selected_workdir),
            resources=self._resources(
                nodes=nodes,
                ncpus=ncpus,
                memory=memory,
                walltime=walltime,
                ngpus=ngpus,
                mpiprocs=mpiprocs,
                ompthreads=ompthreads,
                host=host,
                place=place,
            ),
            body_lines=body_lines,
            environment=validate_environment(environment),
            gpu_devices=tuple(gpu_devices or ()),
            metadata=metadata,
        )

    def submit_script(
        self,
        *,
        script_path: str,
        name: str,
        queue: str,
        workdir: str,
        nodes: int = 1,
        ncpus: int = 1,
        memory: str = "4gb",
        walltime: str = "01:00:00",
        ngpus: int = 0,
        mpiprocs: int | None = None,
        ompthreads: int | None = None,
        host: str | None = None,
        place: str | None = None,
        environment: dict[str, str] | None = None,
        gpu_devices: list[int] | None = None,
    ) -> dict[str, Any]:
        principal = self._require_any("jobs:submit")
        return self._submit_script(
            principal=principal,
            script_path=script_path,
            name=name,
            queue=queue,
            workdir=workdir,
            nodes=nodes,
            ncpus=ncpus,
            memory=memory,
            walltime=walltime,
            ngpus=ngpus,
            mpiprocs=mpiprocs,
            ompthreads=ompthreads,
            host=host,
            place=place,
            environment=environment,
            gpu_devices=gpu_devices,
        )

    def _submit_script(
        self,
        *,
        principal: Principal,
        script_path: str,
        name: str,
        queue: str,
        workdir: str,
        nodes: int = 1,
        ncpus: int = 1,
        memory: str = "4gb",
        walltime: str = "01:00:00",
        ngpus: int = 0,
        mpiprocs: int | None = None,
        ompthreads: int | None = None,
        host: str | None = None,
        place: str | None = None,
        environment: dict[str, str] | None = None,
        gpu_devices: list[int] | None = None,
        expected_source_sha256: str | None = None,
        metadata: dict[str, Any] | None = None,
        script_prelude: tuple[str, ...] = (),
        scheduler_accept_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        script = self.policy.require_file(script_path)
        if script.stat().st_size > 1024 * 1024:
            raise SecurityError("Submitted shell scripts may not exceed 1 MiB")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        source_descriptor = os.open(script, flags)
        try:
            source_metadata = os.fstat(source_descriptor)
            if not stat.S_ISREG(source_metadata.st_mode) or source_metadata.st_size > 1024 * 1024:
                raise SecurityError("Submitted path must remain a regular script of at most 1 MiB")
            chunks: list[bytes] = []
            received = 0
            while received <= 1024 * 1024:
                chunk = os.read(source_descriptor, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
                received += len(chunk)
        finally:
            os.close(source_descriptor)
        script_bytes = b"".join(chunks)
        if len(script_bytes) > 1024 * 1024:
            raise SecurityError("Submitted shell scripts may not exceed 1 MiB")
        source_digest = hashlib.sha256(script_bytes).hexdigest()
        if expected_source_sha256 is not None and source_digest != expected_source_sha256:
            raise SecurityError("Submitted script does not match the TS input manifest")
        snapshot = self.script_snapshot_root / f"{uuid.uuid4().hex}.sh"
        snapshot_descriptor = os.open(snapshot, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            view = memoryview(script_bytes)
            while view:
                written = os.write(snapshot_descriptor, view)
                view = view[written:]
            os.fsync(snapshot_descriptor)
        finally:
            os.close(snapshot_descriptor)
        submission = self._submission(
            name=name,
            queue=queue,
            workdir=workdir,
            body_lines=(
                *script_prelude,
                f"exec /usr/bin/env bash -- {shlex.quote(str(snapshot))}",
            ),
            environment=environment,
            gpu_devices=gpu_devices,
            metadata={
                "kind": "uploaded_script",
                "source": self.policy.relative_name(script),
                "source_sha256": source_digest,
                "snapshot": str(snapshot),
                **(metadata or {}),
            },
            nodes=nodes,
            ncpus=ncpus,
            memory=memory,
            walltime=walltime,
            ngpus=ngpus,
            mpiprocs=mpiprocs,
            ompthreads=ompthreads,
            host=host,
            place=place,
        )
        try:
            result = self.scheduler.submit(submission)
            if scheduler_accept_callback is not None:
                scheduler_accept_callback(result)
        except Exception:
            self.audit.write(
                "job.submit_script", success=False, details={"name": name, "queue": queue}
            )
            raise
        self.ownership.record(
            str(result["job_id"]),
            principal=principal.name,
            actor=self.actor,
            metadata={
                "kind": "uploaded_script",
                "name": name,
                "queue": queue,
                "workdir": submission.workdir,
                "source_sha256": source_digest,
                "wrapper_sha256": result.get("script_sha256"),
                **(metadata or {}),
            },
        )
        self.audit.write(
            "job.submit_script",
            success=True,
            details={
                "job_id": result["job_id"],
                "name": name,
                "queue": queue,
                "script": script_path,
            },
        )
        result["source_script_sha256"] = source_digest
        return result

    def _ts_software_profile(
        self,
        backend: str,
        execution: dict[str, Any],
    ) -> SoftwareProfile | None:
        profile = self.software.profiles.get(backend)
        if profile is None:
            if backend == "gaussian":
                raise ConfigurationError(
                    "TS backend 'gaussian' requires a matching server software profile"
                )
            return None
        queue = str(execution["queue"])
        if queue not in profile.allowed_queues:
            raise SecurityError(
                f"TS backend profile {backend!r} is not allowed in queue {queue!r}"
            )
        if profile.requires_gpu and int(execution["ngpus"]) < 1:
            raise SecurityError(f"TS backend profile {backend!r} requires at least one GPU")
        if profile.activation_script is not None and not profile.activation_script.is_file():
            raise ConfigurationError(
                f"Activation script for TS backend profile {backend!r} is missing: "
                f"{profile.activation_script}"
            )
        return profile

    def submit_ts_job(self, request: dict[str, Any]) -> dict[str, Any]:
        principal = self._require_any("ts:submit")
        normalized = validate_ts_submission_request(request)
        replay = self.ts_submissions.replay(normalized, principal=principal.name)
        if replay is not None:
            return {**replay, "replayed": True}
        execution = normalized["execution"]
        profile = self._ts_software_profile(str(normalized["backend"]), execution)
        script_digest = self._verify_ts_files(normalized)
        replay = self.ts_submissions.reserve(normalized, principal=principal.name)
        if replay is not None:
            return {**replay, "replayed": True}

        submission_id = str(normalized["submission_id"])
        environment = {
            **execution["environment"],
            **(profile.environment if profile is not None else {}),
            "TS_CLUSTER_SUBMISSION_ID": submission_id,
            "TS_CLUSTER_INTENT_ID": str(normalized["intent_id"]),
            "TS_CLUSTER_INTENT_DIGEST": str(normalized["intent_digest"]),
        }
        deterministic_name = "ts_" + hashlib.sha256(submission_id.encode("utf-8")).hexdigest()[:12]
        self.ts_submissions.mark_submitting(submission_id)

        def record_scheduler_accept(raw: dict[str, Any]) -> None:
            job_id = validate_job_id(str(raw.get("job_id", "")))
            self.ts_submissions.mark_scheduler_accepted(submission_id, job_id=job_id)

        try:
            raw = self._submit_script(
                principal=principal,
                script_path=str(normalized["script_path"]),
                name=deterministic_name,
                queue=str(execution["queue"]),
                workdir=str(normalized["workdir"]),
                nodes=int(execution["nodes"]),
                ncpus=int(execution["ncpus"]),
                memory=str(execution["memory"]),
                walltime=str(execution["walltime"]),
                ngpus=int(execution["ngpus"]),
                mpiprocs=execution["mpiprocs"],
                ompthreads=execution["ompthreads"],
                host=execution["host"],
                place=execution["place"],
                environment=environment,
                gpu_devices=list(execution["gpu_devices"]),
                expected_source_sha256=script_digest,
                metadata={
                    "kind": "ts_calculation",
                    "submission_id": submission_id,
                    "intent_id": normalized["intent_id"],
                    "intent_digest": normalized["intent_digest"],
                    "node_id": normalized["node_id"],
                    "backend": normalized["backend"],
                    "input_manifest": normalized["input_manifest"],
                    "expected_artifacts": normalized["expected_artifacts"],
                    "software_profile": profile.name if profile is not None else None,
                },
                script_prelude=(
                    (f"source {shlex.quote(str(profile.activation_script))}",)
                    if profile is not None and profile.activation_script is not None
                    else ()
                ),
                scheduler_accept_callback=record_scheduler_accept,
            )
            result = {
                "schema_version": "ts-cluster-submission-result/1",
                "submission_id": submission_id,
                "intent_id": normalized["intent_id"],
                "intent_digest": normalized["intent_digest"],
                "node_id": normalized["node_id"],
                "backend": normalized["backend"],
                "job_id": raw["job_id"],
                "state": "submitted",
                "expected_artifacts": normalized["expected_artifacts"],
                "scheduler": raw,
                "replayed": False,
            }
            self.ts_submissions.mark_submitted(
                submission_id,
                job_id=str(raw["job_id"]),
                result=result,
            )
        except Exception as exc:
            self.ts_submissions.mark_ambiguous(submission_id, exc)
            record = self.ts_submissions.get(submission_id)
            result = {
                "schema_version": "ts-cluster-submission-result/1",
                "submission_id": submission_id,
                "intent_id": normalized["intent_id"],
                "intent_digest": normalized["intent_digest"],
                "node_id": normalized["node_id"],
                "backend": normalized["backend"],
                "job_id": record.get("job_id"),
                "state": "ambiguous",
                "expected_artifacts": normalized["expected_artifacts"],
                "scheduler": None,
                "error": record.get("error"),
                "replayed": False,
            }
            self.audit.write(
                "ts_job.submit",
                success=False,
                details={"submission_id": submission_id, "intent_id": normalized["intent_id"]},
            )
            return result
        self.audit.write(
            "ts_job.submit",
            success=True,
            details={
                "submission_id": submission_id,
                "intent_id": normalized["intent_id"],
                "job_id": result["job_id"],
            },
        )
        return result

    def get_ts_submission(self, submission_id: str, *, include_history: bool = False) -> dict[str, Any]:
        principal = self._require_any("ts:read")
        validated = validate_ts_submission_id(submission_id)
        record = self.ts_submissions.find(validated)
        if record is None:
            return {
                "schema_version": "ts-cluster-submission/1",
                "submission_id": validated,
                "found": False,
                "state": "not_found",
                "job_id": None,
                "scheduler": None,
                "scheduler_query": {
                    "outcome": "not_run",
                    "error_class": None,
                    "message": None,
                },
            }
        if record["principal"] != principal.name:
            raise SecurityError("Client may only query its own TS submissions")
        job_id = record.get("job_id")
        scheduler = None
        scheduler_query = {
            "outcome": "not_run",
            "error_class": None,
            "message": None,
        }
        if isinstance(job_id, str) and job_id:
            try:
                scheduler = self.scheduler.get_job(job_id, include_history=include_history)
            except SchedulerError as exc:
                scheduler_query = {
                    "outcome": "failed",
                    "error_class": "history_unavailable" if include_history else "scheduler_unavailable",
                    "message": f"{type(exc).__name__}: {exc}"[:2000],
                }
            else:
                scheduler_query = {
                    "outcome": "succeeded",
                    "error_class": None,
                    "message": None,
                }
        if scheduler is not None:
            if scheduler.get("owner") != self.actor:
                raise SecurityError("TS submission job is not owned by the server user")
        return {
            **record,
            "found": True,
            "scheduler": scheduler,
            "scheduler_query": scheduler_query,
        }

    def control_health(self) -> dict[str, Any]:
        self._require_any("ts:read")
        components: dict[str, dict[str, Any]] = {}
        try:
            registry = self.ts_submissions.health()
        except Exception as exc:
            components["submission_registry"] = {
                "outcome": "failed",
                "error_class": type(exc).__name__,
                "message": str(exc)[:2000],
            }
        else:
            components["submission_registry"] = {"outcome": "succeeded", **registry}

        try:
            metadata = self.policy.root.lstat()
            with os.scandir(self.policy.root) as entries:
                next(entries, None)
            storage_ok = (
                stat.S_ISDIR(metadata.st_mode)
                and not stat.S_ISLNK(metadata.st_mode)
                and os.access(self.policy.root, os.R_OK | os.W_OK | os.X_OK)
            )
        except OSError as exc:
            components["workspace_storage"] = {
                "outcome": "failed",
                "error_class": type(exc).__name__,
                "message": str(exc)[:2000],
            }
        else:
            components["workspace_storage"] = {
                "outcome": "succeeded" if storage_ok else "failed",
                "error_class": None if storage_ok else "workspace_root_invalid",
                "message": None,
            }

        gaussian = self.software.profiles.get("gaussian")
        components["gaussian_profile"] = {
            "outcome": (
                "succeeded"
                if gaussian is not None
                and (gaussian.activation_script is None or gaussian.activation_script.is_file())
                else "failed"
            ),
            "configured": gaussian is not None,
            "activation_script_exists": (
                gaussian.activation_script.is_file()
                if gaussian is not None and gaussian.activation_script is not None
                else gaussian is not None
            ),
        }
        return {
            "schema_version": "ts-cluster-control-health/1",
            "ok": all(item.get("outcome") == "succeeded" for item in components.values()),
            "components": components,
        }

    def cancel_ts_submission(self, submission_id: str, *, confirmation: str) -> dict[str, Any]:
        principal = self._require_any("ts:control")
        validated = validate_ts_submission_id(submission_id)
        record = self.ts_submissions.get(validated)
        if record["principal"] != principal.name:
            raise SecurityError("Client may only control its own TS submissions")
        if not isinstance(record.get("job_id"), str):
            raise SecurityError(
                f"TS submission has no known scheduler job in state {record['state']}"
            )
        job_id = validate_job_id(str(record["job_id"]))
        if confirmation != f"{validated}:{job_id}":
            raise SecurityError("TS cancellation confirmation must equal submission_id:job_id")
        if record["state"] != "cancelled":
            self._require_ts_active_job(job_id)
        replay = self.ts_submissions.begin_cancel(
            validated,
            principal=principal.name,
            job_id=job_id,
        )
        if replay is not None:
            return {**replay, "replayed": True}
        try:
            scheduler = self.scheduler.delete(job_id)
            result = {
                "schema_version": "ts-cluster-cancellation-result/1",
                "submission_id": validated,
                "job_id": job_id,
                "state": "cancelled",
                "scheduler": scheduler,
                "replayed": False,
            }
            self.ts_submissions.mark_cancelled(validated, result)
        except Exception as exc:
            self.ts_submissions.mark_cancellation_ambiguous(validated, exc)
            self.audit.write(
                "ts_job.cancel",
                success=False,
                details={"submission_id": validated, "job_id": job_id},
            )
            raise
        self.audit.write(
            "ts_job.cancel",
            success=True,
            details={"submission_id": validated, "job_id": job_id},
        )
        return result

    def _verify_ts_files(self, request: dict[str, Any]) -> str:
        self.policy.require_directory(str(request["workdir"]))
        script_digest = None
        for item in request["input_manifest"]:
            path = self.policy.require_file(str(item["path"]))
            metadata, digest = sha256_regular_file(path)
            if metadata.st_size != item["size"]:
                raise SecurityError(f"TS input size changed: {item['path']}")
            if digest != item["sha256"]:
                raise SecurityError(f"TS input digest changed: {item['path']}")
            if item["path"] == request["script_path"]:
                script_digest = digest
        for relative in request["expected_artifacts"]:
            output = self.policy.resolve(str(relative), must_exist=False)
            if output.exists() or output.is_symlink():
                raise SecurityError(f"TS expected artifact already exists: {relative}")
            if not output.parent.is_dir():
                raise SecurityError(f"TS expected artifact parent does not exist: {relative}")
        if script_digest is None:
            raise SecurityError("TS script digest is unavailable")
        return script_digest

    def submit_software(
        self,
        *,
        software: str,
        name: str,
        workdir: str,
        arguments: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
        queue: str | None = None,
        nodes: int = 1,
        ncpus: int = 1,
        memory: str = "4gb",
        walltime: str = "01:00:00",
        ngpus: int = 0,
        mpiprocs: int | None = None,
        ompthreads: int | None = None,
        host: str | None = None,
        place: str | None = None,
        environment: dict[str, str] | None = None,
        gpu_devices: list[int] | None = None,
    ) -> dict[str, Any]:
        principal = self._require_any("jobs:submit")
        metadata: dict[str, Any]
        if software in self.software.profiles:
            profile = self.software.profiles[software]
            selected_queue = queue or profile.default_queue
            if selected_queue not in profile.allowed_queues:
                raise SecurityError(
                    f"Software profile {software!r} is not allowed in queue {selected_queue!r}"
                )
            if profile.requires_gpu and ngpus < 1:
                raise SecurityError(f"Software profile {software!r} requires at least one GPU")
            invocation = [*profile.command, *validate_arguments(arguments or [])]
            lines: list[str] = []
            if profile.activation_script is not None:
                if not profile.activation_script.is_file():
                    raise ConfigurationError(
                        f"Activation script for {software!r} is missing: "
                        f"{profile.activation_script}"
                    )
                lines.append(f"source {shlex.quote(str(profile.activation_script))}")
            lines.append(f"exec {shlex.join(invocation)}")
            merged_environment = dict(profile.environment)
            merged_environment.update(environment or {})
            metadata = {"kind": "software_profile", "software": software}
            body_lines = tuple(lines)
        elif software in self.software.adapters:
            if arguments:
                raise SecurityError("Python software adapters accept parameters, not raw arguments")
            adapter = self.software.adapters[software]
            built = adapter.build_body(parameters or {})
            if (
                not isinstance(built, tuple)
                or not built
                or not all(isinstance(line, str) for line in built)
            ):
                raise ConfigurationError(
                    f"Software adapter {software!r} returned an invalid job body"
                )
            if any("\x00" in line for line in built):
                raise ConfigurationError(f"Software adapter {software!r} returned a NUL character")
            selected_queue = queue or self.config.scheduler.allowed_queues[0]
            merged_environment = dict(environment or {})
            metadata = {"kind": "python_adapter", "software": software}
            body_lines = built
        else:
            raise SecurityError(f"Unknown software profile or adapter: {software!r}")

        submission = self._submission(
            name=name,
            queue=selected_queue,
            workdir=workdir,
            body_lines=body_lines,
            environment=merged_environment,
            gpu_devices=gpu_devices,
            metadata=metadata,
            nodes=nodes,
            ncpus=ncpus,
            memory=memory,
            walltime=walltime,
            ngpus=ngpus,
            mpiprocs=mpiprocs,
            ompthreads=ompthreads,
            host=host,
            place=place,
        )
        try:
            result = self.scheduler.submit(submission)
        except Exception:
            self.audit.write(
                "job.submit_software", success=False, details={"software": software, "name": name}
            )
            raise
        self.ownership.record(
            str(result["job_id"]),
            principal=principal.name,
            actor=self.actor,
            metadata={
                "kind": metadata["kind"],
                "software": software,
                "name": name,
                "queue": selected_queue,
                "workdir": submission.workdir,
                "wrapper_sha256": result.get("script_sha256"),
            },
        )
        self.audit.write(
            "job.submit_software",
            success=True,
            details={"job_id": result["job_id"], "software": software, "name": name},
        )
        return result

    def software_catalog(self) -> dict[str, Any]:
        self._require_any("cluster:read")
        return self.software.describe()

    def list_files(self, path: str = ".") -> dict[str, Any]:
        self._require_any("files:read")
        return self.storage.list_files(path)

    def file_info(self, path: str, *, include_sha256: bool = False) -> dict[str, Any]:
        self._require_any("files:read")
        return self.storage.file_info(path, include_sha256=include_sha256)

    def create_directory(self, path: str, *, parents: bool = False) -> dict[str, Any]:
        self._require_any("files:write")
        result = self.storage.create_directory(path, parents=parents)
        self.audit.write("file.mkdir", success=True, details={"path": result["path"]})
        return result

    def ensure_ts_directory(self, path: str) -> dict[str, Any]:
        self._require_any("files:write")
        result = self.storage.ensure_directory(path)
        self.audit.write(
            "ts_file.ensure_directory",
            success=True,
            details={"path": result["path"], "created": result["created"]},
        )
        return result

    def prepare_ts_upload(self, path: str, *, size: int, sha256: str) -> dict[str, Any]:
        self._require_any("files:write")
        result = self.storage.prepare_upload(path, size=size, sha256=sha256)
        self.audit.write(
            "ts_file.prepare_upload",
            success=True,
            details={"path": path, "size": size, "replayed": result["replayed"]},
        )
        return result

    def start_upload(
        self,
        path: str,
        *,
        size: int,
        sha256: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        if overwrite:
            self._require_any("files:overwrite")
        else:
            self._require_any("files:write")
        result = self.storage.start_upload(path, size=size, sha256=sha256, overwrite=overwrite)
        self.audit.write(
            "file.upload_start",
            success=True,
            details={"path": result["path"], "size": size, "overwrite": overwrite},
        )
        return result

    def upload_chunk(self, upload_id: str, *, offset: int, data_base64: str) -> dict[str, Any]:
        self._require_any("files:write")
        return self.storage.upload_chunk(upload_id, offset=offset, data_base64=data_base64)

    def finish_upload(self, upload_id: str) -> dict[str, Any]:
        self._require_any("files:write")
        result = self.storage.finish_upload(upload_id)
        self.audit.write(
            "file.upload_finish",
            success=True,
            details={"path": result["path"], "size": result["size"], "sha256": result["sha256"]},
        )
        return result

    def abort_upload(self, upload_id: str) -> dict[str, Any]:
        self._require_any("files:write")
        return self.storage.abort_upload(upload_id)

    def download_chunk(
        self, path: str, *, offset: int = 0, max_bytes: int | None = None
    ) -> dict[str, Any]:
        self._require_any("files:read")
        return self.storage.download_chunk(path, offset=offset, max_bytes=max_bytes)

    def job_log_chunk(
        self,
        job_id: str,
        *,
        stream: str = "output",
        offset: int = 0,
        max_bytes: int | None = None,
    ) -> dict[str, Any]:
        job = self.get_job(job_id, include_history=True)
        field = {"output": "output_path", "error": "error_path"}.get(stream)
        if field is None:
            raise SecurityError("stream must be output or error")
        raw_path = job.get(field)
        if not isinstance(raw_path, str) or not raw_path:
            raise SecurityError(f"Job does not report an {stream} log path")
        path_text = raw_path.split(":", 1)[1] if ":" in raw_path else raw_path
        absolute = Path(path_text).resolve(strict=False)
        try:
            relative = absolute.relative_to(self.policy.root).as_posix()
        except ValueError as exc:
            raise SecurityError("Job log is outside the configured workspace") from exc
        return self.storage.download_chunk(relative, offset=offset, max_bytes=max_bytes)

    def health_check(self) -> dict[str, Any]:
        return {
            "config": str(self.config.source_path),
            "authentication": {
                **self.auth_registry.details(self.auth_context),
                "principals_file": (
                    str(self.config.auth.principals_file)
                    if self.config.auth.principals_file is not None
                    else None
                ),
            },
            "workspace": {
                "path": str(self.policy.root),
                "exists": self.policy.root.is_dir(),
                "writable": self.policy.root.is_dir() and os.access(self.policy.root, os.W_OK),
            },
            "scheduler": self.scheduler.health_check(),
            "software": self.software.describe(),
        }

    @staticmethod
    def pretty(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, indent=2)
