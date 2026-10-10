"""Recipe discovery and target checks do not define a scientific allowlist."""
import copy
import hashlib
import json
import os

import pytest

from research_agent.application import environment_check, executors
from research_agent.application.execution_catalog import installed_catalogs
from research_agent.jobs.config_contract import load_job_config
from tests.unit.test_declarative_executors import binding, catalog


def targets():
    return {'default_environment': 'local', 'environments': {
        'local': {'kind': 'local', 'supervisor': 'process', 'backends': {'shell': {'command': '/bin/sh'}}},
        'cluster': {'kind': 'remote', 'ssh_host': 'unreachable.invalid', 'remote_root': '/scratch/jobs',
                    'submission': {'queue': 'science'}, 'backends': {'shell': {'command': '/cluster/bin/sh'}}},
        'empty': {'kind': 'local', 'supervisor': 'process'}}}


def cli(module, monkeypatch, capsys, *arguments):
    monkeypatch.setattr('sys.argv', [module.__name__, *arguments])
    module.main()
    return capsys.readouterr().out


def test_compact_index_preserves_all_recipe_identities_and_gaussian(monkeypatch, capsys):
    report = json.loads(cli(executors, monkeypatch, capsys, '--list'))
    full = json.loads(cli(executors, monkeypatch, capsys, '--list', '--details'))
    assert report['scope'] == 'predefined_recipes'
    assert report['software_availability'] == 'not_checked'
    assert [(r['id'], r['version']) for r in report['recipes']] == [
        (r['id'], r['version']) for r in full['recipes']]
    assert {'chemical.gaussian', 'chemical.gaussian-input'} <= {r['id'] for r in report['recipes']}
    assert all('resources' not in row and 'argv' not in row for row in report['recipes'])
    assert len(json.dumps(report)) < len(json.dumps(full)) / 3
    filtered = json.loads(cli(executors, monkeypatch, capsys, '--list', '--skill', 'gaussian',
                              '--executor', 'chemical.gaussian-input', '--version', '1'))
    assert [r['id'] for r in filtered['recipes']] == ['chemical.gaussian-input']


def test_recipe_index_honors_binding_selection_without_probing(tmp_path, monkeypatch, capsys):
    catalog(tmp_path / 'catalog', monkeypatch)
    config = tmp_path / 'job.toml'
    config.write_text(binding(config) + '\n[environments.empty]\nkind="local"\n')
    monkeypatch.setattr(executors, 'probe_binding', lambda *_: pytest.fail('listing must not probe'))
    for target, status in [('local', 'configured'), ('empty', 'not_configured')]:
        report = json.loads(cli(executors, monkeypatch, capsys, '--list', '--config', str(config),
                                '--environment', target, '--backend', 'shell'))
        assert report['environment'] == target
        assert report['recipes'] == [{'id': 'external.copy', 'version': '3', 'backend': 'shell',
            'runtime': 'native', 'inputs': {'data': 'input.txt'}, 'binding_status': status}]
    full = executors.list_recipes(details=True)['recipes']
    assert full == installed_catalogs()[0]['executors']
    assert executors.list_recipes(executor='external.missing')['recipes'] == []
    with pytest.raises(ValueError, match='execution_environment_not_configured'):
        executors.list_recipes(config=config, environment='typo')


def test_selected_gaussian_help_uses_runner_contract_without_target_access(monkeypatch, capsys):
    monkeypatch.setattr(executors, 'probe_binding', lambda *_: pytest.fail('help must not probe'))
    output = cli(executors, monkeypatch, capsys, '--config', '/missing/job.toml', '--environment', 'remote',
                 '--executor', 'chemical.gaussian-input', '--version', '1', '--help')
    assert '--input-gjf' in output and '--validation' in output and 'saddle' in output
    assert 'chemical.gaussian-input@1' in output
    assert '--script' in cli(executors, monkeypatch, capsys, '--help')


def test_gaussian_recipes_check_wrapper_and_program_on_selected_local_target():
    settings = load_job_config(os.environ['RESEARCH_AGENT_JOB_CONFIG'])
    backends = settings['environments']['local']['backends']
    backends['gaussian'] = {**copy.deepcopy(backends['validation']), 'command': '/bin/true'}
    settings['environments']['cluster'] = targets()['environments']['cluster']
    for recipe in ('chemical.gaussian', 'chemical.gaussian-input'):
        report = environment_check.check_target(settings, 'local', executor=recipe, version='1', details=True)
        assert report['status'] == 'verified' and report['backend'] == 'gaussian'
        observation = report['environment_evidence']['observation']['python']
        assert observation['files']['executable']['path'].endswith('/true')


def test_help_only_imports_pinned_cli_and_preserves_resource_checks(tmp_path, monkeypatch, capsys):
    path = catalog(tmp_path / 'catalog', monkeypatch)
    entrypoint = path.parent / 'science.py'
    entrypoint.write_text("raise RuntimeError('must not import science for help')\n")
    parser = path.parent / 'cli.py'
    parser.write_text('import argparse\ndef parse_arguments(argv):\n'
                      '    p = argparse.ArgumentParser()\n'
                      '    p.add_argument("--iterations", type=int)\n'
                      '    return p.parse_args(argv)\n')
    declaration = json.loads(path.read_text())
    entry = declaration['executors'][0]
    entry.update(runtime='python', entry='science.py', cli='cli.py', argv=['{entry}', '{args}'])
    for resource in (entrypoint, parser):
        entry['resources'][resource.name] = 'sha256:' + hashlib.sha256(resource.read_bytes()).hexdigest()
    path.write_text(json.dumps(declaration))
    assert '--iterations' in cli(executors, monkeypatch, capsys, '--executor', 'external.copy',
                                 '--version', '3', '--help')
    parser.write_text('raise RuntimeError("tampered")\n')
    with pytest.raises(ValueError, match='execution_resource_changed'):
        executors.print_runner_help('external.copy', '3')


