from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from ts_agent.runtime.env import (
    RuntimeEnvironmentError,
    bind_runtime_process_environment,
    configured_python,
    default_env_prefix,
    default_env_store,
    default_runtime_home,
    package_root_from_file,
    python_payload_sha256,
    require_runtime_python,
    runtime_manifest_path,
    seed_installation_runtime,
    seed_installation_runtime_from_entrypoint,
    seed_workspace_root_from_argv,
    spec_sha256,
    write_manifest,
)
from ts_agent.runtime.probe import probe_runtime_capabilities
import ts_agent.runtime.cli as runtime_cli

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


def test_installed_current_entrypoint_seeds_installation_owned_runtime_paths(tmp_path: Path) -> None:
    installation = tmp_path / "tspi"
    package_home = installation / ".pi" / "packages" / "ts-agent"
    release = package_home / "releases" / "release-a"
    script = release / "scripts" / "ts_web.py"
    script.parent.mkdir(parents=True)
    script.write_text("# probe\n", encoding="utf-8")
    current = package_home / "current"
    current.symlink_to("releases/release-a", target_is_directory=True)
    environment: dict[str, str] = {}

    resolved = seed_installation_runtime_from_entrypoint(
        current / "scripts" / "ts_web.py",
        environ=environment,
    )

    runtime_home = installation / ".agents" / "runtime" / "transition-state-workflow"
    assert resolved == installation
    assert environment == {
        "TS_AGENT_RUNTIME_HOME": str(runtime_home),
        "TS_AGENT_RUNTIME_MANIFEST": str(runtime_home / "env.json"),
        "TS_AGENT_ENV_ROOT": str(
            installation / ".agents" / "envs" / "transition-state-workflow"
        ),
    }


@pytest.mark.parametrize("entrypoint_kind", ["launcher", "internal"])
def test_unified_suite_entrypoint_seeds_installation_owned_runtime_paths(
    tmp_path: Path,
    entrypoint_kind: str,
) -> None:
    installation = tmp_path / "tspi"
    package_home = installation / ".pi" / "packages" / "tspi"
    release = package_home / "releases" / "release-a"
    script = release / "agent" / "scripts" / "ts_web.py"
    script.parent.mkdir(parents=True)
    script.write_text("# probe\n", encoding="utf-8")
    current = package_home / "current"
    current.symlink_to("releases/release-a", target_is_directory=True)
    launcher = installation / "TSWeb"
    launcher.symlink_to(".pi/packages/tspi/current/agent/scripts/ts_web.py")
    entrypoint = (
        launcher
        if entrypoint_kind == "launcher"
        else current / "agent" / "scripts" / "ts_web.py"
    )
    environment: dict[str, str] = {}

    resolved = seed_installation_runtime_from_entrypoint(
        entrypoint,
        environ=environment,
    )

    runtime_home = installation / ".agents" / "runtime" / "transition-state-workflow"
    assert resolved == installation
    assert environment == {
        "TS_AGENT_RUNTIME_HOME": str(runtime_home),
        "TS_AGENT_RUNTIME_MANIFEST": str(runtime_home / "env.json"),
        "TS_AGENT_ENV_ROOT": str(
            installation / ".agents" / "envs" / "transition-state-workflow"
        ),
    }


def test_unified_suite_entrypoint_rejects_target_outside_managed_releases(
    tmp_path: Path,
) -> None:
    installation = tmp_path / "tspi"
    authored = installation / "checkout" / "scripts" / "ts_web.py"
    authored.parent.mkdir(parents=True)
    authored.write_text("# authored\n", encoding="utf-8")
    launcher = installation / "TSWeb"
    launcher.symlink_to("checkout/scripts/ts_web.py")
    environment: dict[str, str] = {}

    assert seed_installation_runtime_from_entrypoint(
        launcher,
        environ=environment,
    ) is None
    assert environment == {}


def test_runtime_path_seed_preserves_explicit_configuration_and_ignores_authored_path(
    tmp_path: Path,
) -> None:
    explicit = {
        "TS_AGENT_RUNTIME_HOME": "/configured/runtime",
        "TS_AGENT_RUNTIME_MANIFEST": "/configured/env.json",
        "TS_AGENT_ENV_ROOT": "/configured/envs",
    }
    stable = tmp_path / ".pi" / "packages" / "ts-agent" / "current" / "scripts" / "ts_web.py"

    assert seed_installation_runtime_from_entrypoint(stable, environ=explicit) == tmp_path
    assert explicit == {
        "TS_AGENT_RUNTIME_HOME": "/configured/runtime",
        "TS_AGENT_RUNTIME_MANIFEST": "/configured/env.json",
        "TS_AGENT_ENV_ROOT": "/configured/envs",
    }

    authored_environment: dict[str, str] = {}
    authored = tmp_path / "checkout" / "scripts" / "ts_web.py"
    assert seed_installation_runtime_from_entrypoint(
        authored,
        environ=authored_environment,
    ) is None
    assert authored_environment == {}


