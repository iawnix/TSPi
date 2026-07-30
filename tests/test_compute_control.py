from __future__ import annotations

import json
from pathlib import Path

import pytest

from strict_helpers import bootstrap_strict_workspace, start_v3_node
from ts_compute import (
    ComputeContractError,
    calculation_status,
    calculation_tail,
    collect_calculation,
    parse_calculation,
    prepare_calculation,
)
from ts_compute.contracts import validate_compute_contract
from ts_remote.job_lifecycle import RemoteJobStatus


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    report_ref = bootstrap_strict_workspace(workspace)
    start_v3_node(
        workspace,
        report_ref,
        node_id="n001",
        phase="tsfreq_validation",
    )
    gjf = workspace / "nodes" / "n001" / "inputs" / "candidate.gjf"
    gjf.write_text(
        "%chk=candidate.chk\n#P B3LYP/6-31G(d) opt=(ts,calcfc) freq\n\nTS\n\n0 1\nH 0 0 0\n\n",
        encoding="utf-8",
    )
    return workspace


def _intent(workspace: Path, *, target: dict[str, str] | None = None) -> Path:
    value = {
        "schema_version": "ts-calculation-intent/1",
        "intent_id": "calc_n001_optfreq_001",
        "node_id": "n001",
        "purpose": "Evaluate the selected candidate at the TS/Freq evidence layer.",
        "evidence_layer": "tsfreq",
        "backend": "gaussian",
        "task_type": "opt_freq",
        "input_refs": {"gjf": "nodes/n001/inputs/candidate.gjf"},
        "settings": {},
        "expected_artifacts": ["nodes/n001/outputs/candidate.log"],
        "execution_target": target or {"kind": "local"},
        "dry_run": True,
    }
    path = workspace / "nodes" / "n001" / "scratch" / "intent.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _remote_target() -> dict[str, str]:
    return {
        "kind": "remote",
        "login_host": "login.test",
        "compute_host": "compute.test",
        "remote_dir": "/remote/ts/n001/calc_n001_optfreq_001",
    }


def _allow_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TS_COMPUTE_LOGIN_HOSTS", "login.test")
    monkeypatch.setenv("TS_COMPUTE_COMPUTE_HOSTS", "compute.test")
    monkeypatch.setenv("TS_COMPUTE_REMOTE_ROOTS", "/remote/ts")


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
    assert (workspace / "nodes/n001/inputs/calculations/calc_n001_optfreq_001.json").is_file()
    assert (workspace / "nodes/n001/remote/calculations/calc_n001_optfreq_001/prepared.json").is_file()
    assert {name: (workspace / name).read_bytes() for name in state_files} == before

    changed = json.loads(intent_path.read_text(encoding="utf-8"))
    changed["purpose"] = "Changed purpose under a reused identifier."
    intent_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="different content"):
        prepare_calculation(workspace, intent_path)


def test_prepare_rejects_non_dry_run_path_escape_and_wrong_route(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    intent_path = _intent(workspace)
    intent = json.loads(intent_path.read_text(encoding="utf-8"))

    intent["dry_run"] = False
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="dry_run=true"):
        prepare_calculation(workspace, intent_path)

    intent["dry_run"] = True
    intent["input_refs"]["gjf"] = "../../outside.gjf"
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="invalid workspace path"):
        prepare_calculation(workspace, intent_path)

    intent["input_refs"]["gjf"] = "nodes/n001/inputs/candidate.gjf"
    intent["expected_artifacts"] = ["nodes/n000/outputs/foreign.log"]
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="nodes/n001/outputs"):
        prepare_calculation(workspace, intent_path)

    intent["expected_artifacts"] = ["nodes/n001/outputs/candidate.log"]
    (workspace / "nodes/n001/inputs/candidate.gjf").write_text(
        "#P B3LYP/6-31G(d) sp\n\nSP\n\n0 1\nH 0 0 0\n\n",
        encoding="utf-8",
    )
    intent_path.write_text(json.dumps(intent), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="route does not match"):
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


