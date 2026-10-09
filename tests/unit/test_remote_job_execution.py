"""Execute remote wrappers with real shells/rsync and a local scheduler fixture."""
from dataclasses import replace
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from job_runtime import JobOutput, JobSpec, JobState, TorqueSSHPlatform
from job_runtime.config_contract import job_config_schema, resolve_submission, validate_job_config
from job_runtime import remote as remote_module


@pytest.fixture
def cluster(tmp_path, monkeypatch):
    target = tmp_path / 'cluster files'
    target.mkdir()
    binaries = tmp_path / 'scheduler'
    binaries.mkdir()
    qsub = binaries / 'qsub'
    qsub.write_text('#!' + sys.executable + '\n' + '''import json, subprocess, sys
from pathlib import Path
Path('qsub-arguments.json').write_text(json.dumps(sys.argv[1:]))
count = Path('submission-count')
count.write_text(str(int(count.read_text()) + 1) if count.exists() else '1')
subprocess.run(['/bin/sh', sys.argv[-1]], check=False)
print('123.fixture')
''')
    qsub.chmod(0o700)
    for name in ('qstat', 'qdel'):
        path = binaries / name
        path.write_text('#!/bin/sh\nexit 1\n')
        path.chmod(0o700)
    scheduler_env = {**os.environ, 'PATH': str(binaries) + ':' + os.defpath,
                     'FIXTURE_PROVIDER_SECRET': 'must-not-reach-calculation', 'PYTHONPATH': '/fixture/host-only'}
    calls = []
    original_capture = remote_module._capture
    def transport(argv, *, timeout, **kwargs):
        calls.append((list(argv), timeout))
        if argv[0] == 'ssh':
            script = shlex.split(argv[-1])[2]
            return original_capture(['/bin/sh', '-c', script], timeout=timeout, env=scheduler_env)
        assert argv[0] == 'rsync'
        # Preserve real rsync flags/filters while replacing only SSH transport.
        local = list(argv)
        index = local.index('-e')
        del local[index:index+2]
        local = [value.removeprefix('fixture:') for value in local]
        return original_capture(local, timeout=timeout)
    monkeypatch.setattr(remote_module, '_capture', transport)
    platform = TorqueSSHPlatform({'ssh_host': 'fixture', 'remote_root': str(target),
                                 'allowed_queues': ['batch'], 'transfer_timeout_seconds': 900})
    return platform, calls, target


def job(tmp_path, *, code='pass', job_id='job_test', resources=None, **kwargs):
    cwd = tmp_path / 'local'
    cwd.mkdir(parents=True)
    return JobSpec(command=(sys.executable, '-c', code), cwd=cwd, job_id=job_id,
                   metadata={'queue': 'batch', 'resources': resources or {}}, **kwargs)


