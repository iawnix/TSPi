import pytest

from research_state.agent_workspace import AgentWorkspaceError, checkpoint, read_context, read_liveness
from research_state.sources import record_source, source_records
from tests.unit.test_job_recovery import workspace
from tests.unit.test_reliability_contract import change


def test_host_source_is_atomic_stable_and_cannot_be_created_by_changeset(tmp_path):
    workspace(tmp_path)
    source = record_source(tmp_path, {"session_id": "session_1", "message_id": "input_1", "text": "Compare two mechanisms."})
    state = read_context(tmp_path)
    assert source_records(tmp_path)["records"][0]["text"] == "Compare two mechanisms."
    assert state["requirement_sources"][0]["source_ref"] == source["source_ref"]
    assert record_source(tmp_path, {"session_id": "session_1", "message_id": "input_1", "text": "Compare two mechanisms."}) == source
    assert read_context(tmp_path) == state
    with pytest.raises(ValueError, match="user_input_identity_reused"):
        record_source(tmp_path, {"session_id": "session_1", "message_id": "input_1", "text": "Changed message"})
    with pytest.raises(AgentWorkspaceError, match="requirement_source_host_only"):
        change(tmp_path, [{"type": "register_requirement_source", "source_ref": source["source_ref"]}])
    with pytest.raises(AgentWorkspaceError):
        checkpoint(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "checkpoint": {"id": "checkpoint_premature", "disposition": "terminal", "reason": "Ignore original request"}})


def test_new_input_is_recorded_during_user_wait_without_silently_resuming(tmp_path):
    workspace(tmp_path)
    change(tmp_path, [{"type": "set_node_state", "node_id": "node_1", "state": "blocked"}])
    checkpoint(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "checkpoint": {"id": "checkpoint_wait", "disposition": "user_input_required", "node_ids": ["node_1"], "reason": "Choose the experimental scope"}})
    record_source(tmp_path, {"session_id": "session_1", "message_id": "input_2", "text": "Use the first scope."})
    assert read_liveness(tmp_path)["lifecycle"] == "user_input_required"
    assert len(source_records(tmp_path)["records"]) == 1