def test_target_check_contacts_only_selected_environment(tmp_path, monkeypatch):
    from research_agent.jobs import environment
    catalog(tmp_path / 'catalog', monkeypatch)
    original = environment._run_target
    observed = []

    def run(settings, selected, script):
        assert selected['environment'] == 'local'
        observed.append(selected['backend'])
        return original(settings, selected, script)

    monkeypatch.setattr(environment, '_run_target', run)
    settings = targets()
    settings['environments']['local']['backends']['broken'] = {'command': '/missing/unrelated'}
    report = environment_check.check_target(settings, 'local', executor='external.copy', version='3')
    assert report == {'environment': 'local', 'scope': 'recipe_requirements',
        'executor': {'id': 'external.copy', 'version': '3'}, 'backend': 'shell',
        'runtime': 'native', 'status': 'verified'}
    assert observed == ['shell']


def test_target_check_uses_selected_remote_binding(tmp_path, monkeypatch):
    catalog(tmp_path / 'catalog', monkeypatch)
    seen = []

    def probe(settings, selected, requirements):
        seen.append(selected)
        return {'fixture': 'remote observation'}

    monkeypatch.setattr(environment_check, 'probe_binding', probe)
    report = environment_check.check_target(targets(), 'cluster', executor='external.copy', version='3', details=True)
    assert report['status'] == 'verified'
    assert report['environment_evidence'] == {'fixture': 'remote observation'}
    assert len(seen) == 1 and seen[0]['kind'] == 'remote'
    assert seen[0]['binding']['command'] == '/cluster/bin/sh'
    assert seen[0]['submission']['queue'] == 'science'


def test_missing_recipe_binding_and_failed_probe_are_distinct(tmp_path, monkeypatch):
    catalog(tmp_path / 'catalog', monkeypatch)
    settings = targets()
    missing = environment_check.check_target(settings, 'local', executor='external.copy', version='missing')
    assert missing['status'] == 'recipe_not_found' and missing['software_availability'] == 'not_checked'
    assert environment_check.check_target(settings, 'empty', backend='shell')['status'] == 'not_configured'
    assert environment_check.check_target(settings, 'unknown', backend='shell')['error'] == 'execution_environment_not_configured'
    settings['environments']['local']['backends']['shell']['command'] = '/missing/scientific-program'
    failed = environment_check.check_target(settings, 'local', executor='external.copy', version='3')
    assert failed['status'] == 'check_failed' and failed['error'] == 'environment_probe_failed'


def test_generic_bindings_can_be_checked_without_loading_recipes(monkeypatch):
    monkeypatch.setattr(environment_check, 'installed_catalogs', lambda: pytest.fail('backend checks need no catalog'))
    assert environment_check.check_target(targets(), 'local', backend='shell')['status'] == 'verified'
    settings = load_job_config(os.environ['RESEARCH_AGENT_JOB_CONFIG'])
    python = copy.deepcopy(settings['environments']['local']['backends']['validation'])
    settings['environments']['local']['backends'] = {'custom': {**python, 'command': '/bin/true'}}
    report = environment_check.check_target(settings, 'local', backend='custom', details=True)
    assert report['status'] == 'verified' and report['runtime'] == 'python'
    assert report['environment_evidence']['observation']['python']
    assert environment_check.check_target(settings, 'local', backend='custom', runtime='native')['status'] == 'verified'


def test_recipe_checks_dependencies_and_command_compatibility(monkeypatch):
    settings = load_job_config(os.environ['RESEARCH_AGENT_JOB_CONFIG'])
    entry = {'id': 'external.analysis', 'version': '1', 'backend': 'validation',
        'runtime': 'python', 'argv': ['{entry}', '{args}'],
        'requirements': {'packages': {'numpy': '>=9999'}}}
    monkeypatch.setattr(environment_check, 'installed_catalogs', lambda: [{'executors': [entry]}])
    report = environment_check.check_target(settings, 'local', executor=entry['id'], version='1')
    assert report['status'] == 'check_failed'
    assert report['error'] == 'environment_dependency_version_mismatch: numpy'
    settings['environments']['local']['backends']['validation']['command'] = '/bin/true'
    report = environment_check.check_target(settings, 'local', executor=entry['id'], version='1')
    assert report['error'] == 'execution_binding_command_mismatch'


def test_target_cli_outputs_json_and_failure_exit_code(tmp_path, monkeypatch, capsys):
    config = tmp_path / 'job.toml'
    binding(config)
    args = ['--config', str(config), '--environment', 'local', '--backend', 'shell']
    report = json.loads(cli(environment_check, monkeypatch, capsys, *args))
    assert report['status'] == 'verified' and 'environment_evidence' not in report
    report = json.loads(cli(environment_check, monkeypatch, capsys, *args, '--details'))
    assert report['environment_evidence']['observation']['files']['executable']
    with pytest.raises(SystemExit) as caught:
        cli(environment_check, monkeypatch, capsys, *args[:-1], 'missing')
    assert caught.value.code == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'not_configured'
