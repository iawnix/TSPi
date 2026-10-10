"""Per-case isolation and local failure evidence retention."""
from __future__ import annotations
import os
import hashlib
import shutil
from pathlib import Path
import pytest


@pytest.fixture
def tmp_path(request, tmp_path_factory):
    # Long test names must not consume the Unix-domain socket path budget.
    case='c'+hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:10]
    return tmp_path_factory.mktemp(case)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    result = yield
    setattr(item, 'report_' + result.get_result().when, result.get_result())


@pytest.fixture(autouse=True)
def restore_tmp_path_permissions(tmp_path: Path, request):
    yield
    for current, directories, files in os.walk(tmp_path, topdown=False):
        for name in files:
            path = Path(current) / name
            if not path.is_symlink(): path.chmod(0o600)
        for name in directories:
            path = Path(current) / name
            if not path.is_symlink(): path.chmod(0o700)
    if tmp_path.exists() and not tmp_path.is_symlink():
        tmp_path.chmod(0o700)
        reports = [getattr(request.node, 'report_' + phase, None) for phase in ('setup','call')]
        if all(report is not None and report.passed for report in reports):
            shutil.rmtree(tmp_path)


@pytest.fixture(autouse=True)
def isolate_installation_environment_paths(tmp_path, monkeypatch):
    monkeypatch.setenv('CORAGENT_HOST_ENV_ROOT', str(tmp_path / 'host-envs'))
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path / 'xdg'))
    previous = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(previous)
