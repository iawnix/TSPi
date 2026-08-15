from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.v4_helpers import bootstrap_v4_workspace, start_research_act
from ts_compute import (
    ComputeContractError,
    calculation_status,
    calculation_tail,
    cancel_calculation,
    collect_calculation,
    create_calculation_intent,
    list_calculation_artifacts,
    parse_calculation,
    preflight_calculation,
    prepare_calculation,
    submit_calculation,
)
from ts_compute.contracts import validate_compute_contract
from ts_remote import lifecycle as remote_lifecycle
from ts_remote.errors import RemotePreSubmitError, RemoteSubmissionAmbiguous, RemoteSubmissionRejected
from ts_remote.models import RemoteJobStatus, RemoteReceipt
from ts_workspace.identity import workspace_id


def _workspace(tmp_path: Path) -> tuple[Path, str]:
    workspace = bootstrap_v4_workspace(tmp_path / "workspace")
    act_id = start_research_act(
        workspace,
        objective="Run the Root-selected Gaussian validation calculation.",
        claim_type="transition_state",
    )["act_id"]
    gjf = workspace / "inputs" / "candidate.gjf"
    gjf.write_text(
        "%chk=candidate.chk\n#P B3LYP/6-31G(d) opt=(ts,calcfc) freq\n\nTS\n\n0 1\nH 0 0 0\n\n",
        encoding="utf-8",
    )
    return workspace, act_id


def _artifact_id(workspace: Path, path: str = "inputs/candidate.gjf") -> str:
    return next(
        item["artifact_id"]
        for item in list_calculation_artifacts(workspace)["artifacts"]
        if item["path"] == path
    )


def _request(
    workspace: Path,
    act_id: str,
    *,
    target: dict[str, object] | None = None,
    dry_run: bool = True,
    task_type: str = "opt_freq",
) -> dict[str, object]:
    return {
        "schema_version": "ts-calculation-request/2",
        "act_id": act_id,
        "purpose": "Evaluate the selected candidate with a bound calculation.",
        "attempt_kind": "primary",
        "recalculation_ref": None,
        "backend": "gaussian",
        "task_type": task_type,
        "input_artifacts": [{"input_role": "gjf", "artifact_id": _artifact_id(workspace)}],
        "settings": {},
        "execution_target": target or {"kind": "local"},
        "dry_run": dry_run,
    }


def _create(
    workspace: Path,
    act_id: str,
    *,
    target: dict[str, object] | None = None,
    dry_run: bool = True,
    task_type: str = "opt_freq",
) -> dict:
    return create_calculation_intent(
        workspace,
        _request(workspace, act_id, target=target, dry_run=dry_run, task_type=task_type),
    )


def _remote_resources() -> dict[str, object]:
    return {
        "queue": "workq",
        "nodes": 1,
        "ncpus": 4,
        "memory": "8gb",
        "walltime": "01:00:00",
        "ngpus": 0,
        "mpiprocs": None,
        "ompthreads": 4,
    }


def _remote_request_target() -> dict[str, object]:
    return {
        "kind": "remote",
        "profile": "test_cluster",
        "resources": _remote_resources(),
    }


def _configure_remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ssh_config = tmp_path / "ssh_config"
    ssh_config.write_text("Host test-login\n  HostName login.test\n", encoding="utf-8")
    config = tmp_path / "remote.toml"
    config.write_text(
        f'''default_profile = "test_cluster"

[profiles.test_cluster]
ssh_host = "test-login"
ssh_config = "{ssh_config}"
scheduler = "torque"
remote_root = "/remote/ts"
allowed_queues = ["workq"]
max_nodes = 1

[profiles.test_cluster.software.gaussian]
command = ["g16"]
allowed_queues = ["workq"]
requires_gpu = false
''',
        encoding="utf-8",
    )
    monkeypatch.setenv("TS_REMOTE_CONFIG", str(config))


def _gaussian_log() -> str:
    return "\n".join(
        [
            " Entering Link 1 = synthetic",
            " #P B3LYP/6-31G(d) opt=(ts,calcfc) freq",
            " -------------------------------------------------------------------",
            " SCF Done:  E(RB3LYP) =  -40.123456     A.U. after 10 cycles",
            " Standard orientation:",
            " ---------------------------------------------------------------------",
            " Center     Atomic      Atomic             Coordinates (Angstroms)",
            " Number     Number       Type             X           Y           Z",
            " ---------------------------------------------------------------------",
            "      1          1           0        0.000000    0.000000    0.000000",
            " ---------------------------------------------------------------------",
            " Maximum Force            0.000010     0.000450     YES",
            " RMS     Force            0.000006     0.000300     YES",
            " Maximum Displacement     0.000020     0.001800     YES",
            " RMS     Displacement     0.000012     0.001200     YES",
            " Stationary point found.",
            " Frequencies --  -512.3000   47.1000   98.2000",
            " Zero-point correction=                           0.012345",
            " Normal termination of Gaussian 16",
        ]
    )


