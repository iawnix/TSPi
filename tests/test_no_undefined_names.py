"""Static guard against undefined names (used-but-not-imported).

Three call-time ``NameError``s once slipped through a refactor because the code
that *used* a name and the import that *provided* it lived in different files,
and neither ``py_compile`` nor ``import`` catches a name referenced inside a
function body that is never reached at import time. pyflakes' F821 does.

This test runs pyflakes over the package source and fails on any undefined name
(F821) or redefinition (F811). It skips cleanly if pyflakes is not installed, so
it never blocks a machine without dev tooling — but on CI it is the backstop.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
SRC = SKILL_ROOT / "src"


def _pyflakes_available() -> bool:
    try:
        import pyflakes  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(not _pyflakes_available(), reason="pyflakes not installed")
def test_no_undefined_names_in_package() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pyflakes", str(SRC)],
        check=False,
        text=True,
        capture_output=True,
    )
    # pyflakes prints one line per finding; we only fail on the serious classes.
    serious = [
        line
        for line in result.stdout.splitlines()
        if "undefined name" in line or "redefinition" in line
    ]
    assert not serious, "pyflakes found undefined names / redefinitions:\n" + "\n".join(serious)
