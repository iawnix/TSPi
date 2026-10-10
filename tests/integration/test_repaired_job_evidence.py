"""A repaired attempt, old failures and authored conclusions retain separate provenance."""
import sys
import time
from types import SimpleNamespace

import pytest

from research_agent.application.api import execute
from research_agent.application.job_state import execution, observe_execution, project_events
from research_agent.foundation.transactions import read_json
from research_agent.research import doctor, nodes, relations, results, views
from research_agent.research.workspace import initialize_workspace, admit_research_workspace
from tests.unit.test_job_recovery import wait_reaped


@pytest.fixture
def research_workspace(tmp_path, monkeypatch):
    initialize_workspace(tmp_path, 'repaired_evidence', 'research')
    admit_research_workspace(tmp_path)
    config = tmp_path / 'job.toml'
    config.write_text('default_environment="local"\n[environments.local]\nkind="local"\nsupervisor="process"\n')
    monkeypatch.setenv('CORAGENT_JOB_CONFIG', str(config))
    return tmp_path


def run_attempt(root, request):
    receipt = execute('job.start', root, request)
    terminal = {'succeeded', 'failed', 'timed_out', 'cancelled'}
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = execute('job.status', root, {'job_id': receipt['job_id']})
            if status['state'] in terminal:
                break
            time.sleep(.02)
        else:
            pytest.fail('Local deterministic attempt did not finish')
        collected = execute('job.collect', root, {'job_id': receipt['job_id']})
        return receipt, collected
    finally:
        status = execute('job.status', root, {'job_id': receipt['job_id']})
        if status['state'] not in terminal:
            execute('job.cancel', root, {'job_id': receipt['job_id']})
        wait_reaped(SimpleNamespace(**receipt))


def test_repaired_job_dedup_and_late_failure_cannot_replace_selected_evidence(research_workspace):
    root = research_workspace
    created = execute('research.create', root, {'goal': 'Evaluate the repaired geometry', 'plan': 'Run, inspect outputs, then interpret.'})
    node_id = created['node']['id']
    source = root / 'geometry.txt'
    source.write_text('invalid geometry')
    program = ("from pathlib import Path; import sys; value=Path('geometry.txt').read_text(); "
               "print(value); "
               "sys.exit(23) if value != 'repaired geometry' else Path('energy.txt').write_text('-40.125 hartree\\n')")
    request = {'node_id': node_id, 'session_id': 'research-session',
               'command': [sys.executable, '-c', program],
               'inputs': [{'source': str(source), 'destination': 'geometry.txt'}],
               'outputs': [{'path': 'energy.txt', 'required': True, 'min_bytes': 1}]}
    failed, failure = run_attempt(root, {**request, 'job_id': 'job_failed_attempt', 'request_id': 'failed-attempt'})
    assert failure['status']['state'] == 'failed'
    failed_receipt = failure['result_receipt']['receipt_id']
    initial = execute('research.result', root, {'node_id': node_id, 'conclusion': 'This input failed before an energy was available; the pathway is unresolved.',
        'evidence_refs': [failed['job_id'], failed_receipt], 'as_assessment': True, 'read_basis': created['read_basis']})
    old = initial['result']

    source.write_text('repaired geometry')
    repaired, success = run_attempt(root, {**request, 'job_id': 'job_repaired_attempt', 'request_id': 'repaired-attempt'})
    repaired_receipt = success['result_receipt']['receipt_id']
    assert success['status']['state'] == 'succeeded'
    assert success['output_validation']['complete']
    assert success['result_receipt']['validator_result'] is None
    assert repaired_receipt != failed_receipt
    assert execution(root, failed['job_id'])['state'] == 'failed'
    assert execution(root, repaired['job_id'])['state'] == 'succeeded'
    assert nodes.get_node(root, node_id)['assessment_ref'] == old['id'], 'Execution success does not select a scientific conclusion'
    assert nodes.get_node(root, node_id)['status'] == 'open'
    intents = [read_json(root / 'operations/jobs' / (job['job_id'] + '.json')) for job in (failed, repaired)]
    assert intents[0]['execution_fingerprint'] != intents[1]['execution_fingerprint']
    assert all(intent['node_id'] == node_id for intent in intents)

    duplicate = execute('job.start', root, {**request, 'job_id': 'job_duplicate_attempt', 'request_id': 'duplicate-attempt'})
    assert duplicate['accepted'] is False and duplicate['code'] == 'duplicate_execution'
    assert duplicate['job_id'] == repaired['job_id'], 'Duplicate points to the successful repaired input, never the earlier failure'
    assert not (root / 'operations/jobs/job_duplicate_attempt.json').exists()
    assert execute('job.collect', root, {'job_id': duplicate['job_id']})['result_receipt']['receipt_id'] == repaired_receipt

    corrected = execute('research.result', root, {'node_id': node_id,
        'observation': 'The repaired attempt exited zero and produced an energy of -40.125 hartree.',
        'conclusion': 'The repaired geometry produced the requested energy; reaction connectivity remains unverified.',
        'limitations': 'No transition-state or connectivity validation was performed.',
        'evidence_refs': [repaired['job_id'], repaired_receipt], 'supersedes': old['id'],
        'as_assessment': True, 'progress': 'Energy obtained; connectivity analysis remains.', 'read_basis': initial['read_basis']})
    assert corrected['assessment_selected']
    stable_node = nodes.get_node(root, node_id)
    observe_execution(root, SimpleNamespace(job_id=failed['job_id']),
                      {'state': 'failed', 'exit_code': 23, 'error': 'Delayed diagnostic from the original invalid input'})
    assert project_events(root) == []
    assert nodes.get_node(root, node_id) == stable_node
    assert execution(root, repaired['job_id'])['state'] == 'succeeded'
    assert results.get_result(root, old['id']) == old
    snapshot = execute('research.read', root, {'focus_node_ids': [node_id]})
    assert snapshot['nodes'][0]['assessment_ref'] == corrected['result']['id']
    assert snapshot['nodes'][0]['status'] == 'open'
    assert any(notice['code'] == 'result_superseded' for notice in execute('research.read', root, {'ref': old['id']})['review_notices'])

    stale = execute('research.result', root, {'node_id': node_id,
        'conclusion': 'An earlier draft describes only the first failure.', 'evidence_refs': [failed_receipt],
        'as_assessment': True, 'read_basis': initial['read_basis']})
    assert stale['result_saved'] and not stale['assessment_selected']
    assert 'revision_conflict' in stale['conflict']
    assert nodes.get_node(root, node_id)['assessment_ref'] == corrected['result']['id']
    assert results.get_result(root, corrected['result']['id'])['evidence_refs'] == [repaired['job_id'], repaired_receipt]
    conflict = observe_execution(root, SimpleNamespace(job_id=repaired['job_id']), {'state': 'failed', 'exit_code': 23})
    assert conflict == {'code': 'job_terminal_conflict', 'confirmed_state': 'succeeded', 'observed_state': 'failed', 'recovery': 'job_reconcile'}
    assert execution(root, repaired['job_id'])['state'] == 'succeeded'
    assert execution(root, repaired['job_id'])['execution_conflict'] == conflict
    assert execute('job.reconcile', root, {'job_id': repaired['job_id']})['state'] == 'succeeded'
    assert execution(root, repaired['job_id'])['execution_conflict'] is None
    assert nodes.get_node(root, node_id)['assessment_ref'] == corrected['result']['id']


