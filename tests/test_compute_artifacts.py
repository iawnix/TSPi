from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.v4_helpers import bootstrap_v4_workspace, start_research_act
from ts_compute import (
    ComputeContractError,
    create_calculation_intent,
    list_calculation_artifacts,
    prepare_calculation,
    submit_calculation,
)
from ts_compute.cli import main as compute_cli_main
from ts_remote.errors import RemoteError


def _workspace(tmp_path: Path) -> tuple[Path, str]:
    workspace = bootstrap_v4_workspace(tmp_path / "workspace")
    refs = start_research_act(
        workspace,
        objective="Exercise deterministic calculation artifact binding.",
    )
    return workspace, refs["act_id"]


def _artifact(catalog: dict, path: str) -> dict:
    return next(item for item in catalog["artifacts"] if item["path"] == path)


def _request(
    act_id: str,
    artifact_id: str,
    *,
    dry_run: bool = True,
    execution_target: dict | None = None,
) -> dict:
    return {
        "schema_version": "ts-calculation-request/2",
        "act_id": act_id,
        "purpose": "Exercise deterministic calculation artifact binding.",
        "attempt_kind": "primary",
        "recalculation_ref": None,
        "backend": "gaussian",
        "task_type": "sp",
        "input_artifacts": [{"input_role": "gjf", "artifact_id": artifact_id}],
        "settings": {},
        "execution_target": execution_target or {"kind": "local"},
        "dry_run": dry_run,
    }


def test_artifact_id_binds_path_and_content(tmp_path: Path) -> None:
    workspace, _ = _workspace(tmp_path)
    source = workspace / "inputs" / "source.gjf"
    source.write_text("# HF/STO-3G\n\nSP\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")

    first = _artifact(list_calculation_artifacts(workspace), "inputs/source.gjf")
    renamed = source.with_name("renamed.com")
    source.rename(renamed)
    second = _artifact(list_calculation_artifacts(workspace), "inputs/renamed.com")
    assert second["artifact_id"] != first["artifact_id"]
    assert second["sha256"] == first["sha256"]

    renamed.write_text("# HF/STO-3G\n\nSP changed\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")
    third = _artifact(list_calculation_artifacts(workspace), "inputs/renamed.com")
    assert third["artifact_id"] != second["artifact_id"]
    assert third["sha256"] != second["sha256"]


def test_catalog_uses_workspace_and_research_act_ownership(tmp_path: Path) -> None:
    workspace, act_id = _workspace(tmp_path)
    root_input = workspace / "inputs" / "source.xyz"
    root_input.write_text("1\nsource\nH 0 0 0\n", encoding="utf-8")
    root_input.with_name("linked.xyz").symlink_to(root_input)
    act_output = workspace / "acts" / act_id / "outputs" / "candidate.xyz"
    act_output.parent.mkdir(parents=True)
    act_output.write_text("1\ncandidate\nH 0 0 0\n", encoding="utf-8")

    with pytest.raises(ComputeContractError, match="unknown ResearchAct"):
        list_calculation_artifacts(workspace, act_id="act_000000000000000000000000")

    catalog = list_calculation_artifacts(workspace)
    assert [item["path"] for item in catalog["artifacts"]] == [
        f"acts/{act_id}/outputs/candidate.xyz",
        "inputs/source.xyz",
    ]
    owned = _artifact(catalog, f"acts/{act_id}/outputs/candidate.xyz")
    shared = _artifact(catalog, "inputs/source.xyz")
    assert owned["owner_act"] == act_id
    assert shared["owner_act"] is None
    assert shared["input_roles"] == ["product", "reactant", "xyz"]
    assert list_calculation_artifacts(workspace, act_id=act_id)["artifacts"] == [owned]


def test_binding_rejects_unknown_incompatible_and_incomplete_roles(tmp_path: Path) -> None:
    workspace, act_id = _workspace(tmp_path)
    gjf = workspace / "inputs" / "source.gjf"
    gjf.write_text("# HF/STO-3G\n\nSP\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")
    xyz = workspace / "inputs" / "source.xyz"
    xyz.write_text("1\nsource\nH 0 0 0\n", encoding="utf-8")
    catalog = list_calculation_artifacts(workspace)
    gjf_artifact = _artifact(catalog, "inputs/source.gjf")
    xyz_artifact = _artifact(catalog, "inputs/source.xyz")

    with pytest.raises(ComputeContractError, match="unknown artifact_id"):
        create_calculation_intent(workspace, _request(act_id, "art_000000000000000000000000"))
    with pytest.raises(ComputeContractError, match="not compatible with input role gjf"):
        create_calculation_intent(workspace, _request(act_id, xyz_artifact["artifact_id"]))

    incomplete = _request(act_id, xyz_artifact["artifact_id"])
    incomplete["backend"] = "ase_neb"
    incomplete["task_type"] = "neb"
    incomplete["input_artifacts"] = [
        {"input_role": "reactant", "artifact_id": xyz_artifact["artifact_id"]}
    ]
    with pytest.raises(ComputeContractError, match=r"missing=\['product'\]"):
        create_calculation_intent(workspace, incomplete)

    second_gjf = workspace / "inputs" / "second.gjf"
    second_gjf.write_text("# HF/STO-3G\n\nSecond\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")
    second_artifact = _artifact(list_calculation_artifacts(workspace), "inputs/second.gjf")
    duplicate = _request(act_id, gjf_artifact["artifact_id"])
    duplicate["input_artifacts"].append(
        {"input_role": "gjf", "artifact_id": second_artifact["artifact_id"]}
    )
    with pytest.raises(ComputeContractError, match="duplicate calculation input role"):
        create_calculation_intent(workspace, duplicate)


