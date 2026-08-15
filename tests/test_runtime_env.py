from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from ts_runtime.env import (
    configured_python,
    default_env_prefix,
    default_env_store,
    default_runtime_home,
    package_root_from_file,
    runtime_manifest_path,
    seed_workspace_root_from_argv,
    spec_sha256,
    write_manifest,
)
import ts_runtime.cli as runtime_cli

ROOT = Path(__file__).resolve().parents[1]


def test_package_root_detection_uses_package_markers_with_nested_skill(tmp_path: Path) -> None:
    package = tmp_path / "package"
    source_file = package / "src" / "agents" / "compute" / "runtime.ts"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("export {};\n", encoding="utf-8")
    (package / "scripts").mkdir()
    skill = package / "skills" / "transition-state-workflow" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: transition-state-workflow\ndescription: test\n---\n", encoding="utf-8")
    (package / "package.json").write_text("{}\n", encoding="utf-8")

    assert package_root_from_file(source_file) == package


def test_default_env_prefix_is_spec_hash_scoped(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    (package / "environment.yml").write_text("name: test\n", encoding="utf-8")

    prefix = default_env_prefix(package, tmp_path / "envs")

    assert prefix.parent == tmp_path / "envs"
    assert prefix.name == spec_sha256(package)[:12]


def test_default_env_store_is_package_relative_without_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TS_AGENT_ENV_ROOT", raising=False)
    monkeypatch.delenv("TS_WORKSPACE_ROOT", raising=False)
    package = tmp_path / "skill"
    package.mkdir()

    store = default_env_store(package)

    assert store == tmp_path / ".envs" / "transition-state-workflow"


def test_workspace_root_owns_runtime_home_and_env_store(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TS_AGENT_ENV_ROOT", raising=False)
    monkeypatch.delenv("TS_AGENT_RUNTIME_HOME", raising=False)
    workspace = tmp_path / "workspace"
    package = tmp_path / "pi" / "git" / "github.com" / "iawnix" / "TSAgentSkill"
    workspace.mkdir()
    package.mkdir(parents=True)
    (package / "environment.yml").write_text("name: test\n", encoding="utf-8")

    assert default_runtime_home(package, workspace) == workspace / ".agents" / "runtime" / "transition-state-workflow"
    assert default_env_store(package, workspace) == workspace / ".agents" / "envs" / "transition-state-workflow"
    assert runtime_manifest_path(package, workspace_root=workspace) == workspace / ".agents" / "runtime" / "transition-state-workflow" / "env.json"


def test_configured_python_reads_runtime_manifest(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    (package / "environment.yml").write_text("name: test\n", encoding="utf-8")
    manifest_path = write_manifest(
        package,
        {
            "schema_version": "ts-agent-runtime-v1",
            "python_executable": sys.executable,
            "spec_sha256": spec_sha256(package),
        },
    )

    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o600
    assert configured_python(package) == Path(sys.executable).resolve()


def test_seed_workspace_root_from_argv_sets_runtime_env(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    monkeypatch.delenv("TS_WORKSPACE_ROOT", raising=False)

    seed_workspace_root_from_argv(["report_workspace", "--root", str(workspace)])

    try:
        assert os.environ["TS_WORKSPACE_ROOT"] == str(workspace)
    finally:
        os.environ.pop("TS_WORKSPACE_ROOT", None)


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
    assert payload["manifest_path"].endswith("/.runtime/transition-state-workflow/env.json")
    assert payload["python_executable"].endswith("/bin/python")


def test_install_env_dry_run_accepts_workspace_runtime_home(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "install_env.py"),
            "--package-root",
            str(ROOT),
            "--workspace-root",
            str(workspace),
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

    assert payload["runtime_home"] == str(workspace / ".agents" / "runtime" / "transition-state-workflow")
    assert payload["manifest_path"] == str(workspace / ".agents" / "runtime" / "transition-state-workflow" / "env.json")
    assert payload["env_prefix"].startswith(str(workspace / ".agents" / "envs" / "transition-state-workflow"))


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


def test_ts_runtime_isolated_run_strips_workspace_runtime_context(monkeypatch) -> None:
    calls: dict[str, object] = {}
    runtime_values = {
        "TS_WORKSPACE_ROOT": "/tmp/live-workspace",
        "TS_AGENT_PYTHON": "/tmp/override-python",
        "TS_AGENT_DISABLE_RUNTIME_REEXEC": "1",
        "TS_AGENT_ENV_ROOT": "/tmp/live-envs",
        "TS_AGENT_RUNTIME_HOME": "/tmp/live-runtime",
        "TS_AGENT_RUNTIME_MANIFEST": "/tmp/live-runtime/env.json",
    }
    for name, value in runtime_values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(runtime_cli, "configured_python", lambda root: Path(sys.executable).resolve())

    def fake_execve(path, argv, env):
        calls["env"] = env
        raise SystemExit(0)

    monkeypatch.setattr(runtime_cli.os, "execve", fake_execve)

    with pytest.raises(SystemExit):
        runtime_cli.run_in_runtime(ROOT, ["-m", "pytest"], isolate_runtime_context=True)

    child_env = calls["env"]
    assert isinstance(child_env, dict)
    assert all(name not in child_env for name in runtime_values)


def test_ts_runtime_isolated_run_cannot_modify_workspace_manifest(tmp_path: Path) -> None:
    workspace = tmp_path / "live-workspace"
    workspace.mkdir()
    manifest = write_manifest(
        ROOT,
        {
            "schema_version": "ts-agent-runtime-v1",
            "python_executable": sys.executable,
            "spec_sha256": spec_sha256(ROOT),
        },
        workspace_root=workspace,
    )
    before = manifest.read_bytes()
    env = dict(os.environ)
    env["TS_WORKSPACE_ROOT"] = str(workspace)

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "ts_runtime.py"),
            "run-isolated",
            "-m",
            "pytest",
            "-q",
            "tests/test_runtime_env.py::test_configured_python_ignores_stale_runtime_manifest",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert manifest.read_bytes() == before


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


def test_ts_runtime_resolve_reports_external_manifest_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "ts_runtime.py"),
            "resolve",
            "--workspace-root",
            str(workspace),
            "--json",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["configured"] is False
    assert payload["manifest_path"] == str(workspace / ".agents" / "runtime" / "transition-state-workflow" / "env.json")
    assert payload["env_prefix"].startswith(str(workspace / ".agents" / "envs" / "transition-state-workflow"))
