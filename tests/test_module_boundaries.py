from __future__ import annotations

from pathlib import Path

from mol_comparator import compare_structures
from ts_backends.base import BackendTask
from ts_backends.gaussian import prepare_gaussian
from ts_web import register_workspace


def test_backend_prepares_command_without_workspace_write() -> None:
    task = BackendTask(node_id="n001", work_dir="nodes/n001", inputs={"gjf": "nodes/n001/inputs/ts.gjf"})
    prepared = prepare_gaussian(task)
    assert prepared.backend == "gaussian"
    assert prepared.command == ["g16", "nodes/n001/inputs/ts.gjf"]


def test_mol_comparator_returns_evidence_shaped_result(tmp_path: Path) -> None:
    xyz = "2\nh2\nH 0 0 0\nH 0 0 0.74\n"
    ref = tmp_path / "ref.xyz"
    target = tmp_path / "target.xyz"
    ref.write_text(xyz, encoding="utf-8")
    target.write_text(xyz, encoding="utf-8")
    result = compare_structures(ref, target)
    assert result["verdict"] == "matched"
    assert result["uncertainty"] == "low"
    assert "metrics" in result


def test_web_registry_rejects_state_dir_inside_source(tmp_path: Path) -> None:
    source = tmp_path / "workspace"
    source.mkdir()
    try:
        register_workspace(source, source / ".web")
    except ValueError as exc:
        assert "state_dir" in str(exc)
    else:
        raise AssertionError("state dir inside source workspace should be rejected")
