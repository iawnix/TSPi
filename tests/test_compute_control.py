from __future__ import annotations

import json
from pathlib import Path

import pytest

from strict_helpers import bootstrap_strict_workspace, start_research_node
from ts_compute import (
    ComputeContractError,
    cancel_calculation,
    calculation_status,
    calculation_tail,
    collect_calculation,
    parse_calculation,
    preflight_calculation,
    prepare_calculation,
    submit_calculation,
)
from ts_compute.contracts import validate_compute_contract
from ts_compute.control import _validate_intent_node_scope
from ts_remote.job_lifecycle import RemoteJobStatus
from ts_remote.base import RemoteReceipt
from ts_remote.mcp import MCPClientError
from ts_workspace.operational import operational_snapshot
from ts_workspace.readers.report import report_workspace


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    report_ref = bootstrap_strict_workspace(workspace)
    start_research_node(
        workspace,
        report_ref,
        node_id="n001",
        node_type="validation",
        scope="tsfreq",
    )
    gjf = workspace / "nodes" / "n001" / "inputs" / "candidate.gjf"
    gjf.write_text(
        "%chk=candidate.chk\n#P B3LYP/6-31G(d) opt=(ts,calcfc) freq\n\nTS\n\n0 1\nH 0 0 0\n\n",
        encoding="utf-8",
    )
    return workspace


def _intent(
    workspace: Path,
    *,
    target: dict[str, object] | None = None,
    dry_run: bool = True,
) -> Path:
    return _intent_v2(
        workspace,
        intent_id="calc_n001_optfreq_001",
        target=target,
        dry_run=dry_run,
    )


def _intent_v2(
    workspace: Path,
    *,
    intent_id: str = "calc_n001_optfreq_v2_001",
    attempt_kind: str = "primary",
    recalculation_ref: dict[str, object] | None = None,
    validation_scope: str | None = "tsfreq",
    target: dict[str, object] | None = None,
    dry_run: bool = True,
) -> Path:
    value = {
        "schema_version": "ts-calculation-intent/2",
        "intent_id": intent_id,
        "node_id": "n001",
        "purpose": "Evaluate the selected candidate with an attempt-scoped calculation.",
        "validation_scope": validation_scope,
        "attempt_kind": attempt_kind,
        "recalculation_ref": recalculation_ref,
        "backend": "gaussian",
        "task_type": "opt_freq",
        "input_refs": {"gjf": "nodes/n001/inputs/candidate.gjf"},
        "settings": {},
        "expected_artifacts": [f"nodes/n001/attempts/{intent_id}/outputs/candidate.log"],
        "execution_target": target or {"kind": "local"},
        "dry_run": dry_run,
    }
    path = workspace / "nodes" / "n001" / "scratch" / f"{intent_id}.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _remote_target() -> dict[str, str]:
    return {
        "kind": "remote",
        "authority": "execution_mirror",
        "transport": "ssh",
        "login_host": "login.test",
        "compute_host": "compute.test",
        "remote_dir": "/remote/ts/n001/calc_n001_optfreq_001",
    }


def _mcp_target() -> dict[str, object]:
    return {
        "kind": "remote",
        "authority": "execution_mirror",
        "transport": "mcp",
        "remote_dir": "runs/n001/calc_n001_optfreq_v2_001",
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
            "environment": {},
            "gpu_devices": [],
        },
    }


def _allow_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TS_COMPUTE_LOGIN_HOSTS", "login.test")
    monkeypatch.setenv("TS_COMPUTE_COMPUTE_HOSTS", "compute.test")
    monkeypatch.setenv("TS_COMPUTE_REMOTE_ROOTS", "/remote/ts")


def _configure_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TS_CLUSTER_MCP_URL", "http://127.0.0.1:8765/mcp")
    monkeypatch.setenv("TS_CLUSTER_MCP_TOKEN", "x" * 32)


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


def _gaussian_irc_log() -> str:
    return "\n".join(
        [
            " Entering Link 1 = synthetic",
            " #P B3LYP/6-31G(d) IRC=(Forward,MaxPoints=2)",
            " -------------------------------------------------------------------",
            " Point Number:   0          Path Number:   1",
            " Point Number  1 in FORWARD path direction.",
            " SCF Done:  E(RB3LYP) =  -40.100000 A.U.",
            " Point Number:   1          Path Number:   1",
            "                    CURRENT STRUCTURE",
            " Center Atomic Coordinates",
            "      1          6        0.000000  0.000000  0.000000",
            "      2          1        1.000000  0.000000  0.000000",
            " NET REACTION COORDINATE UP TO THIS POINT = 0.10000",
            " Point Number  2 in FORWARD path direction.",
            " SCF Done:  E(RB3LYP) =  -40.200000 A.U.",
            " Point Number:   2          Path Number:   1",
            "                    CURRENT STRUCTURE",
            " Center Atomic Coordinates",
            "      1          6        0.100000  0.000000  0.000000",
            "      2          1        1.100000  0.000000  0.000000",
            " NET REACTION COORDINATE UP TO THIS POINT = 0.20000",
            " Calculation of FORWARD path complete.",
            " Normal termination of Gaussian 16",
        ]
    )


