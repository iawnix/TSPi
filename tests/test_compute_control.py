from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from strict_helpers import bootstrap_strict_workspace, start_research_node
from ts_compute import (
    ComputeContractError,
    cancel_calculation,
    calculation_status,
    calculation_tail,
    collect_calculation,
    create_calculation_intent,
    list_calculation_artifacts,
    parse_calculation,
    preflight_calculation,
    prepare_calculation,
    submit_calculation,
)
from ts_compute.contracts import validate_compute_contract
from ts_compute.control import _validate_intent_node_scope
from ts_remote import lifecycle as remote_lifecycle
from ts_remote.models import RemoteJobStatus, RemoteReceipt
from ts_remote.errors import RemotePreSubmitError, RemoteSubmissionAmbiguous, RemoteSubmissionRejected
from ts_workspace.operational import operational_snapshot
from ts_workspace.readers.report import report_workspace
from ts_workspace.identity import workspace_id


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


def _artifact_binding(workspace: Path, ref: str, role: str) -> dict[str, object]:
    catalog = list_calculation_artifacts(workspace)
    artifact = next(item for item in catalog["artifacts"] if item["path"] == ref)
    return {
        "input_role": role,
        "artifact_id": artifact["artifact_id"],
        "path": artifact["path"],
        "sha256": artifact["sha256"],
        "owner_node": artifact["owner_node"],
        "source_intent_id": artifact["source_intent_id"],
    }


def _calculation_request(workspace: Path, *, target: dict[str, object] | None = None) -> dict[str, object]:
    binding = _artifact_binding(workspace, "nodes/n001/inputs/candidate.gjf", "gjf")
    return {
        "schema_version": "ts-calculation-request/1",
        "node_id": "n001",
        "purpose": "Evaluate the selected candidate without hand-authoring an intent file.",
        "attempt_kind": "primary",
        "recalculation_ref": None,
        "backend": "gaussian",
        "task_type": "opt_freq",
        "input_artifacts": [
            {"input_role": "gjf", "artifact_id": binding["artifact_id"]}
        ],
        "settings": {},
        "execution_target": target or {"kind": "local"},
        "dry_run": True,
    }


