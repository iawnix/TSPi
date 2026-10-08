"""Replay the failure mechanisms found in t003 with synthetic data."""
import json
import sys
import time

import pytest

from research_state.agent_workspace import AgentWorkspaceError, apply_change, checkpoint, read_context
from research_memory.decision_context import build_decision_context
from tspi_runtime.api import execute
from tspi_runtime.execution import dispatch
from tspi_runtime.job_monitor import command
from tests.unit.test_job_recovery import workspace


def change(root, operations):
    return apply_change(root, {"principal": "root_agent", "authority": "kernel_write", "operations": operations})


def test_public_queries_find_current_attempt_and_validate_real_state(tmp_path):
    workspace(tmp_path)
    change(tmp_path, [{"type": "register_attempt", "id": "attempt_query", "node_id": "node_1", "state": "started"}])
    assert execute("research.detail", tmp_path, {"kind": "node", "id": "node_1"})["item"]["id"] == "node_1"
    assert any(x["id"] == "attempt_query" for x in execute("research.locate", tmp_path, {"query": "attempt_query"})["matches"])
    assert execute("research.validate", tmp_path)["valid"]

    with pytest.raises(AgentWorkspaceError, match="terminal_with_active_attempts"):
        checkpoint(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "id": "checkpoint_final",
                             "disposition": "terminal", "claim_ids": ["claim_1"], "node_ids": ["node_1"]})


def test_interpretation_rejects_wrong_producer_but_accepts_comparison(tmp_path):
    workspace(tmp_path)
    for name in ["first", "second"]:
        change(tmp_path, [{"type": "register_attempt", "id": "attempt_" + name, "node_id": "node_1", "state": "failed"},
            {"type": "register_artifact", "id": "art_" + name, "producer_attempt_id": "attempt_" + name,
             "location": str(tmp_path / name), "sha256": "sha256:test"}])
    before = read_context(tmp_path)
    op = {"type": "create_interpretation", "id": "interpretation_test", "claim_id": "claim_1",
          "node_id": "node_1", "attempt_ref": "attempt_second", "kind": "result", "summary": "Compare failures", "outcome": "invalid",
          "direct_evidence_refs": ["art_first"]}
    with pytest.raises(AgentWorkspaceError, match="evidence_producer_mismatch"):
        change(tmp_path, [op])
    # The live context evaluation confused an Attempt identity with an Artifact.
    with pytest.raises(AgentWorkspaceError, match="evidence_reference_type_mismatch.*attempt_id=attempt_second"):
        change(tmp_path, [{**op, "direct_evidence_refs": ["attempt_second"]}])
    assert read_context(tmp_path) == before
    change(tmp_path, [{**op, "direct_evidence_refs": ["art_second"], "comparison_evidence_refs": ["art_first"]}])
    assert read_context(tmp_path)["attempt_interpretations"][0]["comparison_evidence_refs"] == ["art_first"]


def test_monitor_updates_attempt_without_agent_status_call(tmp_path):
    workspace(tmp_path)
    job = dispatch("start", {"root": str(tmp_path), "job_id": "job_fail", "node_id": "node_1",
                             "session_id": "session_test", "command": [sys.executable, "-c", "raise SystemExit(23)"]})
    for _ in range(200):
        tick = command(tmp_path, "tick", {})
        assert not tick["registration_errors"]
        attempt = read_context(tmp_path)["attempts"][0]
        if attempt["state"] == "failed":
            break
        time.sleep(.01)
    assert attempt["state"] == "failed"
    assert attempt["exit_code"] == 23
    assert attempt["finished_at"]
    pending = command(tmp_path, "pending", {})["deliveries"]
    assert len(pending) == 1
    from pathlib import Path
    from jsonschema import Draft202012Validator
    schemas = Path(__file__).resolve().parents[2] / 'contracts/tspi-monitor/1'
    event = command(tmp_path, 'event', {'event_id': pending[0]['event_id']})
    binding = command(tmp_path, 'list', {})['monitors'][0]
    for name, value in [('monitor', binding), ('event', event), ('delivery', pending[0])]:
        validator = Draft202012Validator(json.loads((schemas / (name + '.schema.json')).read_text()))
        validator.validate(value)
        assert not validator.is_valid({**value, 'intent_id': 'calc_1'})
    result = dispatch("collect", {"root": str(tmp_path), "job_id": job["job_id"]})
    receipt = result["result_receipt"]
    assert receipt["execution_state"] == "failed"
    assert receipt["attempt_id"] == job["attempt_id"]
    assert dispatch("collect", {"root": str(tmp_path), "job_id": job["job_id"]})["result_receipt"] == receipt


