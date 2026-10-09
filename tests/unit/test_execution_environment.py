"""Real target probes and guards reject changed bindings before science runs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from research_agent.jobs.config_contract import load_job_config, resolve_binding
from research_agent.jobs.environment import guarded_command, probe_binding
from research_agent.jobs.worker import supervisor_environment
from research_agent.application.memory_context import read
from research_agent.artifacts.registry import manifests
from research_agent.application.job_state import execution
from research_agent.foundation.transactions import TransactionCoordinator
from research_agent.application.api import execute
from research_agent.application.executors import prepare_script
from tests.unit.test_job_recovery import workspace


def target():
    settings = load_job_config(os.environ['RESEARCH_AGENT_JOB_CONFIG'])
    return settings, resolve_binding(settings, 'local', 'validation', runtime='python')


def request(tmp_path):
    script = tmp_path / 'science.py'
    script.write_text("from pathlib import Path\nPath('result.txt').write_text('computed once')\n")
    return prepare_script(os.environ['RESEARCH_AGENT_JOB_CONFIG'], 'local', 'validation', script, collect=['result.txt'])


def stage(tmp_path, request):
    cwd = tmp_path / 'guard-test'
    cwd.mkdir()
    for row in request['inputs']:
        destination = cwd / row['destination']
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(row['source'], destination)
    return cwd


def run_guard(cwd, command):
    return subprocess.run(command, cwd=cwd, env={**supervisor_environment(), 'TMPDIR': str(cwd)},
                          capture_output=True, text=True, timeout=15)


def test_actual_python_environment_matches_receipt_and_declared_dependencies():
    settings, selected = target()
    result = probe_binding(settings, selected, {'python': '>=3.11', 'packages': {'rdkit': '>=2025.9,<2027'}, 'imports': ['rdkit.Chem']})
    observed = result['observation']['python']
    assert observed['prefix'] == selected['python']['prefix']
    assert observed['lock_sha256'] and observed['inventory_sha256'] and observed['receipt_sha256']
    assert observed['packages']['rdkit']
    with pytest.raises(ValueError, match='dependency_version_mismatch'):
        probe_binding(settings, selected, {'packages': {'rdkit': '>=9999'}})
    with pytest.raises(ValueError, match='environment_import_failed'):
        probe_binding(settings, selected, {'imports': ['research_agent_nonexistent_dependency']})


def test_target_conda_package_hash_must_match_the_declared_lock(tmp_path):
    import shlex
    settings, selected = target()
    binding = selected['python']
    # Keep identical package URLs and versions; only the package content differs.
    Path(binding['lock_ref']).write_text('@EXPLICIT\nhttps://fixture.invalid/python.conda#'+'a'*64+'\n')
    actual = tmp_path/'actual.lock'
    actual.write_text('@EXPLICIT\nhttps://fixture.invalid/python.conda#'+'b'*64+'\n')
    conda = Path(binding['conda_executable'])
    conda.write_text(conda.read_text().replace(shlex.quote(binding['lock_ref']), shlex.quote(str(actual))))
    with pytest.raises(ValueError, match='environment_conda_inventory_mismatch'):
        probe_binding(settings, selected, {})


@pytest.mark.parametrize('changed', ['lock', 'receipt', 'inventory', 'prefix'])
def test_target_changes_are_detected_without_trusting_runner_self_reports(changed, tmp_path):
    settings, selected = target()
    python = selected['python']
    if changed == 'lock':
        Path(python['lock_ref']).write_text('@EXPLICIT\nhttps://fixture.invalid/changed.conda\n')
    elif changed == 'receipt':
        (Path(python['prefix']) / 'research-agent-environment.json').unlink()
    elif changed == 'inventory':
        site = next(Path(python['prefix']).glob('lib/python*/site-packages'))
        package = site / 'unlocked-1.0.dist-info'
        package.mkdir()
        (package / 'METADATA').write_text('Metadata-Version: 2.1\nName: unlocked\nVersion: 1.0\n')
    else:
        python['prefix'] = str(tmp_path / 'wrong-prefix')
    with pytest.raises(ValueError, match='environment_'):
        probe_binding(settings, selected, {})


def test_queued_python_job_rechecks_receipt_and_guard_code_before_script(tmp_path):
    prepared = request(tmp_path)
    cwd = stage(tmp_path, prepared)
    selected = prepared['metadata']['execution_binding']
    receipt = Path(selected['python']['prefix']) / 'research-agent-environment.json'
    receipt.write_text(receipt.read_text() + '\n')
    result = run_guard(cwd, prepared['command'])
    assert result.returncode == 125 and 'execution_environment_changed' in result.stderr
    assert not (cwd / 'result.txt').exists()
    (cwd / '.research-agent/environment_probe.py').write_text("raise SystemExit(0)\n")
    assert run_guard(cwd, prepared['command']).returncode == 125
    assert not (cwd / 'result.txt').exists()


def test_native_target_needs_no_python_and_checks_activation_before_sourcing(tmp_path):
    binary = tmp_path / 'program'
    binary.write_text('#!/bin/sh\nprintf computed > result.txt\n')
    binary.chmod(0o700)
    activation = tmp_path / 'activate.sh'
    activation.write_text('export SCIENCE_MODE=test\n')
    settings = {'environments': {'local': {'kind': 'local', 'backends': {'native': {
        'command': str(binary), 'activation_script': str(activation)}}}}}
    selected = resolve_binding(settings, 'local', 'native', runtime='native')
    snapshot = probe_binding(settings, selected, {})
    command, inputs = guarded_command(selected, [str(binary)], snapshot)
    assert not inputs and snapshot['observation']['python'] is None
    activation.write_text('touch ' + str(tmp_path / 'bad-activation-ran') + '\n')
    assert run_guard(tmp_path, command).returncode == 125
    assert not (tmp_path / 'bad-activation-ran').exists()
    assert not (tmp_path / 'result.txt').exists()
    activation.write_text('export SCIENCE_MODE=test\n')
    binary.write_text('#!/bin/sh\nprintf changed > result.txt\n')
    assert run_guard(tmp_path, command).returncode == 125
    assert not (tmp_path / 'result.txt').exists()
    assert probe_binding(settings, selected, {})['sha256'] != snapshot['sha256']


def test_submission_rejects_drift_before_attempt_but_replay_returns_original_receipt(tmp_path):
    root = tmp_path / 'workspace'
    root.mkdir()
    workspace(root)
    prepared = request(tmp_path)
    params = {**prepared}
    selected = prepared['metadata']['execution_binding']
    receipt = Path(selected['python']['prefix']) / 'research-agent-environment.json'
    original = receipt.read_bytes()
    receipt.write_bytes(original + b'\n')
    with pytest.raises(ValueError, match='execution_environment_changed'):
        execute('job.start', root, params)
    assert not list((root/'operations/executions').glob('*.json'))
    assert not (root / 'runs/jobs').exists()
    receipt.write_bytes(original)
    started = execute('job.start', root, params)
    for _ in range(250):
        status = execute('job.status', root, {'job_id': started['job_id']})
        if status['state'] in {'succeeded', 'failed'}:
            break
        time.sleep(.02)
    assert status['state'] == 'succeeded'
    receipt.unlink()
    replay = execute('job.start', root, params)
    assert replay['job_id'] == started['job_id']
    assert len(list((root/'operations/executions').glob('*.json'))) == 1


def test_target_probe_does_not_hold_state_lock(tmp_path, monkeypatch):
    root = tmp_path / 'workspace'
    root.mkdir()
    workspace(root)
    prepared = request(tmp_path)
    from research_agent.application import execution_environment
    original = execution_environment.probe_binding
    entered, release = threading.Event(), threading.Event()
    def slow_probe(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)
    monkeypatch.setattr(execution_environment, 'probe_binding', slow_probe)
    def read_while_probing():
        with TransactionCoordinator(root).locked():
            return read(root)['workspace_id']
    with ThreadPoolExecutor(max_workers=2) as pool:
        submit = pool.submit(execute, 'job.start', root, {**prepared})
        try:
            assert entered.wait(5)
            assert pool.submit(read_while_probing).result(timeout=3)
        finally:
            release.set()
        started = submit.result(timeout=15)
    for _ in range(250):
        status = execute('job.status', root, {'job_id': started['job_id']})
        if status['state'] in {'succeeded', 'failed'}:
            break
        time.sleep(.02)
    assert status['state'] == 'succeeded'


def test_execution_binding_cannot_be_a_claim_without_the_guard(tmp_path):
    from research_agent.application.execution_environment import check_binding
    prepared = request(tmp_path)
    prepared['command'] = ['/bin/true']
    with pytest.raises(ValueError, match='execution_guard_required'):
        check_binding(prepared, probe=False)


def test_identical_guard_copy_can_cross_wheel_and_source_submission(tmp_path):
    from research_agent.application.execution_environment import check_binding
    prepared = request(tmp_path)
    guard = next(row for row in prepared['inputs'] if row['destination'] == '.research-agent/environment_probe.py')
    other_installation_copy = tmp_path / 'wheel-environment-probe.py'
    shutil.copyfile(guard['source'], other_installation_copy)
    guard['source'] = str(other_installation_copy)
    check_binding(prepared, probe=False)
    # A different digest cannot stand in for the released guard.
    guard['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='execution_guard_input_missing'):
        check_binding(prepared, probe=False)


@pytest.mark.parametrize('field,value', [('queue', 'extra'), ('queue_wait_seconds', 30), ('resources', {'cpus': 99})])
def test_prepared_submission_rejects_added_or_changed_resource_fields(tmp_path, field, value):
    from research_agent.application.execution_environment import check_configuration
    prepared = request(tmp_path)
    prepared['metadata'][field] = value
    with pytest.raises(ValueError, match='execution_binding_submission_mismatch'):
        check_configuration(prepared)


def test_guard_cannot_be_reused_for_a_different_script(tmp_path):
    from research_agent.application.execution_environment import check_binding
    prepared = request(tmp_path)
    metadata = prepared['metadata']
    metadata['execution_argv'] = ['other.py']
    prepared['command'], _ = guarded_command(metadata['execution_binding'], metadata['execution_argv'], metadata['execution_environment'])
    with pytest.raises(ValueError, match='execution_script_mismatch'):
        check_binding(prepared, probe=False)


def test_ssh_probe_runs_target_checks_and_cleans_remote_scratch(tmp_path, monkeypatch):
    settings, selected = target()
    target_settings = settings['environments']['local']
    target_settings.update(kind='remote', ssh_host='fixture.invalid', remote_root=str(tmp_path / 'new-remote-root'),
                           ssh_config=str(tmp_path / 'ssh-config'), submission={'queue': 'science'})
    activation = tmp_path / 'activate.sh'
    activation.write_text('test -z "${RESEARCH_AGENT_FIXTURE_PROVIDER_SECRET:-}"\nexport REMOTE_TEST_READY=1\n')
    target_settings['backends']['validation']['activation_script'] = str(activation)
    selected = resolve_binding(settings, 'local', 'validation', runtime='python')
    monkeypatch.setenv('RESEARCH_AGENT_FIXTURE_PROVIDER_SECRET', 'test-only-secret')
    from research_agent.jobs import environment
    original, calls = environment._capture, []
    def ssh_transport(command, **kwargs):
        assert command[0] == 'ssh'
        calls.append(command)
        return original(['bash', '-c', command[-1]], **kwargs)
    monkeypatch.setattr('research_agent.jobs.environment._capture', ssh_transport)
    result = probe_binding(settings, selected, {'python': '>=3.11'})
    assert result['observation']['python']['prefix'] == selected['python']['prefix']
    assert calls and 'fixture.invalid' in calls[0] and '-F' in calls[0]
    assert (tmp_path / 'new-remote-root').is_dir()
    assert not list((tmp_path / 'new-remote-root').glob('.environment-*'))
    receipt = Path(selected['python']['prefix']) / 'research-agent-environment.json'
    receipt.unlink()
    with pytest.raises(ValueError, match='environment_receipt_missing'):
        probe_binding(settings, selected, {'python': '>=3.11'})
    assert (tmp_path / 'new-remote-root').is_dir()
    assert not list((tmp_path / 'new-remote-root').glob('.environment-*'))


def test_probe_timeout_terminates_its_child_process_group(tmp_path):
    from research_agent.jobs.environment import _capture
    child = tmp_path / 'child.pid'
    with pytest.raises(subprocess.TimeoutExpired):
        _capture(['bash', '-c', 'sleep 30 & echo $! > "$1"; wait', 'probe-fixture', str(child)], timeout=.2)
    pid = int(child.read_text())
    deadline = time.monotonic() + 3
    while Path('/proc', str(pid)).exists() and time.monotonic() < deadline:
        time.sleep(.01)
    assert not Path('/proc', str(pid)).exists()
