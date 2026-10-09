"""Failure injection at the t006 dispatch and atomic closure boundaries."""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from research_state import agent_workspace as state
from research_state.transactions import TransactionCoordinator
from research_state.workspace import initialize_workspace
from tspi_runtime import execution
from tspi_runtime.api import execute


def change(root, operations):
    return state.apply_change(root, {'principal': 'root_agent', 'authority': 'kernel_write', 'operations': operations})


def gate(node='node_calc'):
    return {'type': 'create_gate', 'id': 'gate_' + node, 'scope': 'node', 'target_id': node,
            'criteria': [{'id': 'done', 'source_type': 'agent_assessment', 'description': 'Inspect results'}]}


def evaluate(node='node_calc'):
    return {'type': 'evaluate_gate', 'gate_id': 'gate_' + node, 'verdict': 'pass',
            'assessments': [{'criterion_id': 'done', 'verdict': 'pass', 'reason': 'Inspected fixture evidence'}]}


def close(node='node_calc'):
    return {'type': 'set_node_state', 'node_id': node, 'state': 'closed', 'outcome': 'completed'}


def setup(root, *, conditions=True):
    initialize_workspace(root, 'review', 'research')
    state.admit_workspace(root, {'authority': 'host'})
    change(root, [
        {'type': 'create_claim', 'id': 'claim_review', 'statement': 'Review execution'},
        {'type': 'create_node', 'id': 'node_calc', 'title': 'Calculate', 'objective': 'Produce evidence', 'claim_ids': ['claim_review']},
        {'type': 'set_focus', 'claim_ids': ['claim_review'], 'node_ids': ['node_calc']},
        {'type': 'create_strategy_plan', 'id': 'strategy_review', 'claim_id': 'claim_review', 'node_id': 'node_calc', 'objective': 'Review', 'rationale': 'Need evidence'},
        *([gate()] if conditions else []),
    ])
    return {'root': str(root), 'job_id': 'job_review', 'request_id': 'review',
            'node_id': 'node_calc', 'command': [sys.executable, '-c', 'pass'], 'platform': 'local'}


def prepare(root, params):
    with TransactionCoordinator(root).locked():
        return execution._prepare_start(root, SimpleNamespace(default='local'), params, prepared_params=params)


def test_simple_node_can_prepare_without_a_gate_or_exemption(tmp_path):
    params = setup(tmp_path, conditions=False)
    assert prepare(tmp_path, params)[0].attempt_id
    assert len(state.read_context(tmp_path)['attempts']) == 1


@pytest.mark.parametrize('stage', ['spec', 'intent'])
def test_pre_dispatch_error_cleans_staging_and_allows_same_request(tmp_path, monkeypatch, stage):
    params = setup(tmp_path)
    name = '_spec' if stage == 'spec' else '_commit_dispatch'
    original = getattr(execution, name)
    def fail(*args, **kwargs):
        if stage == 'spec': original(*args, **kwargs)
        raise ValueError('injected before dispatch')
    monkeypatch.setattr(execution, name, fail)
    with pytest.raises(ValueError, match='injected'):
        prepare(tmp_path, params)
    assert not (tmp_path / 'runs/jobs/job_review').exists()
    assert not state.read_context(tmp_path)['attempts']
    monkeypatch.setattr(execution, name, original)
    assert prepare(tmp_path, params)[0].attempt_id


def test_interrupted_staging_has_owned_recovery_but_foreign_directory_is_preserved(tmp_path, monkeypatch):
    params = setup(tmp_path)
    original = execution._spec
    class Crash(BaseException): pass
    def fail(*args):
        original(*args)
        raise Crash()
    monkeypatch.setattr(execution, '_spec', fail)
    with pytest.raises(Crash): prepare(tmp_path, params)
    assert (tmp_path / 'operations/staging/job_review.json').exists()
    monkeypatch.setattr(execution, '_spec', original)
    assert prepare(tmp_path, params)[0].attempt_id
    foreign = tmp_path / 'runs/jobs/job_foreign'; foreign.mkdir()
    (foreign / 'keep').write_text('unproven execution')
    with pytest.raises(ValueError, match='orphan_job_directory'):
        prepare(tmp_path, {**params, 'job_id': 'job_foreign', 'request_id': 'foreign', 'work_id': 'foreign'})
    assert (foreign / 'keep').read_text() == 'unproven execution'


@pytest.mark.parametrize('boundary', ['prepared', 'committed'])
def test_durable_intent_failure_is_reconciled_without_restaging(tmp_path, monkeypatch, boundary):
    params = setup(tmp_path)
    if boundary == 'prepared':
        original = TransactionCoordinator.commit
        def fail(self, request_id):
            if request_id == 'review:intent': raise OSError('crash after journal prepare')
            return original(self, request_id)
        monkeypatch.setattr(TransactionCoordinator, 'commit', fail)
    else:
        original = execution._commit_dispatch
        def fail(*args):
            original(*args)
            raise OSError('crash after intent commit')
        monkeypatch.setattr(execution, '_commit_dispatch', fail)
    with pytest.raises(OSError): prepare(tmp_path, params)
    assert (tmp_path / 'runs/jobs/job_review/input_manifest.json').exists()
    monkeypatch.undo()
    recovered = prepare(tmp_path, params)
    assert recovered['state'] == 'unknown'
    assert len(state.read_context(tmp_path)['attempts']) == 1