def test_context_prioritizes_current_attempt_over_large_artifact_catalog(tmp_path):
    workspace(tmp_path)
    change(tmp_path, [{"type": "register_attempt", "id": "attempt_current", "node_id": "node_1", "state": "started"}])
    path = tmp_path / "research_map/context.json"
    state = json.loads(path.read_text())
    state["artifacts"] = [{"id": f"art_{i}", "metadata": {"command": "x" * 10000}} for i in range(100)]
    path.write_text(json.dumps(state))
    view = build_decision_context(tmp_path)
    assert view["attempts"][0]["id"] == "attempt_current"
    assert view["goals"][0]["id"] == "claim_1"
    assert len(json.dumps(view, ensure_ascii=False).encode()) < 16000
    assert view['bounds']['used_bytes'] == len(json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())
    assert execute("research.context", tmp_path)["schema_version"] == "research-decision-context/2"
    change(tmp_path, [{"type": "set_focus", "node_ids": ["node_1"], "claim_ids": []}])
    assert build_decision_context(tmp_path)['goals'][0]['id'] == 'claim_1'


def completed_job(root, job_id='job_source', text='evidence'):
    job = dispatch('start', {'root': str(root), 'job_id': job_id, 'node_id': 'node_1',
        'command': [sys.executable, '-c', f'from pathlib import Path;Path("result.json").write_text({text!r})'],
        'outputs': [{'path': 'result.json', 'required': True}]})
    for _ in range(200):
        if dispatch('status', {'root': str(root), 'job_id': job['job_id']})['state'] in {'succeeded', 'failed'}:
            return dispatch('collect', {'root': str(root), 'job_id': job['job_id']})
        time.sleep(.01)
    raise AssertionError('fixture failed to finish')


def test_runtime_provenance_and_result_versions_cannot_be_forged(tmp_path):
    workspace(tmp_path)
    result = completed_job(tmp_path)
    receipt = result['result_receipt']
    attempt = receipt['attempt_id']
    with pytest.raises(AgentWorkspaceError, match='runtime_fact_write_forbidden'):
        change(tmp_path, [{'type': 'transition_attempt', 'attempt_id': attempt, 'state': 'failed'}])
    from tspi_runtime.evidence import dispatch as artifact
    with pytest.raises(ValueError, match='artifact_source_mismatch'):
        artifact('register', {'root': str(tmp_path), 'producer_attempt_id': attempt, 'path': __file__})
    op = {'type': 'create_interpretation', 'kind': 'result', 'id': 'interpretation_result',
        'claim_id': 'claim_1', 'attempt_ref': attempt, 'summary': 'Collected output', 'outcome': 'supports',
        'result_receipt_ref': receipt['receipt_id'], 'direct_evidence_refs': receipt['artifact_refs']}
    change(tmp_path, [op])
    (tmp_path / 'runs/jobs/job_source/result.json').write_text('updated output')
    refreshed = dispatch('collect', {'root': str(tmp_path), 'attempt_id': attempt})
    assert refreshed['result_receipt']['receipt_id'] != receipt['receipt_id']
    assert read_context(tmp_path)['attempt_interpretations'][0]['review_state'] == 'needs_review'
    assert not execute('research.validate', tmp_path)['valid']
    with pytest.raises(AgentWorkspaceError, match='result_receipt_stale'):
        change(tmp_path, [{**op, 'id': 'interpretation_stale'}])
    change(tmp_path, [{**op, 'id': 'interpretation_new', 'supersedes_id': op['id'],
        'result_receipt_ref': refreshed['result_receipt']['receipt_id'],
        'direct_evidence_refs': refreshed['result_receipt']['artifact_refs']}])
    assert execute('research.validate', tmp_path)['valid']


