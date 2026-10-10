import json
import sys

import pytest

from research_agent.application.api import execute
from research_agent.application.execution import dispatch
from research_agent.application.job_monitor import command
from tests.unit.test_job_recovery import workspace


def test_task_ownership_survives_job_submission_and_read_only_pagination(tmp_path):
    workspace(tmp_path)
    for suffix, task in [('a', 'task_first'), ('b', 'task_second')]:
        dispatch('start', {'root': str(tmp_path), 'job_id': 'job_' + suffix,
                          'session_id': 'session_owner', 'user_task_id': task,
                          'command': [sys.executable, '-c', 'pass # ' + suffix]})
    before = {p: p.read_bytes() for p in (tmp_path / 'operations').rglob('*.json')}
    first = execute('job.list', tmp_path, {'session_id': 'session_owner', 'limit': 1})
    assert first['jobs'][0]['user_task_id'] == 'task_first'
    assert first['next_cursor'] == 'job_a'
    second = execute('job.list', tmp_path, {'session_id': 'session_owner', 'cursor': first['next_cursor']})
    assert [row['job_id'] for row in second['jobs']] == ['job_b']
    assert second['next_cursor'] is None
    selected = execute('job.list', tmp_path, {'user_task_id': 'task_first'})
    assert [row['job_id'] for row in selected['jobs']] == ['job_a']
    assert execute('job.list', tmp_path, {'session_id': 'session_other'})['jobs'] == []
    assert {p: p.read_bytes() for p in before} == before
    bindings = command(tmp_path, 'list', {})['monitors']
    assert {row['job_id']: row['user_task_id'] for row in bindings} == {
        'job_a': 'task_first', 'job_b': 'task_second'}


def test_submission_identity_cannot_be_rebound_to_another_task(tmp_path):
    workspace(tmp_path)
    params = {'root': str(tmp_path), 'job_id': 'job_bound', 'session_id': 'session_owner',
              'user_task_id': 'task_first', 'command': [sys.executable, '-c', 'pass']}
    dispatch('start', params)
    with pytest.raises(ValueError, match='different parameters'):
        dispatch('start', {**params, 'user_task_id': 'task_second'})
    intent = json.loads((tmp_path / 'operations/jobs/job_bound.json').read_text())
    assert intent['user_task_id'] == 'task_first'


def test_task_ownership_is_not_a_model_supplied_metadata_field(tmp_path):
    workspace(tmp_path)
    with pytest.raises(ValueError, match='runtime_only'):
        dispatch('start', {'root': str(tmp_path), 'job_id': 'job_forged',
                          'command': [sys.executable, '-c', 'pass'],
                          'metadata': {'user_task_id': 'task_forged'}})
