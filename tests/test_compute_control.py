from __future__ import annotations


def test_remote_crest_stdout_matches_parser_contract():
    from ts_agent.compute.control import _remote_stdout_name
    assert _remote_stdout_name({"backend": "crest", "expected_artifacts": ["outputs/crest.out", "outputs/crest_best.xyz"]}) == "crest.out"

import json
import hashlib
import os
import shutil
import stat
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.workspace_helpers import bootstrap_workspace_fixture, start_research_node
from ts_agent.compute import (
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
from ts_agent.compute.contracts import validate_compute_contract
from ts_agent.remote import lifecycle as remote_lifecycle
from ts_agent.remote.errors import RemotePreSubmitError, RemoteSubmissionAmbiguous, RemoteSubmissionRejected
from ts_agent.remote.models import RemoteJobStatus, RemoteReceipt
from ts_agent.backends.gaussian import parse_log
from ts_agent.compute.task_validation import validate_parsed_task
from ts_agent.workspace.identity import workspace_id
from ts_agent.workspace.operational import _operational_files


def _workspace(tmp_path: Path) -> tuple[Path, str]:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    node_id = start_research_node(
        workspace,
        objective="Run the Root-selected Gaussian validation calculation.",
        claim_type="transition_state",
    )["node_id"]
    gjf = workspace / "inputs" / "candidate.gjf"
    gjf.write_text(
        "%chk=candidate.chk\n#P B3LYP/6-31G(d) opt=(ts,calcfc) freq\n\nTS\n\n0 1\nH 0 0 0\n\n",
        encoding="utf-8",
    )
    return workspace, node_id


def _artifact_id(workspace: Path, path: str = "inputs/candidate.gjf") -> str:
    return next(
        item["artifact_id"]
        for item in list_calculation_artifacts(workspace)["artifacts"]
        if item["path"] == path
    )


def _request(
    workspace: Path,
    node_id: str,
    *,
    target: dict[str, object] | None = None,
    dry_run: bool = True,
    capability: str = "gaussian.opt_freq",
) -> dict[str, object]:
    if capability == "gaussian.sp":
        route = "%chk=candidate.chk\n#P B3LYP/6-31G(d) sp\n\nTS\n\n0 1\nH 0 0 0\n\n"
        (workspace / "inputs" / "candidate.gjf").write_text(route, encoding="utf-8")
    return {
        "schema_version": "ts-calculation-request/5",
        "node_id": node_id,
        "purpose": "Evaluate the selected candidate with a bound calculation.",
        "attempt_kind": "primary",
        "lineage": None,
        "capability": capability,
        "capability_version": "1",
        "input_artifacts": [{"input_role": "gjf", "artifact_id": _artifact_id(workspace)}],
        "parameters": {},
        "execution_target": target or {"kind": "local"},
        "dry_run": dry_run,
    }


def _create(
    workspace: Path,
    node_id: str,
    *,
    target: dict[str, object] | None = None,
    dry_run: bool = True,
    capability: str = "gaussian.opt_freq",
) -> dict:
    return create_calculation_intent(
        workspace,
        _request(workspace, node_id, target=target, dry_run=dry_run, capability=capability),
    )


def test_create_intent_rejects_symlinked_research_node_attempt_root(tmp_path: Path) -> None:
    workspace, node_id = _workspace(tmp_path)
    node_dir = workspace / "nodes" / node_id
    outside = tmp_path / "outside-node"
    node_dir.mkdir(parents=True)
    shutil.move(str(node_dir), str(outside))
    node_dir.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ComputeContractError, match="ResearchNode path contains a symbolic link"):
        _create(workspace, node_id)


def test_load_prepared_rejects_symlinked_nodes_root(tmp_path: Path) -> None:
    workspace, _node_id = _workspace(tmp_path)
    nodes = workspace / "nodes"
    outside = tmp_path / "outside-nodes"
    nodes.rename(outside)
    nodes.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ComputeContractError, match="workspace canonical paths cannot contain symbolic links"):
        preflight_calculation(workspace, "inspect", "node_1", intent_id="calc_1")


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
        node_id=config.node_id,
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
    workspace, node_id = _workspace(tmp_path)
    _configure_remote(tmp_path, monkeypatch)
    created = _create(
        workspace,
        node_id,
        target=_remote_request_target(),
        dry_run=False,
    )
    prepare_calculation(workspace, created["intent_ref"], created["intent_digest"])
    return workspace, node_id, created


