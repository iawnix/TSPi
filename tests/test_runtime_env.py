from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ts_runtime.env import configured_python, default_env_prefix, default_env_store, spec_sha256, write_manifest
import ts_runtime.cli as runtime_cli

ROOT = Path(__file__).resolve().parents[1]


def test_default_env_prefix_is_spec_hash_scoped(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    (package / "environment.yml").write_text("name: test\n", encoding="utf-8")

    prefix = default_env_prefix(package, tmp_path / "envs")

    assert prefix.parent == tmp_path / "envs"
    assert prefix.name == spec_sha256(package)[:12]


def test_default_env_store_is_package_relative_without_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TS_AGENT_ENV_ROOT", raising=False)
    package = tmp_path / "skill"
    package.mkdir()

    store = default_env_store(package)

    assert store == tmp_path / ".envs" / "transition-state-workflow"


def test_configured_python_reads_runtime_manifest(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    (package / "environment.yml").write_text("name: test\n", encoding="utf-8")
    write_manifest(
        package,
        {
            "schema_version": "ts-agent-runtime-v1",
            "python_executable": sys.executable,
            "spec_sha256": spec_sha256(package),
        },
    )

    assert configured_python(package) == Path(sys.executable).resolve()


def test_configured_python_ignores_stale_runtime_manifest(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    (package / "environment.yml").write_text("name: test\n", encoding="utf-8")
    write_manifest(
        package,
        {
            "schema_version": "ts-agent-runtime-v1",
            "python_executable": sys.executable,
            "spec_sha256": "stale",
        },
    )

    assert configured_python(package) is None


def test_install_env_dry_run_reports_hashed_prefix(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "install_env.py"),
            "--package-root",
            str(ROOT),
            "--env-root",
            str(tmp_path / "envs"),
            "--dry-run",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["action"] == "create"
    assert payload["dry_run"] is True
    assert payload["env_prefix"].startswith(str(tmp_path / "envs"))
    assert payload["python_executable"].endswith("/bin/python")


def test_install_env_accepts_user_conda_root(tmp_path: Path) -> None:
    conda_root = tmp_path / "miniforge"
    conda_bin = conda_root / "bin"
    conda = conda_bin / "conda"
    conda_bin.mkdir(parents=True)
    conda.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    conda.chmod(0o755)

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "install_env.py"),
            "--package-root",
            str(ROOT),
            "--env-root",
            str(tmp_path / "envs"),
            "--conda-root",
            str(conda_root),
            "--dry-run",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["conda_root"] == str(conda_root)
    assert payload["conda_executable"] == str(conda)


def test_ts_runtime_run_injects_skill_root_into_pythonpath(monkeypatch) -> None:
    calls: dict[str, object] = {}

    monkeypatch.setattr(runtime_cli, "configured_python", lambda root: Path(sys.executable).resolve())
    monkeypatch.setenv("PYTHONPATH", "/tmp/existing")

    def fake_execve(path, argv, env):
        calls["path"] = path
        calls["argv"] = argv
        calls["env"] = env
        raise SystemExit(0)

    monkeypatch.setattr(runtime_cli.os, "execve", fake_execve)

    with pytest.raises(SystemExit):
        runtime_cli.run_in_runtime(ROOT, ["tools/monitor.py", "--root", "/tmp/ws"])

    assert calls["path"] == str(Path(sys.executable).resolve())
    assert calls["argv"] == [str(Path(sys.executable).resolve()), "tools/monitor.py", "--root", "/tmp/ws"]
    pythonpath = str(calls["env"]["PYTHONPATH"]).split(os.pathsep)
    assert pythonpath[0] == str(ROOT)
    assert "/tmp/existing" in pythonpath


def test_ts_runtime_script_passes_dash_m_arguments() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "ts_runtime.py"),
            "run",
            "-c",
            "print('runtime-ok')",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    assert completed.stdout.strip() == "runtime-ok"