def _receipt_for(config) -> RemoteReceipt:
    return RemoteReceipt(
        schema_version="ts-remote-receipt/1",
        submission_id=config.submission_id,
        intent_id=config.intent_id,
        intent_digest=config.intent_digest,
        act_id=config.act_id,
        profile=config.profile.name,
        scheduler="torque",
        scheduler_id="123.cluster",
        remote_dir=config.remote_dir,
        script_sha256=remote_lifecycle.submission_script_digest(config),
        submitted_at="2026-08-12T00:00:00Z",
        expected_artifacts=config.expected_artifacts,
    )


def _prepared_remote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, str, dict]:
    workspace, act_id = _workspace(tmp_path)
    _configure_remote(tmp_path, monkeypatch)
    created = _create(
        workspace,
        act_id,
        target=_remote_request_target(),
        dry_run=False,
    )
    prepare_calculation(workspace, created["intent_ref"], created["intent_digest"])
    return workspace, act_id, created


def test_intent_paths_ids_and_preflight_are_research_act_bound(tmp_path: Path) -> None:
    workspace, act_id = _workspace(tmp_path)
    first = _create(workspace, act_id)
    second = _create(workspace, act_id)

    prefix = f"calc_{act_id}_gaussian_opt_freq"
    assert first["schema_version"] == "ts-calculation-intent-created/2"
    assert first["intent_id"] == f"{prefix}_0001"
    assert second["intent_id"] == f"{prefix}_0002"
    assert first["intent_ref"] == f"acts/{act_id}/attempts/{prefix}_0001/intent.json"
    assert first["input_refs"] == {"gjf": "inputs/candidate.gjf"}
    assert first["expected_artifacts"] == [
        f"acts/{act_id}/attempts/{prefix}_0001/outputs/gaussian.out"
    ]

    binding = preflight_calculation(
        workspace,
        "prepare",
        act_id,
        "gaussian",
        intent_file=first["intent_ref"],
    )
    assert binding["schema_version"] == "ts-compute-binding/1"
    assert binding["act_id"] == act_id
    assert binding["intent_digest"] == first["intent_digest"]
    prepared = prepare_calculation(workspace, first["intent_ref"], first["intent_digest"])
    assert prepared["result"]["state"] == "prepared"


