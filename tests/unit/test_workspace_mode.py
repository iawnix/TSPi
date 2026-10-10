import pytest
from research_agent.research.workspace import initialize_workspace, admit_research_workspace, WorkspaceModeError
from research_agent.application.memory_context import read
from research_agent.research.doctor import inspect_workspace


def test_workspace_admission_and_identity(tmp_path):
    manifest = initialize_workspace(tmp_path, "workspace_test", "research")
    assert manifest["state"] == "admission_pending"
    with pytest.raises(WorkspaceModeError): read(tmp_path)
    admit_research_workspace(tmp_path)
    assert read(tmp_path)["nodes"] == []
    assert read(tmp_path)["schema_version"] == "research-snapshot/3"
    assert inspect_workspace(tmp_path)["valid"]
    with pytest.raises(WorkspaceModeError): initialize_workspace(tmp_path, "different", "research")
    with pytest.raises(WorkspaceModeError): initialize_workspace(tmp_path, "workspace_test", "invalid")


def test_nested_and_symlink_workspaces_rejected(tmp_path):
    root=tmp_path/"outer"
    initialize_workspace(root, "outer", "research")
    with pytest.raises(WorkspaceModeError): initialize_workspace(root/"inner", "inner", "research")
    link=tmp_path/"link"; link.symlink_to(root)
    with pytest.raises(WorkspaceModeError): admit_research_workspace(link)
