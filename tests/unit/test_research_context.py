from pathlib import Path

from research_memory import FileProjectionWriter, ResearchContextBuilder
from research_state import admit_workspace, read_context, read_liveness
from research_state.workspace import initialize_workspace


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "research"
    initialize_workspace(root, "workspace_memory", "research")
    admit_workspace(root, {"workspace_id": "workspace_memory", "authority": "host"})
    return root


def test_memory_context_builder_reads_state_and_projection(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    pack = ResearchContextBuilder().build(root)

    assert pack.revision == 0
    assert pack.context["workspace_id"] == "workspace_memory"
    assert pack.liveness["workspace_id"] == "workspace_memory"
    assert pack.memory["schema_version"] == "research_memory_index_1"


def test_memory_projection_writer_is_rebuildable_and_state_is_read_only(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    before = read_context(root)
    FileProjectionWriter().write_projection(root, before, read_liveness(root))
    after = read_context(root)

    assert after == before
    assert ResearchContextBuilder().build(root).memory["revision"] == before["revision"]
