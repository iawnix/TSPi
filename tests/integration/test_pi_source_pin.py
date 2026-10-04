from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_pi_source_pin_is_explicit_and_uses_latest_durable_runtime() -> None:
    pin = json.loads((ROOT / "config/pi-source.json").read_text(encoding="utf-8"))
    assert pin == {
        "component": "pi-sdk-runtime",
        "repository": "https://github.com/earendil-works/pi.git",
        "tag": "v1.0.2",
        "commit": "cd32f7725fdbddbaecdff5b1e68491563394e0ca",
        "protocolVersion": 9,
    }
    patch = (ROOT / "config/pi-tspi-runtime.patch").read_text(encoding="utf-8")
    assert "PI_SESSION_WORKER_ENTRY" in patch
    assert "TSPI_PI_DIAGNOSTIC_FILE" in patch
    assert "workspaceId" in patch
    assert "session.sqlite" in patch


def test_prepare_pi_source_verifies_a_matching_checkout() -> None:
    configured = os.environ.get("TSPI_TEST_PI_RUNTIME_ROOT")
    if not configured or not Path(configured).is_dir():
        return
    result = subprocess.run(
        ["python3", str(ROOT / "scripts/prepare_pi_source.py"), "--verify", configured],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_prepare_pi_source_rejects_unpatched_checkout(tmp_path) -> None:
    source = tmp_path / "pi"
    source.mkdir()
    (source / ".git").mkdir()
    from scripts import prepare_pi_source
    original = prepare_pi_source.git
    try:
        prepare_pi_source.git = lambda *_args: prepare_pi_source.pin()["commit"]
        try:
            prepare_pi_source.verify(source)
        except prepare_pi_source.PiSourceError as error:
            assert "missing" in str(error)
        else:
            raise AssertionError("unpatched checkout was accepted")
    finally:
        prepare_pi_source.git = original
