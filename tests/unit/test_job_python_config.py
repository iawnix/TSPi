import importlib.util
from pathlib import Path
import pytest
from job_runtime.config_contract import validate_job_config, resolve_python, python_command


def binding(prefix):
    return {"manager": "conda", "conda_executable": "/opt/conda/bin/conda", "prefix": prefix, "lock_ref": "/opt/locks/python.lock"}


def config():
    return {"default_environment": "local", "environments": {
        "local": {"kind": "local"},
        "remote": {"kind": "remote", "submission": {"queue":"test"}, "python": binding("/opt/runner"), "backends": {
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


def test_skill_preparation_uses_bound_conda_and_rejects_dual_pyscf_binding(tmp_path):
    import json
    import tomllib
    import runpy
    helper = Path(__file__).resolve().parents[2] / "extensions/chemical/skills/method-selection/scripts/prepare_job.py"
    prepare = runpy.run_path(str(helper))["prepare"]
    path = tmp_path / "job.toml"
    text = '''default_environment = "remote"
[environments.remote]
kind = "remote"
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
    job = prepare(path, "remote", "xtb", "xtb", xyz, ["--task", "opt-sp"])
    assert "/opt/runner" in job["command"]
    assert job["platform"] == "remote"
    assert job["metadata"]["python_binding"]["lock_ref"] == "/opt/locks/runner.lock"
    path.write_text(text.replace('[environments.remote.backends.pyscf.python]', '[environments.remote.backends.pyscf]\ncommand = ["/old/python"]\n[environments.remote.backends.pyscf.python]'))
    with pytest.raises(ValueError, match="sole Python binding"):
        prepare(path, "remote", "pyscf", "cf22d", xyz, ["--task", "opt-sp"])


def test_example_and_python_binding_share_public_schema():
    import copy
    import json
    import tomllib
    from jsonschema import Draft202012Validator
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / 'config/job.schema.json').read_text())
    validator = Draft202012Validator(schema)
    example = tomllib.loads((root / 'config/compute.example.toml').read_text())
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
    monkeypatch.setattr('subprocess.run', lambda *a, **k: SimpleNamespace(stdout='@EXPLICIT\nhttps://example.test/wrong.conda\n'))
    with pytest.raises(ValueError, match='does not match'):
        installer(b, adopt=True)
    assert not (prefix / 'tspi-environment.json').exists()


def test_remote_queue_selection_is_explicit_and_allowlisted():
    from job_runtime.config_contract import resolve_submission
    c=config();remote=c['environments']['remote'];remote['allowed_queues']=['test']
    assert resolve_submission(c,'remote','xtb')['queue']=='test'
    remote['submission']['queue']='forbidden'
    with pytest.raises(ValueError,match='not allowed'):resolve_submission(c,'remote','xtb')
    del remote['submission']
    with pytest.raises(ValueError,match='queue_binding_missing'):resolve_submission(c,'remote','xtb')