def test_open_research_act_can_run_any_supported_root_selected_task(tmp_path: Path) -> None:
    workspace, act_id = _workspace(tmp_path)
    source = workspace / "inputs" / "source.gjf"
    source.write_text("# HF/STO-3G opt\n\nOpt\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")
    artifact = _artifact(list_calculation_artifacts(workspace), "inputs/source.gjf")
    request = _request(act_id, artifact["artifact_id"])
    request["task_type"] = "opt"

    created = create_calculation_intent(workspace, request)
    assert created["act_id"] == act_id
    assert created["intent"]["backend"] == "gaussian"
    assert created["intent"]["task_type"] == "opt"
    assert created["intent_ref"].startswith(f"acts/{act_id}/attempts/")


def test_list_artifacts_cli_returns_v4_catalog_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace, act_id = _workspace(tmp_path)
    source = workspace / "acts" / act_id / "inputs" / "source.xyz"
    source.parent.mkdir(parents=True)
    source.write_text("1\nsource\nH 0 0 0\n", encoding="utf-8")

    assert compute_cli_main([
        "list-artifacts",
        "--root",
        str(workspace),
        "--act-id",
        act_id,
    ]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert '"schema_version": "ts-artifact-catalog/2"' in output.out
    assert f'"path": "acts/{act_id}/inputs/source.xyz"' in output.out


def test_compute_cli_serializes_remote_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_remote(_args) -> dict:
        raise RemoteError("remote status unavailable")

    monkeypatch.setattr("ts_compute.cli._dispatch", fail_remote)
    assert compute_cli_main(["capabilities"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {"ok": False, "error": "remote status unavailable"}


def test_prepare_and_submit_reject_stale_input_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, act_id = _workspace(tmp_path)
    gjf = workspace / "inputs" / "source.gjf"
    original = "# HF/STO-3G\n\nSP\n\n0 1\nH 0 0 0\n\n"
    gjf.write_text(original, encoding="utf-8")
    artifact_id = _artifact(list_calculation_artifacts(workspace), "inputs/source.gjf")["artifact_id"]

    stale_before_prepare = create_calculation_intent(workspace, _request(act_id, artifact_id))
    gjf.write_text(original.replace("SP", "changed"), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="input binding changed.*artifact_id mismatch"):
        prepare_calculation(workspace, stale_before_prepare["intent_ref"])

    gjf.write_text(original, encoding="utf-8")
    current_id = _artifact(list_calculation_artifacts(workspace), "inputs/source.gjf")["artifact_id"]
    ssh_config = tmp_path / "ssh_config"
    ssh_config.write_text("Host login.test\n  HostName login.test\n", encoding="utf-8")
    remote_config = tmp_path / "remote.toml"
    remote_config.write_text(
        f'''default_profile = "cluster"
[profiles.cluster]
ssh_host = "login.test"
ssh_config = "{ssh_config}"
scheduler = "torque"
remote_root = "/remote/ts"
allowed_queues = ["batch"]
max_nodes = 1

[profiles.cluster.software.gaussian]
command = ["g16"]
allowed_queues = ["batch"]
''',
        encoding="utf-8",
    )
    monkeypatch.setenv("TS_REMOTE_CONFIG", str(remote_config))
    stale_before_submit = create_calculation_intent(
        workspace,
        _request(
            act_id,
            current_id,
            dry_run=False,
            execution_target={
                "kind": "remote",
                "profile": "cluster",
                "resources": {
                    "queue": "batch",
                    "nodes": 1,
                    "ncpus": 8,
                    "memory": "16gb",
                    "walltime": "04:00:00",
                    "ngpus": 0,
                    "mpiprocs": None,
                    "ompthreads": 8,
                },
            },
        ),
    )
    prepare_calculation(workspace, stale_before_submit["intent_ref"])
    gjf.write_text(original.replace("SP", "changed again"), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="input binding changed.*artifact_id mismatch"):
        submit_calculation(workspace, stale_before_submit["intent_id"])