def test_local_non_dry_run_creates_a_runnable_attempt_intent(tmp_path: Path) -> None:
    workspace, node_id = _workspace(tmp_path)

    created = _create(workspace, node_id, dry_run=False)

    assert created["execution_target"] == {"kind": "local"}
    assert (workspace / created["intent_ref"]).is_file()


def test_local_lifecycle_collects_into_workspace_and_parses_locally(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, node_id = _workspace(tmp_path)
    created = _create(workspace, node_id, dry_run=False)
    prepare_calculation(workspace, created["intent_ref"], created["intent_digest"])

    executable_dir = tmp_path / "bin"
    executable_dir.mkdir()
    executable = executable_dir / "g16"
    executable.write_text(
        "#!/bin/sh\n"
        "input=$(cat)\n"
        "[ -n \"$input\" ] || exit 9\n"
        "cat > gaussian.out <<'EOF'\n"
        f"{_gaussian_log()}\n"
        "EOF\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{executable_dir}:{os.environ['PATH']}")

    submitted = submit_calculation(workspace, created["intent_id"])
    assert submitted["job_id"] == "local-calc_1"
    execution_root = (
        workspace / "nodes" / node_id / "attempts" / created["intent_id"] / "execution" / "local"
    )
    assert (execution_root / "local_receipt.json").is_file()
    tracked = _operational_files(workspace, excluded_activity_refs=set())
    assert execution_root / "local_receipt.json" in tracked
    for _ in range(200):
        status = calculation_status(workspace, created["intent_id"])
        if status["state"] in {"completed", "failed"}:
            break
        time.sleep(0.01)
    assert status["state"] == "completed"
    assert "Normal termination" in calculation_tail(workspace, created["intent_id"])["text"]

    collected = collect_calculation(workspace, created["intent_id"])
    assert collected["artifact_refs"] == [
        f"nodes/{node_id}/attempts/{created['intent_id']}/outputs/gaussian.out"
    ]
    parsed = parse_calculation(workspace, created["intent_id"])
    assert parsed["state"] == "parsed"
    assert parsed["program_status"] == "completed"


def test_local_lifecycle_cancels_a_running_process_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, node_id = _workspace(tmp_path)
    created = _create(workspace, node_id, dry_run=False)
    prepare_calculation(workspace, created["intent_ref"], created["intent_digest"])

    executable_dir = tmp_path / "bin"
    executable_dir.mkdir()
    executable = executable_dir / "g16"
    executable.write_text(
        "#!/bin/sh\n"
        "sleep 30\n"
        "printf 'should not finish\\n' > gaussian.out\n",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{executable_dir}:{os.environ['PATH']}")

    submitted = submit_calculation(workspace, created["intent_id"])
    assert submitted["state"] == "submitted"
    for _ in range(200):
        observed = calculation_status(workspace, created["intent_id"])
        if observed["state"] == "running":
            break
        time.sleep(0.01)
    assert observed["state"] == "running"

    cancelled = cancel_calculation(
        workspace,
        created["intent_id"],
        expected_job_id=submitted["job_id"],
    )
    assert cancelled["state"] == "stopped"
    assert cancelled["program_status"] == "stopped"
    assert cancel_calculation(workspace, created["intent_id"])["state"] == "stopped"


def test_unavailable_capability_fails_without_implicit_substitution_or_attempt(tmp_path: Path) -> None:
    workspace, node_id = _workspace(tmp_path)

    with pytest.raises(ComputeContractError, match="capability unavailable"):
        _create(workspace, node_id, capability="photochemistry.surface_hop")

    attempts = workspace / "nodes" / node_id / "attempts"
    assert not attempts.exists()


def test_intent_paths_ids_and_preflight_are_research_node_bound(tmp_path: Path) -> None:
    workspace, node_id = _workspace(tmp_path)
    first = _create(workspace, node_id)
    second = _create(workspace, node_id)

    assert first["schema_version"] == "ts-calculation-intent-created/4"
    assert first["intent_id"] == "calc_1"
    assert second["intent_id"] == "calc_2"
    assert first["intent_ref"] == f"nodes/{node_id}/attempts/calc_1/intent.json"
    assert first["input_refs"] == {"gjf": "inputs/candidate.gjf"}
    assert first["expected_artifacts"] == [
        f"nodes/{node_id}/attempts/calc_1/outputs/gaussian.out"
    ]

    binding = preflight_calculation(
        workspace,
        "prepare",
        node_id,
        capability="gaussian.opt_freq",
        capability_version="1",
        intent_file=first["intent_ref"],
    )
    assert binding["schema_version"] == "ts-compute-binding/1"
    assert binding["node_id"] == node_id
    assert binding["intent_digest"] == first["intent_digest"]
    prepared = prepare_calculation(workspace, first["intent_ref"], first["intent_digest"])
    assert prepared["result"]["state"] == "prepared"


def test_existing_intent_rejects_retired_intent_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, node_id = _workspace(tmp_path)
    _configure_remote(tmp_path, monkeypatch)
    created = _create(
        workspace,
        node_id,
        target=_remote_request_target(),
        dry_run=False,
    )
    existing = dict(created["intent"])
    existing["schema_version"] = "ts-calculation-intent/6"
    intent_path = workspace / created["intent_ref"]
    intent_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ComputeContractError, match="unsupported calculation intent"):
        prepare_calculation(workspace, created["intent_ref"])


def test_intent_sequence_reservation_is_concurrent_and_failure_atomic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, node_id = _workspace(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        created = list(pool.map(lambda _: _create(workspace, node_id), range(12)))
    assert len({item["intent_id"] for item in created}) == 12
    assert all((workspace / item["intent_ref"]).is_file() for item in created)

    workspace2, node_id2 = _workspace(tmp_path / "second")

    def fail_write(path: Path, _data: object) -> None:
        path.with_name(f"{path.name}.tmp").write_text("partial", encoding="utf-8")
        raise OSError("simulated intent write failure")

    monkeypatch.setattr("ts_agent.compute.control.write_json", fail_write)
    with pytest.raises(OSError, match="simulated intent write failure"):
        _create(workspace2, node_id2)
    assert not (workspace2 / "nodes" / node_id2 / "attempts").exists()


def test_remote_target_is_workspace_and_research_node_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, node_id = _workspace(tmp_path)
    _configure_remote(tmp_path, monkeypatch)
    created = _create(workspace, node_id, target=_remote_request_target())
    identity = workspace_id(workspace, create=False)
    assert created["execution_target"]["remote_dir"] == (
        f"/remote/ts/workspaces/{identity}/runs/{node_id}/{created['intent_id']}"
    )
    assert created["execution_target"]["authority"] == "execution_mirror"


def test_remote_submit_status_tail_collect_and_cancel_are_receipt_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, node_id, created = _prepared_remote(tmp_path, monkeypatch)
    calls = {"submit": 0, "status": 0, "collect": 0, "cancel": 0}

    def fake_submit(config):
        calls["submit"] += 1
        assert config.node_id == node_id
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
        payload = _gaussian_log()
        (output_dir / "gaussian.out").write_text(payload, encoding="utf-8")
        return list(artifacts), [{
            "remote_path": f"{config.remote_dir}/gaussian.out",
            "size": len(payload.encode("utf-8")),
            "sha256": "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        }]

    def fake_cancel(_config, _job_id):
        calls["cancel"] += 1
        return {"state": "accepted", "updated_at": "2026-08-12T00:01:00Z"}

    monkeypatch.setattr("ts_agent.compute.control.remote_lifecycle.submit", fake_submit)
    monkeypatch.setattr("ts_agent.compute.control.remote_lifecycle.status", fake_status)
    monkeypatch.setattr("ts_agent.compute.control.remote_lifecycle.tail", lambda *_args: "running\n")
    monkeypatch.setattr("ts_agent.compute.control.remote_lifecycle.collect", fake_collect)
    monkeypatch.setattr("ts_agent.compute.control.remote_lifecycle.cancel", fake_cancel)

    submitted = submit_calculation(workspace, created["intent_id"])
    assert submit_calculation(workspace, created["intent_id"]) == submitted
    assert submitted["job_id"] == "123.cluster"
    observed = calculation_status(workspace, created["intent_id"])
    assert observed["state"] == "running"
    assert calculation_tail(workspace, created["intent_id"], "gaussian.out", 40)["text"] == "running\n"
    collected = collect_calculation(workspace, created["intent_id"], ["gaussian.out"])
    assert collected["artifact_refs"] == [
        f"nodes/{node_id}/attempts/{created['intent_id']}/outputs/remote/gaussian.out"
    ]
    assert collect_calculation(workspace, created["intent_id"], ["gaussian.out"]) == collected
    assert cancel_calculation(workspace, created["intent_id"], expected_job_id="123.cluster")["state"] == "stopped"
    assert calls == {"submit": 1, "status": 1, "collect": 1, "cancel": 1}
    monkeypatch.setattr(
        "ts_agent.compute.control._prepared_task_for_intent",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ComputeContractError("provider metadata unavailable")),
    )
    assert collect_calculation(workspace, created["intent_id"], ["gaussian.out"]) == collected


def test_pre_submit_failure_is_retryable_but_scheduler_rejection_is_not(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, _node_id, created = _prepared_remote(tmp_path, monkeypatch)
    attempts = 0

    def transient(config):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RemotePreSubmitError("upload", OSError("network unavailable"))
        return _receipt_for(config)

    monkeypatch.setattr("ts_agent.compute.control.remote_lifecycle.submit", transient)
    failed = submit_calculation(workspace, created["intent_id"])
    assert failed["state"] == "failed"
    assert failed["control"]["effect_attempted"] is False
    assert failed["control"]["retry_disposition"] == "retry_same_submission"
    assert submit_calculation(workspace, created["intent_id"])["state"] == "submitted"

    workspace2, _node_id2, created2 = _prepared_remote(tmp_path / "rejected", monkeypatch)
    monkeypatch.setattr(
        "ts_agent.compute.control.remote_lifecycle.submit",
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
    workspace, _node_id, created = _prepared_remote(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "ts_agent.compute.control.remote_lifecycle.submit",
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
        "ts_agent.compute.control.remote_lifecycle.status",
        lambda _config, job_id: RemoteJobStatus(
            state="queued",
            program_status="not_run",
            job_id=job_id,
            scheduler_state="Q",
        ),
    )
    monkeypatch.setattr(
        "ts_agent.compute.control.remote_lifecycle.read_submission_record",
        lambda config: durable(config, valid=False),
    )
    with pytest.raises(ComputeContractError, match="reconciliation record does not match"):
        calculation_status(workspace, created["intent_id"])

    monkeypatch.setattr(
        "ts_agent.compute.control.remote_lifecycle.read_submission_record",
        lambda config: durable(config, valid=True),
    )
    assert calculation_status(workspace, created["intent_id"])["state"] == "queued"
    assert submit_calculation(workspace, created["intent_id"])["job_id"] == "123.cluster"


def test_failed_collection_leaves_no_partial_output_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, node_id, created = _prepared_remote(tmp_path, monkeypatch)
    monkeypatch.setattr("ts_agent.compute.control.remote_lifecycle.submit", _receipt_for)

    def fail_collect(_config, _artifacts, staging):
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "gaussian.out").write_text("partial\n", encoding="utf-8")
        raise OSError("simulated transfer failure")

    monkeypatch.setattr("ts_agent.compute.control.remote_lifecycle.collect", fail_collect)
    submit_calculation(workspace, created["intent_id"])
    with pytest.raises(OSError, match="simulated transfer failure"):
        collect_calculation(workspace, created["intent_id"], ["gaussian.out"])
    attempt = workspace / "nodes" / node_id / "attempts" / created["intent_id"]
    assert not (attempt / "outputs").exists()
    assert not list(attempt.glob(".collect-*"))


def test_gaussian_parse_is_attempt_scoped_idempotent_and_scientifically_read_only(tmp_path: Path) -> None:
    workspace, node_id = _workspace(tmp_path)
    created = _create(workspace, node_id)
    prepare_calculation(workspace, created["intent_ref"], created["intent_digest"])
    artifact_ref = f"nodes/{node_id}/attempts/{created['intent_id']}/outputs/gaussian.out"
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
    assert "status" not in result["parser_facts"]
    assert "validation_failures" not in result["parser_facts"]
    assert result["task_validation"] == {"status": "completed", "failures": []}
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
    with pytest.raises(ComputeContractError, match=f"nodes/{node_id}/attempts/{created['intent_id']}/outputs"):
        parse_calculation(workspace, created["intent_id"], "inputs/foreign.log")


@pytest.mark.parametrize(
    ("task_type", "body"),
    [
        ("sp", " SCF Done:  E(RHF) =  -1.000000     A.U.\n"),
        (
            "opt",
            " Standard orientation:\n"
            " ---------------------------------------------------------------------\n"
            " Center Atomic Atomic Coordinates (Angstroms)\n"
            " Number Number Type X Y Z\n"
            " ---------------------------------------------------------------------\n"
            " 1 1 0 0.000000 0.000000 0.000000\n"
            " ---------------------------------------------------------------------\n"
            " Maximum Force 0.000010 0.000450 YES\n"
            " RMS Force 0.000006 0.000300 YES\n"
            " Maximum Displacement 0.000020 0.001800 YES\n"
            " RMS Displacement 0.000012 0.001200 YES\n"
            " Stationary point found.\n",
        ),
        ("freq", " Frequencies --  10.0 20.0 30.0\n"),
        (
            "opt_freq",
            " Standard orientation:\n"
            " ---------------------------------------------------------------------\n"
            " Center Atomic Atomic Coordinates (Angstroms)\n"
            " Number Number Type X Y Z\n"
            " ---------------------------------------------------------------------\n"
            " 1 1 0 0.000000 0.000000 0.000000\n"
            " ---------------------------------------------------------------------\n"
            " Maximum Force 0.000010 0.000450 YES\n"
            " RMS Force 0.000006 0.000300 YES\n"
            " Maximum Displacement 0.000020 0.001800 YES\n"
            " RMS Displacement 0.000012 0.001200 YES\n"
            " Stationary point found.\n"
            " Frequencies --  10.0 20.0 30.0\n",
        ),
    ],
)
def test_gaussian_task_validation_does_not_apply_transition_state_semantics(
    tmp_path: Path,
    task_type: str,
    body: str,
) -> None:
    log = tmp_path / f"{task_type}.log"
    log.write_text(
        " Entering Link 1 = synthetic\n"
        f" #P HF/STO-3G {task_type}\n"
        " -------------------------------------------------------------------\n"
        f"{body}"
        " Normal termination of Gaussian 16\n",
        encoding="utf-8",
    )

    facts = parse_log(log)["summary"]

    assert validate_parsed_task("gaussian", task_type, facts) == {
        "status": "completed",
        "failures": [],
    }
    assert "status" not in facts
    assert "validation_failures" not in facts


def test_gaussian_optimization_reports_missing_convergence_evidence_once() -> None:
    validation = validate_parsed_task("gaussian", "opt", {
        "normal_termination": True,
        "missing_artifacts": [],
        "stationary_point_found": True,
        "final_geometry_atoms": 1,
        "final_convergence_evidence_present": False,
        "final_convergence_satisfied": False,
    })

    assert validation == {
        "status": "incomplete",
        "failures": ["optimization_convergence_evidence_missing"],
    }


def test_compute_result_contract_rejects_scientific_verdict_fields() -> None:
    result = {
        "schema_version": "ts-calculation-result/2",
        "job_id": None,
        "intent_id": "calc_1",
        "node_id": "node_1",
        "capability": "gaussian.opt_freq",
        "capability_version": "1",
        "expected_output_roles": ["program_output", "optimized_geometry", "frequencies"],
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

    result["parser_facts"] = {}
    result["intent_id"] = "calc_test"
    with pytest.raises(ComputeContractError, match="does not match"):
        validate_compute_contract("calculation_result.schema.json", result)