def test_compute_preflight_binds_workspace_intent_scope_and_digest(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    intent_path = _intent_v2(workspace)
    binding = preflight_calculation(
        workspace,
        "prepare",
        "n001",
        "gaussian",
        intent_file=intent_path,
    )

    assert binding["schema_version"] == "ts-compute-binding/1"
    assert binding["node_id"] == "n001"
    assert binding["backend"] == "gaussian"
    assert binding["intent_ref"].startswith("nodes/n001/scratch/")
    assert binding["intent_digest"].startswith("sha256:")

    with pytest.raises(ComputeContractError, match="node_id does not match"):
        preflight_calculation(workspace, "prepare", "n000", "gaussian", intent_file=intent_path)
    with pytest.raises(ComputeContractError, match="backend does not match"):
        preflight_calculation(workspace, "prepare", "n001", "xtb", intent_file=intent_path)


def test_compute_preflight_rejects_external_or_changed_intent(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    intent_path = _intent_v2(workspace)
    outside = tmp_path / "outside.json"
    outside.write_text(intent_path.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ComputeContractError, match="inside the TS workspace"):
        preflight_calculation(workspace, "prepare", "n001", "gaussian", intent_file=outside)

    linked = intent_path.with_name("linked-intent.json")
    linked.symlink_to(intent_path)
    with pytest.raises(ComputeContractError, match="symbolic link"):
        preflight_calculation(workspace, "prepare", "n001", "gaussian", intent_file=linked)

    binding = preflight_calculation(workspace, "prepare", "n001", "gaussian", intent_file=intent_path)
    changed = json.loads(intent_path.read_text(encoding="utf-8"))
    changed["purpose"] = "Changed after preflight."
    intent_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="changed after compute preflight"):
        prepare_calculation(workspace, intent_path, binding["intent_digest"])


def test_prepare_rejects_legacy_intent_schema(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    intent_path = _intent(workspace)
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    intent["schema_version"] = "ts-calculation-intent/1"
    intent_path.write_text(json.dumps(intent), encoding="utf-8")

    with pytest.raises(ComputeContractError, match="unsupported calculation intent schema_version"):
        prepare_calculation(workspace, intent_path)


def test_prepare_is_node_scoped_idempotent_and_preserves_research_state(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    intent_path = _intent(workspace)
    state_files = ["research_state.json", "hypotheses.json", "evidence_registry.json"]
    before = {name: (workspace / name).read_bytes() for name in state_files}

    first = prepare_calculation(workspace, intent_path)
    second = prepare_calculation(workspace, intent_path)

    assert first == second
    assert first["result"]["state"] == "prepared"
    assert first["result"]["program_status"] == "not_run"
    assert "claim_verdict" not in json.dumps(first)
    assert first["prepared"]["prepared_task"]["command"] == [
        "g16",
        "nodes/n001/inputs/candidate.gjf",
    ]
    assert (workspace / "nodes/n001/attempts/calc_n001_optfreq_001/intent.json").is_file()
    assert (workspace / "nodes/n001/attempts/calc_n001_optfreq_001/prepared.json").is_file()
    assert {name: (workspace / name).read_bytes() for name in state_files} == before

    changed = json.loads(intent_path.read_text(encoding="utf-8"))
    changed["purpose"] = "Changed purpose under a reused identifier."
    intent_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="different content"):
        prepare_calculation(workspace, intent_path)


def test_v2_prepare_uses_local_attempt_directory_and_explicit_scope(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    intent_path = _intent_v2(workspace)

    prepared = prepare_calculation(workspace, intent_path)

    attempt = workspace / "nodes/n001/attempts/calc_n001_optfreq_v2_001"
    assert (attempt / "intent.json").is_file()
    assert (attempt / "prepared.json").is_file()
    assert not (workspace / "nodes/n001/remote/calculations/calc_n001_optfreq_v2_001").exists()
    assert prepared["result"]["provenance"]["validation_scope"] == "tsfreq"
    assert prepared["result"]["provenance"]["attempt_kind"] == "primary"
    assert prepared["prepared"]["prepared_task"]["expected_artifacts"] == [
        "nodes/n001/attempts/calc_n001_optfreq_v2_001/outputs/candidate.log"
    ]

    value = json.loads(intent_path.read_text(encoding="utf-8"))
    value["validation_scope"] = "connectivity"
    value["intent_id"] = "calc_n001_wrong_scope"
    value["expected_artifacts"] = ["nodes/n001/attempts/calc_n001_wrong_scope/outputs/candidate.log"]
    intent_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="must match the validation node"):
        prepare_calculation(workspace, intent_path)

    value["validation_scope"] = "tsfreq"
    with pytest.raises(ComputeContractError, match="allowed only for candidate_search or validation"):
        _validate_intent_node_scope(
            workspace,
            value,
            {"schema_version": "ts-node/2", "node_type": "mechanism", "mechanism_action": "evaluate"},
        )


def test_v2_recalculation_requires_local_source_attempt_and_remote_mirror_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    prepare_calculation(workspace, _intent_v2(workspace))

    recalculation_id = "calc_n001_optfreq_v2_recalc"
    source_ref = {
        "source_node": "n001",
        "source_intent_id": "calc_n001_optfreq_v2_001",
        "changed_settings": ["functional", "basis_set"],
        "purpose": "method_robustness",
    }
    result = prepare_calculation(
        workspace,
        _intent_v2(
            workspace,
            intent_id=recalculation_id,
            attempt_kind="recalculation",
            recalculation_ref=source_ref,
        ),
    )
    assert result["result"]["provenance"]["recalculation_ref"] == source_ref

    missing_source = _intent_v2(
        workspace,
        intent_id="calc_n001_missing_source",
        attempt_kind="recalculation",
        recalculation_ref={**source_ref, "source_intent_id": "calc_missing"},
    )
    with pytest.raises(ComputeContractError, match="one local source attempt"):
        prepare_calculation(workspace, missing_source)

    _allow_remote(monkeypatch)
    remote = _remote_target()
    remote_intent = _intent_v2(workspace, intent_id="calc_n001_remote_v2", target=remote)
    remote_result = prepare_calculation(workspace, remote_intent)
    assert remote_result["prepared"]["execution_policy"]["authority"] == "execution_mirror"
    assert remote_result["result"]["provenance"]["remote_authority"] == "execution_mirror"

    invalid = json.loads(remote_intent.read_text(encoding="utf-8"))
    invalid["intent_id"] = "calc_n001_remote_unlabelled"
    invalid["expected_artifacts"] = ["nodes/n001/attempts/calc_n001_remote_unlabelled/outputs/candidate.log"]
    del invalid["execution_target"]["authority"]
    remote_intent.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="calculation_intent_v2.schema.json validation failed"):
        prepare_calculation(workspace, remote_intent)


def test_prepare_accepts_executable_intent_and_rejects_path_escape_and_wrong_route(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    intent_path = _intent(workspace)
    intent = json.loads(intent_path.read_text(encoding="utf-8"))

    intent["dry_run"] = False
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    prepared = prepare_calculation(workspace, intent_path)
    assert prepared["result"]["state"] == "prepared"

    intent["intent_id"] = "calc_n001_optfreq_unsafe"
    intent["dry_run"] = True
    intent["input_refs"]["gjf"] = "../../outside.gjf"
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="invalid workspace path"):
        prepare_calculation(workspace, intent_path)

    intent["input_refs"]["gjf"] = "nodes/n001/inputs/candidate.gjf"
    intent["expected_artifacts"] = ["nodes/n000/outputs/foreign.log"]
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="nodes/n001/attempts/calc_n001_optfreq_unsafe/outputs"):
        prepare_calculation(workspace, intent_path)

    intent["expected_artifacts"] = ["nodes/n001/outputs/candidate.log"]
    (workspace / "nodes/n001/inputs/candidate.gjf").write_text(
        "#P B3LYP/6-31G(d) sp\n\nSP\n\n0 1\nH 0 0 0\n\n",
        encoding="utf-8",
    )
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="route does not match"):
        prepare_calculation(workspace, intent_path)


