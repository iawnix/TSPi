from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pi_source_pin_is_explicit_and_valid() -> None:
    pin = json.loads((ROOT / "config" / "pi-source.json").read_text(encoding="utf-8"))
    assert pin["repository"] == "https://github.com/earendil-works/pi.git"
    assert pin["tag"] == "v0.85.1"
    assert len(pin["commit"]) == 40
    assert pin["commit"] == "d981de1229ef899957bbe968bc8dcda02a21f477"
    assert pin["protocolVersion"] == 8
    patch = (ROOT / "config" / "pi-worker-entry.patch").read_text(encoding="utf-8")
    assert "PI_SESSION_WORKER_ENTRY" in patch
    assert "packages/coding-agent/src/experimental/process.ts" in patch
    resolver_patch = (ROOT / "config" / "pi-source-resolver.patch").read_text(encoding="utf-8")
    assert "source-resolver.ts" in resolver_patch
    assert "resolveTypeboxPath" in resolver_patch


def test_prepare_pi_source_verifies_a_matching_checkout() -> None:
    configured = os.environ.get("TSPI_PI_SOURCE")
    if not configured:
        return
    source = Path(configured)
    if not source.is_dir():
        return
    result = subprocess.run(
        ["python3", str(ROOT / "scripts" / "prepare_pi_source.py"), "--verify", str(source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_prepare_runtime_build_is_idempotent(tmp_path, monkeypatch):
    from scripts import prepare_pi_source

    monkeypatch.setattr(prepare_pi_source.shutil, "which", lambda name: "/bin/npm")
    calls = []

    def run(command, **kwargs):
        calls.append(command[2])
        outputs = ["packages/ai/src/providers/data/amazon-bedrock.json"] if command[2] == "hydrate:model-data" else ["packages/chord/dist/index.js", "packages/coding-agent/dist/bundle"]
        for output in outputs:
            path = tmp_path / output
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

    monkeypatch.setattr(prepare_pi_source.subprocess, "run", run)
    prepare_pi_source._prepare_runtime_build(tmp_path)
    prepare_pi_source._prepare_runtime_build(tmp_path)
    assert calls == ["hydrate:model-data", "build:offline"]
