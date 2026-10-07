import pytest
from research_state import agent_workspace as state
from tests.unit.test_job_recovery import workspace

AUTH = {"principal": "root_agent", "authority": "kernel_write"}


def test_email_bash_preflight_has_no_calculation_dependency_but_needs_lifecycle_recovery(tmp_path):
    workspace(tmp_path)
    change(tmp_path, [{"type": "create_node", "id": "node_delivery", "title": "Email",
                       "objective": "Deliver results", "claim_ids": ["claim_1"], "dependency_ids": ["node_1"]}])
    tool = {"name": "bash", "effect": "execution_control", "phase": "prepare",
            "args": {"command": '"$TSPI_PYTHON" email_cli.py check'}}
    def admit():
        return state.read_liveness(tmp_path, {"tool": tool})["tool_admission"]
    assert admit()["accepted"]
    job = {"name": "job_start", "effect": "execution_control", "args": {"nodeId": "node_delivery"}}
    assert state.read_liveness(tmp_path, {"tool": job})["tool_admission"]["code"] == "research_node_not_ready"
    change(tmp_path, [{"type": "set_node_state", "node_id": "node_1", "state": "blocked", "summary": "Missing binding"}])
    state.checkpoint(tmp_path, {**AUTH, "id": "checkpoint_blocked", "disposition": "blocked", "reason": "Missing binding"})
    assert admit()["code"] == "research_lifecycle_blocked"
    state.checkpoint(tmp_path, {**AUTH, "id": "checkpoint_recover", "disposition": "continue_required", "reason": "Binding repaired"})
    assert admit()["accepted"]
    assert state.read_context(tmp_path)["attempts"] == []


def test_change_supersedes_recovery_checkpoint_and_requires_a_new_checkpoint(tmp_path):
    workspace(tmp_path)
    state.checkpoint(tmp_path, {**AUTH, "id": "checkpoint_recovery", "disposition": "continue_required"})
    assert state.read_liveness(tmp_path)["disposition"] == "continue_required"
    change(tmp_path, [{"type": "set_node_state", "node_id": "node_1", "state": "active"}])
    live = state.read_liveness(tmp_path)
    assert live.get("disposition") is None
    assert live["lifecycle"] == "decision_needed"
    assert live["needs_checkpoint"] is True
    assert live["execution_ready"] is True
    assert live["continuation"] is None


def test_issue_resolution_preserves_original_evidence_and_validates_references(tmp_path):
    workspace(tmp_path)
    change(tmp_path, [{"type": "create_finding", "id": "issue_binding", "node_id": "node_1",
                       "kind": "issue", "statement": "Python binding missing", "severity": "blocking"}])
    revision = state.read_context(tmp_path)["revision"]
    with pytest.raises(state.AgentWorkspaceError, match="evidence_reference_unknown"):
        change(tmp_path, [{"type": "resolve_issue", "id": "issue_binding", "resolution": "Fixed", "source_refs": ["missing"]}])
    assert state.read_context(tmp_path)["revision"] == revision
    operation = {"type": "resolve_issue", "id": "issue_binding", "resolution": "Binding repaired and probe passed"}
    change(tmp_path, [operation])
    finding = state.read_context(tmp_path)["findings"][0]
    assert finding["status"] == "resolved"
    assert finding["statement"] == "Python binding missing"
    assert finding["source_refs"] == []
    change(tmp_path, [operation])
    assert state.read_context(tmp_path)["findings"][0] == finding
    with pytest.raises(state.AgentWorkspaceError, match="different resolution"):
        change(tmp_path, [{**operation, "resolution": "Changed history"}])


def change(root, operations):
    return state.apply_change(root, {**AUTH, "operations": operations})


def test_blocked_delivery_does_not_block_calculation_or_monitor(tmp_path):
    workspace(tmp_path)
    change(tmp_path, [
        {"type": "create_node", "id": "node_delivery", "title": "Delivery", "objective": "Email", "dependency_ids": ["node_1"]},
        {"type": "set_node_state", "node_id": "node_delivery", "state": "blocked", "summary": "Recipient configuration missing"},
    ])
    with pytest.raises(state.AgentWorkspaceError, match="user_wait_scope_invalid"):
        state.checkpoint(tmp_path, {**AUTH, "id": "checkpoint_bad", "disposition": "user_input_required", "reason": "Need recipient", "node_ids": ["node_delivery"]})
    live = state.read_liveness(tmp_path, {"tool": {"name": "job_start", "effect": "execution_control", "args": {"nodeId": "node_1"}}})
    assert live["tool_admission"]["accepted"]
    change(tmp_path, [{"type": "register_attempt", "id": "attempt_running", "node_id": "node_1", "state": "running"}])
    state.checkpoint(tmp_path, {**AUTH, "id": "checkpoint_external", "disposition": "waiting_external", "unresolved_refs": ["attempt_running"]})
    wake = state.turn(tmp_path, {"protocol": "research_turn_request", "version": 1, "request_id": "wake", "operation": "wake", "input": {}})
    assert wake["status"] == "completed"
    assert wake["output"].get("admitted", True)
    assert state.read_liveness(tmp_path)["blocked_node_ids"] == ["node_delivery"]


