"""Complete public installation, real managed Jobs, reuse and owned-store purge."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from scripts.build_package import build_package
from scripts import _job_install as jobs
from research_agent.foundation.layout import paths

ROOT = Path(__file__).resolve().parents[2]


def test_public_package_install_accepts_jobs_reuses_environment_and_uninstalls(tmp_path):
    built = build_package(output_dir=tmp_path/'package', agent_manifest_path=None, allow_dirty=True, include_web=False)
    root = tmp_path/'installation'
    paths(root).initialize()
    acceptance = tmp_path/'acceptance'
    acceptance.mkdir()
    cache = root/'var/cache/job-install'
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.symlink_to(acceptance, target_is_directory=True)
    pin = json.loads((ROOT/'config/pi-source.json').read_text())
    pi_root = root/'runtimes/pi'/pin['commit']
    pi_root.mkdir(parents=True)
    subprocess.run(['cp','--reflink=auto','-a',os.environ['CORAGENT_TEST_PI_RUNTIME_ROOT']+'/.',str(pi_root)],check=True)
    config = tmp_path/'job.toml'
    config.write_text('default_environment="local"\n[environments.local]\nkind="local"\nsupervisor="process"\n')
    conda = os.environ.get('CORAGENT_TEST_CONDA') or shutil.which('conda')
    assert conda, 'Prepare with CORAGENT_TEST_CONDA set'
    environment = dict(os.environ, CONDA_OFFLINE='true')
    for key in ('CORAGENT_JOB_CONFIG', 'CORAGENT_INSTALL_ROOT', 'CORAGENT_RUNTIME_MANIFEST'):
        environment.pop(key, None)
    agent_config = tmp_path/'model-config'
    agent_config.mkdir()
    command = [sys.executable,'-S','-B',str(ROOT/'scripts/installer.py'),'install','--source','package',
               '--package-manifest',built['manifest'],'--install-root',str(root),'--conda-root',str(Path(conda).parent.parent),
               '--job-profile','local:structure','--job-software-root','local='+str(tmp_path/'scientific'),
               '--job-offline','--service-scope','none','--without-web','--without-model-icons',
               '--agent-config-dir',str(agent_config),
               '--phone-access','disabled','--non-interactive','--yes','--allow-dirty','--json']
    subprocess.run([*command,'--job-config',str(config)],env=environment,check=True)
    record = json.loads((root/jobs.RECORD).read_text())
    assert record['readiness']['targets']['local']['status'] == 'execution_verified'
    assert len(record['readiness']['targets']['local']['jobs']) == 2
    assert record['publication']['targets']['local']['status'] == 'execution_verified'
    prefix = Path(record['environments'][0]['binding']['prefix'])
    stamp = (prefix/'bin/python').stat().st_ino
    runtime = json.loads((paths(root).runtime_home/'env.json').read_text())
    python = runtime['python_executable']
    clean = jobs.acceptance_environment(root/'current/agent', python)
    subprocess.run([python,'-c','import research_agent,pathlib,sys; '
                    'assert pathlib.Path(research_agent.__file__).is_relative_to(sys.prefix)'],env=clean,check=True)
    subprocess.run(command,env=environment,check=True)
    assert (prefix/'bin/python').stat().st_ino == stamp
    repeated = json.loads((root/jobs.RECORD).read_text())
    assert repeated['environments'][0]['binding'] == record['environments'][0]['binding']
    subprocess.run([python,str(root/'current/agent/scripts/uninstall.py'),'--install-root',str(root),
                    '--service-scope','none','--purge-all','--non-interactive','--yes','--json'],env=environment,check=True)
    assert not root.exists()
    assert not (tmp_path/'scientific').exists()


def test_remote_provisioning_transports_and_executes_real_helper_offline(tmp_path, monkeypatch):
    # Replace only SSH transport with a local shell in the runner's network
    # namespace. The bundle, target helper, Conda install and probe are real.
    conda = os.environ.get('CORAGENT_TEST_CONDA') or shutil.which('conda')
    assert conda
    profile = jobs.profiles(ROOT)['wrapper']
    content = jobs.resource(Path(profile['root']), profile['lock']).read_bytes()
    checksum = jobs.digest(content+b'\0')
    store = tmp_path/'target-store'
    request = {'store':str(store),'owner':'transport-fixture','offline':True,
               'binding':{'manager':'conda','conda_executable':conda,'prefix':str(store/('wrapper-'+checksum[:16])),
                          'lock_ref':str(store/'locks'/checksum/'wrapper.lock')},
               'files':{'wrapper.lock':base64.b64encode(content).decode()},
               'profile':{key:profile[key] for key in ('lock','platform')}}
    original = subprocess.run
    def ssh(command, **kwargs):
        assert command[0] == 'ssh'
        kwargs['env']['CONDA_PKGS_DIRS'] = os.environ['CONDA_PKGS_DIRS']
        return original(['/bin/sh','-c',command[-1]], **kwargs)
    monkeypatch.setattr(subprocess, 'run', ssh)
    for _ in range(2):
        result = jobs.invoke_target({'kind':'remote','ssh_host':'fixture'}, request, ROOT)
        assert result['status'] == 'environment_verified'
    assert not list(store.glob('.installer-*'))