def test_recent_results_follow_publication_sequence_not_uuid_or_clock(research_workspace, monkeypatch):
    root = research_workspace
    initial = execute('research.create', root, {'goal': 'Correct an earlier failed interpretation'})
    node_id = initial['node']['id']
    identities = iter(['f' * 32, 'e' * 32, '0' * 32])
    monkeypatch.setattr(results, 'uuid', SimpleNamespace(uuid4=lambda: SimpleNamespace(hex=next(identities))))
    monkeypatch.setattr(results, 'now', lambda: '2026-10-10T00:00:00+00:00')
    published = []
    for conclusion in ('Old failure', 'Second inconclusive attempt', 'Corrected positive observation'):
        published.append(execute('research.result', root, {'node_id': node_id, 'conclusion': conclusion})['result'])
    assert list(relations.graph(root)['results']) == sorted(item['id'] for item in published)
    snapshot = execute('research.read', root, {'focus_node_ids': [node_id]})
    assert [item['id'] for item in snapshot['nodes'][0]['recent_results']] == [item['id'] for item in published[-2:]]
    detail = execute('research.read', root, {'ref': node_id})
    assert [item['id'] for item in detail['results']] == [item['id'] for item in published]
    assert detail['node']['assessment_ref'] is None, 'Recency never selects an assessment'
    markdown = views.documents(root)[f'research/nodes/{node_id}/README.md']
    assert markdown.index('Old failure') < markdown.index('Second inconclusive attempt') < markdown.index('Corrected positive observation')
    doctor.rebuild(root)
    rebuilt = execute('research.read', root, {'focus_node_ids': [node_id]})
    assert [item['id'] for item in rebuilt['nodes'][0]['recent_results']] == [item['id'] for item in published[-2:]]
