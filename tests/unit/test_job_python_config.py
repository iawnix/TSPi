import importlib.util
from pathlib import Path
import pytest
from research_agent.jobs.config_contract import validate_job_config, resolve_python, python_command


def binding(prefix):
    return {"manager": "conda", "conda_executable": "/opt/conda/bin/conda", "prefix": prefix, "lock_ref": "/opt/locks/python.lock"}


def config():
    return {"default_environment": "local", "environments": {
        "local": {"kind": "local"},
        "remote": {"kind": "remote", "ssh_host": "fixture", "remote_root": "/scratch/jobs", "submission": {"queue":"test"}, "python": binding("/opt/runner"), "backends": {
            "xtb": {"command": ["/opt/xtb"]}, "pyscf": {"python": binding("/opt/cf22d")}}}}}


def test_conda_selection_and_host_python_isolation():
    c = validate_job_config(config())
    assert resolve_python(c, "remote", "xtb")["prefix"] == "/opt/runner"
    assert resolve_python(c, "remote", "pyscf")["prefix"] == "/opt/cf22d"
    command = python_command(resolve_python(c, "remote", "xtb"))
    assert command[:6] == ["env", "-u", "PYTHONHOME", "-u", "PYTHONPATH", "PYTHONNOUSERSITE=1"]
    assert command[-3:] == ["-p", "/opt/runner", "python"]


def test_legacy_interpreter_is_not_a_second_configuration_protocol():
    c = config(); c["environments"]["remote"]["python"] = "/usr/bin/python3"
    with pytest.raises(ValueError, match="migrate legacy"):
        validate_job_config(c)


def test_skill_preparation_uses_bound_conda_and_rejects_dual_pyscf_binding(tmp_path, mock_environment_probe):
    import json
    import tomllib
    from research_agent.application.executors import prepare
    path = tmp_path / "job.toml"
    text = '''default_environment = "remote"
[environments.remote]
kind = "remote"
ssh_host = "fixture"
remote_root = "/scratch/jobs"
[environments.remote.submission]
queue = "test"
[environments.remote.python]
manager = "conda"
conda_executable = "/opt/conda/bin/conda"
prefix = "/opt/runner"
lock_ref = "/opt/locks/runner.lock"
[environments.remote.backends.xtb]
command = ["/opt/xtb"]
[environments.remote.backends.pyscf.python]
manager = "conda"
conda_executable = "/opt/conda/bin/conda"
prefix = "/opt/cf22d"
lock_ref = "/opt/locks/cf22d.lock"
'''
    path.write_text(text)
    xyz = tmp_path / "water.xyz"; xyz.write_text("1\nH\nH 0 0 0\n")
    job = prepare(path, "remote", "chemical.xtb", "1", {"geometry": xyz}, ["--task", "opt-sp"])
    assert "/opt/runner" in job["command"]
    assert job["platform"] == "remote"
    assert job["metadata"]["python_binding"]["lock_ref"] == "/opt/locks/runner.lock"
    with pytest.raises(ValueError, match="runner_arguments_invalid.*",):
        prepare(path, "remote", "chemical.xtb", "1", {"geometry": xyz}, ["--task", "opt-sp", "--method", "GFN2-xTB"])
    with pytest.raises(ValueError, match="owned by the execution descriptor"):
        prepare(path, "remote", "chemical.xtb", "1", {"geometry": xyz}, ["--task", "sp", "--output-dir", "/tmp/escaped"])
    path.write_text(text.replace('[environments.remote.backends.pyscf.python]', '[environments.remote.backends.pyscf]\ncommand = ["/old/python"]\n[environments.remote.backends.pyscf.python]'))
    with pytest.raises(ValueError, match="executor_binding_unused_command"):
        prepare(path, "remote", "chemical.cf22d", "1", {"geometry": xyz}, ["--task", "opt-sp"])


def test_example_and_python_binding_share_public_schema():
    import copy
    import json
    import tomllib
    from jsonschema import Draft202012Validator
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / 'config/job.schema.json').read_text())
    from research_agent.jobs.config_contract import job_config_schema
    assert schema == job_config_schema()
    validator = Draft202012Validator(schema)
    example = tomllib.loads((root / 'config/job.example.toml').read_text())
    validator.validate(example)
    validate_job_config(example)
    inherited = copy.deepcopy(example)
    inherited['environments']['remote']['backends']['pyscf'] = {}
    validator.validate(inherited)
    validate_job_config(inherited)
    assert resolve_python(inherited, 'remote', 'pyscf') == inherited['environments']['remote']['python']
    for invalid in ['/usr/bin/python3', {**binding('/opt/env'), 'manager': 'venv'},
                    {**binding('/opt/env'), 'prefix': 'relative'}, {**binding('/opt/env'), 'extra': True}]:
        c = copy.deepcopy(example)
        c['environments']['remote']['python'] = invalid
        assert list(validator.iter_errors(c))
        with pytest.raises(ValueError):
            validate_job_config(c)


def test_installer_refuses_unverified_prefix_and_does_not_publish_bad_receipt(tmp_path, monkeypatch):
    import runpy
    from types import SimpleNamespace
    root = Path(__file__).resolve().parents[2]
    installer = runpy.run_path(str(root / 'scripts/install_job_environment.py'))['install']
    prefix = tmp_path / 'science'; prefix.mkdir()
    lock = tmp_path / 'science.lock'; lock.write_text('@EXPLICIT\nhttps://example.test/python.conda\n')
    b = {**binding(str(prefix)), 'lock_ref': str(lock)}
    with pytest.raises(ValueError, match='no matching environment receipt'):
        installer(b)
    monkeypatch.setattr('subprocess.run', lambda *a, **k: SimpleNamespace(stdout='@EXPLICIT\nhttps://example.test/wrong.conda\n', returncode=0))
    with pytest.raises(ValueError, match='does not match'):
        installer(b, adopt=True)
    assert not (prefix / 'coragent-environment.json').exists()


