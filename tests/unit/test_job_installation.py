"""Installation plans and ordinary Job acceptance use deterministic local inputs."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

from scripts import _job_install as jobs
from scripts import install_wizard as wizard
from tests.unit.test_remote_job_execution import cluster

ROOT = Path(__file__).resolve().parents[2]


def options(tmp_path, *extra):
    return wizard.parse_args(['--install-root', str(tmp_path/'install'), '--conda-root', str(tmp_path/'conda'),
                              '--job-software-root', 'local=' + str(tmp_path/'software'), *extra], use_environment=False)


def test_fresh_plan_generates_default_bindings_and_no_files(tmp_path):
    args = options(tmp_path)
    plan = jobs.plan(args)
    structure = plan['settings']['environments']['local']['backends']['structure']
    assert structure['python'] == plan['settings']['environments']['local']['backends']['validation']['python']
    assert structure['python']['prefix'].startswith(str(tmp_path/'software/structure-'))
    assert plan['targets'] == ['local']
    assert plan['configuration_source'] == 'generated'
    assert structure['environment']['CORAGENT_NAME_RESOLVER_CONFIG'] == str(tmp_path/'install/etc/name-resolver.toml')
    assert not (tmp_path/'install').exists()
    assert not (tmp_path/'software').exists()
    assert jobs.plan(options(tmp_path, '--without-default-job-environment'))['environments'] == []


def test_profile_completes_partial_native_binding_and_rejects_unknown_target(tmp_path):
    config = tmp_path/'job.toml'
    config.write_text('default_environment="local"\n[environments.local]\nkind="local"\n'
                      '[environments.local.backends.xtb]\ncommand="/native/xtb"\n')
    value = jobs.plan(options(tmp_path, '--job-config',str(config),'--job-profile','local:wrapper'))
    wizard._validate_job_config(value['settings'])
    assert value['settings']['environments']['local']['backends']['xtb']['command'] == '/native/xtb'
    with pytest.raises(ValueError, match='target is not configured'):
        jobs.plan(options(tmp_path, '--job-conda', 'typo=/bin/conda'))


def test_explicit_repeatable_options_override_environment_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv('CORAGENT_JOB_PROFILE','local:render,local:pyscf')
    args = wizard.parse_args(['--job-profile','local:structure','--job-profile','local:wrapper'])
    assert args.job_profile == ['local:structure','local:wrapper']
    assert wizard.parse_args([]).job_profile == ['local:render','local:pyscf']


def test_existing_bindings_are_preserved_and_remote_is_not_contacted(tmp_path, monkeypatch):
    config = tmp_path/'job.toml'
    config.write_text('default_environment="local"\n[environments.local]\nkind="local"\n'
                      '[environments.local.backends.shell]\ncommand="/bin/sh"\n'
                      '[environments.cluster]\nkind="remote"\nssh_host="fixture"\nremote_root="/jobs"\n'
                      '[environments.cluster.submission]\nqueue="batch"\n')
    monkeypatch.setattr(subprocess, 'run', lambda *_a, **_k: pytest.fail('planning must not run commands'))
    value = jobs.plan(options(tmp_path, '--job-config', str(config)))
    assert value['settings'] == tomllib.loads(config.read_text())
    assert value['targets'] == ['local']
    assert value['environments'] == []
    with pytest.raises(ValueError, match='job-software-root'):
        jobs.plan(options(tmp_path, '--job-config', str(config), '--job-profile', 'cluster:pyscf'))
    remote = jobs.plan(options(tmp_path, '--job-config', str(config), '--job-profile', 'cluster:pyscf',
                              '--job-software-root', 'cluster=/remote/envs', '--job-conda', 'cluster=/remote/conda/bin/conda'))
    row = remote['environments'][0]
    assert row['binding']['prefix'].startswith('/remote/envs/pyscf-')
    assert remote['targets'] == ['cluster', 'local']


def test_managed_upgrade_reuses_identity_and_detects_concurrent_config_change(tmp_path):
    args = options(tmp_path)
    first = jobs.plan(args)
    first['readiness'] = {'targets': {}}
    jobs.publish(first)
    second = jobs.plan(args)
    assert second['environments'][0]['binding'] == first['environments'][0]['binding']
    config = Path(args.install_root)/'etc/job.toml'
    config.write_text(config.read_text() + '\n# operator edit\n')
    with pytest.raises(ValueError, match='input changed'):
        jobs.publish(second)


def test_bootstrap_validation_works_without_site_packages(tmp_path):
    config = tmp_path/'job.toml'
    config.write_text('default_environment="local"\n[environments.local]\nkind="local"\n'
                      '[environments.local.backends.shell]\ncommand="/bin/sh"\n')
    result = subprocess.run([sys.executable, '-S', '-B', str(ROOT/'scripts/installer.py'), 'install',
                             '--source', 'local', '--dry-run', '--job-config', str(config),
                             '--install-root', str(tmp_path/'install')], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['plan']['scientific_execution']['verify_targets'] == ['local']
    assert not (tmp_path/'install').exists()


def test_candidate_and_published_config_work_inside_real_jobs(tmp_path):
    from scripts._job_acceptance import accept
    config = tomllib.loads(Path(os.environ['CORAGENT_JOB_CONFIG']).read_text())
    local = config['environments']['local']
    local['backends'] = {'structure': local['backends']['structure']}
    source = tmp_path/'job.toml'
    source.write_bytes(jobs.toml_bytes({'default_environment':'local','environments':{'local':local}}))
    args = options(tmp_path, '--job-config', str(source))
    plan = jobs.plan(args)
    stage = tmp_path/'candidate'
    stage.mkdir()
    resolver = stage/'resolver.toml'
    resolver.write_text(plan['resolver'])
    candidate = copy.deepcopy(plan['settings'])
    candidate['environments']['local']['backends']['structure']['environment']['CORAGENT_NAME_RESOLVER_CONFIG'] = str(resolver)
    staged = stage/'job.toml'
    staged.write_bytes(jobs.toml_bytes(candidate))
    report = accept(staged, ROOT, stage/'jobs', ['local'], 20)
    assert report['targets']['local']['status'] == 'execution_verified', report
    assert len(report['targets']['local']['jobs']) == 2
    assert report['external_services'] == 'not_checked'
    plan['readiness'] = report
    jobs.publish(plan)
    result = accept(Path(args.install_root)/'etc/job.toml', ROOT, stage/'published', ['local'], 20, bindings_only=True)
    assert result['targets']['local']['status'] == 'execution_verified', result


def test_ssh_payload_contains_only_selected_target_resources(tmp_path, monkeypatch):
    request = {'store':'/remote/envs','binding':{'prefix':'/remote/envs/structure'},'files':{},'owner':'fixture'}
    target = {'kind':'remote','ssh_host':'cluster','ssh_config':'/fixture/ssh-config'}
    def run(command, **kwargs):
        assert command[0] == 'ssh' and command[-2] == 'cluster'
        payload = json.loads(kwargs['input'])
        assert payload['request'] == request
        assert set(payload['bundle']) == {'scripts/_job_target.py','scripts/install_job_environment.py',
            'backend/src/research_agent/jobs/config_contract.py','backend/src/research_agent/jobs/environment_probe.py'}
        assert 'models.json' not in kwargs['input'] and 'auth.json' not in kwargs['input']
        return subprocess.CompletedProcess(command, 0, 'CORAGENT_PROVISION={"status":"environment_verified"}\n', '')
    monkeypatch.setattr(subprocess, 'run', run)
    assert jobs.invoke_target(target, request, ROOT)['status'] == 'environment_verified'


@pytest.mark.parametrize('scheduler', ['pbs', 'torque'])
def test_remote_acceptance_uses_scheduler_collects_results_and_removes_test_jobs(cluster, tmp_path, monkeypatch, scheduler):
    from scripts._job_acceptance import accept
    from research_agent.jobs import environment
    platform, calls, remote_root = cluster
    local = tomllib.loads(Path(os.environ['CORAGENT_JOB_CONFIG']).read_text())['environments']['local']
    resolver = tmp_path/'remote-resolver.toml'
    resolver.write_text('default_resolver="auto"\n')
    structure = {**local['backends']['structure'],
                 'environment': {'CORAGENT_NAME_RESOLVER_CONFIG': str(resolver)}}
    target = {'kind':'remote', **platform.config, 'scheduler':scheduler,
              'submission':{'queue':'batch','resources':{'cpus':1,'walltime':'00:00:20'}},
              'backends':{'structure':structure}}
    config = tmp_path/'remote-job.toml'
    config.write_bytes(jobs.toml_bytes({'default_environment':'cluster','environments':{'cluster':target}}))
    original_capture = environment._capture
    def transport(command, **kwargs):
        assert command[0] == 'ssh'
        return original_capture(['/bin/sh','-c',command[-1]], **kwargs)
    monkeypatch.setattr(environment, '_capture', transport)
    result = accept(config, ROOT, tmp_path/'acceptance', ['cluster'], 20)
    assert result['targets']['cluster']['status'] == 'execution_verified', result
    assert len(result['targets']['cluster']['jobs']) == 2
    assert any(command[0] == 'rsync' for command, _ in calls)
    assert not list(remote_root.glob('job_*'))


def test_acceptance_waits_for_cancellation_and_reports_pending_jobs(tmp_path, monkeypatch):
    from scripts import _job_acceptance as acceptance
    calls = []
    def execute(operation, *args):
        calls.append(operation)
        if operation == 'job.start':
            return {'job_id':'job_fixture'}
        if operation == 'job.status':
            return {'state':'queued'}
        return {}
    ticks = iter(range(100))
    monkeypatch.setattr(acceptance, 'execute', execute)
    monkeypatch.setattr(acceptance.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(acceptance.time, 'sleep', lambda _:None)
    with pytest.raises(RuntimeError, match='cancellation_pending'):
        acceptance.run_job(tmp_path, {'request_id':'request'}, 3)
    assert calls.count('job.cancel') == 1
    assert calls[-1] == 'job.status'


def test_target_provisioning_reuses_verified_environment_and_recovers_interrupted_prefix(tmp_path, monkeypatch):
    from scripts import _job_target as target
    import base64
    store = tmp_path/'managed'
    raw = b'@EXPLICIT\nhttps://fixture.invalid/python.conda\n'
    digest = jobs.digest(raw + b'\0')
    prefix = store/('structure-' + digest[:16])
    request = {'store':str(store),'owner':'fixture','offline':True,
               'binding':{'manager':'conda','conda_executable':'/fixture/conda','prefix':str(prefix),
                          'lock_ref':str(store/'locks'/digest/'structure.lock')},
               'profile':{'lock':'structure.lock','platform':{'system':'Linux','machines':['x86_64'],'glibc':'2.28'}},
               'files':{'structure.lock':base64.b64encode(raw).decode()}}
    monkeypatch.setattr(target.platform, 'libc_ver', lambda:('glibc','2.35'))
    monkeypatch.setattr(target.platform, 'machine', lambda:'x86_64')
    calls=[]
    def install(binding, **kwargs):
        assert kwargs['offline']
        calls.append(prefix.exists())
        prefix.mkdir(exist_ok=True)
        (prefix/'coragent-environment.json').write_text('{}')
        return {'lock_sha256':digest,'inventory_sha256':'fixture'}
    monkeypatch.setattr(target, 'install', install)
    assert target.provision(request)['status'] == 'environment_verified'
    assert target.provision(request)['status'] == 'environment_verified'
    assert calls == [False,True]
    (prefix/'coragent-environment.json').unlink()
    (prefix/'partial').write_text('interrupted')
    (store/('.'+prefix.name+'.pending')).write_text(json.dumps({'installation_id':'fixture'},sort_keys=True)+'\n')
    target.provision(request)
    assert not (prefix/'partial').exists()
    with pytest.raises(ValueError, match='immutable_file_changed'):
        target.provision({**request,'owner':'different'})


def test_purge_selects_only_owned_unreferenced_local_environments(tmp_path):
    from contextlib import ExitStack
    root, store, workspace = tmp_path/'install', tmp_path/'software', tmp_path/'research'
    store.mkdir()
    (store/'installation-owner.json').write_text(json.dumps({'installation_id':jobs.digest(os.fsencode(root))[:16]}))
    record = {'environments':[{'kind':'local','managed':True,'store':str(store)}]}
    jobs.write_private(root/jobs.RECORD,json.dumps(record).encode())
    with ExitStack() as guards:
        removed, retained = jobs.cleanup_stores(root, workspace, guards)
        assert removed == [store] and retained == []
    jobs.write_private(workspace/'t001/operations/executions/job_fixture.json',b'{"state":"running"}')
    with ExitStack() as guards:
        removed, retained = jobs.cleanup_stores(root, workspace, guards)
        assert removed == [] and retained == [str(store)]


def test_failed_preparation_store_is_kept_while_acceptance_job_is_unfinished(tmp_path):
    from contextlib import ExitStack
    root, store = tmp_path/'install', tmp_path/'software'
    store.mkdir()
    (store/'installation-owner.json').write_text(json.dumps({'installation_id':jobs.digest(os.fsencode(root))[:16]}))
    jobs.write_private(root/jobs.STORES,json.dumps([{'kind':'local','store':str(store)}]).encode())
    job = root/'var/cache/job-install/candidate/jobs/local/operations/executions/job_fixture.json'
    jobs.write_private(job,b'{"state":"running"}')
    with ExitStack() as guards:
        assert jobs.cleanup_stores(root,tmp_path/'research',guards) == ([],[str(store)])
    jobs.write_private(job,b'{"state":"cancelled"}')
    with ExitStack() as guards:
        assert jobs.cleanup_stores(root,tmp_path/'research',guards) == ([store],[])
