from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_package import PACKAGE_FILES
from tests.runtime_helpers import write_test_runtime_manifest


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "transition-state-workflow"
AGENTS_ROOT = ROOT / "src" / "agents"
THEME_PATH = ROOT / "themes" / "ts-theme.json"
TSPI_LAUNCHER = ROOT / "TSPi"


def _copy_tspi_install(tmp_path: Path) -> tuple[Path, Path]:
    install_root = tmp_path / "tspi-install"
    package_home = install_root / ".pi" / "packages" / "ts-agent"
    package_root = package_home / "releases" / "test-release"
    package_root.mkdir(parents=True)
    (package_root / "package.json").write_text(
        '{"name":"@iawnix/ts-agent","version":"0.10.0"}\n',
        encoding="utf-8",
    )
    (package_root / ".ts-agent-release.json").write_text(
        json.dumps(
            {
                "schema_version": "ts-agent-release/1",
                "release_id": "test-release",
                "package": {"name": "@iawnix/ts-agent", "version": "0.10.0"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    shutil.copy2(TSPI_LAUNCHER, package_root / "TSPi")
    (package_root / "TSPi").chmod(0o755)
    (package_root / "scripts").mkdir()
    for name in ("tspi_host.py", "ts_compute.py"):
        shutil.copy2(ROOT / "scripts" / name, package_root / "scripts" / name)
    for name in ("ts_runtime", "ts_validation", "ts_workspace"):
        shutil.copytree(
            ROOT / name,
            package_root / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    shutil.copy2(ROOT / "environment.yml", package_root / "environment.yml")
    write_test_runtime_manifest(package_root, install_root)
    (package_home / "current").symlink_to("releases/test-release")
    launcher = install_root / "TSPi"
    launcher.symlink_to(".pi/packages/ts-agent/current/TSPi")
    return install_root, launcher


def _installed_package_root(install_root: Path) -> Path:
    return install_root / ".pi" / "packages" / "ts-agent" / "releases" / "test-release"


def _fake_pi(path: Path, body: str = "raise SystemExit(0)\n") -> Path:
    path.write_text(f"#!/usr/bin/env python3\n{body}", encoding="utf-8")
    path.chmod(0o755)
    return path


def _run_tspi(
    launcher: Path,
    *args: str,
    pi_bin: Path | str = "/bin/true",
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(launcher), *args],
        cwd=launcher.parent,
        env={**os.environ, "PI_BIN": str(pi_bin), **(env or {})},
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_public_skill_uses_nested_pi_skill_layout() -> None:
    assert (SKILL_ROOT / "SKILL.md").is_file()
    assert (SKILL_ROOT / "agents" / "openai.yaml").is_file()
    assert (SKILL_ROOT / "references" / "state_model.md").is_file()
    assert not (SKILL_ROOT / "references" / "research_node_ontology.md").exists()
    assert (SKILL_ROOT / "assets" / "templates" / "ts_final_report.md").is_file()
    assert not (ROOT / "SKILL.md").exists()
    assert not (ROOT / "references").exists()
    assert not (ROOT / "templates").exists()


def test_agent_sources_have_explicit_ownership_boundaries() -> None:
    assert (ROOT / "extensions" / "shared" / "tool-catalog.ts").is_file()
    assert not (ROOT / "extensions" / "ts-workflow-context").exists()
    assert not (ROOT / "extensions" / "ts-workflow-subagent").exists()
    for name in ("agent-protocol.cjs", "fact-kinds.cjs", "failure-taxonomy.cjs", "run-journal.cjs", "session-lifecycle.cjs"):
        assert (ROOT / "src" / "agent-core" / name).is_file()
    assert (AGENTS_ROOT / "review" / "runtime.ts").is_file()
    assert (AGENTS_ROOT / "review" / "prompts" / "core.md").is_file()
    assert {path.name for path in AGENTS_ROOT.iterdir()} == {"review"}
    assert (ROOT / "src" / "artifacts" / "request-contract.cjs").is_file()
    assert (ROOT / "ts_runtime" / "probe.py").is_file()
    assert (ROOT / "ts_structures" / "seed.py").is_file()
    assert (ROOT / "ts_validation" / "engine.py").is_file()
    assert (ROOT / "ts_workspace" / "bootstrap.py").is_file()
    assert (ROOT / "ts_workspace" / "engine.py").is_file()
    assert not (ROOT / "ts_workspace" / "engine_v3.py").exists()
    assert not (ROOT / "ts_workspace" / "migrate_v2.py").exists()
    assert not list((ROOT / "ts_workspace" / "validators").glob("*.py"))
    for legacy in ("agent-core", "review-agent", "compute-agent", "artifact-agent", "agent-skills"):
        assert not (ROOT / legacy).exists()


def test_deterministic_tool_policy_lives_outside_agent_sources() -> None:
    assert not list(AGENTS_ROOT.rglob("SKILL.md"))
    assert not (AGENTS_ROOT / "compute").exists()
    assert not (AGENTS_ROOT / "artifacts").exists()
    assert (SKILL_ROOT / "references" / "compute_tools.md").is_file()
    assert (SKILL_ROOT / "references" / "artifact_tools.md").is_file()


def test_package_manifest_exposes_only_the_public_skill_and_allowlisted_runtime() -> None:
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert manifest["pi"]["skills"] == ["./skills/transition-state-workflow"]
    assert manifest["pi"]["themes"] == ["./themes/ts-theme.json"]
    assert manifest["files"] == PACKAGE_FILES
    assert manifest["private"] is True
    assert "tests/" not in manifest["files"]
    assert "docs/*.md" in manifest["files"]
    for name in ("ARCHITECTURE.md", "INSTALLATION.md", "MAINTAINER_GUIDE.md"):
        assert (ROOT / "docs" / name).is_file()
    assert all("src/agents" not in entry for entry in manifest["pi"]["skills"])


def test_tspi_shell_is_a_thin_executable_shim() -> None:
    completed = subprocess.run(
        ["bash", "-n", str(TSPI_LAUNCHER)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    source = TSPI_LAUNCHER.read_text(encoding="utf-8")
    assert completed.returncode == 0, completed.stderr
    assert TSPI_LAUNCHER.stat().st_mode & 0o111
    assert len(source.splitlines()) <= 20
    assert "scripts/tspi_host.py" in source
    assert "TS_AGENT_INSTALL_ROOT" in source
    for mechanism in ("configure_remote", "configure_notifications", "acquire_root_agent_lock", "ts_compute.py"):
        assert mechanism not in source
    help_result = subprocess.run(
        [str(TSPI_LAUNCHER), "--help"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "Usage:" in help_result.stdout


def test_tspi_loads_installation_owned_remote_profile_without_probing(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    ssh_config = install_root / ".pi" / "ssh_config"
    ssh_config.parent.mkdir(parents=True, exist_ok=True)
    ssh_config.write_text("Host cluster-login\n  HostName cluster.test\n", encoding="utf-8")
    remote_config = install_root / ".pi" / "remote.toml"
    remote_config.write_text(
        f'''default_profile = "cluster_1w"
[profiles.cluster_1w]
ssh_host = "cluster-login"
ssh_config = "{ssh_config}"
scheduler = "torque"
remote_root = "/remote/ts"
allowed_queues = ["batch"]
max_nodes = 1
''',
        encoding="utf-8",
    )
    diagnostic = _installed_package_root(install_root) / "scripts" / "ts_compute.py"
    diagnostic.write_text("raise SystemExit('remote probe must not run')\n", encoding="utf-8")
    fake_pi = _fake_pi(
        tmp_path / "fake-pi.py",
        "import json, os\nprint(json.dumps({'config': os.environ['TS_REMOTE_CONFIG'], 'display': os.environ['TS_REMOTE_DISPLAY_TARGET']}))\n",
    )

    completed = _run_tspi(launcher, "--workspace", "no-probe", pi_bin=fake_pi)

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"config": str(remote_config), "display": "cluster-login · Torque"}
    assert "remote probe must not run" not in completed.stderr


@pytest.mark.parametrize(
    ("enabled", "expected"),
    [(False, "disabled"), (True, "researcher@example.org")],
)
def test_tspi_loads_installation_owned_notification_config(
    tmp_path: Path,
    enabled: bool,
    expected: str,
) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    config = install_root / ".pi" / "notifications.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "[notifications.email]\n"
        f"enabled = {'true' if enabled else 'false'}\n"
        'recipient = "researcher@example.org"\n'
        'clawemail_root = "/tmp/clawemail"\n',
        encoding="utf-8",
    )
    config.chmod(0o600)
    fake_pi = _fake_pi(
        tmp_path / "fake-pi.py",
        "import json, os\nprint(json.dumps({'config': os.environ['TS_NOTIFICATION_CONFIG'], 'display': os.environ['TS_NOTIFICATION_DISPLAY_TARGET']}))\n",
    )

    completed = _run_tspi(launcher, "--workspace", "notify", pi_bin=fake_pi)

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"config": str(config), "display": expected}


def test_tspi_rejects_non_private_notification_config(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    config = install_root / ".pi" / "notifications.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "[notifications.email]\nenabled = true\n"
        'recipient = "researcher@example.org"\n'
        'clawemail_root = "/tmp/clawemail"\n',
        encoding="utf-8",
    )
    config.chmod(0o644)

    completed = _run_tspi(launcher, "--workspace", "notify")

    assert completed.returncode == 1
    assert "must not be accessible by group or others" in completed.stderr
    assert not (install_root / "workspaces" / "notify").exists()


def test_tspi_requires_an_installed_release(tmp_path: Path) -> None:
    install_root = tmp_path / "tspi-install"
    install_root.mkdir()
    launcher = install_root / "TSPi"
    shutil.copy2(TSPI_LAUNCHER, launcher)
    launcher.chmod(0o755)
    (install_root / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts" / "tspi_host.py", install_root / "scripts" / "tspi_host.py")
    shutil.copytree(ROOT / "ts_runtime", install_root / "ts_runtime", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    completed = _run_tspi(launcher, "--workspace", "release-required")

    assert completed.returncode == 1
    assert "no installed TS Agent release" in completed.stderr
    assert "install a validated release" in completed.stderr


def test_tspi_check_remote_runs_one_strict_diagnostic(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    config = install_root / ".pi" / "remote.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        'default_profile = "cluster"\n[profiles.cluster]\nssh_host = "cluster-login"\nscheduler = "torque"\n',
        encoding="utf-8",
    )
    diagnostic = _installed_package_root(install_root) / "scripts" / "ts_compute.py"
    diagnostic.write_text("print('{\"ok\": true}')\n", encoding="utf-8")

    completed = _run_tspi(launcher, "--check-remote")

    assert completed.returncode == 0, completed.stderr
    assert "remote check passed (cluster-login · Torque)" in completed.stdout
    assert not (install_root / "workspaces").exists()


def test_tspi_remote_diagnostic_preserves_structured_failure(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    config = install_root / ".pi" / "remote.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        'default_profile = "cluster"\n[profiles.cluster]\nssh_host = "cluster-login"\nscheduler = "torque"\n',
        encoding="utf-8",
    )
    diagnostic = _installed_package_root(install_root) / "scripts" / "ts_compute.py"
    diagnostic.write_text(
        "print('{\"ok\": false, \"error\": {\"class\": \"ssh_unreachable\"}}')\nraise SystemExit(3)\n",
        encoding="utf-8",
    )

    completed = _run_tspi(launcher, "--check-remote")

    assert completed.returncode == 1
    assert "ssh_unreachable" in completed.stderr


def test_tspi_rejects_a_symlinked_remote_config(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    target = tmp_path / "remote.toml"
    target.write_text("default_profile = 'cluster'\n", encoding="utf-8")
    config = install_root / ".pi" / "remote.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.symlink_to(target)

    completed = _run_tspi(launcher, "--check-remote")

    assert completed.returncode == 1
    assert "invalid TS_REMOTE_CONFIG" in completed.stderr


def test_tspi_runs_pi_with_bootstrapped_workspace_and_install_runtime(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    fake_pi = _fake_pi(
        tmp_path / "fake-pi.py",
        """import json
import os
import sys
print(json.dumps({
    "argv": sys.argv[1:],
    "cwd": os.getcwd(),
    "workspace": os.environ["TS_WORKSPACE_ROOT"],
    "notification_config": os.environ.get("TS_NOTIFICATION_CONFIG"),
    "notification_display": os.environ["TS_NOTIFICATION_DISPLAY_TARGET"],
    "runtime_home": os.environ["TS_AGENT_RUNTIME_HOME"],
    "runtime_manifest": os.environ["TS_AGENT_RUNTIME_MANIFEST"],
    "env_root": os.environ["TS_AGENT_ENV_ROOT"],
    "managed_python": os.environ["TS_AGENT_PYTHON"],
    "path_python": __import__("shutil").which("python"),
    "path_python3": __import__("shutil").which("python3"),
    "no_user_site": os.environ.get("PYTHONNOUSERSITE"),
    "python_cache": os.environ["PYTHONPYCACHEPREFIX"],
    "pytest_options": os.environ["PYTEST_ADDOPTS"],
    "remote_config": os.environ.get("TS_REMOTE_CONFIG"),
    "remote_display": os.environ["TS_REMOTE_DISPLAY_TARGET"],
}))
""",
    )

    completed = _run_tspi(
        launcher,
        "--workspace",
        "reaction-a",
        "--model",
        "test",
        pi_bin=fake_pi,
        env={
            "TS_NOTIFICATION_CONFIG": "",
            "TS_AGENT_RUNTIME_HOME": "/tmp/old-runtime",
            "TS_AGENT_RUNTIME_MANIFEST": "/tmp/old-runtime/env.json",
            "TS_AGENT_ENV_ROOT": "/tmp/old-env",
        },
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    workspace = install_root / "workspaces" / "reaction-a"
    assert result["cwd"] == result["workspace"] == str(workspace)
    assert result["notification_config"] is None
    assert result["notification_display"] == "not configured"
    assert result["runtime_home"] == str(install_root / ".agents" / "runtime" / "transition-state-workflow")
    assert result["runtime_manifest"] == str(
        install_root / ".agents" / "runtime" / "transition-state-workflow" / "env.json"
    )
    assert result["env_root"] == str(install_root / ".agents" / "envs" / "transition-state-workflow")
    assert result["managed_python"] == str(Path(sys.executable).resolve())
    assert Path(result["path_python"]).resolve() == Path(sys.executable).resolve()
    assert Path(result["path_python3"]).resolve() == Path(sys.executable).resolve()
    assert result["no_user_site"] == "1"
    assert result["python_cache"] == str(install_root / ".pi" / "runtime-cache" / "python" / "reaction-a")
    assert result["pytest_options"].endswith(
        f"--cache-dir={install_root / '.pi' / 'runtime-cache' / 'pytest' / 'reaction-a'}"
    )
    assert result["remote_config"] is None
    assert result["remote_display"] == "not configured"
    session_index = result["argv"].index("--session-dir")
    assert result["argv"][session_index + 1] == str(workspace / ".pi" / "sessions")
    assert (workspace / ".pi" / "root-agent.lock").is_file()
    assert json.loads((workspace / ".pi" / "settings.json").read_text(encoding="utf-8")) == {"quietStartup": True}
    assert json.loads((workspace / "research_state.json").read_text(encoding="utf-8"))["schema_version"] == "ts-research-state/4"
    assert (workspace / ".agents" / "workspace-identity.json").is_file()


def test_tspi_fails_closed_without_managed_runtime_manifest(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    manifest = install_root / ".agents" / "runtime" / "transition-state-workflow" / "env.json"
    manifest.unlink()

    completed = _run_tspi(launcher, "--workspace", "missing-runtime")

    assert completed.returncode == 1
    assert "managed TS Python runtime is missing or stale" in completed.stderr
    assert not (install_root / "workspaces" / "missing-runtime").exists()


def test_tspi_workspace_preserves_pi_settings_while_bootstrapping(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    settings = install_root / "workspaces" / "existing" / ".pi" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"quietStartup": False, "theme": "custom", "warnings": {"deprecated": False}}),
        encoding="utf-8",
    )

    completed = _run_tspi(launcher, "--workspace", "existing")

    assert completed.returncode == 0, completed.stderr
    assert json.loads(settings.read_text(encoding="utf-8")) == {
        "quietStartup": True,
        "theme": "custom",
        "warnings": {"deprecated": False},
    }
    assert (install_root / "workspaces" / "existing" / "observations.json").is_file()


def test_tspi_rejects_symlinked_workspace_pi_settings(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    settings = install_root / "workspaces" / "symlink-settings" / ".pi" / "settings.json"
    settings.parent.mkdir(parents=True)
    target = tmp_path / "settings.json"
    target.write_text("{}\n", encoding="utf-8")
    settings.symlink_to(target)

    completed = _run_tspi(launcher, "--workspace", "symlink-settings")

    assert completed.returncode == 1
    assert "workspace Pi settings cannot be a symbolic link" in completed.stderr
    assert target.read_text(encoding="utf-8") == "{}\n"


def test_tspi_workspace_launch_does_not_require_remote_configuration(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    fake_pi = _fake_pi(
        tmp_path / "fake-pi.py",
        "import json, os\nprint(json.dumps({'cwd': os.getcwd(), 'remote_display': os.environ['TS_REMOTE_DISPLAY_TARGET']}))\n",
    )

    completed = _run_tspi(launcher, "--workspace", "offline-research", pi_bin=fake_pi)

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "cwd": str(install_root / "workspaces" / "offline-research"),
        "remote_display": "not configured",
    }
    assert completed.stderr == ""


def test_tspi_check_remote_is_strict_when_configuration_is_missing(tmp_path: Path) -> None:
    _, launcher = _copy_tspi_install(tmp_path)

    completed = _run_tspi(launcher, "--check-remote")

    assert completed.returncode == 1
    assert "remote configuration is missing" in completed.stderr
    assert "remote check passed" not in completed.stdout


def test_tspi_requires_a_safe_workspace_name(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)

    no_workspace = _run_tspi(launcher)
    traversal = _run_tspi(launcher, "--workspace", "../escaped")

    assert no_workspace.returncode == 2
    assert "a research workspace is required" in no_workspace.stderr
    assert traversal.returncode == 1
    assert "invalid workspace name" in traversal.stderr
    assert not (install_root.parent / "escaped").exists()


def test_tspi_root_lock_rejects_a_second_writer(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    blocking_pi = _fake_pi(
        tmp_path / "blocking-pi.py",
        "print('ready', flush=True)\ninput()\n",
    )
    command = [str(launcher), "--workspace", "lock-test"]
    env = {**os.environ, "PI_BIN": str(blocking_pi)}
    holder = subprocess.Popen(
        command,
        cwd=install_root,
        env=env,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "ready"
        contender = subprocess.run(
            command,
            cwd=install_root,
            env=env,
            input="release\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert contender.returncode == 1
        assert "another Root Agent already owns workspace" in contender.stderr
        independent = subprocess.run(
            [str(launcher), "--workspace", "independent-test"],
            cwd=install_root,
            env=env,
            input="release\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert independent.returncode == 0, independent.stderr
        assert independent.stdout.strip() == "ready"
    finally:
        assert holder.stdin is not None
        holder.stdin.write("release\n")
        holder.stdin.flush()
        holder.communicate(timeout=5)

    assert (install_root / "workspaces" / "lock-test" / ".pi" / "root-agent.lock").is_file()
    assert (install_root / "workspaces" / "independent-test" / ".pi" / "root-agent.lock").is_file()


def test_ts_theme_loads_with_pi_theme_loader() -> None:
    script = """
import { loadThemeFromPath } from "./node_modules/@earendil-works/pi-coding-agent/dist/modes/interactive/theme/theme.js";
const theme = loadThemeFromPath(process.argv[1]);
process.stdout.write(JSON.stringify({ name: theme.name, sourcePath: theme.sourcePath }));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script, str(THEME_PATH)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    loaded = json.loads(completed.stdout)
    assert loaded == {"name": "ts-theme", "sourcePath": str(THEME_PATH)}