def test_ssh_submit_and_cancel_are_bound_idempotent_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _allow_remote(monkeypatch)
    prepare_calculation(
        workspace,
        _intent(workspace, target=_remote_target(), dry_run=False),
    )
    calls = {"submit": 0, "cancel": 0}

    def fake_submit(config):
        calls["submit"] += 1
        return RemoteReceipt(
            node_id=config.node_id,
            host=config.compute_host,
            remote_dir=config.remote_dir,
            command=config.command,
            receipt_path=f"{config.remote_dir}/remote_receipt.json",
            metadata={"transport": "ssh"},
        )

    def fake_poll(config):
        return RemoteJobStatus(
            node_id=config.node_id,
            host=config.compute_host,
            remote_dir=config.remote_dir,
            state="running",
            pid="123",
        )

    def fake_kill(config, *, expected_pid):
        calls["cancel"] += 1
        assert expected_pid == "123"
        return RemoteJobStatus(
            node_id=config.node_id,
            host=config.compute_host,
            remote_dir=config.remote_dir,
            state="killed",
            pid="123",
        )

    monkeypatch.setattr("ts_compute.control.job_lifecycle.submit_async", fake_submit)
    monkeypatch.setattr("ts_compute.control.job_lifecycle.poll", fake_poll)
    monkeypatch.setattr("ts_compute.control.job_lifecycle.kill", fake_kill)

    binding = preflight_calculation(
        workspace,
        "submit",
        "n001",
        "gaussian",
        intent_id="calc_n001_optfreq_001",
    )
    assert binding["transport"] == "ssh"
    assert binding["execution_summary"]["login_host"] == "login.test"

    submitted = submit_calculation(workspace, "calc_n001_optfreq_001", binding["intent_digest"])
    assert submitted["state"] == "submitted"
    assert submit_calculation(workspace, "calc_n001_optfreq_001") == submitted
    assert calls["submit"] == 1
    inspected = calculation_status(workspace, "calc_n001_optfreq_001")
    assert inspected["job_id"] == "123"

    cancel_binding = preflight_calculation(
        workspace,
        "cancel",
        "n001",
        "gaussian",
        intent_id="calc_n001_optfreq_001",
    )
    assert cancel_binding["state"] == "running"
    cancelled = cancel_calculation(
        workspace,
        "calc_n001_optfreq_001",
        cancel_binding["intent_digest"],
        cancel_binding["job_id"],
    )
    assert cancelled["state"] == "stopped"
    assert cancelled["program_status"] == "stopped"
    assert cancel_calculation(workspace, "calc_n001_optfreq_001") == cancelled
    assert calls["cancel"] == 1


@pytest.mark.parametrize(
    ("operation", "failure_text", "error_class"),
    [
        ("submit", "qsub result unknown", "submission_ambiguous"),
        ("cancel", "qdel result unknown", "cancellation_ambiguous"),
    ],
)
def test_ssh_ambiguous_control_outcome_refuses_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    failure_text: str,
    error_class: str,
) -> None:
    workspace = _workspace(tmp_path)
    _allow_remote(monkeypatch)
    prepare_calculation(workspace, _intent(workspace, target=_remote_target(), dry_run=False))

    def receipt(config):
        return RemoteReceipt(
            node_id=config.node_id,
            host=config.compute_host,
            remote_dir=config.remote_dir,
            command=config.command,
            receipt_path=f"{config.remote_dir}/remote_receipt.json",
        )

    monkeypatch.setattr("ts_compute.control.job_lifecycle.submit_async", receipt)
    if operation == "cancel":
        submit_calculation(workspace, "calc_n001_optfreq_001")
        monkeypatch.setattr(
            "ts_compute.control.job_lifecycle.poll",
            lambda config: RemoteJobStatus(
                node_id=config.node_id,
                host=config.compute_host,
                remote_dir=config.remote_dir,
                state="running",
                pid="123",
            ),
        )
        calculation_status(workspace, "calc_n001_optfreq_001")
        monkeypatch.setattr(
            "ts_compute.control.job_lifecycle.kill",
            lambda _config, *, expected_pid: (_ for _ in ()).throw(RuntimeError(failure_text)),
        )
        result = cancel_calculation(workspace, "calc_n001_optfreq_001")
        invoke = lambda: cancel_calculation(workspace, "calc_n001_optfreq_001")
    else:
        monkeypatch.setattr(
            "ts_compute.control.job_lifecycle.submit_async",
            lambda _config: (_ for _ in ()).throw(RuntimeError(failure_text)),
        )
        result = submit_calculation(workspace, "calc_n001_optfreq_001")
        invoke = lambda: submit_calculation(workspace, "calc_n001_optfreq_001")

    assert result["state"] == "unknown"
    assert result["error_class"] == error_class
    with pytest.raises(ComputeContractError, match="refuses automatic replay"):
        invoke()
    with pytest.raises(ComputeContractError, match="refuses automatic replay"):
        preflight_calculation(
            workspace,
            operation,
            "n001",
            "gaussian",
            intent_id="calc_n001_optfreq_001",
        )


