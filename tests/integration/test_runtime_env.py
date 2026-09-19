from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from ts_agent.runtime.env import (
    PACKAGE_ROOT_OVERRIDE,
    RuntimeEnvironmentError,
    bind_runtime_process_environment,
    configured_python,
    default_env_prefix,
    default_env_store,
    default_kernel_prefix,
    default_runtime_home,
    package_root_from_file,
    python_payload_sha256,
    require_runtime_python,
    resolve_package_root,
    runtime_manifest_path,
    seed_installation_runtime,
    seed_installation_runtime_from_entrypoint,
    seed_workspace_root_from_argv,
    spec_sha256,
    write_manifest,
)
import ts_agent.runtime.probe as runtime_probe_module
import ts_agent.runtime.cli as runtime_cli
from ts_agent.runtime.probe import probe_runtime_capabilities
from scripts import _runtime_install as runtime_install
from scripts._bootstrap import bootstrap_python_package

ROOT = Path(__file__).resolve().parents[2]


def _write_runtime_specs(package: Path) -> None:
    (package / "environment.yml").write_text("name: test\n", encoding="utf-8")
    (package / "requirements-runtime.txt").write_text(
        "xyzrender>=0.2.1\n",
        encoding="utf-8",
    )


def test_resolve_package_root_honors_process_binding(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "package"
    monkeypatch.setenv(PACKAGE_ROOT_OVERRIDE, str(package))

    assert resolve_package_root() == package.resolve()


def test_package_bootstrap_replaces_an_inherited_package_root(monkeypatch) -> None:
    monkeypatch.setenv(PACKAGE_ROOT_OVERRIDE, "/tmp/other-tspi-release")
    monkeypatch.setenv("TS_AGENT_DISABLE_RUNTIME_REEXEC", "1")

    bootstrap_python_package(ROOT)

    assert os.environ[PACKAGE_ROOT_OVERRIDE] == str(ROOT)


def test_package_root_detection_uses_package_markers_with_nested_skill(tmp_path: Path) -> None:
    package = tmp_path / "package"
    source_file = package / "packages" / "ts-agent-runtime" / "agents" / "compute" / "runtime.ts"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("export {};\n", encoding="utf-8")
    (package / "scripts").mkdir()
    skill = package / "skills" / "tspi-research-kernel" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: tspi-research-kernel\ndescription: test\n---\n", encoding="utf-8")
    (package / "package.json").write_text("{}\n", encoding="utf-8")

    assert package_root_from_file(source_file) == package


def test_default_env_prefix_is_spec_hash_scoped(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    _write_runtime_specs(package)

    prefix = default_env_prefix(package, tmp_path / "envs")

    assert prefix.parent == tmp_path / "envs" / "base"
    assert prefix.name == spec_sha256(package)[:12]


def test_scientific_base_hash_covers_conda_and_pip_specs(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    _write_runtime_specs(package)
    initial = spec_sha256(package)

    (package / "requirements-runtime.txt").write_text(
        "xyzrender>=0.3\n",
        encoding="utf-8",
    )

    assert spec_sha256(package) != initial


def test_repository_conda_spec_does_not_delegate_runtime_pip_installation() -> None:
    conda_spec = (ROOT / "environment.yml").read_text(encoding="utf-8")
    pip_requirements = (ROOT / "requirements-runtime.txt").read_text(encoding="utf-8")

    assert "\n  - pip:" not in conda_spec
    assert "xyzrender>=0.2.1" in pip_requirements.splitlines()


def test_default_kernel_prefix_is_python_payload_scoped(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    _write_runtime_specs(package)
    payload_sha256 = _write_test_python_payload(package)

    prefix = default_kernel_prefix(package, tmp_path / "envs")

    assert prefix.parent == tmp_path / "envs" / "kernels"
    assert prefix.name == payload_sha256[:16]


def test_default_env_store_is_package_relative_without_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TS_AGENT_ENV_ROOT", raising=False)
    monkeypatch.delenv("TS_WORKSPACE_ROOT", raising=False)
    package = tmp_path / "skill"
    package.mkdir()

    store = default_env_store(package)

    assert store == tmp_path / ".envs" / "tspi"


def test_installed_current_entrypoint_seeds_installation_owned_runtime_paths(tmp_path: Path) -> None:
    installation = tmp_path / "tspi"
    package_home = installation / ".pi" / "packages" / "tspi"
    release = package_home / "releases" / "release-a"
    script = release / "web" / "bin" / "ts-web"
    script.parent.mkdir(parents=True)
    script.write_text("# probe\n", encoding="utf-8")
    current = package_home / "current"
    current.symlink_to("releases/release-a", target_is_directory=True)
    environment: dict[str, str] = {}

    resolved = seed_installation_runtime_from_entrypoint(
        current / "web" / "bin" / "ts-web",
        environ=environment,
    )

    runtime_home = installation / ".agents" / "runtime" / "tspi"
    assert resolved == installation
    assert environment == {
        "TS_AGENT_RUNTIME_HOME": str(runtime_home),
        "TS_AGENT_RUNTIME_MANIFEST": str(runtime_home / "env.json"),
        "TS_AGENT_ENV_ROOT": str(
            installation / ".agents" / "envs" / "tspi"
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
    script = release / "web" / "bin" / "ts-web"
    script.parent.mkdir(parents=True)
    script.write_text("# probe\n", encoding="utf-8")
    current = package_home / "current"
    current.symlink_to("releases/release-a", target_is_directory=True)
    launcher = installation / "TSWeb"
    launcher.symlink_to(".pi/packages/tspi/current/web/bin/ts-web")
    entrypoint = (
        launcher
        if entrypoint_kind == "launcher"
        else current / "web" / "bin" / "ts-web"
    )
    environment: dict[str, str] = {}

    resolved = seed_installation_runtime_from_entrypoint(
        entrypoint,
        environ=environment,
    )

    runtime_home = installation / ".agents" / "runtime" / "tspi"
    assert resolved == installation
    assert environment == {
        "TS_AGENT_RUNTIME_HOME": str(runtime_home),
        "TS_AGENT_RUNTIME_MANIFEST": str(runtime_home / "env.json"),
        "TS_AGENT_ENV_ROOT": str(
            installation / ".agents" / "envs" / "tspi"
        ),
    }


def test_unified_suite_entrypoint_rejects_target_outside_managed_releases(
    tmp_path: Path,
) -> None:
    installation = tmp_path / "tspi"
    authored = installation / "checkout" / "bin" / "ts-web"
    authored.parent.mkdir(parents=True)
    authored.write_text("# authored\n", encoding="utf-8")
    launcher = installation / "TSWeb"
    launcher.symlink_to("checkout/bin/ts-web")
    environment: dict[str, str] = {}

    assert seed_installation_runtime_from_entrypoint(
        launcher,
        environ=environment,
    ) is None
    assert environment == {}


def test_suite_web_launcher_seeds_installation_owned_runtime_paths(
    tmp_path: Path,
) -> None:
    installation = tmp_path / "tspi"
    package_home = installation / ".pi" / "packages" / "tspi"
    release = package_home / "releases" / "release-a"
    script = release / "web" / "bin" / "ts-web"
    script.parent.mkdir(parents=True)
    script.write_text("# historical probe\n", encoding="utf-8")
    current = package_home / "current"
    current.symlink_to("releases/release-a", target_is_directory=True)
    launcher = installation / "TSWeb"
    launcher.symlink_to(".pi/packages/tspi/current/web/bin/ts-web")
    environment: dict[str, str] = {}

    resolved = seed_installation_runtime_from_entrypoint(
        launcher,
        environ=environment,
    )

    runtime_home = installation / ".agents" / "runtime" / "tspi"
    assert resolved == installation
    assert environment == {
        "TS_AGENT_RUNTIME_HOME": str(runtime_home),
        "TS_AGENT_RUNTIME_MANIFEST": str(runtime_home / "env.json"),
        "TS_AGENT_ENV_ROOT": str(installation / ".agents" / "envs" / "tspi"),
    }


def test_runtime_path_seed_preserves_explicit_configuration_and_ignores_authored_path(
    tmp_path: Path,
) -> None:
    explicit = {
        "TS_AGENT_RUNTIME_HOME": "/configured/runtime",
        "TS_AGENT_RUNTIME_MANIFEST": "/configured/env.json",
        "TS_AGENT_ENV_ROOT": "/configured/envs",
    }
    stable = tmp_path / ".pi" / "packages" / "tspi" / "current" / "web" / "bin" / "ts-web"
    release = tmp_path / ".pi" / "packages" / "tspi" / "releases" / "release-a" / "web" / "bin"
    release.mkdir(parents=True)
    (release / "ts-web").write_text("#!/bin/sh\n", encoding="utf-8")
    current = tmp_path / ".pi" / "packages" / "tspi" / "current"
    current.symlink_to("releases/release-a", target_is_directory=True)

    assert seed_installation_runtime_from_entrypoint(stable, environ=explicit) == tmp_path
    assert explicit == {
        "TS_AGENT_RUNTIME_HOME": "/configured/runtime",
        "TS_AGENT_RUNTIME_MANIFEST": "/configured/env.json",
        "TS_AGENT_ENV_ROOT": "/configured/envs",
    }

    authored_environment: dict[str, str] = {}
    authored = tmp_path / "checkout" / "components" / "ts-web" / "bin" / "ts-web"
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

    runtime_home = tmp_path / ".agents" / "runtime" / "tspi"
    assert environment == {
        "TS_AGENT_RUNTIME_HOME": str(runtime_home),
        "TS_AGENT_RUNTIME_MANIFEST": str(runtime_home / "env.json"),
        "TS_AGENT_ENV_ROOT": str(tmp_path / ".agents" / "envs" / "tspi"),
    }


def test_workspace_root_owns_runtime_home_and_env_store(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TS_AGENT_ENV_ROOT", raising=False)
    monkeypatch.delenv("TS_AGENT_RUNTIME_HOME", raising=False)
    workspace = tmp_path / "workspace"
    package = tmp_path / "pi" / "git" / "github.com" / "iawnix" / "TSPi"
    workspace.mkdir()
    package.mkdir(parents=True)
    _write_runtime_specs(package)

    assert default_runtime_home(package, workspace) == workspace / ".agents" / "runtime" / "tspi"
    assert default_env_store(package, workspace) == workspace / ".agents" / "envs" / "tspi"
    assert runtime_manifest_path(package, workspace_root=workspace) == workspace / ".agents" / "runtime" / "tspi" / "env.json"


def test_configured_python_reads_runtime_manifest(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    _write_runtime_specs(package)
    payload_sha256 = _write_test_python_payload(package)
    runtime_probe = _runtime_probe(payload_sha256=payload_sha256)
    # Keep this fixture valid on both Conda (where ``sys.prefix`` equals
    # ``sys.base_prefix``) and venv interpreters.  The production contract
    # deliberately requires distinct base and kernel prefixes, so model that
    # layout with small synthetic files rather than weakening the validator.
    base_prefix = tmp_path / "managed-base"
    kernel_prefix = tmp_path / "managed-kernel"
    base_python = base_prefix / "bin" / "python"
    python = kernel_prefix / "bin" / "python"
    numpy_origin = base_prefix / "lib" / "numpy.py"
    rdkit_origin = base_prefix / "lib" / "rdkit.py"
    matplotlib_origin = base_prefix / "lib" / "matplotlib.py"
    xyzrender = base_prefix / "bin" / "xyzrender"
    for path in (base_python, python, numpy_origin, rdkit_origin, matplotlib_origin, xyzrender):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# test runtime file\n", encoding="utf-8")
    xyzrender.chmod(0o755)
    runtime_probe["python"]["executable"] = str(python)
    runtime_probe["distribution"]["root"] = str(kernel_prefix)
    runtime_probe["modules"]["numpy"]["origin"] = str(numpy_origin)
    runtime_probe["modules"]["rdkit"]["origin"] = str(rdkit_origin)
    runtime_probe["modules"]["matplotlib"]["origin"] = str(matplotlib_origin)
    runtime_probe["commands"]["xyzrender"]["path"] = str(xyzrender)
    manifest_path = write_manifest(
        package,
        {
            "schema_version": "ts-agent-runtime/3",
            "python_executable": str(python),
            "env_prefix": str(base_prefix),
            "base_python_executable": str(base_python),
            "kernel_env_prefix": str(kernel_prefix),
            "spec_sha256": spec_sha256(package),
            "python_payload_sha256": payload_sha256,
            "runtime_probe": runtime_probe,
        },
    )

    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o600
    assert configured_python(package) == python.resolve()


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
    _write_runtime_specs(package)
    write_manifest(
        package,
        {
            "schema_version": "ts-agent-runtime/3",
            "python_executable": sys.executable,
            "spec_sha256": "stale",
        },
    )

    assert configured_python(package) is None


def test_runtime_one_manifest_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    _write_runtime_specs(package)
    _write_test_python_payload(package)
    manifest = runtime_manifest_path(package)
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "ts-agent-runtime/1",
                "env_prefix": str(tmp_path / "previous-runtime"),
                "python_executable": sys.executable,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert configured_python(package) is None


def test_configured_python_rejects_unprobed_or_external_modules(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    _write_runtime_specs(package)
    payload_sha256 = _write_test_python_payload(package)
    env_prefix = tmp_path / "managed-base"
    kernel_prefix = tmp_path / "managed-kernel"
    base_python = env_prefix / "bin" / "python"
    python = kernel_prefix / "bin" / "python"
    numpy_origin = env_prefix / "lib" / "numpy.py"
    rdkit_origin = env_prefix / "lib" / "rdkit.py"
    matplotlib_origin = env_prefix / "lib" / "matplotlib.py"
    xyzrender = env_prefix / "bin" / "xyzrender"
    for path in (base_python, python, numpy_origin, rdkit_origin, matplotlib_origin, xyzrender):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# test runtime file\n", encoding="utf-8")
    xyzrender.chmod(0o755)
    base = {
        "schema_version": "ts-agent-runtime/3",
        "python_executable": str(python),
        "env_prefix": str(env_prefix),
        "base_python_executable": str(base_python),
        "kernel_env_prefix": str(kernel_prefix),
        "spec_sha256": spec_sha256(package),
        "python_payload_sha256": payload_sha256,
    }
    write_manifest(package, {**base, "runtime_probe": {"ok": True}})
    assert configured_python(package) is None

    probe = _runtime_probe(payload_sha256=payload_sha256)
    probe["python"]["executable"] = str(python)
    probe["modules"]["numpy"]["origin"] = str(numpy_origin)
    probe["modules"]["rdkit"]["origin"] = str(rdkit_origin)
    probe["modules"]["matplotlib"]["origin"] = str(matplotlib_origin)
    probe["commands"]["xyzrender"]["path"] = str(xyzrender)
    probe["distribution"]["root"] = str(kernel_prefix)
    write_manifest(package, {**base, "runtime_probe": probe})
    assert configured_python(package) == python

    probe["distribution"]["version"] = "0.10.0"
    write_manifest(package, {**base, "runtime_probe": probe})
    assert configured_python(package) is None
    probe["distribution"]["version"] = "0.12.0"

    external_rdkit = tmp_path / "user-site" / "rdkit.py"
    external_rdkit.parent.mkdir()
    external_rdkit.write_text("# external test module\n", encoding="utf-8")
    probe["modules"]["rdkit"]["origin"] = str(external_rdkit)
    write_manifest(package, {**base, "runtime_probe": probe})
    assert configured_python(package) is None


def test_required_runtime_fails_closed_for_stale_manifest(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    _write_runtime_specs(package)
    write_manifest(
        package,
        {
            "schema_version": "ts-agent-runtime/3",
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


def test_scientific_runtime_probe_exercises_required_capabilities(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_probe_module,
        "_probe_render_capabilities",
        lambda: {
            "matplotlib": {"version": "3.9.0", "origin": str(Path(__file__).resolve())},
            "xyzrender": {"version": "0.2.1", "path": str(Path(sys.executable).resolve())},
        },
    )
    result = probe_runtime_capabilities(require_distribution=False)

    assert result["schema_version"] == "ts-runtime-probe/3"
    assert result["ok"] is True
    assert result["capabilities"] == {
        "reaction_analysis": True,
        "ase_thermochemistry": True,
        "rdkit_smiles_parse": True,
        "rdkit_etkdg_embed": True,
        "rdkit_uff_optimize": True,
        "matplotlib_render": True,
        "xyzrender_cli": True,
    }
    assert Path(result["modules"]["numpy"]["origin"]).is_file()
    assert Path(result["modules"]["rdkit"]["origin"]).is_file()


def test_render_probe_executes_the_managed_xyzrender(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "base"
    renderer = base / "bin/xyzrender"
    renderer.parent.mkdir(parents=True)
    renderer.write_text("#!/bin/sh\n[ \"$1\" = \"--help\" ]\n", encoding="utf-8")
    renderer.chmod(0o755)
    monkeypatch.setattr(runtime_probe_module.sys, "base_prefix", str(base))
    monkeypatch.setattr(runtime_probe_module.importlib.metadata, "version", lambda name: "0.3.8")

    result = runtime_probe_module._probe_render_capabilities()

    assert result["xyzrender"] == {"version": "0.3.8", "path": str(renderer)}
    assert Path(result["matplotlib"]["origin"]).is_file()


def test_render_probe_rejects_an_ambient_xyzrender(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "base"
    ambient = tmp_path / "ambient"
    ambient.mkdir()
    renderer = ambient / "xyzrender"
    renderer.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    renderer.chmod(0o755)
    monkeypatch.setattr(runtime_probe_module.sys, "base_prefix", str(base))
    monkeypatch.setattr(runtime_probe_module.sys, "prefix", str(base))
    monkeypatch.setenv("PATH", str(ambient))

    with pytest.raises(RuntimeError, match="managed scientific runtime is missing"):
        runtime_probe_module._probe_render_capabilities()


def test_reused_scientific_base_is_repaired_when_its_probe_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prefix = tmp_path / "envs/base/spec"
    python = prefix / "bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python.chmod(0o755)
    spec = tmp_path / "environment.yml"
    spec.write_text("name: test\n", encoding="utf-8")
    requirements = tmp_path / "requirements-runtime.txt"
    requirements.write_text("xyzrender>=0.2.1\n", encoding="utf-8")
    probes = iter(
        [
            runtime_install.RuntimeInstallError("xyzrender is missing"),
            {"ok": True},
        ]
    )

    def probe(*_args):
        result = next(probes)
        if isinstance(result, Exception):
            raise result
        return result

    calls: list[list[str]] = []

    def run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(runtime_install, "_run_base_probe", probe)
    monkeypatch.setattr(runtime_install.subprocess, "run", run)

    action = runtime_install._prepare_base(
        "/opt/conda/bin/conda",
        prefix,
        python,
        spec,
        requirements,
        tmp_path,
        "reuse",
    )

    assert action == "update"
    assert calls == [
        [
            "/opt/conda/bin/conda",
            "env",
            "update",
            "--solver",
            "libmamba",
            "-p",
            str(prefix),
            "-f",
            str(spec),
            "--prune",
        ],
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--requirement",
            str(requirements),
        ],
    ]


def test_scientific_base_reports_pip_failure_after_conda_succeeds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prefix = tmp_path / "envs/base/spec"
    python = prefix / "bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python.chmod(0o755)
    spec = tmp_path / "environment.yml"
    spec.write_text("name: test\n", encoding="utf-8")
    requirements = tmp_path / "requirements-runtime.txt"
    requirements.write_text("xyzrender>=0.2.1\n", encoding="utf-8")
    calls: list[list[str]] = []

    def run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 7 if command[0] == str(python) else 0)

    monkeypatch.setattr(runtime_install.subprocess, "run", run)
    monkeypatch.setattr(
        runtime_install,
        "_run_base_probe",
        lambda *_args: pytest.fail("the capability probe must not run after pip fails"),
    )

    with pytest.raises(
        runtime_install.RuntimeInstallError,
        match="pip dependency installation failed with exit code 7",
    ):
        runtime_install._prepare_base(
            "/opt/conda/bin/conda",
            prefix,
            python,
            spec,
            requirements,
            tmp_path,
            "create",
        )

    assert calls[0][:3] == ["/opt/conda/bin/conda", "env", "create"]
    assert calls[1] == [
        str(python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--requirement",
        str(requirements),
    ]


def test_damaged_scientific_base_requires_conda_for_repair(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prefix = tmp_path / "envs/base/spec"
    python = prefix / "bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python.chmod(0o755)
    spec = tmp_path / "environment.yml"
    spec.write_text("name: test\n", encoding="utf-8")
    requirements = tmp_path / "requirements-runtime.txt"
    requirements.write_text("xyzrender>=0.2.1\n", encoding="utf-8")
    monkeypatch.setattr(
        runtime_install,
        "_run_base_probe",
        lambda *_args: (_ for _ in ()).throw(
            runtime_install.RuntimeInstallError("xyzrender is missing")
        ),
    )

    with pytest.raises(runtime_install.RuntimeInstallError, match="required to repair"):
        runtime_install._prepare_base(
            None,
            prefix,
            python,
            spec,
            requirements,
            tmp_path,
            "reuse",
        )


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
    assert payload["base_action"] == "create"
    assert payload["kernel_action"] == "create"
    assert payload["dry_run"] is True
    assert payload["env_prefix"].startswith(str(tmp_path / "envs" / "base"))
    assert payload["kernel_env_prefix"].startswith(str(tmp_path / "envs" / "kernels"))
    assert payload["manifest_path"].endswith("/.runtime/tspi/env.json")
    assert payload["runtime_requirements"] == str(ROOT / "requirements-runtime.txt")
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

    assert payload["runtime_home"] == str(workspace / ".agents" / "runtime" / "tspi")
    assert payload["manifest_path"] == str(workspace / ".agents" / "runtime" / "tspi" / "env.json")
    assert payload["env_prefix"].startswith(str(workspace / ".agents" / "envs" / "tspi" / "base"))
    assert payload["kernel_env_prefix"].startswith(str(workspace / ".agents" / "envs" / "tspi" / "kernels"))


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


def test_install_env_reuses_scientific_base_and_isolates_kernel_overlay(tmp_path: Path) -> None:
    import numpy
    import rdkit

    if shutil.which("xyzrender") is None:
        pytest.skip("the current scientific base does not include the required xyzrender executable")

    base_prefix = Path(sys.base_prefix).resolve()
    assert Path(numpy.__file__).resolve().is_relative_to(base_prefix)
    assert Path(rdkit.__file__).resolve().is_relative_to(base_prefix)
    env_root = tmp_path / "envs"
    managed_base = env_root / "base" / spec_sha256(ROOT)[:12]
    managed_base.parent.mkdir(parents=True)
    managed_base.symlink_to(base_prefix, target_is_directory=True)
    runtime_home = tmp_path / "runtime"
    command = [
        sys.executable,
        str(ROOT / "scripts" / "install_env.py"),
        "--package-root",
        str(ROOT),
        "--env-root",
        str(env_root),
        "--runtime-home",
        str(runtime_home),
        "--json",
    ]

    first = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    second = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    created = json.loads(first.stdout)
    reused = json.loads(second.stdout)
    manifest = json.loads((runtime_home / "env.json").read_text(encoding="utf-8"))

    kernel_prefix = Path(created["kernel_env_prefix"])
    assert created["base_action"] == "reuse"
    assert created["kernel_action"] == "create"
    assert reused["base_action"] == "reuse"
    assert reused["kernel_action"] == "reuse"
    assert kernel_prefix.parent == env_root / "kernels"
    assert Path(created["python_executable"]).is_relative_to(kernel_prefix)
    assert manifest["schema_version"] == "ts-agent-runtime/3"
    assert Path(manifest["runtime_probe"]["distribution"]["root"]).is_relative_to(kernel_prefix)
    for name in ("numpy", "rdkit", "matplotlib"):
        assert Path(manifest["runtime_probe"]["modules"][name]["origin"]).is_relative_to(base_prefix)


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
            "schema_version": "ts-agent-runtime/3",
            "python_executable": sys.executable,
            "env_prefix": str(Path(sys.base_prefix).resolve()),
            "base_python_executable": str(Path(sys._base_executable).resolve()),
            "kernel_env_prefix": str(Path(sys.prefix).resolve()),
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
            "tests/integration/test_runtime_env.py::test_configured_python_ignores_stale_runtime_manifest",
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
    assert payload["manifest_path"] == str(workspace / ".agents" / "runtime" / "tspi" / "env.json")
    assert payload["env_prefix"].startswith(str(workspace / ".agents" / "envs" / "tspi" / "base"))
    assert payload["kernel_env_prefix"].startswith(str(workspace / ".agents" / "envs" / "tspi" / "kernels"))


def _runtime_probe(*, payload_sha256: str | None = None) -> dict[str, object]:
    import numpy
    import rdkit

    executable = Path(sys.executable).resolve()
    numpy_origin = Path(numpy.__file__).resolve()
    rdkit_origin = Path(rdkit.__file__).resolve()
    kernel_prefix = Path(sys.prefix).resolve()
    return {
        "schema_version": "ts-runtime-probe/3",
        "ok": True,
        "python": {"version": sys.version.split()[0], "executable": str(executable)},
        "distribution": {
            "name": "ts-agent-kernel",
            "installed": True,
            "version": "0.12.0",
            "root": str(kernel_prefix),
            "payload_sha256": payload_sha256 or python_payload_sha256(ROOT),
        },
        "modules": {
            "numpy": {"version": numpy.__version__, "origin": str(numpy_origin)},
            "rdkit": {"version": rdkit.__version__, "origin": str(rdkit_origin)},
            "matplotlib": {"version": "3.9.0", "origin": str(numpy_origin)},
        },
        "commands": {
            "xyzrender": {"version": "0.2.1", "path": str(executable)},
        },
        "capabilities": {
            "rdkit_smiles_parse": True,
            "rdkit_etkdg_embed": True,
            "rdkit_uff_optimize": True,
            "matplotlib_render": True,
            "xyzrender_cli": True,
        },
    }


def _write_test_python_payload(package: Path) -> str:
    source = package / "packages" / "ts-agent-kernel" / "ts_agent"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text('"""test payload"""\n', encoding="utf-8")
    (package / "package.json").write_text(
        '{"name":"@iawnix/ts-agent","version":"0.12.0"}\n',
        encoding="utf-8",
    )
    return python_payload_sha256(package)
