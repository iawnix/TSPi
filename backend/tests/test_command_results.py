"""Validate actual JSON transport replies; production does not validate responses."""
import json
import sys
import time

import pytest
from jsonschema import Draft202012Validator

from research_agent.application.api import COMMAND_DEFINITIONS, execute
from research_agent.application import job_monitor
from research_agent.research.workspace import initialize_workspace, admit_research_workspace


@pytest.fixture
def command_workspace(tmp_path, monkeypatch):
    root = tmp_path / 'workspace'
    root.mkdir()
    initialize_workspace(root, 'ws_command_results', 'research')
    admit_research_workspace(root)
    config = tmp_path / 'job.toml'
    config.write_text('default_environment = "local"\n[environments.local]\nkind = "local"\nsupervisor = "process"\n')
    monkeypatch.setenv('CORAGENT_JOB_CONFIG', str(config))
    return root


def checked(command, value):
    # The bridge serializes tuples and StrEnum values to JSON before Node sees them.
    value = json.loads(json.dumps(value))
    errors = list(Draft202012Validator(COMMAND_DEFINITIONS[command]['result']).iter_errors(value))
    assert not errors, [(list(error.absolute_path), error.validator) for error in errors]
    return value


def test_all_command_results_match_actual_api_replies(command_workspace):
    root = command_workspace
    covered = set()

    def call(command_id, **params):
        value = checked(command_id, execute(command_id, root, params))
        covered.add(command_id)
        return value

    source = call('research.source', session_id='fixture', message_id='question', text='Investigate a local result')
    created = call('research.create', goal='Investigate', session_id='fixture', source_refs=[source['source_ref']])
    node = created['node']['id']
    call('research.observe', session_id='fixture', read_basis=created['read_basis'])
    call('research.update', node_id=node, note='Progress recorded', session_id='fixture',
         progress='Prepared local test', read_basis=created['read_basis'])
    call('research.result', node_id=node, conclusion='Observed a deterministic result', session_id='fixture')
    call('research.search', query='Investigate')
    call('research.read', session_id='fixture')
    call('research.read', ref=node, session_id='fixture')
    call('research.read', ref=node, field='goal', session_id='fixture')
    call('research.read', ref=node, limit=10, session_id='fixture')
    material = call('artifact.create', name='fixture.txt', content='fixture evidence')
    call('artifact.read', artifact_ref=material['artifact_ref'])
    (root / 'input.txt').write_text('local fixture')
    call('artifact.register', path='input.txt')
    request = {'request_id': 'fixture-preparation', 'command': [sys.executable, '-c', 'pass'],
               'inputs': [{'source': 'input.txt', 'destination': 'input.txt'}]}
    (root / 'prepared.json').write_text(json.dumps(request))
    prepared = call('job.prepare', request_file='prepared.json')
    call('job.resolve_prepared', prepared_ref=prepared['prepared_ref'])
    call('job.probe', job_id='job_probe_contract', command=[sys.executable, '-c', 'pass'])
    job = call('job.start', job_id='job_contract', node_id=node, session_id='fixture',
               command=[sys.executable, '-c', "print('local contract fixture')"])
    try:
        deadline = time.monotonic() + 10
        while True:
            status = call('job.status', job_id=job['job_id'])
            if status['state'] in {'succeeded', 'failed', 'timed_out', 'cancelled'}:
                break
            assert time.monotonic() < deadline, 'local fixture did not finish'
            time.sleep(.02)
        call('job.reconcile', job_id=job['job_id'])
        call('job.cancel', job_id=job['job_id'])
        call('job.collect', job_id=job['job_id'])
        jobs = call('job.list', session_id='fixture', limit=1)
        assert jobs['jobs'][0]['job_id'] == job['job_id']
        job_monitor.command(root, 'tick', {})
        event = job_monitor.command(root, 'pending', {})['deliveries'][0]['event_id']
        call('job.monitor_assess', event_id=event, session_id='fixture')
    finally:
        execute('job.cancel', root, {'job_id': job['job_id']})
    assert covered == set(COMMAND_DEFINITIONS)


def test_read_result_discriminant_and_required_fields(command_workspace):
    root = command_workspace
    snapshot = execute('research.read', root)
    validator = Draft202012Validator(COMMAND_DEFINITIONS['research.read']['result'])
    assert validator.is_valid(snapshot)
    assert not validator.is_valid({**snapshot, 'sequence': 'invalid'})
    assert not validator.is_valid({**snapshot, 'schema_version': 'research-read/2'})
    mutation = execute('research.create', root, {'goal': 'Contract mutation'})
    validator = Draft202012Validator(COMMAND_DEFINITIONS['research.create']['result'])
    assert not validator.is_valid({key: value for key, value in mutation.items() if key != 'node'})
    assert not validator.is_valid({**mutation, 'node': {**mutation['node'], 'revision': 'invalid'}})


def test_result_schemas_cover_non_success_variants():
    checked('job.start', {'job_id': 'job_fixture', 'state': 'unknown', 'error': 'dispatch uncertain'})
    checked('job.start', {'job_id': 'job_fixture', 'accepted': False, 'code': 'duplicate_execution',
                          'execution_fingerprint': 'fixture-digest', 'recovery': 'Reuse existing job'})
    checked('job.status', {'job_id': 'job_fixture', 'platform': 'local', 'state': 'unknown', 'error': 'No receipt'})
    checked('job.probe', {'platform': 'unconfigured', 'available': False, 'reason': 'No adapter'})
    checked('job.probe', {'platform': 'remote', 'available': False, 'ssh_host': 'fixture.invalid',
                          'scheduler': 'torque', 'remote_root': '/fixture', 'cwd_exists': True,
                          'inputs_present': True, 'missing_inputs': [], 'error': 'Unreachable'})


def test_result_catalog_is_complete_and_schemas_are_well_formed():
    assert len(COMMAND_DEFINITIONS) == 20
    for definition in COMMAND_DEFINITIONS.values():
        Draft202012Validator.check_schema(definition['result'])
