from __future__ import annotations

from pathlib import Path

import ts_remote
from tests.workspace_helpers import bootstrap_workspace_fixture, start_research_node
from ts_backends.base import Backend, BackendTask
from ts_backends.gaussian import GaussianBackend, prepare_gaussian
from ts_render import MolVisualizer
from ts_structures import compare_structures
from ts_web import normalize_workspace, register_workspace
from ts_workspace.state import STATE_FILES


def test_backend_prepares_command_without_workspace_write() -> None:
    task = BackendTask(
        node_id="node_1",
        task_type="opt_freq",
        work_dir="nodes/node_1",
        inputs={"gjf": "inputs/ts.gjf"},
    )
    prepared = prepare_gaussian(task)
    assert prepared.backend == "gaussian"
    assert prepared.node_id == task.node_id
    assert prepared.command == ["g16", "inputs/ts.gjf"]
    assert prepared.expected_artifacts == [
        "nodes/node_1/outputs/gaussian.out"
    ]
    assert isinstance(GaussianBackend(), Backend)


def test_remote_boundary_exposes_scheduler_lifecycle_without_raw_runner() -> None:
    assert callable(ts_remote.submit)
    assert callable(ts_remote.status)
    assert callable(ts_remote.collect)
    assert callable(ts_remote.cancel)
    assert not hasattr(ts_remote, "Runner")
    assert not hasattr(ts_remote, "SshRunner")


def test_ts_structures_returns_observation_shaped_measurements(tmp_path: Path) -> None:
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


def test_web_normalizer_is_read_only(tmp_path: Path) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(workspace)
    before = {
        path.relative_to(workspace): (path.stat().st_mtime_ns, path.read_bytes())
        for path in workspace.rglob("*")
        if path.is_file()
    }
    view = normalize_workspace(workspace)
    after = {
        path.relative_to(workspace): (path.stat().st_mtime_ns, path.read_bytes())
        for path in workspace.rglob("*")
        if path.is_file()
    }
    assert view["valid"] is True
    assert after == before


def test_ts_render_writes_artifact_without_canonical_state_mutation(tmp_path: Path, monkeypatch) -> None:
    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    node_id = start_research_node(workspace)["node_id"]
    xyz = workspace / "inputs" / "reactant.xyz"
    xyz.write_text("1\nreactant\nH 0 0 0\n", encoding="utf-8")
    fake = tmp_path / "xyzrender"
    fake.write_text(
        """#!/usr/bin/env python3
import sys
from pathlib import Path
if "-o" in sys.argv:
    path = Path(sys.argv[sys.argv.index("-o") + 1])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake image")
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("TS_RENDER_XYZRENDER", str(fake))
    before = {name: (workspace / name).read_bytes() for name in STATE_FILES}

    result = MolVisualizer().render_molecule(
        xyz,
        workspace / "nodes" / node_id / "outputs" / "render.png",
    )

    assert result.ok is True
    assert before == {name: (workspace / name).read_bytes() for name in STATE_FILES}
