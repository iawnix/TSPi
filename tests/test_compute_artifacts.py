from __future__ import annotations

from pathlib import Path

import pytest

from strict_helpers import bootstrap_strict_workspace, start_research_node
from ts_compute import (
    ComputeContractError,
    create_calculation_intent,
    list_calculation_artifacts,
    prepare_calculation,
    submit_calculation,
)
from ts_compute.cli import main as compute_cli_main


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    report_ref = bootstrap_strict_workspace(workspace)
    start_research_node(
        workspace,
        report_ref,
        node_id="n001",
        node_type="candidate_search",
        scope="endpoint_conformer",
    )
    return workspace


def _artifact(catalog: dict, path: str) -> dict:
    return next(item for item in catalog["artifacts"] if item["path"] == path)


def _request(
    artifact_id: str,
    *,
    dry_run: bool = True,
    execution_target: dict | None = None,
) -> dict:
    return {
        "schema_version": "ts-calculation-request/1",
        "node_id": "n001",
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


def test_artifact_id_is_stable_after_same_owner_rename_and_changes_with_content(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source = workspace / "nodes/n001/inputs/source.gjf"
    source.write_text("# HF/STO-3G\n\nSP\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")

    first = _artifact(list_calculation_artifacts(workspace), "nodes/n001/inputs/source.gjf")
    renamed = source.with_name("renamed.com")
    source.rename(renamed)
    second = _artifact(list_calculation_artifacts(workspace), "nodes/n001/inputs/renamed.com")
    assert second["artifact_id"] == first["artifact_id"]
    assert second["sha256"] == first["sha256"]

    renamed.write_text("# HF/STO-3G\n\nSP changed\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")
    third = _artifact(list_calculation_artifacts(workspace), "nodes/n001/inputs/renamed.com")
    assert third["artifact_id"] != second["artifact_id"]
    assert third["sha256"] != second["sha256"]


def test_catalog_excludes_symlinks_and_unregistered_nodes_and_reports_roles(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source = workspace / "nodes/n001/inputs/source.xyz"
    source.write_text("1\nsource\nH 0 0 0\n", encoding="utf-8")
    source.with_name("linked.xyz").symlink_to(source)
    orphan = workspace / "nodes/orphan/inputs/orphan.xyz"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("1\norphan\nH 0 0 0\n", encoding="utf-8")

    with pytest.raises(ComputeContractError, match="unknown workspace node: orphan"):
        list_calculation_artifacts(workspace, node_id="orphan")

    catalog = list_calculation_artifacts(workspace, node_id="n001")

    assert [item["path"] for item in catalog["artifacts"]] == ["nodes/n001/inputs/source.xyz"]
    artifact = catalog["artifacts"][0]
    assert artifact["owner_node"] == "n001"
    assert artifact["source_intent_id"] is None
    assert artifact["input_roles"] == ["product", "reactant", "xyz"]


def test_binding_rejects_missing_ambiguous_and_role_incompatible_artifacts(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    gjf = workspace / "nodes/n001/inputs/source.gjf"
    gjf.write_text("# HF/STO-3G\n\nSP\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")
    xyz = workspace / "nodes/n001/inputs/source.xyz"
    xyz.write_text("1\nsource\nH 0 0 0\n", encoding="utf-8")
    catalog = list_calculation_artifacts(workspace)
    gjf_artifact = _artifact(catalog, "nodes/n001/inputs/source.gjf")
    xyz_artifact = _artifact(catalog, "nodes/n001/inputs/source.xyz")

    with pytest.raises(ComputeContractError, match="unknown calculation artifact_id"):
        create_calculation_intent(workspace, _request("art_000000000000000000000000"))
    with pytest.raises(ComputeContractError, match="not compatible with input role gjf"):
        create_calculation_intent(workspace, _request(xyz_artifact["artifact_id"]))

    missing_role = _request(xyz_artifact["artifact_id"])
    missing_role["backend"] = "ase_neb"
    missing_role["task_type"] = "neb"
    missing_role["input_artifacts"] = [
        {"input_role": "reactant", "artifact_id": xyz_artifact["artifact_id"]}
    ]
    with pytest.raises(ComputeContractError, match=r"missing=\['product'\]"):
        create_calculation_intent(workspace, missing_role)

    second = workspace / "nodes/n001/inputs/second.gjf"
    second.write_text("# HF/STO-3G\n\nSecond\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")
    second_artifact = _artifact(
        list_calculation_artifacts(workspace),
        "nodes/n001/inputs/second.gjf",
    )
    duplicate_role = _request(gjf_artifact["artifact_id"])
    duplicate_role["input_artifacts"].append(
        {"input_role": "gjf", "artifact_id": second_artifact["artifact_id"]}
    )
    with pytest.raises(ComputeContractError, match="duplicate calculation input role"):
        create_calculation_intent(workspace, duplicate_role)

    gjf.with_name("duplicate.com").write_bytes(gjf.read_bytes())
    with pytest.raises(ComputeContractError, match="artifact_id is ambiguous"):
        create_calculation_intent(workspace, _request(gjf_artifact["artifact_id"]))


def test_list_artifacts_cli_returns_catalog_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace = _workspace(tmp_path)
    source = workspace / "nodes/n001/inputs/source.xyz"
    source.write_text("1\nsource\nH 0 0 0\n", encoding="utf-8")

    assert compute_cli_main([
        "list-artifacts",
        "--root",
        str(workspace),
        "--node-id",
        "n001",
    ]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert '"schema_version": "ts-compute-artifact-catalog/1"' in output.out
    assert '"path": "nodes/n001/inputs/source.xyz"' in output.out


def test_prepare_and_submit_reject_stale_input_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    gjf = workspace / "nodes/n001/inputs/source.gjf"
    original = "# HF/STO-3G\n\nSP\n\n0 1\nH 0 0 0\n\n"
    gjf.write_text(original, encoding="utf-8")
    artifact_id = _artifact(
        list_calculation_artifacts(workspace),
        "nodes/n001/inputs/source.gjf",
    )["artifact_id"]

    stale_before_prepare = create_calculation_intent(workspace, _request(artifact_id))
    gjf.write_text(original.replace("SP", "changed"), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="input binding changed.*artifact_id mismatch"):
        prepare_calculation(workspace, stale_before_prepare["intent_ref"])

    gjf.write_text(original, encoding="utf-8")
    current_id = _artifact(
        list_calculation_artifacts(workspace),
        "nodes/n001/inputs/source.gjf",
    )["artifact_id"]
    monkeypatch.setenv("TS_COMPUTE_LOGIN_HOSTS", "login.test")
    monkeypatch.setenv("TS_COMPUTE_COMPUTE_HOSTS", "compute.test")
    monkeypatch.setenv("TS_COMPUTE_REMOTE_ROOTS", "/remote/ts")
    stale_before_submit = create_calculation_intent(
        workspace,
        _request(
            current_id,
            dry_run=False,
            execution_target={
                "kind": "remote",
                "transport": "ssh",
                "login_host": "login.test",
                "compute_host": "compute.test",
                "remote_root": "/remote/ts",
            },
        ),
    )
    prepare_calculation(workspace, stale_before_submit["intent_ref"])
    gjf.write_text(original.replace("SP", "changed again"), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="input binding changed.*artifact_id mismatch"):
        submit_calculation(workspace, stale_before_submit["intent_id"])