def test_concurrent_dispatch_starts_once_and_reuses_receipt(tmp_path):
    params = setup(tmp_path)
    params['command'] = [sys.executable, '-c', "from pathlib import Path; p=Path('started');p.write_text(p.read_text()+'x' if p.exists() else 'x')"]
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: execution.dispatch('start', params), range(2)))
        assert len({r['job_id'] for r in results}) == 1
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = execution.dispatch('status', {'root': str(tmp_path), 'job_id': 'job_review'})
            if status['state'] == 'succeeded': break
            time.sleep(.02)
        assert status['state'] == 'succeeded'
        assert (tmp_path / 'runs/jobs/job_review/started').read_text() == 'x'
        assert execution.dispatch('start', params)['job_id'] == 'job_review'
        assert len(state.read_context(tmp_path)['attempts']) == 1
    finally:
        if (tmp_path / 'runs/jobs/job_review/receipt.json').exists():
            execution.dispatch('cancel', {'root': str(tmp_path), 'job_id': 'job_review'})


def test_atomic_closure_points_to_delivery_and_valid_prefix_succeeds(tmp_path):
    setup(tmp_path)
    change(tmp_path, [{'type': 'create_node', 'id': 'node_email', 'title': 'Delivery', 'objective': 'Deliver report',
                       'claim_ids': ['claim_review'], "dependencies": [{"node_id": 'node_calc', "condition": "completed"}]}, gate('node_email')])
    before = (tmp_path / 'research_map/context.json').read_bytes()
    with pytest.raises(state.AgentWorkspaceError) as error:
        change(tmp_path, [evaluate(), close(), close('node_email')])
    assert 'NodeGate' in str(error.value)
    assert error.value.details['operation_index'] == 2
    assert error.value.details['target_id'] == 'node_email'
    assert error.value.details['atomic_batch_committed'] is False
    assert (tmp_path / 'research_map/context.json').read_bytes() == before
    change(tmp_path, [evaluate(), close()])
    change(tmp_path, [evaluate('node_email'), close('node_email')])
    checkpoint = state.checkpoint(tmp_path, {'principal': 'root_agent', 'authority': 'kernel_write', "checkpoint": {'id': 'checkpoint_review', 'disposition': 'terminal', 'node_ids': ['node_calc', 'node_email'], 'claim_ids': ['claim_review'], "reason": 'All scoped work is settled'}})
    assert checkpoint['accepted']


def test_receipt_commit_failure_after_start_is_unknown_and_retry_reuses_job(tmp_path, monkeypatch):
    params = setup(tmp_path)
    original = TransactionCoordinator.commit_files
    def fail(self, request_id, operation, *args, **kwargs):
        if operation == 'job.receipt': raise OSError('receipt disk unavailable')
        return original(self, request_id, operation, *args, **kwargs)
    monkeypatch.setattr(TransactionCoordinator, 'commit_files', fail)
    try:
        with pytest.raises(execution.JobSubmissionError) as error:
            execution.dispatch('start', params)
        assert error.value.code == 'submission_ambiguous'
        assert error.value.details['action_outcome'] == 'unknown'
        monkeypatch.setattr(TransactionCoordinator, 'commit_files', original)
        result = execution.dispatch('start', params)
        assert result['job_id'] == 'job_review' and result['pid']
        assert len(state.read_context(tmp_path)['attempts']) == 1
    finally:
        if (tmp_path / 'runs/jobs/job_review/receipt.json').exists():
            execution.dispatch('cancel', {'root': str(tmp_path), 'job_id': 'job_review'})


def test_contract_queries_and_precise_assessment_errors(tmp_path):
    setup(tmp_path)
    catalog = execute('research.operations', tmp_path, {'query': 'evaluate_gate'})
    assert [x['type'] for x in catalog['operations']] == ['evaluate_gate']
    assert 'criterion_id' in catalog['operations'][0]['nested_schema']['assessments']['required']
    assert [x['type'] for x in execute('research.operations', tmp_path, {'query': 'completion_exemption'})['operations']] == []
    wrong = evaluate(); wrong['assessments'][0]['status'] = wrong['assessments'][0].pop('verdict')
    with pytest.raises(state.AgentWorkspaceError, match=r'operation_contract_invalid: evaluate_gate.assessments.0:.*status'):
        change(tmp_path, [wrong])


def test_final_batch_cannot_attach_an_unpassed_gate_after_closing_node(tmp_path):
    setup(tmp_path)
    before = state.read_context(tmp_path)
    extra = {**gate(), 'id': 'gate_added_after_close'}
    with pytest.raises(state.AgentWorkspaceError) as error:
        change(tmp_path, [evaluate(), close(), extra])
    assert error.value.code == 'research_invariant_violation'
    assert error.value.details['phase'] == 'final_validation'
    assert any(issue['code'] == 'completed_gate_not_current' for issue in error.value.details['issues'])
    assert state.read_context(tmp_path) == before
