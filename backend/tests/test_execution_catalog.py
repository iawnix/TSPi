"""Execution resource identity is independent of Pi's Skill discovery."""
import hashlib
import json

import pytest

from research_agent.application.execution_catalog import installed_catalogs
from research_agent.application import executors


def _package(root):
    domain = root / 'domains' / 'science'
    domain.mkdir(parents=True)
    script = domain / 'run.py'
    script.write_text('print("science")\n')
    descriptor = {
        'id': 'science.example', 'version': '1', 'backend': 'science',
        'runtime': 'python', 'entry': 'run.py', 'argv': ['{entry}', '{input:data}', '{args}'],
        'inputs': {'data': 'data.json'}, 'outputs': [],
        'resources': {'run.py': 'sha256:' + hashlib.sha256(script.read_bytes()).hexdigest()},
    }
    catalog = {'schema_version': 'research-agent-execution/1', 'name': 'science', 'version': '0.18.0',
               'executors': [descriptor], 'validators': [], 'acceptance_profiles': []}
    path = domain / 'execution.json'
    path.write_text(json.dumps(catalog))
    (root / 'package.json').write_text(json.dumps({'researchAgent': {'execution': ['domains/science/execution.json']}}))
    return path, catalog


def test_executor_works_without_a_skill_or_node(tmp_path, monkeypatch):
    _, expected = _package(tmp_path)
    monkeypatch.setenv('RESEARCH_AGENT_PACKAGE_ROOT', str(tmp_path))
    monkeypatch.setenv('PATH', '')
    base, descriptor = executors.registered_executor('science.example', '1')
    assert base == tmp_path / 'domains/science'
    assert descriptor == expected['executors'][0]
    assert not (base / 'skills').exists()


def test_resource_edits_are_rejected_after_previous_load(tmp_path):
    path, _ = _package(tmp_path)
    installed_catalogs(tmp_path)
    (path.parent / 'run.py').write_text('print("different computation")\n')
    with pytest.raises(ValueError, match='execution_resource_changed'):
        installed_catalogs(tmp_path)


def test_skill_text_edits_do_not_change_execution_identity(tmp_path):
    path, _ = _package(tmp_path)
    before = installed_catalogs(tmp_path)
    (path.parent / 'SKILL.md').write_text('Revised scientific guidance.')
    assert installed_catalogs(tmp_path) == before


def test_symlink_resource_rejected_even_when_digest_matches(tmp_path):
    path, _ = _package(tmp_path)
    script = path.parent / 'run.py'
    source = path.parent / 'real.py'
    script.rename(source)
    script.symlink_to(source)
    with pytest.raises(ValueError, match='execution_resource_symlink'):
        installed_catalogs(tmp_path)


def test_executor_entry_must_belong_to_its_own_resources(tmp_path):
    path, catalog = _package(tmp_path)
    catalog['executors'][0]['resources'] = {}
    path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError, match='executor_entry_resource_required'):
        installed_catalogs(tmp_path)


def test_input_cannot_overwrite_executable(tmp_path):
    path, catalog = _package(tmp_path)
    catalog['executors'][0]['inputs']['data'] = 'run.py'
    path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError, match='execution_destinations_overlap_or_reserved'):
        installed_catalogs(tmp_path)


def test_duplicate_registered_identity_is_rejected(tmp_path):
    path, catalog = _package(tmp_path)
    catalog['executors'].append(catalog['executors'][0])
    path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError, match='execution_catalog_identity_duplicate'):
        installed_catalogs(tmp_path)


def test_catalog_resource_cannot_escape_domain(tmp_path):
    path, catalog = _package(tmp_path)
    catalog['executors'][0]['resources']['../secret.py'] = 'sha256:' + 'a' * 64
    path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError, match='execution_resource_path_invalid'):
        installed_catalogs(tmp_path)


def test_native_executor_cannot_require_python_packages(tmp_path):
    path, catalog = _package(tmp_path)
    entry = catalog['executors'][0]
    entry.update(runtime='native', argv=['{command}'], requirements={'packages': {'numpy': '>=1'}})
    del entry['entry']
    path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError, match='native_execution_cannot_require_python'):
        installed_catalogs(tmp_path)


def test_validator_input_roles_are_unique(tmp_path):
    path, catalog = _package(tmp_path)
    digest = catalog['executors'][0]['resources']['run.py']
    catalog['validators'] = [{'id': 'science.check', 'version': '1', 'backend': 'science',
        'entry': 'run.py', 'sha256': digest, 'input_contract': {'schema_version': 'validator-input/1',
        'roles': [{'name': 'result', 'source': 'collected_output'}, {'name': 'result', 'source': 'registered_artifact'}]}}]
    path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError, match='validator_input_role_duplicate'):
        installed_catalogs(tmp_path)