def test_dependencies_and_optional_bad_finding_preserve_independent_readiness(tmp_path):
    workspace(tmp_path)
    change(tmp_path, [{"type": "create_node", "id": "node_child", "title": "Child", "objective": "Needs parent", "claim_ids": ["claim_1"], "dependency_ids": ["node_1"]}])
    before = state.read_context(tmp_path)["revision"]
    with pytest.raises(state.AgentWorkspaceError, match="evidence_reference_unknown.*artifact_create"):
        change(tmp_path, [{"type": "create_finding", "id": "finding_probe", "node_id": "node_1", "kind": "fact", "statement": "Transport responds", "source_refs": ["job_probe:local"], "provenance": {"source": "probe"}}])
    assert state.read_context(tmp_path)["revision"] == before
    live = state.read_liveness(tmp_path)
    assert "node_1" in live["ready_node_ids"]
    assert "node_child" not in live["ready_node_ids"]
    denied = state.read_liveness(tmp_path, {"tool": {"name": "job_start", "effect": "execution_control", "args": {"nodeId": "node_child"}}})
    assert denied["tool_admission"]["code"] == "research_node_not_ready"


def test_independent_work_in_shared_research_scope_and_duplicate_guard(tmp_path):
    workspace(tmp_path)
    change(tmp_path, [{"type":"register_attempt", "id":"attempt_remote", "node_id":"node_1", "state":"running",
                       "metadata":{"job_id":"job_remote", "job_metadata":{"work_id":"remote_cf22d"}}}])
    def admit(**args):
        return state.read_liveness(tmp_path, {"tool":{"name":"job_start","effect":"execution_control","args":{"nodeId":"node_1",**args}}})["tool_admission"]
    assert admit(workId="local_xtb")["accepted"]
    assert admit(workId="remote_cf22d")["code"] == "research_work_already_submitted"
    assert admit()["code"] == "research_work_identity_required"
    assert admit(requestId="remote")["accepted"]
    change(tmp_path, [{"type":"set_node_state","node_id":"node_1","state":"blocked","summary":"Actual missing input"}])
    assert not admit(workId="local_xtb")["accepted"]


def test_continuation_is_durable_bounded_and_checkpoint_renaming_is_not_progress(tmp_path):
    workspace(tmp_path)
    def checkpoint(i):
        state.checkpoint(tmp_path,{**AUTH,"id":f"checkpoint_{i}","session_id":"session-a","disposition":"continue_required"})
        return state.read_liveness(tmp_path)
    first = checkpoint(1)["continuation"]
    assert first["admitted"]
    assert checkpoint(2)["continuation"] == first
    assert state.read_liveness(tmp_path)["continuation"] == first
    for i in range(2,10):
        change(tmp_path,[{"type":"set_focus","node_ids":["node_1"],"claim_ids":["claim_1"]}])
        live = checkpoint(i+1)
    assert live["continuation"]["admitted"] is False
    assert live["continuation"]["reason"] == "continuation_budget_exhausted"
    change(tmp_path,[{"type":"register_attempt","id":"attempt_wait","node_id":"node_1","state":"running"}])
    state.checkpoint(tmp_path,{**AUTH,"id":"checkpoint_external","disposition":"waiting_external","unresolved_refs":["attempt_wait"]})
    assert state.read_liveness(tmp_path)["continuation"] is None


def test_continuation_stops_when_next_turn_has_no_research_progress(tmp_path):
    workspace(tmp_path)
    for index in range(2):
        state.checkpoint(tmp_path,{**AUTH,'id':f'checkpoint_turn_{index}','turn_id':str(index),
            'session_id':'session-a','disposition':'continue_required'})
    result=state.read_liveness(tmp_path)['continuation']
    assert result['admitted'] is False and result['reason']=='no_research_progress'