def test_exact_selectors_and_explicit_repeat(tmp_path):
    workspace(tmp_path)
    first = completed_job(tmp_path)
    receipt = first['result_receipt']
    assert dispatch('status', {'root': str(tmp_path), 'attempt_id': receipt['attempt_id']})['job_id'] == 'job_source'
    with pytest.raises(ValueError, match='job_selector_conflict'):
        dispatch('collect', {'root': str(tmp_path), 'attempt_id': receipt['attempt_id'], 'job_id': 'job_other'})
    with pytest.raises(ValueError, match='job_not_found'):
        dispatch('collect', {'root': str(tmp_path), 'job_id': 'job_sour'})
    params = {'root': str(tmp_path), 'job_id': 'job_second', 'node_id': 'node_1',
        'command': [sys.executable, '-c', 'from pathlib import Path;Path("result.json").write_text(\'evidence\')'],
        'outputs': [{'path': 'result.json', 'required': True}]}
    blocked = dispatch('start', params)
    assert blocked['code'] == 'duplicate_execution'
    assert len(read_context(tmp_path)['attempts']) == 1
    repeated = dispatch('start', {**params, 'repeat': {'predecessor_job_id': 'job_source',
        'reason': 'Measure repeatability', 'budget': 'One local process'}})
    assert repeated['job_id'] == 'job_second'
    for _ in range(200):
        if dispatch('status', {'root': str(tmp_path), 'job_id': 'job_second'})['state'] == 'succeeded':
            break
        time.sleep(.01)


def test_gate_requires_executed_registered_validator(tmp_path):
    workspace(tmp_path)
    change(tmp_path, [{'type': 'create_gate', 'id': 'gate_frequency', 'scope': 'node', 'target_id': 'node_1',
        'criteria': [{'id': 'single_mode', 'source_type': 'validator_result',
                      'validator_id': 'chemical.gaussian_frequency', 'validator_version': '1'}]}])
    parsed = json.dumps({'summary': {'normal_termination': True}, 'frequencies': [-100, 10, 20]})
    result = completed_job(tmp_path, text=parsed)
    raw = next(a['artifact_id'] for a in result['artifacts'] if a['provenance']['source_path'].endswith('result.json'))
    evaluation = {'type': 'evaluate_gate', 'gate_id': 'gate_frequency', 'verdict': 'pass',
        'assessments': [{'criterion_id': 'single_mode', 'verdict': 'pass', 'result_receipt_ref': result['result_receipt']['receipt_id']}]}
    with pytest.raises(AgentWorkspaceError, match='gate_validator_receipt_required'):
        change(tmp_path, [evaluation])
    job = dispatch('start', {'root': str(tmp_path), 'job_id': 'job_validate', 'node_id': 'node_1',
                            'validator_id': 'chemical.gaussian_frequency', 'input_artifact_ids': [raw]})
    for _ in range(200):
        if dispatch('status', {'root': str(tmp_path), 'job_id': job['job_id']})['state'] in {'succeeded', 'failed'}:
            break
        time.sleep(.01)
    validated = dispatch('collect', {'root': str(tmp_path), 'job_id': job['job_id']})['result_receipt']
    assert validated['validator_result']['verdict'] == 'pass'
    evaluation['assessments'][0]['result_receipt_ref'] = validated['receipt_id']
    change(tmp_path, [evaluation])
    change(tmp_path, [{'type': 'set_node_state', 'node_id': 'node_1', 'state': 'closed', 'outcome': 'completed'}])
    assert execute('research.validate', tmp_path)['valid']
    (tmp_path / 'runs/jobs/job_source/result.json').write_text('changed source')
    dispatch('collect', {'root': str(tmp_path), 'job_id': 'job_source'})
    assert 'completed_gate_not_current' in {i['code'] for i in execute('research.validate', tmp_path)['issues']}
    from tspi_runtime.validators import prepare
    with pytest.raises(ValueError, match='validator_input_stale'):
        prepare(tmp_path, {'validator_id': 'chemical.gaussian_frequency', 'input_artifact_ids': [raw]})


