"""Subjects, corrections and report freshness without scientific truth gates."""
import json
import pytest
from jsonschema import Draft202012Validator
from research_agent.application.api import execute as execute_api, COMMAND_DEFINITIONS
from research_agent.research import results, nodes, relations, views
from tests.unit.test_job_recovery import workspace


def execute(command, root, params):
    value = execute_api(command, root, params)
    Draft202012Validator(COMMAND_DEFINITIONS[command]['result']).validate(json.loads(json.dumps(value)))
    return value


def material(root, name):
    return execute('artifact.create', root, {'name': name, 'content': name})['artifact_ref']


def test_subjects_and_uncertain_checks_survive_publication_and_read(tmp_path):
    workspace(tmp_path)
    target, actual, check = [material(tmp_path, name) for name in ['target', 'actual', 'inconclusive']]
    node = execute('research.create', tmp_path, {'goal': 'Compare identities', 'subjects': {'target': target}})
    saved = execute('research.result', tmp_path, {'node_id': node['node']['id'],
        'subjects': {'target': target, 'calculated': actual}, 'check_refs': [check],
        'observation': 'A structure comparison was inconclusive', 'conclusion': 'The identity remains unresolved'})
    assert saved['result']['subjects']['calculated'] == actual
    assert saved['result']['checks'] == [{'ref': check, 'kind': 'artifact', 'validation': None}]
    assert saved['result_saved'] and not saved['assessment_selected']
    read = execute('research.read', tmp_path, {'ref': saved['result']['id']})
    assert read['result'] == saved['result'] and read['review_notices'] == []
    with pytest.raises(ValueError, match='subjects_require_fixed'):
        execute('research.result', tmp_path, {'node_id': node['node']['id'], 'conclusion': 'No', 'subjects': {'target': node['node']['id']}})


def test_atomic_correction_stale_read_does_not_publish_or_change_progress(tmp_path):
    workspace(tmp_path)
    initial = execute('research.create', tmp_path, {'goal': 'Study'})
    node_id = initial['node']['id']
    old = execute('research.result', tmp_path, {'node_id': node_id, 'conclusion': 'Initial'})['result']
    latest = execute('research.update', tmp_path, {'node_id': node_id, 'note': 'New evidence',
        'progress': 'New observation', 'read_basis': initial['read_basis']})
    request = {'node_id': node_id, 'conclusion': 'Correction', 'supersedes': old['id'], 'as_assessment': True,
               'progress': 'Identity unresolved', 'read_basis': initial['read_basis']}
    with pytest.raises(ValueError, match='revision_conflict'):
        execute('research.result', tmp_path, request)
    assert len(relations.graph(tmp_path)['results']) == 1
    assert nodes.get_node(tmp_path, node_id)['progress'] == 'New observation'
    saved = execute('research.result', tmp_path, {**request, 'read_basis': latest['read_basis']})
    assert saved['assessment_selected'] and saved['node']['progress'] == 'Identity unresolved'
    assert results.get_result(tmp_path, old['id']) == old
    assert execute('research.read', tmp_path, {'ref': saved['result']['id']})['review_notices'] == []
    assert execute('research.read', tmp_path, {'ref': old['id']})['review_notice_count'] > 0
    execute('research.update', tmp_path, {'node_id': node_id, 'note': 'Just a note'})
    assert execute('research.read', tmp_path, {'ref': saved['result']['id']})['review_notices'] == []
    execute('research.update', tmp_path, {'node_id': node_id, 'note': 'Revise goal', 'goal': 'Different target',
                                        'read_basis': saved['read_basis']})
    read = execute('research.read', tmp_path, {'ref': saved['result']['id']})
    assert any(n['code'] == 'node_context_changed' for n in read['review_notices'])
    assert read['result'] == saved['result']
    snapshot = execute('research.read', tmp_path, {})
    assert snapshot['nodes'][0]['review_notice_count'] > 0
    assert 'needs review' in views.documents(tmp_path)[f'research/nodes/{node_id}/README.md']


def test_report_citing_corrected_result_requests_review_without_rewriting(tmp_path):
    workspace(tmp_path)
    source = execute('research.create', tmp_path, {'goal': 'Source'})['node']['id']
    one = execute('research.result', tmp_path, {'node_id': source, 'conclusion': 'Preliminary'})['result']
    report_node = execute('research.create', tmp_path, {'goal': 'Report'})['node']['id']
    report = execute('research.result', tmp_path, {'node_id': report_node, 'conclusion': 'Report', 'inputs': [one['id']]})['result']
    two = execute('research.result', tmp_path, {'node_id': source, 'conclusion': 'Corrected', 'supersedes': one['id']})['result']
    read = execute('research.read', tmp_path, {'ref': report['id']})
    assert {'code': 'cited_result_superseded', 'used': one['id'], 'superseded_by': two['id']} in read['review_notices']
    assert results.get_result(tmp_path, report['id']) == report