def test_intent_sequence_reservation_is_concurrent_and_failure_atomic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, act_id = _workspace(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        created = list(pool.map(lambda _: _create(workspace, act_id), range(12)))
    assert len({item["intent_id"] for item in created}) == 12
    assert all((workspace / item["intent_ref"]).is_file() for item in created)

    workspace2, act_id2 = _workspace(tmp_path / "second")

    def fail_write(path: Path, _data: object) -> None:
        path.with_name(f"{path.name}.tmp").write_text("partial", encoding="utf-8")
        raise OSError("simulated intent write failure")

    monkeypatch.setattr("ts_compute.control.write_json", fail_write)
    with pytest.raises(OSError, match="simulated intent write failure"):
        _create(workspace2, act_id2)
    assert not (workspace2 / "acts" / act_id2 / "attempts").exists()


def test_remote_target_is_workspace_and_research_act_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, act_id = _workspace(tmp_path)
    _configure_remote(tmp_path, monkeypatch)
    created = _create(workspace, act_id, target=_remote_request_target())
    identity = workspace_id(workspace, create=False)
    assert created["execution_target"]["remote_dir"] == (
        f"/remote/ts/workspaces/{identity}/runs/{act_id}/{created['intent_id']}"
    )
    assert created["execution_target"]["authority"] == "execution_mirror"


def test_remote_submit_status_tail_collect_and_cancel_are_receipt_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, act_id, created = _prepared_remote(tmp_path, monkeypatch)
    calls = {"submit": 0, "status": 0, "collect": 0, "cancel": 0}

    def fake_submit(config):
        calls["submit"] += 1
        assert config.act_id == act_id
        assert config.remote_dir == created["execution_target"]["remote_dir"]
        return _receipt_for(config)

    def fake_status(_config, job_id):
        calls["status"] += 1
        return RemoteJobStatus(
            state="running",
            program_status="not_run",
            job_id=job_id,
            scheduler_state="R",
        )

    def fake_collect(config, artifacts, output_dir):
        calls["collect"] += 1
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "gaussian.out").write_text(_gaussian_log(), encoding="utf-8")
        return list(artifacts), [{
            "remote_path": f"{config.remote_dir}/gaussian.out",
            "size": (output_dir / "gaussian.out").stat().st_size,
            "sha256": "sha256:" + "b" * 64,
        }]

    def fake_cancel(_config, _job_id):
        calls["cancel"] += 1
        return {"state": "accepted", "updated_at": "2026-08-12T00:01:00Z"}

    monkeypatch.setattr("ts_compute.control.remote_lifecycle.submit", fake_submit)
    monkeypatch.setattr("ts_compute.control.remote_lifecycle.status", fake_status)
    monkeypatch.setattr("ts_compute.control.remote_lifecycle.tail", lambda *_args: "running\n")
    monkeypatch.setattr("ts_compute.control.remote_lifecycle.collect", fake_collect)
    monkeypatch.setattr("ts_compute.control.remote_lifecycle.cancel", fake_cancel)

    submitted = submit_calculation(workspace, created["intent_id"])
    assert submit_calculation(workspace, created["intent_id"]) == submitted
    assert submitted["job_id"] == "123.cluster"
    observed = calculation_status(workspace, created["intent_id"])
    assert observed["state"] == "running"
    assert calculation_tail(workspace, created["intent_id"], "gaussian.out", 40)["text"] == "running\n"
    collected = collect_calculation(workspace, created["intent_id"], ["gaussian.out"])
    assert collected["artifact_refs"] == [
        f"acts/{act_id}/attempts/{created['intent_id']}/outputs/remote/gaussian.out"
    ]
    assert cancel_calculation(workspace, created["intent_id"], expected_job_id="123.cluster")["state"] == "stopped"
    assert calls == {"submit": 1, "status": 1, "collect": 1, "cancel": 1}


def test_pre_submit_failure_is_retryable_but_scheduler_rejection_is_not(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, _act_id, created = _prepared_remote(tmp_path, monkeypatch)
    attempts = 0

    def transient(config):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RemotePreSubmitError("upload", OSError("network unavailable"))
        return _receipt_for(config)

    monkeypatch.setattr("ts_compute.control.remote_lifecycle.submit", transient)
    failed = submit_calculation(workspace, created["intent_id"])
    assert failed["state"] == "failed"
    assert failed["control"]["effect_attempted"] is False
    assert failed["control"]["retry_disposition"] == "retry_same_submission"
    assert submit_calculation(workspace, created["intent_id"])["state"] == "submitted"

    workspace2, _act_id2, created2 = _prepared_remote(tmp_path / "rejected", monkeypatch)
    monkeypatch.setattr(
        "ts_compute.control.remote_lifecycle.submit",
        lambda _config: (_ for _ in ()).throw(
            RemoteSubmissionRejected({"state": "rejected", "error": "queue disabled"})
        ),
    )
    rejected = submit_calculation(workspace2, created2["intent_id"])
    assert rejected["error_class"] == "scheduler_submission_rejected"
    assert rejected["control"]["retry_disposition"] == "new_intent"
    with pytest.raises(ComputeContractError, match="refuses automatic replay"):
        submit_calculation(workspace2, created2["intent_id"])


def test_ambiguous_submit_reconciles_only_from_a_matching_durable_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, _act_id, created = _prepared_remote(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "ts_compute.control.remote_lifecycle.submit",
        lambda _config: (_ for _ in ()).throw(
            RemoteSubmissionAmbiguous({"state": "unknown", "phase": "submit_request_started"})
        ),
    )
    ambiguous = submit_calculation(workspace, created["intent_id"])
    assert ambiguous["state"] == "unknown"
    assert ambiguous["error_class"] == "submission_ambiguous"
    with pytest.raises(ComputeContractError, match="refuses automatic replay"):
        submit_calculation(workspace, created["intent_id"])

    def durable(config, *, valid: bool) -> dict:
        return {
            "schema_version": "ts-remote-submission/1",
            "submission_id": config.submission_id,
            "state": "accepted",
            "script_sha256": (
                remote_lifecycle.submission_script_digest(config)
                if valid
                else "c" * 64
            ),
            "job_id": "123.cluster",
            "updated_at": "2026-08-12T00:00:00Z",
        }

    monkeypatch.setattr(
        "ts_compute.control.remote_lifecycle.status",
        lambda _config, job_id: RemoteJobStatus(
            state="queued",
            program_status="not_run",
            job_id=job_id,
            scheduler_state="Q",
        ),
    )
    monkeypatch.setattr(
        "ts_compute.control.remote_lifecycle.read_submission_record",
        lambda config: durable(config, valid=False),
    )
    with pytest.raises(ComputeContractError, match="reconciliation record does not match"):
        calculation_status(workspace, created["intent_id"])

    monkeypatch.setattr(
        "ts_compute.control.remote_lifecycle.read_submission_record",
        lambda config: durable(config, valid=True),
    )
    assert calculation_status(workspace, created["intent_id"])["state"] == "queued"
    assert submit_calculation(workspace, created["intent_id"])["job_id"] == "123.cluster"


def test_failed_collection_leaves_no_partial_output_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, act_id, created = _prepared_remote(tmp_path, monkeypatch)
    monkeypatch.setattr("ts_compute.control.remote_lifecycle.submit", _receipt_for)

    def fail_collect(_config, _artifacts, staging):
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "gaussian.out").write_text("partial\n", encoding="utf-8")
        raise OSError("simulated transfer failure")

    monkeypatch.setattr("ts_compute.control.remote_lifecycle.collect", fail_collect)
    submit_calculation(workspace, created["intent_id"])
    with pytest.raises(OSError, match="simulated transfer failure"):
        collect_calculation(workspace, created["intent_id"], ["gaussian.out"])
    attempt = workspace / "acts" / act_id / "attempts" / created["intent_id"]
    assert not (attempt / "outputs").exists()
    assert not list(attempt.glob(".collect-*"))