def test_monitor_commit_recovers_both_state_and_event(tmp_path, monkeypatch):
    workspace(tmp_path)
    job = dispatch('start', {'root': str(tmp_path), 'job_id': 'job_crash', 'node_id': 'node_1',
        'session_id': 'session_test', 'command': [sys.executable, '-c', 'raise SystemExit(7)']})
    for _ in range(200):
        if (tmp_path / 'runs/jobs/job_crash/status.json').exists():
            break
        time.sleep(.01)
    from research_state import transactions
    original = transactions._atomic_json
    crashed = []
    def interrupted(path, value):
        if 'research_map' in str(path) and not crashed:
            crashed.append(True)
            raise OSError('fixture crash after durable commit decision')
        return original(path, value)
    with monkeypatch.context() as patch:
        patch.setattr(transactions, '_atomic_json', interrupted)
        tick = command(tmp_path, 'tick', {})
        assert tick['registration_errors']
    assert read_context(tmp_path)['attempts'][0]['state'] == 'failed'
    assert len(command(tmp_path, 'pending', {})['deliveries']) == 1
    command(tmp_path, 'tick', {})
    assert len(command(tmp_path, 'pending', {})['deliveries']) == 1
    assert len(list((tmp_path / 'operations/jobs').glob('*.json'))) == 1


def test_unknown_and_conflicting_observations_never_allow_terminal(tmp_path):
    workspace(tmp_path)
    result = completed_job(tmp_path)
    from tspi_runtime.execution import _receipt
    from tspi_runtime.job_state import observe_attempt
    receipt = _receipt(tmp_path, {'job_id': result['job_id']})
    conflict = observe_attempt(tmp_path, receipt, {'state': 'failed', 'exit_code': 5})
    assert conflict['code'] == 'job_terminal_conflict'
    from research_state.invariants import active_attempts
    assert active_attempts(read_context(tmp_path)) == [receipt.attempt_id]
    assert not execute('research.validate', tmp_path)['valid']
    dispatch('reconcile', {'root': str(tmp_path), 'job_id': receipt.job_id})
    assert read_context(tmp_path)['attempts'][0]['state'] == 'succeeded'
    assert not active_attempts(read_context(tmp_path))


def test_rejects_old_contract_and_detects_prepared_input_mutation(tmp_path):
    workspace(tmp_path)
    with pytest.raises(AgentWorkspaceError, match='unsupported|unknown'):
        change(tmp_path, [{'type': 'create_attempt', 'id': 'attempt_old_alias', 'node_id': 'node_1', 'state': 'started'}])
    with pytest.raises(ValueError, match='schema_field_invalid'):
        dispatch('start', {'root': str(tmp_path), 'requestId': 'old', 'command': ['true']})
    with pytest.raises(AgentWorkspaceError, match='schema_field_invalid'):
        apply_change(tmp_path, {'principal': 'root_agent', 'authority': 'kernel_write', 'expectedRevision': 0,
            'operations': [{'type': 'set_focus', 'node_ids': [], 'claim_ids': []}]})
    source = tmp_path / 'input.txt'
    source.write_text('changed')
    with pytest.raises(ValueError, match='prepared_input_changed'):
        dispatch('start', {'root': str(tmp_path), 'job_id': 'job_changed', 'node_id': 'node_1', 'command': ['true'],
            'inputs': [{'source': str(source), 'destination': 'input.txt', 'sha256': '0' * 64}]})
    assert not (tmp_path / 'runs/jobs/job_changed').exists()
    manifest = tmp_path / 'workspace_manifest.json'
    value = json.loads(manifest.read_text()); value['schema_version'] = 'research_state_workspace_1'
    manifest.write_text(json.dumps(value))
    with pytest.raises(Exception, match='unsupported_workspace_manifest'):
        execute('research.context', tmp_path)
    with pytest.raises(Exception, match='unsupported_workspace_manifest'):
        dispatch('status', {'root': str(tmp_path), 'job_id': 'job_changed'})


def test_gate_revision_invalidates_previous_assessment_and_retains_reason(tmp_path):
    workspace(tmp_path)
    criterion = {'id': 'review', 'source_type': 'agent_assessment', 'description': 'Review evidence'}
    change(tmp_path, [{'type': 'create_gate', 'id': 'gate_review', 'scope': 'node', 'target_id': 'node_1', 'criteria': [criterion]},
        {'type': 'evaluate_gate', 'gate_id': 'gate_review', 'verdict': 'pass',
         'assessments': [{'criterion_id': 'review', 'verdict': 'pass', 'reason': 'Inspected all available files'}]}])
    change(tmp_path, [{'type': 'revise_gate', 'gate_id': 'gate_review', 'criteria': [{**criterion, 'description': 'Include new evidence'}],
                      'reason': 'User expanded the research scope'}])
    gate = read_context(tmp_path)['gates'][0]
    assert gate['version'] == 2
    assert gate['revisions'][0]['reason'] == 'User expanded the research scope'
    with pytest.raises(AgentWorkspaceError, match='before a NodeGate passes'):
        change(tmp_path, [{'type': 'set_node_state', 'node_id': 'node_1', 'state': 'closed', 'outcome': 'completed'}])


