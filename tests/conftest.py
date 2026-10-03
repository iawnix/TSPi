"""Shared pytest hygiene for tests that exercise read-only release trees."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def pytest_sessionstart(session: pytest.Session) -> None:
    """Load first-party Providers at the application boundary for tests.

    ``research_compute`` deliberately does not import Chemistry.  Production
    launchers register extensions during bootstrap, so tests that exercise the
    complete compute lifecycle must perform the same explicit bootstrap.
    """

    from scripts._bootstrap import register_first_party_providers

    register_first_party_providers(ROOT)


@pytest.fixture(autouse=True)
def restore_tmp_path_permissions(tmp_path: Path):
    """Make pytest's temporary directory removable after permission tests.

    Release validation tests intentionally harden files and directories to
    owner-read/execute modes.  pytest removes ``tmp_path`` after fixture
    teardown, so restore write access here while the tree is still available.
    """

    yield
    for current, directories, files in os.walk(tmp_path, topdown=False):
        for name in files:
            path = Path(current) / name
            if not path.is_symlink():
                path.chmod(0o600)
        for name in directories:
            path = Path(current) / name
            if not path.is_symlink():
                path.chmod(0o700)
    if tmp_path.exists() and not tmp_path.is_symlink():
        tmp_path.chmod(0o700)
        # Keep long source-test runs bounded.  pytest's session-level
        # retention is useful for debugging, but these tests create large
        # release archives and no longer need them after each case passes.
        shutil.rmtree(tmp_path)