def test_control_guard_survives_host_process_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _allow_remote(monkeypatch)
    prepare_calculation(workspace, _intent(workspace, target=_remote_target(), dry_run=False))
    monkeypatch.setattr(
        "ts_compute.control.job_lifecycle.submit_async",
        lambda _config: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        submit_calculation(workspace, "calc_n001_optfreq_001")

    base = workspace / "nodes/n001/attempts/calc_n001_optfreq_001"
    assert (base / "submit_guard.json").is_file()
    assert not (base / "submit_result.json").exists()
    operations = operational_snapshot(workspace)
    assert operations["operational_summary"]["control_pending_count"] == 1
    assert operations["pending_controls"] == [
        {
            "operation": "submit",
            "intent_id": "calc_n001_optfreq_001",
            "guard_ref": "nodes/n001/attempts/calc_n001_optfreq_001/submit_guard.json",
        }
    ]
    with pytest.raises(ComputeContractError, match="durable control guard"):
        submit_calculation(workspace, "calc_n001_optfreq_001")
    with pytest.raises(ComputeContractError, match="manual reconciliation"):
        preflight_calculation(
            workspace,
            "submit",
            "n001",
            "gaussian",
            intent_id="calc_n001_optfreq_001",
        )


def test_mcp_control_preflight_requires_host_connection_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    prepare_calculation(
        workspace,
        _intent_v2(workspace, target=_mcp_target(), dry_run=False),
    )
    monkeypatch.delenv("TS_CLUSTER_MCP_URL", raising=False)
    monkeypatch.delenv("TS_CLUSTER_MCP_TOKEN", raising=False)

    with pytest.raises(ComputeContractError, match="TS_CLUSTER_MCP_URL is not configured"):
        preflight_calculation(
            workspace,
            "submit",
            "n001",
            "gaussian",
            intent_id="calc_n001_optfreq_v2_001",
        )
    with pytest.raises(ComputeContractError, match="TS_CLUSTER_MCP_URL is not configured"):
        submit_calculation(workspace, "calc_n001_optfreq_v2_001")
    assert not (
        workspace / "nodes/n001/attempts/calc_n001_optfreq_v2_001/submit_guard.json"
    ).exists()


def test_mcp_staging_failure_is_not_submission_ambiguous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _configure_mcp(monkeypatch)
    intent_id = "calc_n001_optfreq_v2_001"
    prepare_calculation(
        workspace,
        _intent_v2(workspace, target=_mcp_target(), dry_run=False),
    )

    class FlakyStagingClient:
        def __init__(self) -> None:
            self.ensure_calls = 0

        def ensure_directory(self, _path: str) -> None:
            self.ensure_calls += 1
            if self.ensure_calls == 1:
                raise MCPClientError("MCP tool 'ts_ensure_directory' failed: ReadTimeout")

        def upload_file(self, _source: Path, remote_path: str):
            return {"path": remote_path}

        def submit(self, request):
            return RemoteReceipt(
                node_id="n001",
                host="cluster-mcp",
                remote_dir=request["workdir"],
                command=["mcp", "ts_submit_job", request["submission_id"]],
                receipt_path=f"{request['workdir']}/ts_submission.json",
                scheduler_id="42003.cluster",
                metadata={"submission_id": request["submission_id"]},
            )

    client = FlakyStagingClient()
    monkeypatch.setattr("ts_compute.control._mcp_client", lambda: client)

    result = submit_calculation(workspace, intent_id)

    assert result["state"] == "failed"
    assert result["error_class"] == "mcp_staging_failed"
    assert result["provenance"]["failure_type"] == "MCPClientError"
    assert result["provenance"]["submission_phase"] == "ensure_directory"
    assert result["provenance"]["submission_attempted"] is False
    assert result["provenance"]["retry_safe"] is True
    assert "ReadTimeout" in result["provenance"]["failure_message"]
    assert result["control"] == {
        "schema_version": "ts-control-outcome/1",
        "operation": "submit",
        "phase": "ensure_directory",
        "effect_outcome": "failed",
        "effect_attempted": False,
        "retry_disposition": "retry_same_submission",
        "reconciliation_required": False,
        "submission_id": result["control"]["submission_id"],
        "job_id": None,
    }
    preflight = preflight_calculation(
        workspace,
        "submit",
        "n001",
        "gaussian",
        intent_id=intent_id,
    )
    assert preflight["intent_id"] == intent_id
    before_retry = operational_snapshot(workspace)
    assert before_retry["operational_summary"]["control_unresolved_count"] == 1
    assert before_retry["operational_summary"]["control_retryable_count"] == 1
    root_report = report_workspace(workspace)
    assert root_report["retryable_controls"] == before_retry["retryable_controls"]
    assert root_report["operational_summary"]["control_retryable_count"] == 1

    submitted = submit_calculation(workspace, intent_id)
    assert submitted["state"] == "submitted"
    assert submitted["job_id"] == "42003.cluster"
    base = workspace / f"nodes/n001/attempts/{intent_id}"
    assert json.loads((base / "submit_result.json").read_text(encoding="utf-8"))["state"] == "failed"
    assert (base / "submit_attempt_0002_guard.json").is_file()
    assert json.loads((base / "submit_attempt_0002_result.json").read_text(encoding="utf-8"))["state"] == "submitted"
    after_retry = operational_snapshot(workspace)
    assert after_retry["unresolved_controls"] == []
    assert after_retry["retryable_controls"] == []


def test_mcp_scheduler_submit_failure_remains_ambiguous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _configure_mcp(monkeypatch)
    intent_id = "calc_n001_optfreq_v2_001"
    prepare_calculation(
        workspace,
        _intent_v2(workspace, target=_mcp_target(), dry_run=False),
    )

    class FailingSubmitClient:
        def ensure_directory(self, _path: str) -> None:
            return None

        def upload_file(self, _source: Path, remote_path: str):
            return {"path": remote_path}

        def submit(self, _request):
            raise MCPClientError("MCP tool 'ts_submit_job' failed: ReadTimeout")

    monkeypatch.setattr("ts_compute.control._mcp_client", lambda: FailingSubmitClient())

    result = submit_calculation(workspace, intent_id)

    assert result["state"] == "unknown"
    assert result["error_class"] == "submission_ambiguous"
    assert result["provenance"]["submission_phase"] == "scheduler_submit"
    assert result["provenance"]["submission_attempted"] is True
    assert result["provenance"]["retry_safe"] is False


def test_mcp_ambiguous_record_uses_bound_scheduler_state_when_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _configure_mcp(monkeypatch)
    intent_id = "calc_n001_optfreq_v2_001"
    prepare_calculation(
        workspace,
        _intent_v2(workspace, target=_mcp_target(), dry_run=False),
    )

    class AmbiguousRecordClient:
        def __init__(self) -> None:
            self.request: dict[str, object] | None = None

        def ensure_directory(self, _path: str) -> None:
            return None

        def upload_file(self, _source: Path, remote_path: str):
            return {"path": remote_path}

        def submit(self, request):
            self.request = request
            raise MCPClientError("MCP submit response was interrupted")

        def status(self, submission_id: str, *, include_history: bool):
            assert include_history is True
            assert self.request is not None
            return {
                "schema_version": "ts-cluster-submission/1",
                "submission_id": submission_id,
                "found": True,
                "state": "ambiguous",
                "job_id": "42005.cluster",
                "request": self.request,
                "result": None,
                "scheduler": {"state": "R"},
                "scheduler_query": {"outcome": "succeeded", "error_class": None, "message": None},
                "updated_at": "2026-08-06T04:00:00+00:00",
            }

    client = AmbiguousRecordClient()
    monkeypatch.setattr("ts_compute.control._mcp_client", lambda: client)

    assert submit_calculation(workspace, intent_id)["state"] == "unknown"
    status = calculation_status(workspace, intent_id)

    assert status["state"] == "running"
    assert status["job_id"] == "42005.cluster"
    base = workspace / f"nodes/n001/attempts/{intent_id}"
    reconciliation = json.loads((base / "submit_reconciliation.json").read_text(encoding="utf-8"))
    assert reconciliation["state"] == "submitted"
    assert reconciliation["provenance"]["server_submission_state"] == "ambiguous"


def test_mcp_status_reconciles_ambiguous_submit_and_unblocks_collection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _configure_mcp(monkeypatch)
    intent_id = "calc_n001_optfreq_v2_001"
    prepare_calculation(
        workspace,
        _intent_v2(workspace, target=_mcp_target(), dry_run=False),
    )

    class ReconciliationClient:
        def __init__(self) -> None:
            self.request: dict[str, object] | None = None
            self.submit_calls = 0
            self.cancel_calls = 0
            self.server_state = "submitted"

        def ensure_directory(self, _path: str) -> None:
            return None

        def upload_file(self, _source: Path, remote_path: str):
            return {"path": remote_path}

        def submit(self, request):
            self.submit_calls += 1
            self.request = request
            raise MCPClientError("MCP tool 'ts_submit_job' failed: stream disconnected")

        def status(self, submission_id: str, *, include_history: bool):
            assert include_history is True
            assert self.request is not None
            return {
                "schema_version": "ts-cluster-submission/1",
                "submission_id": submission_id,
                "found": True,
                "state": self.server_state,
                "job_id": "42004.cluster",
                "request": self.request,
                "result": {
                    "schema_version": (
                        "ts-cluster-cancellation-result/1"
                        if self.server_state == "cancelled"
                        else "ts-cluster-submission-result/1"
                    ),
                    "state": self.server_state,
                    "job_id": "42004.cluster",
                    "scheduler": {"action": "delete"} if self.server_state == "cancelled" else None,
                },
                "scheduler": {"state": "R"},
                "scheduler_query": {"outcome": "succeeded", "error_class": None, "message": None},
                "updated_at": "2026-08-06T04:00:00+00:00",
            }

        def cancel(self, _submission_id: str, _job_id: str):
            self.cancel_calls += 1
            self.server_state = "cancelled"
            raise MCPClientError("MCP tool 'ts_cancel_submission' failed: stream disconnected")

        def download_file(self, _remote_path: str, destination: Path):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(_gaussian_log(), encoding="utf-8")
            return {"path": str(destination), "size": destination.stat().st_size, "sha256": "3" * 64}

    client = ReconciliationClient()
    monkeypatch.setattr("ts_compute.control._mcp_client", lambda: client)

    ambiguous = submit_calculation(workspace, intent_id)
    assert ambiguous["state"] == "unknown"
    before = operational_snapshot(workspace)
    assert before["operational_summary"]["ambiguous_submission_count"] == 1

    status = calculation_status(workspace, intent_id)
    assert status["state"] == "running"
    base = workspace / f"nodes/n001/attempts/{intent_id}"
    reconciliation = json.loads((base / "submit_reconciliation.json").read_text(encoding="utf-8"))
    assert reconciliation["state"] == "submitted"
    assert reconciliation["job_id"] == "42004.cluster"
    assert reconciliation["control"]["phase"] == "reconciled"
    assert (base / "mcp_receipt.json").is_file()
    after = operational_snapshot(workspace)
    assert after["unresolved_controls"] == []
    assert after["ambiguous_submissions"] == []

    collected = collect_calculation(workspace, intent_id, ["candidate.log"])
    assert collected["state"] == "collected"
    assert submit_calculation(workspace, intent_id)["job_id"] == "42004.cluster"
    assert client.submit_calls == 1

    cancelled = cancel_calculation(workspace, intent_id, expected_job_id="42004.cluster")
    assert cancelled["state"] == "unknown"
    assert operational_snapshot(workspace)["operational_summary"]["ambiguous_cancellation_count"] == 1
    stopped = calculation_status(workspace, intent_id)
    assert stopped["state"] == "stopped"
    cancel_reconciliation = json.loads((base / "cancel_reconciliation.json").read_text(encoding="utf-8"))
    assert cancel_reconciliation["state"] == "stopped"
    assert cancel_reconciliation["control"]["phase"] == "reconciled"
    assert operational_snapshot(workspace)["ambiguous_cancellations"] == []
    assert cancel_calculation(workspace, intent_id)["state"] == "stopped"
    assert client.cancel_calls == 1


def test_mcp_transport_submit_status_tail_collect_and_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _configure_mcp(monkeypatch)
    intent_id = "calc_n001_optfreq_v2_001"
    prepared = prepare_calculation(
        workspace,
        _intent_v2(workspace, target=_mcp_target(), dry_run=False),
    )
    policy = prepared["prepared"]["execution_policy"]
    workspace_id = policy["workspace_id"]
    remote_dir = f"workspaces/{workspace_id}/runs/n001/calc_n001_optfreq_v2_001"
    assert policy["namespace_version"] == "ts-mcp-workspace/1"
    assert policy["requested_remote_dir"] == "runs/n001/calc_n001_optfreq_v2_001"
    assert policy["remote_dir"] == remote_dir
    assert policy["submission_id"].startswith(f"tsjob_{workspace_id}_{intent_id}_")

    class FakeMCPClient:
        def __init__(self) -> None:
            self.request: dict[str, object] | None = None
            self.uploads: list[tuple[str, str]] = []
            self.cancels: list[tuple[str, str]] = []
            self.scheduler_state = "R"

        def ensure_directory(self, path: str) -> None:
            assert path == remote_dir

        def upload_file(self, source: Path, remote_path: str):
            self.uploads.append((source.name, remote_path))
            return {"path": remote_path}

        def submit(self, request):
            self.request = request
            return RemoteReceipt(
                node_id="n001",
                host="cluster-mcp",
                remote_dir=request["workdir"],
                command=["mcp", "ts_submit_job", request["submission_id"]],
                receipt_path=f"{request['workdir']}/ts_submission.json",
                scheduler_id="42001.cluster",
                metadata={
                    "submission_id": request["submission_id"],
                    "intent_id": request["intent_id"],
                    "intent_digest": request["intent_digest"],
                    "backend": request["backend"],
                    "expected_artifacts": json.dumps(request["expected_artifacts"]),
                },
            )

        def status(self, submission_id: str, *, include_history: bool):
            assert include_history is True
            assert self.request is not None
            scheduler = {"state": self.scheduler_state}
            if self.scheduler_state == "F":
                scheduler["exit_status"] = 0
            return {
                "schema_version": "ts-cluster-submission/1",
                "submission_id": submission_id,
                "state": "submitted",
                "job_id": "42001.cluster",
                "request": self.request,
                "scheduler": scheduler,
            }

        def read_tail(self, remote_path: str, *, max_bytes: int):
            assert remote_path.endswith("/candidate.log")
            return {"data": b"line 1\nNormal termination\n", "size": 26, "sha256": "1" * 64}

        def download_file(self, remote_path: str, destination: Path):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(_gaussian_log(), encoding="utf-8")
            return {"path": str(destination), "size": destination.stat().st_size, "sha256": "2" * 64}

        def cancel(self, submission_id: str, job_id: str):
            self.cancels.append((submission_id, job_id))
            return {
                "schema_version": "ts-cluster-cancellation-result/1",
                "submission_id": submission_id,
                "job_id": job_id,
                "state": "cancelled",
                "scheduler": {"action": "delete"},
            }

    client = FakeMCPClient()
    monkeypatch.setattr("ts_compute.control._mcp_client", lambda: client)

    binding = preflight_calculation(
        workspace,
        "submit",
        "n001",
        "gaussian",
        intent_id=intent_id,
    )
    assert binding["transport"] == "mcp"
    assert binding["execution_summary"]["queue"] == "workq"
    submitted = submit_calculation(workspace, intent_id, binding["intent_digest"])
    assert submitted["job_id"] == "42001.cluster"
    assert client.request is not None
    assert client.request["intent_digest"] == binding["intent_digest"]
    assert client.request["workdir"] == remote_dir
    assert client.request["submission_id"] == policy["submission_id"]
    assert str(client.request["intent_digest"]).count("sha256:") == 1
    assert {name for name, _remote in client.uploads} == {"candidate.gjf", "run_mcp_job.sh"}
    runner = workspace / f"nodes/n001/attempts/{intent_id}/run_mcp_job.sh"
    runner_text = runner.read_text(encoding="utf-8")
    assert 'scratch_root=$(mktemp -d "${scratch_base%/}/ts-gaussian.XXXXXX")' in runner_text
    assert 'export GAUSS_SCRDIR="$scratch_root"' in runner_text
    assert "trap cleanup EXIT" in runner_text
    assert "g16 < candidate.gjf > candidate.log 2> remote_job.stderr" in runner_text
    assert 'rm -rf -- "$scratch_root"' in runner_text

    status = calculation_status(workspace, intent_id)
    assert status["state"] == "running"
    assert status["program_status"] == "not_run"
    assert status["job_id"] == "42001.cluster"
    status_path = workspace / f"nodes/n001/attempts/{intent_id}/status.json"
    bound_status = status_path.read_bytes()
    original_status = client.status

    def changed_job_status(submission_id: str, *, include_history: bool):
        changed = original_status(submission_id, include_history=include_history)
        changed["job_id"] = "99999.cluster"
        return changed

    client.status = changed_job_status
    with pytest.raises(ComputeContractError, match="durable submit result"):
        calculation_status(workspace, intent_id)
    assert status_path.read_bytes() == bound_status
    client.status = original_status
    tail = calculation_tail(workspace, intent_id, "candidate.log", 1)
    assert tail["text"] == "Normal termination"
    client.scheduler_state = "C"
    status = calculation_status(workspace, intent_id)
    assert status["state"] == "completed"
    assert status["program_status"] == "not_run"
    assert status["error_class"] is None
    client.scheduler_state = "F"
    status = calculation_status(workspace, intent_id)
    assert status["program_status"] == "completed"
    collected = collect_calculation(workspace, intent_id, ["candidate.log"])
    assert collected["program_status"] == "completed"
    assert collected["artifact_refs"] == [
        "nodes/n001/attempts/calc_n001_optfreq_v2_001/outputs/collected/candidate.log"
    ]

    with pytest.raises(ComputeContractError, match="active or unresolved"):
        cancel_calculation(workspace, intent_id, expected_job_id="42001.cluster")


def test_mcp_namespace_separates_identical_intents_in_two_workspaces(tmp_path: Path) -> None:
    first_workspace = _workspace(tmp_path / "first")
    second_workspace = _workspace(tmp_path / "second")

    first = prepare_calculation(
        first_workspace,
        _intent_v2(first_workspace, target=_mcp_target(), dry_run=False),
    )["prepared"]["execution_policy"]
    second = prepare_calculation(
        second_workspace,
        _intent_v2(second_workspace, target=_mcp_target(), dry_run=False),
    )["prepared"]["execution_policy"]

    assert first["workspace_id"] != second["workspace_id"]
    assert first["requested_remote_dir"] == second["requested_remote_dir"]
    assert first["remote_dir"] != second["remote_dir"]
    assert first["submission_id"] != second["submission_id"]
    assert first["remote_dir"].startswith(f"workspaces/{first['workspace_id']}/")
    assert second["remote_dir"].startswith(f"workspaces/{second['workspace_id']}/")


def test_mcp_prepared_record_without_workspace_namespace_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _configure_mcp(monkeypatch)
    intent_id = "calc_n001_optfreq_v2_001"
    prepared_result = prepare_calculation(
        workspace,
        _intent_v2(workspace, target=_mcp_target(), dry_run=False),
    )
    prepared = prepared_result["prepared"]
    prepared["execution_policy"] = prepared_result["intent"]["execution_target"]
    prepared_path = workspace / f"nodes/n001/attempts/{intent_id}/prepared.json"
    prepared_path.write_text(json.dumps(prepared), encoding="utf-8")

    with pytest.raises(ComputeContractError, match="execution policy does not match"):
        submit_calculation(workspace, intent_id)


def test_mcp_cancel_is_bound_to_preflight_job_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _configure_mcp(monkeypatch)
    intent_id = "calc_n001_optfreq_v2_001"
    prepare_calculation(
        workspace,
        _intent_v2(workspace, target=_mcp_target(), dry_run=False),
    )

    class FakeMCPClient:
        request: dict[str, object] | None = None
        cancels: list[tuple[str, str]] = []

        def ensure_directory(self, _path: str) -> None:
            return None

        def upload_file(self, _source: Path, remote_path: str):
            return {"path": remote_path}

        def submit(self, request):
            self.request = request
            return RemoteReceipt(
                node_id="n001",
                host="cluster-mcp",
                remote_dir=request["workdir"],
                command=["mcp", "ts_submit_job", request["submission_id"]],
                receipt_path=f"{request['workdir']}/ts_submission.json",
                scheduler_id="42001.cluster",
                metadata={"submission_id": request["submission_id"]},
            )

        def cancel(self, submission_id: str, job_id: str):
            self.cancels.append((submission_id, job_id))
            return {
                "schema_version": "ts-cluster-cancellation-result/1",
                "submission_id": submission_id,
                "job_id": job_id,
                "state": "cancelled",
                "scheduler": {"action": "delete"},
            }

    client = FakeMCPClient()
    monkeypatch.setattr("ts_compute.control._mcp_client", lambda: client)
    submit_calculation(workspace, intent_id)
    binding = preflight_calculation(
        workspace,
        "cancel",
        "n001",
        "gaussian",
        intent_id=intent_id,
    )
    assert binding["job_id"] == "42001.cluster"

    with pytest.raises(ComputeContractError, match="changed after preflight binding"):
        cancel_calculation(workspace, intent_id, expected_job_id="other.cluster")
    cancelled = cancel_calculation(workspace, intent_id, expected_job_id=binding["job_id"])
    assert cancelled["state"] == "stopped"
    assert client.request is not None
    assert client.cancels == [(client.request["submission_id"], "42001.cluster")]


def test_mcp_target_rejects_embedded_connection_or_incomplete_resources(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    intent_path = _intent_v2(workspace, target=_mcp_target())
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    intent["execution_target"]["endpoint"] = "https://cluster.example/mcp"
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="calculation_intent_v2.schema.json validation failed"):
        prepare_calculation(workspace, intent_path)

    del intent["execution_target"]["endpoint"]
    intent["execution_target"]["execution"]["walltime"] = "01:00:00"
    intent["execution_target"]["execution"]["environment"] = {"API_TOKEN": "secret"}
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="credential fields"):
        prepare_calculation(workspace, intent_path)

    intent["execution_target"]["execution"]["environment"] = {}
    del intent["execution_target"]["execution"]["walltime"]
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="calculation_intent_v2.schema.json validation failed"):
        prepare_calculation(workspace, intent_path)