def test_failed_new_install_removes_only_its_partial_prefix(tmp_path, monkeypatch):
    import runpy
    import subprocess
    root = Path(__file__).resolve().parents[2]
    installer = runpy.run_path(str(root / 'scripts/install_job_environment.py'))['install']
    prefix = tmp_path/'partial'
    lock = tmp_path/'science.lock'
    lock.write_text('@EXPLICIT\nhttps://example.test/python.conda#' + 'a'*64 + '\n')
    def broken_install(argv, **kwargs):
        assert argv[1] == 'create'
        prefix.mkdir()
        (prefix/'partial-file').write_text('interrupted installation')
        raise subprocess.CalledProcessError(1, argv)
    monkeypatch.setattr('subprocess.run', broken_install)
    with pytest.raises(subprocess.CalledProcessError):
        installer({**binding(str(prefix)), 'lock_ref':str(lock)})
    assert not prefix.exists() and lock.exists()


@pytest.mark.parametrize('contents', ['package==1.0\n', 'package>=1.0 --hash=sha256:'+'a'*64+'\n'])
def test_pip_install_requires_pinned_versions_and_hashes_before_creating_prefix(tmp_path, monkeypatch, contents):
    import runpy
    root = Path(__file__).resolve().parents[2]
    installer = runpy.run_path(str(root/'scripts/install_job_environment.py'))['install']
    lock = tmp_path/'science.lock'; lock.write_text('@EXPLICIT\nhttps://example.test/python.conda\n')
    lock.with_suffix('.requirements.txt').write_text(contents)
    monkeypatch.setattr('subprocess.run', lambda *a, **kw: pytest.fail('invalid lock must fail before installation'))
    with pytest.raises(ValueError, match='environment_pip_lock_invalid'):
        installer({**binding(str(tmp_path/'science')), 'lock_ref':str(lock)})
    assert not (tmp_path/'science').exists()


def test_remote_queue_selection_is_explicit_and_allowlisted():
    from research_agent.jobs.config_contract import resolve_submission
    c=config();remote=c['environments']['remote'];remote['allowed_queues']=['test']
    assert resolve_submission(c,'remote','xtb')['queue']=='test'
    remote['submission']['queue']='forbidden'
    with pytest.raises(ValueError,match='not allowed'):resolve_submission(c,'remote','xtb')
    del remote['submission']
    with pytest.raises(ValueError,match='queue_binding_missing'):resolve_submission(c,'remote','xtb')


@pytest.mark.parametrize('mutate', [
    lambda target: target.update(ssh_host='-oProxyCommand=bad'),
    lambda target: target.update(remote_root='/scratch/../other'),
    lambda target: target.update(scheduler='slurm'),
    lambda target: target.update(command_timeout_seconds=0),
    lambda target: target.update(max_nodes=2),
    lambda target: target.update(commands={'pbsnodes': 'pbsnodes'}),
    lambda target: target['backends']['xtb'].update(requires_gpu=False),
    lambda target: target['backends']['xtb'].update(allowed_queues=['bad queue']),
])
def test_runtime_and_generated_schema_reject_invalid_remote_settings(mutate):
    from jsonschema import Draft202012Validator
    from research_agent.jobs.config_contract import job_config_schema
    value = config(); mutate(value['environments']['remote'])
    with pytest.raises(ValueError): validate_job_config(value)
    assert list(Draft202012Validator(job_config_schema()).iter_errors(value))


def test_platform_selection_has_no_implicit_local_or_remote_alias(tmp_path, monkeypatch):
    from research_agent.jobs.config import platforms_from_config
    monkeypatch.delenv('CORAGENT_JOB_CONFIG', raising=False)
    with pytest.raises(ValueError, match='job_config_required'): platforms_from_config()
    path = tmp_path / 'remote.toml'
    path.write_text('default_environment="cluster_a"\n[environments.cluster_a]\nkind="remote"\nssh_host="fixture"\nremote_root="/scratch/jobs"\n')
    platforms, default = platforms_from_config(path)
    assert set(platforms) == {'cluster_a'} and default == 'cluster_a'


def test_local_supervisor_is_explicit_and_part_of_prepared_binding(tmp_path):
    from research_agent.jobs.config_contract import resolve_binding, binding_digest
    from research_agent.jobs.config import platforms_from_config
    settings = config()
    settings['environments']['local']['backends'] = {'shell': {'command': '/bin/sh'}}
    baseline = resolve_binding(settings, 'local', 'shell', runtime='native')
    assert baseline['supervisor'] == 'systemd'
    settings['environments']['local']['supervisor'] = 'process'
    selected = resolve_binding(validate_job_config(settings), 'local', 'shell', runtime='native')
    assert selected['supervisor'] == 'process'
    assert binding_digest(selected) != binding_digest(baseline)
    path = tmp_path / 'process.toml'
    path.write_text('default_environment="local"\n[environments.local]\nkind="local"\nsupervisor="process"\n')
    platforms, _ = platforms_from_config(path)
    assert platforms['local'].supervisor == 'process'
    settings['environments']['remote']['supervisor'] = 'process'
    with pytest.raises(ValueError, match='local supervisor'):
        validate_job_config(settings)