def test_create_calculation_intent_derives_attempt_paths_and_templates(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    first = create_calculation_intent(workspace, _calculation_request(workspace))
    second = create_calculation_intent(workspace, _calculation_request(workspace))

    assert first["schema_version"] == "ts-calculation-intent-created/1"
    assert first["intent_id"] == "calc_n001_gaussian_opt_freq_0001"
    assert second["intent_id"] == "calc_n001_gaussian_opt_freq_0002"
    assert first["intent_ref"] == (
        "nodes/n001/attempts/calc_n001_gaussian_opt_freq_0001/intent.json"
    )
    assert first["input_refs"] == {"gjf": "nodes/n001/inputs/candidate.gjf"}
    assert first["input_bindings"] == [
        _artifact_binding(workspace, "nodes/n001/inputs/candidate.gjf", "gjf")
    ]
    assert first["expected_artifacts"] == [
        "nodes/n001/attempts/calc_n001_gaussian_opt_freq_0001/outputs/gaussian.out"
    ]
    assert first["intent"]["validation_scope"] == "tsfreq"
    assert first["intent"]["execution_target"] == {"kind": "local"}
    assert not list((workspace / "nodes/n001/scratch").glob("*.json"))

    prepared = prepare_calculation(workspace, first["intent_ref"], first["intent_digest"])
    assert prepared["result"]["state"] == "prepared"


def test_create_calculation_intent_reserves_unique_sequences_concurrently(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    with ThreadPoolExecutor(max_workers=8) as pool:
        created = list(
            pool.map(
                lambda _: create_calculation_intent(workspace, _calculation_request(workspace)),
                range(12),
            )
        )

    intent_ids = sorted(item["intent_id"] for item in created)
    assert intent_ids == [
        f"calc_n001_gaussian_opt_freq_{sequence:04d}"
        for sequence in range(1, 13)
    ]
    assert all((workspace / item["intent_ref"]).is_file() for item in created)


def test_create_calculation_intent_preserves_write_failure_and_cleans_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)

    def fail_write(path: Path, _data: object) -> None:
        path.with_name(f"{path.name}.tmp").write_text("partial", encoding="utf-8")
        raise OSError("simulated intent write failure")

    monkeypatch.setattr("ts_compute.control.write_json", fail_write)
    with pytest.raises(OSError, match="simulated intent write failure"):
        create_calculation_intent(workspace, _calculation_request(workspace))

    attempt = workspace / "nodes/n001/attempts/calc_n001_gaussian_opt_freq_0001"
    assert not attempt.exists()


def test_create_calculation_intent_accepts_logical_artifact_binding(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    request = _calculation_request(workspace)

    created = create_calculation_intent(workspace, request)

    assert created["input_refs"] == {"gjf": "nodes/n001/inputs/candidate.gjf"}
    assert created["input_bindings"][0]["artifact_id"] == request["input_artifacts"][0]["artifact_id"]


def test_create_calculation_intent_rejects_unknown_artifact_or_agent_named_outputs(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "nodes/n001/inputs/second.com").write_text(
        "#P HF/STO-3G opt freq\n\nSecond\n\n0 1\nH 0 0 0\n\n",
        encoding="utf-8",
    )

    request = _calculation_request(workspace)
    request["input_artifacts"] = [
        {"input_role": "gjf", "artifact_id": "art_000000000000000000000000"}
    ]
    with pytest.raises(ComputeContractError, match="unknown calculation artifact_id"):
        create_calculation_intent(workspace, request)

    request = _calculation_request(workspace)
    request["settings"] = {"output": "chosen-by-agent.log"}
    with pytest.raises(ComputeContractError, match="settings.output is generated"):
        create_calculation_intent(workspace, request)


def test_create_calculation_intent_derives_workspace_scoped_remote_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _configure_remote(tmp_path, monkeypatch)
    request = _calculation_request(workspace, target=_remote_request_target())

    created = create_calculation_intent(workspace, request)
    identity = workspace_id(workspace, create=False)

    assert created["execution_target"] == {
        "kind": "remote",
        "authority": "execution_mirror",
        "profile": "test_cluster",
        "workspace_id": identity,
        "remote_dir": (
            f"/remote/ts/workspaces/{identity}/runs/n001/"
            "calc_n001_gaussian_opt_freq_0001"
        ),
        "resources": _remote_resources(),
    }


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
        "input_bindings": [
            _artifact_binding(workspace, "nodes/n001/inputs/candidate.gjf", "gjf")
        ],
        "settings": {},
        "expected_artifacts": [f"nodes/n001/attempts/{intent_id}/outputs/candidate.log"],
        "execution_target": target or {"kind": "local"},
        "dry_run": dry_run,
    }
    path = workspace / "nodes" / "n001" / "scratch" / f"{intent_id}.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


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


def _remote_target(
    workspace: Path,
    intent_id: str = "calc_n001_optfreq_001",
) -> dict[str, object]:
    identity = workspace_id(workspace, create=True)
    return {
        "kind": "remote",
        "authority": "execution_mirror",
        "profile": "test_cluster",
        "workspace_id": identity,
        "remote_dir": f"/remote/ts/workspaces/{identity}/runs/n001/{intent_id}",
        "resources": _remote_resources(),
    }


def _configure_remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ssh_config = tmp_path / "ssh_config"
    ssh_config.write_text("Host test-login\\n  HostName login.test\\n", encoding="utf-8")
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
    return config


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

    _configure_remote(tmp_path, monkeypatch)
    remote = _remote_target(workspace, "calc_n001_remote_v2")
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
    intent["input_bindings"][0]["path"] = "../../outside.gjf"
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="invalid workspace path"):
        prepare_calculation(workspace, intent_path)

    intent["input_refs"]["gjf"] = "nodes/n001/inputs/candidate.gjf"
    intent["input_bindings"][0] = _artifact_binding(
        workspace, "nodes/n001/inputs/candidate.gjf", "gjf"
    )
    intent["expected_artifacts"] = ["nodes/n000/outputs/foreign.log"]
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="nodes/n001/attempts/calc_n001_optfreq_unsafe/outputs"):
        prepare_calculation(workspace, intent_path)

    intent["expected_artifacts"] = ["nodes/n001/outputs/candidate.log"]
    (workspace / "nodes/n001/inputs/candidate.gjf").write_text(
        "#P B3LYP/6-31G(d) sp\n\nSP\n\n0 1\nH 0 0 0\n\n",
        encoding="utf-8",
    )
    intent["input_bindings"][0] = _artifact_binding(
        workspace, "nodes/n001/inputs/candidate.gjf", "gjf"
    )
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="route does not match"):
        prepare_calculation(workspace, intent_path)

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