def test_remote_process_has_declared_environment_scratch_stdin_and_resources(cluster, tmp_path):
    platform, calls, target = cluster
    spec = job(tmp_path, resources={'cpus': 2, 'memory_mb': 128, 'walltime': '00:00:20'},
               timeout_seconds=10, env={'GAUSS_SCRDIR': '{scratch}', 'LITERAL': 'quoted\n$(must-not-run)'},
               outputs=(JobOutput('observed.json', required=True),), code='''import json,os,sys
from pathlib import Path
Path('observed.json').write_text(json.dumps({'input':sys.stdin.read(),'env':dict(os.environ)}))
# A calculation must not replace the control-plane spec or receipt on fetch.
Path('spec.json').write_text('forged')
Path('receipt.json').write_text('forged')
Path('status.json').write_text('forged')
''')
    source = spec.cwd / 'data.txt'
    source.write_text('staged stdin')
    spec = replace(spec, stdin=source, inputs=(source,), metadata={**spec.metadata,
                   'execution_binding': {'binding': {'scratch_root': str(target / 'scratch')}}})
    receipt = platform.start(spec)
    assert platform.status(receipt).state == JobState.SUCCEEDED
    result = platform.collect(receipt)
    assert result['output_validation']['complete']
    observed = json.loads((spec.cwd / 'observed.json').read_text())
    assert observed['input'] == 'staged stdin'
    env = observed['env']
    assert 'FIXTURE_PROVIDER_SECRET' not in env and 'PYTHONPATH' not in env
    assert env['LITERAL'] == 'quoted\n$(must-not-run)'
    assert env['TMPDIR'] == env['GAUSS_SCRDIR'] == receipt.metadata['scratch_path']
    assert Path(env['TMPDIR']).is_relative_to(target / 'scratch')
    assert env['OMP_NUM_THREADS'] == env['MKL_NUM_THREADS'] == env['OPENBLAS_NUM_THREADS'] == '2'
    assert json.loads((spec.cwd / 'spec.json').read_text())['metadata']['resources'] == spec.metadata['resources']
    assert json.loads((spec.cwd / 'receipt.json').read_text())['job_id'] == receipt.job_id
    assert json.loads((spec.cwd / 'status.json').read_text())['state'] == 'succeeded'
    args = json.loads((spec.cwd / 'qsub-arguments.json').read_text())
    assert 'nodes=1:ppn=2' in args and 'mem=128mb' in args and 'walltime=00:00:10' in args
    assert args[args.index('-m') + 1] == 'n' and args[args.index('-r') + 1] == 'n'
    assert {timeout for args, timeout in calls if args[0] == 'rsync'} == {900}
    assert {timeout for args, timeout in calls if args[0] == 'ssh'} == {60}


@pytest.mark.parametrize('timeout,code,expected', [
    (.15, 'import time; time.sleep(30)', JobState.TIMED_OUT),
    (5, 'raise SystemExit(124)', JobState.FAILED),
    (None, 'raise SystemExit(124)', JobState.FAILED),
])
def test_remote_timeout_keeps_real_program_exit_distinct(cluster, tmp_path, timeout, code, expected):
    platform, _, _ = cluster
    receipt = platform.start(job(tmp_path, code=code, timeout_seconds=timeout))
    assert platform.status(receipt).state == expected


def test_same_job_name_in_different_workspaces_has_distinct_remote_execution(cluster, tmp_path):
    platform, _, _ = cluster
    first = platform.start(job(tmp_path / 'first', code='pass'))
    assert platform.status(first).state == JobState.SUCCEEDED
    second = platform.start(job(tmp_path / 'second', code='raise SystemExit(17)'))
    assert first.metadata['remote_dir'] != second.metadata['remote_dir']
    assert platform.status(second).state == JobState.FAILED
    assert platform.status(first).state == JobState.SUCCEEDED


def test_lost_submit_response_recovers_scoped_directory_without_resubmission(cluster, tmp_path, monkeypatch):
    platform, _, _ = cluster
    run = platform._run_ssh
    def lose_response(script, **kwargs):
        result = run(script, **kwargs)
        if 'qsub ' in script and 'scheduler.id' in script:
            raise subprocess.TimeoutExpired('fixture ssh', 1)
        return result
    monkeypatch.setattr(platform, '_run_ssh', lose_response)
    spec = job(tmp_path)
    with pytest.raises(subprocess.TimeoutExpired):
        platform.start(spec)
    recovered = platform.recover_receipt(spec.job_id, spec.cwd)
    assert recovered.metadata['remote_dir'] == platform._remote_dir(spec)
    assert platform.status(recovered).state == JobState.SUCCEEDED
    assert (Path(recovered.metadata['remote_dir']) / 'submission-count').read_text() == '1'
    with pytest.raises(ValueError, match='reconcile instead of resubmitting'):
        platform.start(spec)


def test_adapter_requires_resolved_queue_even_when_config_has_defaults(cluster, tmp_path):
    platform, calls, _ = cluster
    platform.config['submission'] = {'queue': 'batch', 'resources': {'cpus': 9}}
    with pytest.raises(ValueError, match='queue_binding_missing'):
        platform.start(replace(job(tmp_path), metadata={}))
    assert not calls