def test_gaussian_parse_is_attempt_scoped_idempotent_and_scientifically_read_only(tmp_path: Path) -> None:
    workspace, act_id = _workspace(tmp_path)
    created = _create(workspace, act_id)
    prepare_calculation(workspace, created["intent_ref"], created["intent_digest"])
    artifact_ref = f"acts/{act_id}/attempts/{created['intent_id']}/outputs/gaussian.out"
    log = workspace / artifact_ref
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(_gaussian_log(), encoding="utf-8")
    scientific_before = {
        name: (workspace / name).read_bytes()
        for name in ("research_state.json", "claims.json", "observations.json", "validation_results.json")
    }

    result = parse_calculation(workspace, created["intent_id"], artifact_ref)
    assert result["state"] == "parsed"
    assert result["program_status"] == "completed"
    assert result["parser_facts"]["normal_termination"] is True
    assert result["parser_facts"]["imaginary_frequency_count"] == 1
    assert "claim_status" not in result
    assert scientific_before == {
        name: (workspace / name).read_bytes()
        for name in scientific_before
    }
    assert parse_calculation(workspace, created["intent_id"], artifact_ref) == result

    log.write_text(_gaussian_log() + "\nchanged\n", encoding="utf-8")
    with pytest.raises(ComputeContractError, match="different source content"):
        parse_calculation(workspace, created["intent_id"], artifact_ref)

    foreign = workspace / "inputs" / "foreign.log"
    foreign.write_text(_gaussian_log(), encoding="utf-8")
    with pytest.raises(ComputeContractError, match=f"acts/{act_id}/attempts/{created['intent_id']}/outputs"):
        parse_calculation(workspace, created["intent_id"], "inputs/foreign.log")


def test_compute_result_contract_rejects_scientific_verdict_fields() -> None:
    result = {
        "schema_version": "ts-calculation-result/2",
        "job_id": None,
        "intent_id": "calc_test",
        "act_id": "act_0123456789abcdef01234567",
        "state": "prepared",
        "program_status": "not_run",
        "exit_status": None,
        "artifact_refs": [],
        "parser_facts": {},
        "error_class": None,
        "provenance": {},
        "claim_status": "supported",
    }
    with pytest.raises(ComputeContractError, match="Additional properties"):
        validate_compute_contract("calculation_result.schema.json", result)

    del result["claim_status"]
    result["parser_facts"] = {"claim_status": "supported"}
    with pytest.raises(ComputeContractError, match="claim_status"):
        validate_compute_contract("calculation_result.schema.json", result)