def test_collect_crash_recovers_receipt_evidence_and_attempt_together(tmp_path, monkeypatch):
    workspace(tmp_path)
    job = dispatch('start', {'root': str(tmp_path), 'job_id': 'job_collect_crash', 'node_id': 'node_1',
        'command': [sys.executable, '-c', 'print("collected evidence")']})
    for _ in range(200):
        if dispatch('status', {'root': str(tmp_path), 'job_id': job['job_id']})['state'] == 'succeeded':
            break
        time.sleep(.01)
    from research_state import transactions
    original = transactions._atomic_json
    crashed = []
    def interrupted(path, value):
        if 'research_map' in str(path) and not crashed:
            crashed.append(True)
            raise OSError('collection commit interrupted')
        return original(path, value)
    with monkeypatch.context() as patch:
        patch.setattr(transactions, '_atomic_json', interrupted)
        with pytest.raises(OSError, match='collection commit interrupted'):
            dispatch('collect', {'root': str(tmp_path), 'job_id': job['job_id']})
    state = read_context(tmp_path)
    assert state['attempts'][0]['state'] == 'succeeded'
    result_id = state['attempts'][0]['metadata']['latest_result_receipt_ref']
    receipt = json.loads((tmp_path / 'operations/results' / (result_id + '.json')).read_text())
    assert set(receipt['artifact_refs']) <= {a['id'] for a in state['artifacts']}
    assert dispatch('collect', {'root': str(tmp_path), 'job_id': job['job_id']})['result_receipt'] == receipt


def test_missing_submission_receipt_updates_attempt_on_explicit_status(tmp_path, monkeypatch):
    workspace(tmp_path)
    from tspi_runtime.execution import _runtime
    def unavailable(*args, **kwargs):
        raise OSError('submission response lost')
    monkeypatch.setattr(_runtime(tmp_path), 'job_start', unavailable)
    with pytest.raises(RuntimeError, match='requires reconciliation'):
        dispatch('start', {'root': str(tmp_path), 'job_id': 'job_no_receipt', 'node_id': 'node_1', 'command': ['true']})
    assert dispatch('status', {'root': str(tmp_path), 'job_id': 'job_no_receipt'})['state'] == 'unknown'
    assert read_context(tmp_path)['attempts'][0]['state'] == 'unknown'
    row = build_decision_context(tmp_path)['attempts'][0]
    assert row['required_action']['tool'] == 'job_reconcile'


def test_retired_command_fields_fail_before_workspace_or_runtime_access(tmp_path):
    from tspi_runtime.evidence import dispatch as artifact
    before = {path: path.read_bytes() for path in tmp_path.iterdir()}
    for key in ('jobId', 'intent_id', 'unexpected_option'):
        with pytest.raises(ValueError, match='schema_field_invalid'):
            execute('job.collect', tmp_path, {key: 'old'})
        with pytest.raises(ValueError, match='schema_field_invalid'):
            dispatch('collect', {'root': str(tmp_path), key: 'old'})
    for key in ('source_intent_id', 'owner_node', 'artifactId'):
        with pytest.raises(ValueError, match='schema_field_invalid'):
            artifact('register', {'root': str(tmp_path), 'path': 'missing', key: 'old'})
    for key in ('node_ref', 'storage_operation'):
        with pytest.raises(ValueError, match='schema_field_invalid'):
            execute('research.evidence', tmp_path, {key: 'old'})
    assert {path: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_artifact_record_decoder_does_not_translate_retired_manifests():
    from research_state.evidence import ArtifactManifest, EvidenceModelError
    current = {'id': 'art_fixture', 'node_id': 'node_1', 'location': 'runs/result.json',
               'producer_attempt_id': 'attempt_1'}
    assert ArtifactManifest.from_dict(current).producer_attempt_id == 'attempt_1'
    for field in ('path', 'artifact_id', 'owner_node', 'source_intent_id', 'role'):
        with pytest.raises(EvidenceModelError, match='artifact_schema_invalid'):
            ArtifactManifest.from_dict({**current, field: None})
