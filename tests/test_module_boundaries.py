from __future__ import annotations

from pathlib import Path

from mol_comparator import compare_structures
from ts_backends.base import Backend, BackendTask
from ts_backends.gaussian import GaussianBackend, prepare_gaussian
from ts_remote.base import Runner
from ts_remote.ssh import SshRunner
from ts_web import normalize_workspace, register_workspace


def test_backend_prepares_command_without_workspace_write() -> None:
    task = BackendTask(node_id="n001", work_dir="nodes/n001", inputs={"gjf": "nodes/n001/inputs/ts.gjf"})
    prepared = prepare_gaussian(task)
    assert prepared.backend == "gaussian"
    assert prepared.command == ["g16", "nodes/n001/inputs/ts.gjf"]
    assert prepared.expected_artifacts == ["nodes/n001/outputs/gaussian.out"]
    assert isinstance(GaussianBackend(), Backend)


def test_remote_runner_returns_node_scoped_receipt() -> None:
    runner = SshRunner()
    receipt = runner.submit(node_id="n001", host="compute-0-30", remote_dir="/remote/n001", command=["g16", "ts.gjf"])
    assert isinstance(runner, Runner)
    assert receipt.node_id == "n001"
    assert receipt.receipt_path == "/remote/n001/remote_receipt.json"


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


def test_web_normalizer_is_read_only() -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "single_step_success"
    before = {str(path.relative_to(fixture)) for path in fixture.rglob("*") if path.is_file()}
    view = normalize_workspace(fixture)
    after = {str(path.relative_to(fixture)) for path in fixture.rglob("*") if path.is_file()}
    assert view["valid"] is True
    assert after == before