def test_prepare_rejects_canonical_state_as_backend_input(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    intent_path = _intent(workspace)
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    intent["backend"] = "xtb"
    intent["task_type"] = "opt"
    intent["input_refs"] = {"xyz": "research_state.json"}
    intent["expected_artifacts"] = ["nodes/n001/outputs/xtbopt.xyz"]
    intent_path.write_text(json.dumps(intent), encoding="utf-8")

    with pytest.raises(ComputeContractError, match="workspace inputs or node inputs/outputs"):
        prepare_calculation(workspace, intent_path)


def test_gaussian_prepare_reports_unexpected_input_roles(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source_xyz = workspace / "nodes/n001/inputs/source.xyz"
    source_xyz.write_text("1\nsource\nH 0 0 0\n", encoding="utf-8")
    intent_path = _intent(workspace)
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    intent["input_refs"]["source_xyz"] = "nodes/n001/inputs/source.xyz"
    intent_path.write_text(json.dumps(intent), encoding="utf-8")

    with pytest.raises(ComputeContractError, match=r"unexpected=\['source_xyz'\]"):
        prepare_calculation(workspace, intent_path)


def test_remote_target_requires_host_and_directory_allowlists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _workspace(tmp_path)
    intent_path = _intent(workspace, target=_remote_target())

    with pytest.raises(ComputeContractError, match="TS_COMPUTE_LOGIN_HOSTS"):
        prepare_calculation(workspace, intent_path)

    _allow_remote(monkeypatch)
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    intent["execution_target"]["remote_dir"] = "/other/n001"
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="outside TS_COMPUTE_REMOTE_ROOTS"):
        prepare_calculation(workspace, intent_path)


def test_remote_target_requires_explicit_transport(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    target = _remote_target()
    del target["transport"]
    intent_path = _intent(workspace, target=target)

    with pytest.raises(ComputeContractError, match="calculation_intent_v2.schema.json validation failed"):
        prepare_calculation(workspace, intent_path)


def test_status_tail_and_collect_use_prepared_remote_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _allow_remote(monkeypatch)
    prepare_calculation(workspace, _intent(workspace, target=_remote_target(), dry_run=False))
    seen: dict[str, object] = {}

    poll_states = iter(["running"])

    def fake_poll(config):
        seen.setdefault("poll", []).append(config)
        state = next(poll_states)
        return RemoteJobStatus(
            node_id="n001",
            host="compute.test",
            remote_dir="/remote/ts/n001/calc_n001_optfreq_001",
            state=state,
            pid="123",
            exit_status=0 if state == "completed" else None,
            files=["candidate.log"],
        )

    def fake_tail(config, *, artifact, lines):
        seen["tail"] = (artifact, lines)
        return "normal termination\n"

    def fake_fetch(config, *, artifacts, tolerate_missing):
        seen["fetch"] = (list(artifacts), tolerate_missing)
        config.output_dir.mkdir(parents=True, exist_ok=True)
        (config.output_dir / "candidate.log").write_text(_gaussian_log(), encoding="utf-8")
        return list(artifacts)

    monkeypatch.setattr("ts_compute.control.job_lifecycle.poll", fake_poll)
    monkeypatch.setattr("ts_compute.control.job_lifecycle.tail", fake_tail)
    monkeypatch.setattr("ts_compute.control.job_lifecycle.fetch", fake_fetch)
    monkeypatch.setattr(
        "ts_compute.control.job_lifecycle.submit_async",
        lambda config: RemoteReceipt(
            node_id=config.node_id,
            host=config.compute_host,
            remote_dir=config.remote_dir,
            command=config.command,
            receipt_path=f"{config.remote_dir}/remote_receipt.json",
            scheduler_id="123",
            metadata={"expected_artifacts": json.dumps(list(config.expected_artifacts))},
        ),
    )

    submit_calculation(workspace, "calc_n001_optfreq_001")
    status = calculation_status(workspace, "calc_n001_optfreq_001")
    tail = calculation_tail(workspace, "calc_n001_optfreq_001", "candidate.log", 40)
    collected = collect_calculation(workspace, "calc_n001_optfreq_001", ["candidate.log"])

    assert status["state"] == "running"
    assert status["program_status"] == "not_run"
    assert tail["text"] == "normal termination\n"
    assert seen["tail"] == ("candidate.log", 40)
    assert seen["fetch"] == (["candidate.log"], False)
    assert collected["program_status"] == "not_run"
    assert collected["artifact_refs"] == [
        "nodes/n001/attempts/calc_n001_optfreq_001/outputs/collected/candidate.log"
    ]
    assert len(seen["poll"]) == 1
    config = seen["poll"][-1]
    assert config.login_host == "login.test"
    assert config.compute_host == "compute.test"
    assert config.command == ["g16", "candidate.gjf"]
    assert config.stdout_name == "candidate.log"

    with pytest.raises(ComputeContractError, match="not allowlisted"):
        calculation_tail(workspace, "calc_n001_optfreq_001", "arbitrary.log", 40)
    with pytest.raises(ComputeContractError, match="unique subset"):
        collect_calculation(workspace, "calc_n001_optfreq_001", ["arbitrary.log"])
    with pytest.raises(ComputeContractError, match="overwrite"):
        collect_calculation(workspace, "calc_n001_optfreq_001", ["candidate.log"])


def test_collect_requires_durable_submit_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _workspace(tmp_path)
    _allow_remote(monkeypatch)
    prepare_calculation(workspace, _intent(workspace, target=_remote_target()))

    with pytest.raises(ComputeContractError, match="durable successful submit result"):
        collect_calculation(workspace, "calc_n001_optfreq_001", ["candidate.log"])


def test_collect_does_not_refresh_active_scheduler_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _allow_remote(monkeypatch)
    prepare_calculation(workspace, _intent(workspace, target=_remote_target(), dry_run=False))
    polls = 0

    def fake_poll(_config):
        nonlocal polls
        polls += 1
        return RemoteJobStatus(
            node_id="n001",
            host="compute.test",
            remote_dir="/remote/ts/n001/calc_n001_optfreq_001",
            state="running",
            pid="123",
        )

    def fake_fetch(config, *, artifacts, tolerate_missing):
        config.output_dir.mkdir(parents=True, exist_ok=True)
        (config.output_dir / "candidate.log").write_text(_gaussian_log(), encoding="utf-8")
        return list(artifacts)

    monkeypatch.setattr("ts_compute.control.job_lifecycle.poll", fake_poll)
    monkeypatch.setattr("ts_compute.control.job_lifecycle.fetch", fake_fetch)
    monkeypatch.setattr(
        "ts_compute.control.job_lifecycle.submit_async",
        lambda config: RemoteReceipt(
            node_id=config.node_id,
            host=config.compute_host,
            remote_dir=config.remote_dir,
            command=config.command,
            receipt_path=f"{config.remote_dir}/remote_receipt.json",
            scheduler_id="123",
            metadata={"expected_artifacts": json.dumps(list(config.expected_artifacts))},
        ),
    )

    submit_calculation(workspace, "calc_n001_optfreq_001")
    calculation_status(workspace, "calc_n001_optfreq_001")
    collected = collect_calculation(workspace, "calc_n001_optfreq_001", ["candidate.log"])

    assert collected["program_status"] == "not_run"
    assert polls == 1


def test_prepared_backend_metadata_is_revalidated_before_remote_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _allow_remote(monkeypatch)
    prepare_calculation(workspace, _intent(workspace, target=_remote_target()))
    prepared_path = workspace / "nodes/n001/attempts/calc_n001_optfreq_001/prepared.json"
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    prepared["prepared_task"]["command"] = ["arbitrary-command"]
    prepared_path.write_text(json.dumps(prepared), encoding="utf-8")

    with pytest.raises(ComputeContractError, match="backend metadata does not match"):
        calculation_status(workspace, "calc_n001_optfreq_001")


def test_gaussian_parse_returns_program_facts_without_workspace_verdict(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    prepare_calculation(workspace, _intent(workspace))
    log = workspace / "nodes" / "n001" / "attempts" / "calc_n001_optfreq_001" / "outputs" / "candidate.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(_gaussian_log(), encoding="utf-8")
    state_before = (workspace / "research_state.json").read_bytes()

    result = parse_calculation(
        workspace,
        "calc_n001_optfreq_001",
        "nodes/n001/attempts/calc_n001_optfreq_001/outputs/candidate.log",
    )

    assert result["state"] == "parsed"
    assert result["program_status"] == "completed"
    assert result["parser_facts"]["normal_termination"] is True
    assert result["parser_facts"]["imaginary_frequency_count"] == 1
    assert "claim_verdict" not in result
    assert "accepted_ts" not in result
    assert (workspace / "research_state.json").read_bytes() == state_before
    assert (workspace / "nodes/n001/attempts/calc_n001_optfreq_001/outputs/calculation_result.json").is_file()
    assert (workspace / "nodes/n001/attempts/calc_n001_optfreq_001/outputs/parsed/validation_summary.json").is_file()
    assert parse_calculation(
        workspace,
        "calc_n001_optfreq_001",
        "nodes/n001/attempts/calc_n001_optfreq_001/outputs/candidate.log",
    ) == result

    log.write_text(_gaussian_log() + "\n additional completed output\n", encoding="utf-8")
    with pytest.raises(ComputeContractError, match="different source content"):
        parse_calculation(
            workspace,
            "calc_n001_optfreq_001",
            "nodes/n001/attempts/calc_n001_optfreq_001/outputs/candidate.log",
        )

    foreign = workspace / "nodes" / "n000" / "outputs" / "candidate.log"
    foreign.write_text(_gaussian_log(), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="nodes/n001/attempts/calc_n001_optfreq_001/outputs"):
        parse_calculation(workspace, "calc_n001_optfreq_001", "nodes/n000/outputs/candidate.log")


def test_gaussian_irc_parse_writes_attempt_contract_artifacts(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    intent_id = "calc_n001_irc_001"
    gjf = workspace / "nodes/n001/inputs/irc.gjf"
    gjf.write_text(
        "%chk=irc.chk\n#P B3LYP/6-31G(d) IRC=(Forward,MaxPoints=2)\n\nIRC\n\n0 1\nH 0 0 0\n\n",
        encoding="utf-8",
    )
    intent = {
        "schema_version": "ts-calculation-intent/2",
        "intent_id": intent_id,
        "node_id": "n001",
        "purpose": "Parse one forward IRC path without making a connectivity verdict.",
        "validation_scope": "tsfreq",
        "attempt_kind": "primary",
        "recalculation_ref": None,
        "backend": "gaussian",
        "task_type": "irc",
        "input_refs": {"gjf": "nodes/n001/inputs/irc.gjf"},
        "settings": {},
        "expected_artifacts": [f"nodes/n001/attempts/{intent_id}/outputs/irc.log"],
        "execution_target": {"kind": "local"},
        "dry_run": True,
    }
    intent_path = workspace / "nodes/n001/scratch/irc-intent.json"
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    prepare_calculation(workspace, intent_path)
    source = workspace / f"nodes/n001/attempts/{intent_id}/outputs/irc.log"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(_gaussian_irc_log(), encoding="utf-8")

    result = parse_calculation(workspace, intent_id, f"nodes/n001/attempts/{intent_id}/outputs/irc.log")

    parse_dir = workspace / f"nodes/n001/attempts/{intent_id}/outputs/parsed"
    assert result["program_status"] == "completed"
    assert result["provenance"]["parser_contract"] == "gaussian-irc-parser/1"
    assert result["parser_facts"]["first_point_number"] == 1
    assert result["parser_facts"]["last_point_number"] == 2
    assert result["parser_facts"]["point_zero_policy"] == "coordinate_free_ts_marker_excluded"
    assert (parse_dir / "irc_path_summary.json").is_file()
    assert (parse_dir / "irc_path_points.json").is_file()
    assert (parse_dir / "irc_endpoint.xyz").is_file()
    assert (workspace / f"nodes/n001/attempts/{intent_id}/outputs/calculation_result.json").is_file()


def test_compute_result_contract_rejects_scientific_verdict_fields() -> None:
    result = {
        "schema_version": "ts-calculation-result/1",
        "job_id": None,
        "intent_id": "calc_test",
        "node_id": "n001",
        "state": "prepared",
        "program_status": "not_run",
        "exit_status": None,
        "artifact_refs": [],
        "parser_facts": {},
        "error_class": None,
        "provenance": {},
        "claim_verdict": "supported",
    }
    with pytest.raises(ComputeContractError, match="Additional properties"):
        validate_compute_contract("calculation_result.schema.json", result)

    del result["claim_verdict"]
    result["parser_facts"] = {"accepted_ts": True}
    with pytest.raises(ComputeContractError, match="accepted_ts"):
        validate_compute_contract("calculation_result.schema.json", result)