def test_authoritative_installation_seed_replaces_stale_runtime_paths(tmp_path: Path) -> None:
    environment = {
        "TS_AGENT_RUNTIME_HOME": "/stale/runtime",
        "TS_AGENT_RUNTIME_MANIFEST": "/stale/env.json",
        "TS_AGENT_ENV_ROOT": "/stale/envs",
    }

    seed_installation_runtime(tmp_path, environ=environment, authoritative=True)

    runtime_home = tmp_path / ".agents" / "runtime" / "transition-state-workflow"
    assert environment == {
        "TS_AGENT_RUNTIME_HOME": str(runtime_home),
        "TS_AGENT_RUNTIME_MANIFEST": str(runtime_home / "env.json"),
        "TS_AGENT_ENV_ROOT": str(tmp_path / ".agents" / "envs" / "transition-state-workflow"),
    }


def test_workspace_root_owns_runtime_home_and_env_store(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TS_AGENT_ENV_ROOT", raising=False)
    monkeypatch.delenv("TS_AGENT_RUNTIME_HOME", raising=False)
    workspace = tmp_path / "workspace"
    package = tmp_path / "pi" / "git" / "github.com" / "iawnix" / "TSPi"
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
    payload_sha256 = _write_test_python_payload(package)
    runtime_probe = _runtime_probe(payload_sha256=payload_sha256)
    manifest_path = write_manifest(
        package,
        {
            "schema_version": "ts-agent-runtime/1",
            "python_executable": sys.executable,
            "env_prefix": str(_probe_common_prefix(runtime_probe)),
            "spec_sha256": spec_sha256(package),
            "python_payload_sha256": payload_sha256,
            "runtime_probe": runtime_probe,
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
            "schema_version": "ts-agent-runtime/1",
            "python_executable": sys.executable,
            "spec_sha256": "stale",
        },
    )

    assert configured_python(package) is None


def test_configured_python_rejects_unprobed_or_external_modules(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    (package / "environment.yml").write_text("name: test\n", encoding="utf-8")
    payload_sha256 = _write_test_python_payload(package)
    env_prefix = tmp_path / "managed-env"
    python = env_prefix / "bin" / "python"
    numpy_origin = env_prefix / "lib" / "numpy.py"
    rdkit_origin = env_prefix / "lib" / "rdkit.py"
    for path in (python, numpy_origin, rdkit_origin):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# test runtime file\n", encoding="utf-8")
    base = {
        "schema_version": "ts-agent-runtime/1",
        "python_executable": str(python),
        "env_prefix": str(env_prefix),
        "spec_sha256": spec_sha256(package),
        "python_payload_sha256": payload_sha256,
    }
    write_manifest(package, {**base, "runtime_probe": {"ok": True}})
    assert configured_python(package) is None

    probe = _runtime_probe(payload_sha256=payload_sha256)
    probe["python"]["executable"] = str(python)
    probe["modules"]["numpy"]["origin"] = str(numpy_origin)
    probe["modules"]["rdkit"]["origin"] = str(rdkit_origin)
    probe["distribution"]["root"] = str(env_prefix)
    write_manifest(package, {**base, "runtime_probe": probe})
    assert configured_python(package) == python

    probe["distribution"]["version"] = "0.10.0"
    write_manifest(package, {**base, "runtime_probe": probe})
    assert configured_python(package) is None
    probe["distribution"]["version"] = "0.11.0"

    external_rdkit = tmp_path / "user-site" / "rdkit.py"
    external_rdkit.parent.mkdir()
    external_rdkit.write_text("# external test module\n", encoding="utf-8")
    probe["modules"]["rdkit"]["origin"] = str(external_rdkit)
    write_manifest(package, {**base, "runtime_probe": probe})
    assert configured_python(package) is None


def test_required_runtime_fails_closed_for_stale_manifest(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    (package / "environment.yml").write_text("name: test\n", encoding="utf-8")
    write_manifest(
        package,
        {
            "schema_version": "ts-agent-runtime/1",
            "python_executable": sys.executable,
            "spec_sha256": "stale",
        },
    )

    with pytest.raises(RuntimeEnvironmentError, match="missing or stale"):
        require_runtime_python(package)


def test_runtime_process_binding_owns_python_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    executable = Path(sys.executable).resolve()
    monkeypatch.setenv("PATH", f"/usr/bin{os.pathsep}{executable.parent}")
    monkeypatch.setenv("PYTHONHOME", "/tmp/foreign-python")
    monkeypatch.delenv("PYTHONNOUSERSITE", raising=False)

    bind_runtime_process_environment(executable)

    assert os.environ["TS_AGENT_PYTHON"] == str(executable)
    assert os.environ["PATH"].split(os.pathsep)[0] == str(executable.parent)
    assert os.environ["PATH"].split(os.pathsep).count(str(executable.parent)) == 1
    assert os.environ["PYTHONNOUSERSITE"] == "1"
    assert "PYTHONHOME" not in os.environ


def test_scientific_runtime_probe_exercises_rdkit_capabilities() -> None:
    result = probe_runtime_capabilities(require_distribution=False)

    assert result["schema_version"] == "ts-runtime-probe/2"
    assert result["ok"] is True
    assert result["capabilities"] == {
        "rdkit_smiles_parse": True,
        "rdkit_etkdg_embed": True,
        "rdkit_uff_optimize": True,
    }
    assert Path(result["modules"]["numpy"]["origin"]).is_file()
    assert Path(result["modules"]["rdkit"]["origin"]).is_file()


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
    assert payload["python_distribution"] == "ts-agent-kernel"
    assert payload["python_payload_sha256"] == python_payload_sha256(ROOT)


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


def test_ts_runtime_run_preserves_pythonpath_without_source_injection(monkeypatch) -> None:
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
    assert pythonpath == ["/tmp/existing"]


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
            "schema_version": "ts-agent-runtime/1",
            "python_executable": sys.executable,
            "env_prefix": str(Path(sys.executable).resolve().parent.parent),
            "spec_sha256": spec_sha256(ROOT),
            "python_payload_sha256": python_payload_sha256(ROOT),
            "runtime_probe": _runtime_probe(payload_sha256=python_payload_sha256(ROOT)),
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
    env = dict(os.environ)
    for name in (
        "TS_AGENT_PYTHON",
        "TS_AGENT_RUNTIME_HOME",
        "TS_AGENT_RUNTIME_MANIFEST",
        "TS_AGENT_ENV_ROOT",
    ):
        env.pop(name, None)
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
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["configured"] is False
    assert payload["manifest_path"] == str(workspace / ".agents" / "runtime" / "transition-state-workflow" / "env.json")
    assert payload["env_prefix"].startswith(str(workspace / ".agents" / "envs" / "transition-state-workflow"))


def _runtime_probe(*, payload_sha256: str | None = None) -> dict[str, object]:
    import numpy
    import rdkit

    executable = Path(sys.executable).resolve()
    numpy_origin = Path(numpy.__file__).resolve()
    rdkit_origin = Path(rdkit.__file__).resolve()
    prefix = Path(os.path.commonpath((executable, numpy_origin, rdkit_origin)))
    return {
        "schema_version": "ts-runtime-probe/2",
        "ok": True,
        "python": {"version": sys.version.split()[0], "executable": str(executable)},
        "distribution": {
            "name": "ts-agent-kernel",
            "installed": True,
            "version": "0.11.0",
            "root": str(prefix),
            "payload_sha256": payload_sha256 or python_payload_sha256(ROOT),
        },
        "modules": {
            "numpy": {"version": numpy.__version__, "origin": str(numpy_origin)},
            "rdkit": {"version": rdkit.__version__, "origin": str(rdkit_origin)},
        },
        "capabilities": {
            "rdkit_smiles_parse": True,
            "rdkit_etkdg_embed": True,
            "rdkit_uff_optimize": True,
        },
    }


def _write_test_python_payload(package: Path) -> str:
    source = package / "python" / "ts_agent"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text('"""test payload"""\n', encoding="utf-8")
    (package / "package.json").write_text(
        '{"name":"@iawnix/ts-agent","version":"0.11.0"}\n',
        encoding="utf-8",
    )
    return python_payload_sha256(package)


def _probe_common_prefix(probe: dict[str, object]) -> Path:
    python = probe["python"]
    modules = probe["modules"]
    paths = [python["executable"], *(module["origin"] for module in modules.values())]
    return Path(os.path.commonpath(paths))