def test_status_tail_and_collect_use_prepared_remote_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _allow_remote(monkeypatch)
    prepare_calculation(workspace, _intent(workspace, target=_remote_target()))
    seen: dict[str, object] = {}

    def fake_poll(config):
        seen["poll"] = config
        return RemoteJobStatus(
            node_id="n001",
            host="compute.test",
            remote_dir="/remote/ts/n001/calc_n001_optfreq_001",
            state="completed",
            pid="123",
            exit_status=0,
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

    status = calculation_status(workspace, "calc_n001_optfreq_001")
    tail = calculation_tail(workspace, "calc_n001_optfreq_001", "candidate.log", 40)
    collected = collect_calculation(workspace, "calc_n001_optfreq_001", ["candidate.log"])

    assert status["state"] == "completed"
    assert status["program_status"] == "completed"
    assert tail["text"] == "normal termination\n"
    assert seen["tail"] == ("candidate.log", 40)
    assert seen["fetch"] == (["candidate.log"], False)
    assert collected["program_status"] == "completed"
    assert collected["artifact_refs"] == [
        "nodes/n001/outputs/calculations/calc_n001_optfreq_001/collected/candidate.log"
    ]
    config = seen["poll"]
    assert config.login_host == "login.test"
    assert config.compute_host == "compute.test"
    assert config.command == ["g16", "candidate.gjf"]

    with pytest.raises(ComputeContractError, match="not allowlisted"):
        calculation_tail(workspace, "calc_n001_optfreq_001", "arbitrary.log", 40)
    with pytest.raises(ComputeContractError, match="unique subset"):
        collect_calculation(workspace, "calc_n001_optfreq_001", ["arbitrary.log"])
    with pytest.raises(ComputeContractError, match="overwrite"):
        collect_calculation(workspace, "calc_n001_optfreq_001", ["candidate.log"])


def test_collect_requires_terminal_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _workspace(tmp_path)
    _allow_remote(monkeypatch)
    prepare_calculation(workspace, _intent(workspace, target=_remote_target()))

    with pytest.raises(ComputeContractError, match="terminal calculation status"):
        collect_calculation(workspace, "calc_n001_optfreq_001", ["candidate.log"])


def test_prepared_backend_metadata_is_revalidated_before_remote_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    _allow_remote(monkeypatch)
    prepare_calculation(workspace, _intent(workspace, target=_remote_target()))
    prepared_path = workspace / "nodes/n001/remote/calculations/calc_n001_optfreq_001/prepared.json"
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    prepared["prepared_task"]["command"] = ["arbitrary-command"]
    prepared_path.write_text(json.dumps(prepared), encoding="utf-8")

    with pytest.raises(ComputeContractError, match="backend metadata does not match"):
        calculation_status(workspace, "calc_n001_optfreq_001")


def test_gaussian_parse_returns_program_facts_without_workspace_verdict(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    prepare_calculation(workspace, _intent(workspace))
    log = workspace / "nodes" / "n001" / "outputs" / "candidate.log"
    log.write_text(_gaussian_log(), encoding="utf-8")
    state_before = (workspace / "research_state.json").read_bytes()

    result = parse_calculation(workspace, "calc_n001_optfreq_001", "nodes/n001/outputs/candidate.log")

    assert result["state"] == "parsed"
    assert result["program_status"] == "completed"
    assert result["parser_facts"]["normal_termination"] is True
    assert result["parser_facts"]["imaginary_frequency_count"] == 1
    assert "claim_verdict" not in result
    assert "accepted_ts" not in result
    assert (workspace / "research_state.json").read_bytes() == state_before
    assert (workspace / "nodes/n001/outputs/calculations/calc_n001_optfreq_001/calculation_result.json").is_file()
    assert (workspace / "nodes/n001/outputs/calculations/calc_n001_optfreq_001/parsed/validation_summary.json").is_file()
    assert parse_calculation(
        workspace,
        "calc_n001_optfreq_001",
        "nodes/n001/outputs/candidate.log",
    ) == result

    log.write_text(_gaussian_log() + "\n additional completed output\n", encoding="utf-8")
    with pytest.raises(ComputeContractError, match="different source content"):
        parse_calculation(workspace, "calc_n001_optfreq_001", "nodes/n001/outputs/candidate.log")

    foreign = workspace / "nodes" / "n000" / "outputs" / "candidate.log"
    foreign.write_text(_gaussian_log(), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="nodes/n001/outputs"):
        parse_calculation(workspace, "calc_n001_optfreq_001", "nodes/n000/outputs/candidate.log")


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