def test_pbs_resources_use_select_and_the_shorter_execution_limit(tmp_path):
    platform = TorqueSSHPlatform({'ssh_host': 'fixture', 'remote_root': '/scratch', 'scheduler': 'pbs'})
    spec = job(tmp_path, timeout_seconds=30, resources={'cpus': 2, 'memory_mb': 128, 'walltime': '00:00:20'})
    args = platform._qsub_arguments(spec)
    assert 'select=1:ncpus=2:mem=128mb' in args and 'walltime=00:00:20' in args
    assert not any('nodes=' in arg for arg in args)


def test_raw_job_submission_resolves_defaults_before_recording_attempt(tmp_path, monkeypatch):
    from research_state.workspace import initialize_workspace
    from research_state.agent_workspace import admit_workspace, apply_change, read_context
    from tspi_runtime.execution import dispatch
    root = tmp_path / 'workspace'
    initialize_workspace(root, 'resources_test', 'research')
    admit_workspace(root, {'authority': 'host'})
    apply_change(root, {'principal': 'root_agent', 'authority': 'kernel_write', 'operations': [
        {'type': 'create_node', 'id': 'node_resources', 'title': 'Resource probe', 'objective': 'Verify execution resources'}]})
    config = tmp_path / 'defaults.toml'
    config.write_text('default_environment="local"\n[environments.local]\nkind="local"\n'
                      '[environments.local.submission.resources]\ncpus=1\nmemory_mb=256\nwalltime="00:00:15"\n')
    monkeypatch.setenv('TS_JOB_CONFIG', str(config))
    request = {'root': str(root), 'job_id': 'job_defaults', 'node_id': 'node_resources',
               'command': ['/bin/true'], 'metadata': {'resources': {'memory_mb': 128}}}
    result = dispatch('start', request)
    expected = {'cpus': 1, 'memory_mb': 128, 'walltime': '00:00:15'}
    assert result['metadata']['resources'] == expected
    state = read_context(root)
    assert state['attempts'][0]['metadata']['job_metadata']['resources'] == expected
    # A later default change must not alter a previously accepted Job or start it again.
    config.write_text(config.read_text().replace('cpus=1', 'cpus=2'))
    assert dispatch('start', request)['metadata']['resources'] == expected


@pytest.mark.parametrize('kind,scheduler,submission', [
    ('local', None, {'queue': 'batch'}),
    ('local', None, {'resources': {'select': '1:ncpus=2'}}),
    ('remote', 'torque', {'resources': {'select': '1:ncpus=2'}}),
    ('remote', 'pbs', {'resources': {'select': '1:ncpus=2', 'cpus': 2}}),
    ('remote', 'pbs', {'resources': {'walltime': '00:00:00'}}),
])
def test_runtime_and_schema_agree_on_scheduler_resource_errors(kind, scheduler, submission):
    from jsonschema import Draft202012Validator
    target = {'kind': kind, 'submission': submission}
    if kind == 'remote': target.update(ssh_host='fixture', remote_root='/scratch', scheduler=scheduler)
    config = {'default_environment': 'test', 'environments': {'test': target}}
    with pytest.raises(ValueError): validate_job_config(config)
    assert list(Draft202012Validator(job_config_schema()).iter_errors(config))


def test_submission_merges_target_backend_and_requested_resources_once():
    config = {'environments': {'cluster': {'kind': 'remote', 'allowed_queues': ['batch'],
        'submission': {'queue': 'batch', 'resources': {'cpus': 8, 'memory_mb': 1000, 'walltime': '00:05:00'}},
        'backends': {'method': {'submission': {'resources': {'cpus': 2}}}}}}}
    result = resolve_submission(config, 'cluster', 'method', requested={'resources': {'memory_mb': 500}})
    assert result == {'queue': 'batch', 'resources': {'cpus': 2, 'memory_mb': 500, 'walltime': '00:05:00'}}
    with pytest.raises(ValueError, match='not allowed'):
        resolve_submission(config, 'cluster', 'method', requested={'queue': 'other'})
