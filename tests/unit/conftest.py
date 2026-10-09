from __future__ import annotations

import pytest
import json
import shlex
import sys
import venv
import runpy
from pathlib import Path


@pytest.fixture(autouse=True)
def execution_platform_fixture(tmp_path, monkeypatch):
    """Give unit tests an explicit local environment without production fallbacks."""

    config = tmp_path / "job.toml"
    conda = tmp_path / "fixture-conda"
    prefix = tmp_path / "target-python"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(prefix)
    site = next(prefix.glob('lib/python*/site-packages'))
    # Wheel tests import scientific dependencies from the base and ResearchAgent from
    # the overlay. Keep both installed package directories in this test target.
    packages = [path for path in sys.path if Path(path).name in {'site-packages', 'dist-packages'}]
    (site / 'fixture-packages.pth').write_text('\n'.join(packages) + '\n')
    lock = tmp_path / "fixture.lock"
    lock.write_text('@EXPLICIT\nhttps://fixture.invalid/python.conda\n')
    conda.write_text("#!/bin/sh\nset -eu\nif [ \"$1\" = list ]; then cat " + shlex.quote(str(lock)) +
                     "; else shift 5; exec " + shlex.quote(str(prefix / 'bin/python')) + ' "$@"; fi\n')
    conda.chmod(0o700)
    install = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts/install_job_environment.py'))['install']
    install({'manager': 'conda', 'conda_executable': str(conda), 'prefix': str(prefix), 'lock_ref': str(lock)}, adopt=True)
    config.write_text(
        """default_environment = \"local\"

[environments.local]
kind = \"local\"
supervisor = \"process\"

[environments.local.backends.validation]
[environments.local.backends.validation.python]
manager = "conda"
conda_executable = CONDA_PATH
prefix = PYTHON_PREFIX
lock_ref = LOCK_PATH

[environments.local.backends.structure.python]
manager = "conda"
conda_executable = CONDA_PATH
prefix = PYTHON_PREFIX
lock_ref = LOCK_PATH

[environments.local.backends.gaussian]
command = \"g16\"

[environments.local.backends.xtb]
command = \"xtb\"

[environments.local.backends.crest]
command = \"crest\"

[environments.local.backends.ase_neb_xtb]
command = \"xtb\"
""".replace("CONDA_PATH", json.dumps(str(conda))).replace("PYTHON_PREFIX", json.dumps(str(prefix)))
        .replace("LOCK_PATH", json.dumps(str(tmp_path / "fixture.lock"))),
        encoding="utf-8",
    )
    monkeypatch.setenv("RESEARCH_AGENT_JOB_CONFIG", str(config))


@pytest.fixture
def mock_environment_probe(monkeypatch):
    """Routing-only tests use nonexistent hosts; guard behavior has real tests."""
    import importlib
    from research_agent.jobs.config_contract import binding_digest
    # Load every module that holds an alias before replacing the original.
    # Otherwise a lazy import can retain the fake after monkeypatch teardown.
    modules = [importlib.import_module(name) for name in (
        'research_agent.jobs.environment',
        'research_agent.application.executors',
        'research_agent.application.execution_environment',
        'research_agent.application.environment_check',
    )]
    def probe(settings, selected, requirements):
        observation = {"files": {}, "python": {"fixture": "routing-only"}}
        return {"schema_version": "job-environment/1", "requirements": requirements,
                "observation": observation, "sha256": binding_digest(observation)}
    for module in modules:
        monkeypatch.setattr(module, 'probe_binding', probe)
