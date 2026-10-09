"""Handwritten contract cases independently exercise generated boundaries."""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from research_agent.application.api import COMMAND_DEFINITIONS, CommandError, validate_command_params

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('command,params', [
    ('research.create', {'goal': 'Investigate the reaction', 'session_id': 'session-fixture'}),
    ('research.observe', {'read_basis': 'read_' + 'a' * 64, 'session_id': 'session-fixture'}),
    ('research.update', {'node_id': 'node_' + 'a' * 32, 'note': 'Observation', 'assessment_ref': None}),
    ('job.start', {'command': ['/bin/true'], 'environment': {'OMP_NUM_THREADS': '2'}}),
    ('artifact.read', {'artifact_ref': 'a1', 'offset': 0, 'limit': 4096}),
])
def test_application_contract_accepts_transport_values(command, params):
    validate_command_params(command, params)


@pytest.mark.parametrize('command,params', [
    ('research.create', {'goal': 'Investigate', 'unknown': True}),
    ('research.update', {'node_id': 'node_' + 'a' * 32}),
    ('research.search', {'origin': 'untrusted-origin'}),
    ('job.start', {'command': ['/bin/true'], 'environment': {'OMP_NUM_THREADS': 2}}),
    ('artifact.read', {'artifact_ref': 'a1', 'limit': '4096'}),
])
def test_application_contract_rejects_malformed_parameters(command, params):
    with pytest.raises(CommandError):
        validate_command_params(command, params)


def test_transport_context_is_not_a_public_command_parameter():
    params = {'goal': 'Investigate', 'workspace_root': '/fixture/workspace'}
    with pytest.raises(CommandError, match='unsupported fields'):
        validate_command_params('research.create', params)
    validate_command_params('research.create', params, transport_fields=('workspace_root',))


def test_model_schemas_do_not_accept_application_identity_fields():
    shared = json.loads((ROOT / 'contracts/commands/shared.json').read_text())['tools']
    for key, schema in shared.items():
        assert not {'session_id', 'workspace_id', 'principal', 'read_basis', 'producer_token'} & schema['properties'].keys(), key
    schema = shared['create']
    validator = Draft202012Validator(schema)
    assert not list(validator.iter_errors({'goal': 'Investigate'}))
    assert list(validator.iter_errors({'goal': 'Investigate', 'session_id': 'forged'}))


def test_generated_catalogs_and_examples_agree():
    node = json.loads((ROOT / 'apps/agent/tools/command-catalog.json').read_text())
    assert {row['id']: row for row in node['commands']} == COMMAND_DEFINITIONS
    fixtures = json.loads((ROOT / 'contracts/generated/command-fixtures.json').read_text())
    assert {case['command'] for case in fixtures['cases']} == set(COMMAND_DEFINITIONS)
    for case in fixtures['cases']:
        validate_command_params(case['command'], case['params'])


def test_model_tool_constraints_survive_generation():
    schema = json.loads((ROOT / 'contracts/commands/shared.json').read_text())['tools']['jobStart']
    validator = Draft202012Validator(schema)
    valid = {'node_id': 'node_' + 'a' * 32, 'request_file': 'reviewed.json', 'request_sha256': 'a' * 64}
    assert not list(validator.iter_errors(valid))
    assert list(validator.iter_errors({'node_id': valid['node_id'], 'request_file': 'reviewed.json'}))
    assert list(validator.iter_errors({**valid, 'repeat': {'predecessor_job_id': 'job_previous'}}))