def test_remote_submit_status_tail_collect_and_cancel_are_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _configure_remote(tmp_path, monkeypatch)
    target = _remote_target(workspace)
    prepare_calculation(workspace, _intent(workspace, target=target, dry_run=False))
    calls: dict[str, int] = {"submit": 0, "status": 0, "collect": 0, "cancel": 0}

    def fake_submit(config):
        calls["submit"] += 1
        assert config.profile.name == "test_cluster"
        assert config.command == ("g16", "candidate.gjf")
        assert config.remote_dir == target["remote_dir"]
        return _receipt_for(config)

    def fake_status(config, job_id):
        calls["status"] += 1
        assert job_id == "123.cluster"
        return RemoteJobStatus(
            state="running",
            program_status="not_run",
            job_id=job_id,
            scheduler_state="R",
        )

    def fake_collect(config, artifacts, output_dir):
        calls["collect"] += 1
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "candidate.log").write_text(_gaussian_log(), encoding="utf-8")
        return list(artifacts), [{
            "remote_path": f"{config.remote_dir}/candidate.log",
            "size": (output_dir / "candidate.log").stat().st_size,
            "sha256": "sha256:" + "b" * 64,
        }]

    def fake_cancel(config, job_id):
        calls["cancel"] += 1
        assert job_id == "123.cluster"
        return {"state": "accepted", "updated_at": "2026-08-12T00:01:00Z"}

    monkeypatch.setattr("ts_compute.control.remote_lifecycle.submit", fake_submit)
    monkeypatch.setattr("ts_compute.control.remote_lifecycle.status", fake_status)
    monkeypatch.setattr("ts_compute.control.remote_lifecycle.tail", lambda _config, _artifact, _lines: "running\\n")
    monkeypatch.setattr("ts_compute.control.remote_lifecycle.collect", fake_collect)
    monkeypatch.setattr("ts_compute.control.remote_lifecycle.cancel", fake_cancel)

    submitted = submit_calculation(workspace, "calc_n001_optfreq_001")
    assert submit_calculation(workspace, "calc_n001_optfreq_001") == submitted
    assert submitted["state"] == "submitted"
    assert submitted["job_id"] == "123.cluster"
    assert submitted["provenance"]["profile"] == "test_cluster"
    assert "transport" not in submitted["provenance"]

    observed = calculation_status(workspace, "calc_n001_optfreq_001")
    assert observed["state"] == "running"
    assert observed["provenance"]["scheduler_state"] == "R"
    tail = calculation_tail(workspace, "calc_n001_optfreq_001", "candidate.log", 40)
    assert tail["text"] == "running\\n"
    collected = collect_calculation(workspace, "calc_n001_optfreq_001", ["candidate.log"])
    assert collected["state"] == "collected"
    assert collected["artifact_refs"] == [
        "nodes/n001/attempts/calc_n001_optfreq_001/outputs/collected/candidate.log"
    ]
    cancelled = cancel_calculation(workspace, "calc_n001_optfreq_001", expected_job_id="123.cluster")
    assert cancelled["state"] == "stopped"
    assert calls == {"submit": 1, "status": 1, "collect": 1, "cancel": 1}


def test_remote_pre_submit_failure_is_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _configure_remote(tmp_path, monkeypatch)
    prepare_calculation(
        workspace,
        _intent(workspace, target=_remote_target(workspace), dry_run=False),
    )
    attempts = 0

    def fake_submit(config):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RemotePreSubmitError("upload", OSError("network unavailable"))
        return _receipt_for(config)

    monkeypatch.setattr("ts_compute.control.remote_lifecycle.submit", fake_submit)
    failed = submit_calculation(workspace, "calc_n001_optfreq_001")
    assert failed["state"] == "failed"
    assert failed["error_class"] == "remote_staging_failed"
    assert failed["control"]["effect_attempted"] is False
    assert failed["control"]["retry_disposition"] == "retry_same_submission"

    submitted = submit_calculation(workspace, "calc_n001_optfreq_001")
    assert submitted["state"] == "submitted"
    assert attempts == 2


def test_scheduler_rejection_is_known_and_requires_a_new_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _configure_remote(tmp_path, monkeypatch)
    prepare_calculation(
        workspace,
        _intent(workspace, target=_remote_target(workspace), dry_run=False),
    )
    attempts = 0

    def fake_submit(config):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RemoteSubmissionRejected({"state": "rejected", "error": "queue disabled"})
        return _receipt_for(config)

    monkeypatch.setattr("ts_compute.control.remote_lifecycle.submit", fake_submit)
    rejected = submit_calculation(workspace, "calc_n001_optfreq_001")

    assert rejected["state"] == "failed"
    assert rejected["error_class"] == "scheduler_submission_rejected"
    assert rejected["control"]["effect_attempted"] is True
    assert rejected["control"]["retry_disposition"] == "new_intent"
    assert rejected["provenance"]["submission_attempted"] is True
    assert rejected["provenance"]["retry_safe"] is False
    with pytest.raises(ComputeContractError, match="refuses automatic replay"):
        submit_calculation(workspace, "calc_n001_optfreq_001")


