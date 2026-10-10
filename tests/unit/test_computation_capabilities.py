"""Real local probe/CLI/Job regressions; software readiness is not chemistry."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

import pytest

from research_agent.application.api import execute
from research_agent.application.executors import prepare
from research_agent.jobs.config_contract import load_job_config
from tests.unit.test_declarative_executors import binding, catalog
from tests.unit.test_job_recovery import workspace

def run_cli(*args):
    completed = subprocess.run([sys.executable, '-m', 'research_agent.application.environment_check', *args],
                               capture_output=True, text=True, timeout=30)
    assert 'Traceback' not in completed.stderr
    return completed.returncode, json.loads(completed.stdout)


def native_fixture(tmp_path, monkeypatch):
    catalog(tmp_path / 'catalog', monkeypatch)
    marker = tmp_path / 'program-started'
    program = tmp_path / 'fixture-program'
    program.write_text('#!/bin/sh\nprintf invoked > ' + shlex.quote(str(marker)) + '\nexec /bin/sh "$@"\n')
    program.chmod(0o700)
    config = tmp_path / 'selected.toml'
    config.write_text(binding(config).replace('"/bin/sh"', json.dumps(str(program))))
    monkeypatch.setenv('CORAGENT_JOB_CONFIG', str(config))
    args = ['--config', str(config), '--environment', 'local', '--executor', 'external.copy', '--version', '3', '--details']
    return config, program, marker, args


def test_probe_detects_missing_executable_in_actual_target_and_does_not_confuse_it_with_missing_recipe(tmp_path, monkeypatch):
    config, program, marker, args = native_fixture(tmp_path, monkeypatch)
    program.unlink()
    status, missing = run_cli(*args)
    assert status == 1 and missing['status'] == 'check_failed'
    assert missing['error'] == 'environment_executable_missing'
    assert missing['backend'] == 'shell'
    assert not marker.exists()
    status, unconfigured = run_cli('--config', str(config), '--environment', 'local', '--backend', 'unconfigured')
    assert status == 1 and unconfigured['status'] == 'not_configured'
    assert unconfigured['error'] == 'executor_binding_missing'
    status, recipe = run_cli('--config', str(config), '--environment', 'local', '--executor', 'external.unknown', '--version', '1')
    assert status == 1 and recipe['status'] == 'recipe_not_found'
    assert recipe['software_availability'] == 'not_checked'


def test_verified_native_prerequisites_do_not_execute_program_but_prepared_job_does(tmp_path, monkeypatch):
    config, program, marker, args = native_fixture(tmp_path, monkeypatch)
    status, report = run_cli(*args)
    assert status == 0 and report['status'] == 'verified'
    observation = report['environment_evidence']['observation']
    assert observation['python'] is None
    assert observation['files']['executable'] == {'path': str(program), 'sha256': 'sha256:' + hashlib.sha256(program.read_bytes()).hexdigest()}
    assert not marker.exists(), 'prerequisite verification is not a solver execution or a scientific result'
    root = tmp_path / 'workspace'; workspace(root)
    data = root / 'input.txt'; data.write_text('Synthetic material; no scientific verdict\n')
    prepared = prepare(config, 'local', 'external.copy', '3', {'data': data})
    receipt = execute('job.start', root, prepared)
    try:
        for _ in range(200):
            observed = execute('job.status', root, {'job_id': receipt['job_id']})
            if observed['state'] in {'succeeded', 'failed'}:
                break
            time.sleep(.01)
        assert observed['state'] == 'succeeded'
        assert marker.exists()
        collected = execute('job.collect', root, {'job_id': receipt['job_id']})
        assert collected['output_validation']['complete']
        assert (Path(receipt['cwd']) / 'result.txt').read_text() == data.read_text()
        assert 'scientific_verdict' not in collected, 'execution/collection does not synthesize a scientific result'
    finally:
        execute('job.cancel', root, {'job_id': receipt['job_id']})


@pytest.mark.parametrize('change', ['configuration', 'executable_bytes', 'executable_deleted'])
def test_prepared_availability_evidence_cannot_authorize_a_stale_binding(tmp_path, monkeypatch, change):
    config, program, marker, _ = native_fixture(tmp_path, monkeypatch)
    root = tmp_path / 'workspace'; workspace(root)
    data = root / 'input.txt'; data.write_text('input\n')
    prepared = prepare(config, 'local', 'external.copy', '3', {'data': data})
    if change == 'configuration':
        config.write_text(config.read_text().replace(str(program), '/bin/sh'))
        expected = 'execution_binding_changed'
    elif change == 'executable_bytes':
        program.write_text(program.read_text() + '# changed since preparation\n')
        expected = 'execution_environment_changed'
    else:
        program.unlink()
        expected = 'environment_executable_missing'
    with pytest.raises(ValueError, match=expected):
        execute('job.start', root, prepared)
    assert not marker.exists()
    assert not list((root / 'operations/executions').glob('*.json'))


@pytest.mark.parametrize('requirement', ['package', 'import', 'initialization'])
def test_actual_python_probe_distinguishes_missing_dependency_from_executable_and_binding(tmp_path, monkeypatch, requirement):
    config = Path(os.environ['CORAGENT_JOB_CONFIG'])
    path = catalog(tmp_path / 'catalog', monkeypatch)
    script = path.parent / 'fixture.py'; script.write_text('raise AssertionError("probe must not execute the scientific entrypoint")\n')
    declaration = json.loads(path.read_text())
    entry = declaration['executors'][0]
    entry.update(backend='validation', runtime='python', entry=script.name, argv=['{entry}'], inputs={}, outputs=[],
                 resources={script.name: 'sha256:' + hashlib.sha256(script.read_bytes()).hexdigest()},
                 requirements={'packages': {'coragent-nonexistent-dependency-fixture': '>=1'}} if requirement == 'package'
                 else {'imports': ['coragent_nonexistent_dependency_fixture']})
    module = None
    if requirement == 'initialization':
        settings = load_job_config(config)
        prefix = Path(settings['environments']['local']['backends']['validation']['python']['prefix'])
        module = next(prefix.glob('lib/python*/site-packages')) / 'coragent_initialization_fixture.py'
        module.write_text('raise RuntimeError("fixture-private-error-content")\n')
        entry['requirements'] = {'imports': ['coragent_initialization_fixture']}
    try:
        path.write_text(json.dumps(declaration))
        status, result = run_cli('--config', str(config), '--environment', 'local', '--executor', entry['id'], '--version', entry['version'])
        assert status == 1 and result['status'] == 'check_failed'
        assert result['runtime'] == 'python'
        assert result['error'] == ('environment_import_failed' if requirement == 'initialization' else 'environment_dependency_missing')
        assert 'fixture-private-error-content' not in json.dumps(result)
    finally:
        if module is not None:
            module.unlink()


def test_missing_activation_script_is_a_binding_failure_without_running_the_program(tmp_path, monkeypatch):
    config, _, marker, args = native_fixture(tmp_path, monkeypatch)
    config.write_text(config.read_text() + 'activation_script=' + json.dumps(str(tmp_path / 'missing-activation.sh')) + '\n')
    status, result = run_cli(*args)
    assert status == 1 and result['status'] == 'check_failed'
    assert result['error'] == 'environment_activation_missing'
    assert not marker.exists()


def test_platform_probe_does_not_claim_that_the_configured_software_is_installed(tmp_path, monkeypatch):
    config, program, _, args = native_fixture(tmp_path, monkeypatch)
    program.unlink()
    root = tmp_path / 'workspace'; workspace(root)
    platform = execute('job.probe', root, {'platform': 'local'})
    assert platform['cwd_exists'] and platform['inputs_present']
    assert 'executable' not in platform
    status, software = run_cli(*args)
    assert status == 1 and software['error'] == 'environment_executable_missing'