def test_ambiguous_remote_submit_refuses_replay_and_reconciles_from_remote_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _configure_remote(tmp_path, monkeypatch)
    prepare_calculation(
        workspace,
        _intent(workspace, target=_remote_target(workspace), dry_run=False),
    )
    monkeypatch.setattr(
        "ts_compute.control.remote_lifecycle.submit",
        lambda _config: (_ for _ in ()).throw(
            RemoteSubmissionAmbiguous(
                {"state": "unknown", "phase": "submit_request_started"}
            )
        ),
    )

    ambiguous = submit_calculation(workspace, "calc_n001_optfreq_001")
    assert ambiguous["state"] == "unknown"
    assert ambiguous["error_class"] == "submission_ambiguous"
    assert ambiguous["control"]["phase"] == "submit_request_started"
    with pytest.raises(ComputeContractError, match="refuses automatic replay"):
        submit_calculation(workspace, "calc_n001_optfreq_001")

    def remote_record(config, *, correct_digest=True):
        return {
            "schema_version": "ts-remote-submission/1",
            "submission_id": config.submission_id,
            "state": "accepted",
            "script_sha256": (
                remote_lifecycle.submission_script_digest(config)
                if correct_digest
                else "c" * 64
            ),
            "job_id": "123.cluster",
            "updated_at": "2026-08-12T00:00:00Z",
        }

    monkeypatch.setattr(
        "ts_compute.control.remote_lifecycle.read_submission_record",
        lambda config: remote_record(config, correct_digest=False),
    )
    monkeypatch.setattr(
        "ts_compute.control.remote_lifecycle.status",
        lambda _config, job_id: RemoteJobStatus(
            state="queued",
            program_status="not_run",
            job_id=job_id,
            scheduler_state="Q",
        ),
    )
    with pytest.raises(ComputeContractError, match="reconciliation record does not match"):
        calculation_status(workspace, "calc_n001_optfreq_001")

    monkeypatch.setattr(
        "ts_compute.control.remote_lifecycle.read_submission_record",
        lambda config: remote_record(config),
    )
    reconciled = calculation_status(workspace, "calc_n001_optfreq_001")
    assert reconciled["state"] == "queued"
    assert submit_calculation(workspace, "calc_n001_optfreq_001")["job_id"] == "123.cluster"


def test_collect_uses_receipt_without_scheduler_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _configure_remote(tmp_path, monkeypatch)
    prepare_calculation(
        workspace,
        _intent(workspace, target=_remote_target(workspace), dry_run=False),
    )
    monkeypatch.setattr("ts_compute.control.remote_lifecycle.submit", _receipt_for)
    monkeypatch.setattr(
        "ts_compute.control.remote_lifecycle.status",
        lambda *_args: (_ for _ in ()).throw(AssertionError("collect must not query scheduler")),
    )

    def fake_collect(_config, artifacts, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "candidate.log").write_text(_gaussian_log(), encoding="utf-8")
        return list(artifacts), []

    monkeypatch.setattr("ts_compute.control.remote_lifecycle.collect", fake_collect)
    submit_calculation(workspace, "calc_n001_optfreq_001")
    result = collect_calculation(workspace, "calc_n001_optfreq_001", ["candidate.log"])
    assert result["state"] == "collected"
    assert result["program_status"] == "not_run"


def test_remote_target_rejects_legacy_transport_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _configure_remote(tmp_path, monkeypatch)
    request = _calculation_request(workspace, target=_remote_request_target())
    request["execution_target"]["transport"] = "mcp"
    with pytest.raises(ComputeContractError, match="calculation_request.schema.json validation failed"):
        create_calculation_intent(workspace, request)



def test_prepare_rejects_canonical_state_as_backend_input(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    intent_path = _intent(workspace)
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    intent["backend"] = "xtb"
    intent["task_type"] = "opt"
    intent["input_refs"] = {"xyz": "research_state.json"}
    intent["input_bindings"] = [{
        **intent["input_bindings"][0],
        "input_role": "xyz",
        "path": "research_state.json",
    }]
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
    intent["input_bindings"].append(
        _artifact_binding(workspace, "nodes/n001/inputs/source.xyz", "source_xyz")
    )
    intent_path.write_text(json.dumps(intent), encoding="utf-8")

    with pytest.raises(ComputeContractError, match=r"unexpected=\['source_xyz'\]"):
        prepare_calculation(workspace, intent_path)


def test_prepared_backend_metadata_is_revalidated_before_remote_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _configure_remote(tmp_path, monkeypatch)
    prepare_calculation(workspace, _intent(workspace, target=_remote_target(workspace)))
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
        "input_bindings": [
            _artifact_binding(workspace, "nodes/n001/inputs/irc.gjf", "gjf")
        ],
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
