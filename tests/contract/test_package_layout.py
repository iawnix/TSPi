from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_package import PACKAGE_FILES, SKILL_ENTRIES
from tests.support.runtime_helpers import write_test_runtime_manifest, write_test_suite_manifest


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "tspi-research-kernel"
ORCHESTRATION_SKILL_ROOT = ROOT / "skills" / "tspi-orchestration"
RUNTIME_ROOT = ROOT / "packages" / "ts-agent-runtime"
AGENTS_ROOT = RUNTIME_ROOT / "agents"
PYTHON_PACKAGE = ROOT / "packages" / "ts-agent-kernel" / "ts_agent"
THEME_PATH = ROOT / "themes" / "ts-theme.json"
TSPI_LAUNCHER = ROOT / "TSPi"
GENERATION_BRAND = re.compile(
    r"(?i)(?<![A-Za-z0-9])v[2-5](?![A-Za-z0-9])"
)
VERSION_BRANDED_PATH = re.compile(r"(?i)(?:^|[_-])v[2-5](?:[._-]|$)")
TEXT_SUFFIXES = frozenset({".cjs", ".html", ".js", ".json", ".md", ".py", ".toml", ".ts", ".yaml", ".yml"})
ALLOWED_CONTRACT_OR_THIRD_PARTY_LABELS = (
    "etkdg=" + "v" + "3",
    "ts-" + "leg" + "acy-notification-state-archive/1",
    "APK Signature Scheme " + "v" + "2",
    "Verified using " + "v" + "2" + " scheme",
    "https://tsphone.iawnix.xyz/schema/bridge-" + "v" + "3.json",
    "https://tsphone.iawnix.xyz/schema/events-" + "v" + "3.json",
    "/api/" + "v" + "4/version",
    # These are storage/protocol version labels, not generation branding.
    "v3 history",
    "v3 session",
    "v3 transcript",
    "v3 会话",
    "v3 历史",
    "v3 文件",
    "v4 histories",
    "v4 历史",
    "Experimental/v4",
    "实验性/v4",
    "native v3",
    "原生 v3",
    "ordinary Pi v3",
)


def _copy_tspi_install(tmp_path: Path) -> tuple[Path, Path]:
    install_root = tmp_path / "tspi-install"
    package_home = install_root / ".pi" / "packages" / "tspi"
    suite_root = package_home / "releases" / "test-suite"
    package_root = suite_root / "agent"
    package_root.mkdir(parents=True)
    (package_root / "package.json").write_text(
        '{"name":"@iawnix/ts-agent","version":"0.10.0"}\n',
        encoding="utf-8",
    )
    (package_root / "themes").mkdir()
    shutil.copy2(ROOT / "themes" / "ts-theme.json", package_root / "themes" / "ts-theme.json")
    app_server = package_root / "apps" / "app-server" / "pi-app-server.mjs"
    app_server.parent.mkdir(parents=True)
    app_server.write_text("// test app server entry\n", encoding="utf-8")
    # The launcher validates the pinned ordinary Pi checkout before it execs
    # Node.  Keep this fixture self-contained by creating a tiny local Git
    # checkout with the two paths the normal CLI requires.  The fake `node`
    # below still runs the test Pi, so no real Pi dependency is needed here.
    source_staging = install_root / ".pi" / "pi-source-fixture"
    (source_staging / "packages" / "coding-agent" / "src" / "experimental").mkdir(parents=True)
    (source_staging / "packages" / "coding-agent" / "src" / "cli.ts").write_text(
        "export {};\n", encoding="utf-8"
    )
    (source_staging / "packages" / "coding-agent" / "src" / "experimental" / "source-resolver.ts").write_text(
        "export {};\n", encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(source_staging), "init", "--quiet"], check=True)
    subprocess.run(["git", "-C", str(source_staging), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source_staging),
            "-c",
            "user.name=TSPi test fixture",
            "-c",
            "user.email=tspi-fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture ordinary Pi source",
        ],
        check=True,
    )
    pi_commit = subprocess.run(
        ["git", "-C", str(source_staging), "rev-parse", "HEAD"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    source = install_root / ".pi" / "runtime-cache" / "pi" / pi_commit
    source.parent.mkdir(parents=True, exist_ok=True)
    source_staging.rename(source)
    (package_root / "config").mkdir()
    pi_pin = json.loads((ROOT / "config" / "pi-source.json").read_text(encoding="utf-8"))
    pi_pin["commit"] = pi_commit
    (package_root / "config" / "pi-source.json").write_text(
        json.dumps(pi_pin, indent=2) + "\n", encoding="utf-8"
    )
    write_test_suite_manifest(suite_root)
    shutil.copy2(TSPI_LAUNCHER, package_root / "TSPi")
    (package_root / "TSPi").chmod(0o755)
    (package_root / "scripts").mkdir()
    for name in ("_bootstrap.py", "tspi_launcher.py", "ts_compute.py"):
        shutil.copy2(ROOT / "scripts" / name, package_root / "scripts" / name)
    shutil.copytree(
        ROOT / "packages" / "ts-agent-kernel",
        package_root / "packages" / "ts-agent-kernel",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
    )
    shutil.copy2(ROOT / "pyproject.toml", package_root / "pyproject.toml")
    shutil.copy2(ROOT / "environment.yml", package_root / "environment.yml")
    shutil.copy2(ROOT / "requirements-runtime.txt", package_root / "requirements-runtime.txt")
    write_test_runtime_manifest(package_root, install_root)
    (package_home / "current").symlink_to("releases/test-suite")
    launcher = install_root / "TSPi"
    launcher.symlink_to(".pi/packages/tspi/current/agent/TSPi")
    fake_node = install_root / "fake-bin" / "node"
    fake_node.parent.mkdir(parents=True)
    fake_node.write_text("#!/bin/sh\nexec \"$PI_BIN\" \"$@\"\n", encoding="utf-8")
    fake_node.chmod(0o755)
    return install_root, launcher


def _installed_package_root(install_root: Path) -> Path:
    return install_root / ".pi" / "packages" / "tspi" / "releases" / "test-suite" / "agent"


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
    install_root = launcher.parent
    runtime_key = hashlib.sha256(os.fsencode(str(install_root))).hexdigest()[:12]
    runtime_dir = Path("/tmp") / f"tspi-test-{runtime_key}"
    runtime_dir.mkdir(mode=0o700, exist_ok=True)
    host_state = install_root / ".pi" / "app-server-host"
    host_workspace = host_state / "workspace"
    (host_workspace / ".pi").mkdir(parents=True, exist_ok=True, mode=0o700)
    (install_root / ".pi").chmod(0o700)
    host_state.chmod(0o700)
    host_workspace.chmod(0o700)
    (host_workspace / ".pi").chmod(0o700)
    server_id = "123e4567-e89b-42d3-a456-426614174000"
    identity = host_state / "server-id"
    identity.write_text(server_id + "\n", encoding="ascii")
    identity.chmod(0o600)
    socket_dir = runtime_dir / hashlib.sha256(os.fsencode(host_workspace.resolve())).hexdigest()[:16]
    socket_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    endpoint = socket_dir / f"{server_id}.sock"
    endpoint.unlink(missing_ok=True)
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(endpoint))
    environment = {
        **os.environ,
        "PATH": f"{install_root / 'fake-bin'}:{os.environ.get('PATH', '')}",
        "TSPI_APP_SERVER_RUNTIME_DIR": str(runtime_dir),
        "PI_BIN": str(pi_bin),
        **(env or {}),
    }
    try:
        return subprocess.run(
            [str(launcher), *args],
            cwd=launcher.parent,
            env=environment,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    finally:
        listener.close()
        endpoint.unlink(missing_ok=True)
        socket_dir.rmdir()
        runtime_dir.rmdir()


def test_public_skill_uses_nested_pi_skill_layout() -> None:
    assert (SKILL_ROOT / "SKILL.md").is_file()
    assert not (SKILL_ROOT / "agents").exists()
    assert (SKILL_ROOT / "references" / "state_model.md").is_file()
    assert not (SKILL_ROOT / "references" / "research_node_ontology.md").exists()
    assert not (SKILL_ROOT / "assets" / "templates" / "ts_final_report.md").exists()
    assert not (ROOT / "SKILL.md").exists()
    assert not (ROOT / "references").exists()
    assert not (ROOT / "templates").exists()


def test_public_skill_family_matches_the_owned_capabilities() -> None:
    expected = {
        "tspi-research-kernel",
        "tspi-orchestration",
        "tspi-ts-candidate-generation",
        "tspi-ts-validation",
        "tspi-irc",
        "tspi-energetics",
        "tspi-method-selection",
        "cf22d",
        "tspi-xtb",
        "tspi-crest",
        "tspi-qbics",
        "tspi-gaussian",
        "tspi-report",
        "tspi-render",
        "tspi-email",
        "tspi-mechanism-reasoning",
        "tspi-chemical-input",
    }
    actual = {path.name for path in (ROOT / "skills").iterdir() if path.is_dir()}
    assert actual == expected
    for name in expected:
        skill = ROOT / "skills" / name
        assert (skill / "SKILL.md").is_file()
        assert (skill / "SKILL.zh-CN.md").is_file()


def test_current_sources_do_not_use_generation_branded_language_or_paths() -> None:
    roots = [
        ROOT / "README.md",
        ROOT / "docs",
        ROOT / "extensions",
        ROOT / "scripts",
        ROOT / "skills",
        RUNTIME_ROOT,
        ROOT / "apps",
        ROOT / "tests",
        ROOT / "packages" / "ts-agent-kernel",
    ]
    files: set[Path] = set()
    for root in roots:
        if root.is_file():
            files.add(root)
        elif root.is_dir():
            files.update(path for path in root.rglob("*") if path.is_file() and path.suffix in TEXT_SUFFIXES)

    branded_paths = [path.relative_to(ROOT).as_posix() for path in files if VERSION_BRANDED_PATH.search(path.name)]
    branded_text: list[tuple[str, str]] = []
    for path in sorted(files):
        text = path.read_text(encoding="utf-8")
        for allowed in ALLOWED_CONTRACT_OR_THIRD_PARTY_LABELS:
            text = text.replace(allowed, "")
        match = GENERATION_BRAND.search(text)
        if match:
            branded_text.append((path.relative_to(ROOT).as_posix(), match.group(0)))

    assert branded_paths == []
    assert branded_text == []


def test_agent_sources_have_explicit_ownership_boundaries() -> None:
    assert (RUNTIME_ROOT / "host-api" / "commands.mjs").is_file()
    assert (RUNTIME_ROOT / "host-api" / "tools.mjs").is_file()
    assert (ROOT / "extensions" / "pi" / "runtime.ts").is_file()
    assert (ROOT / "extensions" / "pi" / "research" / "extension.ts").is_file()
    assert (ROOT / "extensions" / "pi" / "ui" / "extension.ts").is_file()
    for name in ("artifacts", "compute", "review"):
        assert (ROOT / "extensions" / "pi" / name / "tools.ts").is_file()
    for removed in ("adapters", "core", "shared", "ts-workflow-control", "ts-workflow-ui", "ts-workflow-review", "ts-workflow-compute", "ts-workflow-artifacts"):
        assert not (ROOT / "extensions" / removed).exists()
    for name in ("agent-protocol.cjs", "fact-kinds.cjs", "failure-taxonomy.cjs", "run-journal.cjs", "session-lifecycle.cjs"):
        assert (RUNTIME_ROOT / "agent-core" / name).is_file()
    assert (AGENTS_ROOT / "review" / "runtime.ts").is_file()
    assert (AGENTS_ROOT / "review" / "prompts" / "core.md").is_file()
    assert (AGENTS_ROOT / "compute" / "runtime.ts").is_file()
    assert (AGENTS_ROOT / "compute" / "prompts" / "core.md").is_file()
    assert {path.name for path in AGENTS_ROOT.iterdir()} == {"compute", "review"}
    assert (RUNTIME_ROOT / "artifacts" / "request-contract.cjs").is_file()
    assert (PYTHON_PACKAGE / "runtime" / "probe.py").is_file()
    assert (PYTHON_PACKAGE / "structures" / "seed.py").is_file()


def test_pi_extension_entrypoints_only_install_owned_modules() -> None:
    for name in ("research", "ui", "review", "compute", "artifacts"):
        source = (ROOT / "extensions" / "pi" / name / "index.ts").read_text(encoding="utf-8")
        assert len(source.splitlines()) <= 10
        assert "registerTool" not in source
        assert "registerCommand" not in source
        assert "new PiRuntime" not in source
    assert (PYTHON_PACKAGE / "research" / "kernel.py").is_file()
    assert (PYTHON_PACKAGE / "research" / "model.py").is_file()
    assert (PYTHON_PACKAGE / "workspace" / "bootstrap.py").is_file()
    assert (PYTHON_PACKAGE / "workspace" / "engine.py").is_file()
    assert not list((PYTHON_PACKAGE / "workspace").glob("*_v[0-9]*.py"))
    assert not (PYTHON_PACKAGE / "workspace" / "validators").exists()
    assert not any(path.is_dir() for path in ROOT.glob("ts_*"))
    for removed in ("agent-core", "review-agent", "compute-agent", "artifact-agent", "agent-skills"):
        assert not (ROOT / removed).exists()


def test_child_agent_sources_do_not_embed_skills_or_artifact_operators() -> None:
    assert not list(AGENTS_ROOT.rglob("SKILL.md"))
    assert not (AGENTS_ROOT / "artifacts").exists()
    assert {path.name for path in AGENTS_ROOT.iterdir()} == {"compute", "review"}
    assert (ORCHESTRATION_SKILL_ROOT / "references" / "compute_tools.md").is_file()
    assert (ORCHESTRATION_SKILL_ROOT / "references" / "artifact_tools.md").is_file()


def test_package_manifest_exposes_the_public_skill_family_and_allowlisted_runtime() -> None:
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert manifest["pi"]["skills"] == SKILL_ENTRIES
    assert manifest["pi"]["themes"] == ["./themes/ts-theme.json"]
    assert manifest["files"] == PACKAGE_FILES
    assert manifest["private"] is True
    assert "tests/" not in manifest["files"]
    assert "docs/*.md" in manifest["files"]
    assert "packages/ts-agent-kernel/ts_agent/research/*.py" in manifest["files"]
    assert "packages/ts-agent-kernel/ts_agent/projection/*.py" not in manifest["files"]
    assert "python-dist/*.whl" in manifest["files"]
    assert "scripts/_runtime_install.py" in manifest["files"]
    assert "scripts/_wheel.py" in manifest["files"]
    assert manifest["peerDependencies"] == {
        "@earendil-works/pi-agent-core": "*",
        "@earendil-works/pi-ai": "*",
        "@earendil-works/pi-coding-agent": "*",
        "@earendil-works/pi-tui": "*",
        "typebox": "*",
    }
    assert {
        name: manifest["devDependencies"][name]
        for name in manifest["peerDependencies"]
        if name.startswith("@earendil-works/pi-")
    } == {
        "@earendil-works/pi-agent-core": "0.85.1",
        "@earendil-works/pi-ai": "0.85.1",
        "@earendil-works/pi-coding-agent": "0.85.1",
        "@earendil-works/pi-tui": "0.85.1",
    }
    assert "dependencies" not in manifest
    for name in ("ARCHITECTURE.md", "INSTALLATION.md", "MAINTAINER_GUIDE.md"):
        assert (ROOT / "docs" / name).is_file()
    assert all("packages/ts-agent-runtime/agents" not in entry for entry in manifest["pi"]["skills"])


def test_repository_layout_has_named_source_boundaries() -> None:
    assert not (ROOT / "python").exists()
    assert not (ROOT / "src").exists()
    assert (ROOT / "packages" / "ts-agent-kernel" / "ts_agent").is_dir()
    assert (ROOT / "packages" / "ts-agent-runtime").is_dir()
    assert (ROOT / "apps" / "app-server").is_dir()
    assert (ROOT / "apps" / "app-server" / "pi-app-server.mjs").is_file()
    assert not (ROOT / "apps" / "host").exists()
    assert not (ROOT / "apps" / "terminal").exists()


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
    assert (ROOT / "scripts" / "ts_web_provider.py").stat().st_mode & 0o111
    assert len(source.splitlines()) <= 20
    assert "scripts/tspi_launcher.py" in source
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


def test_tspi_loads_installation_owned_compute_profile_without_probing(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    ssh_config = install_root / ".pi" / "ssh_config"
    ssh_config.parent.mkdir(parents=True, exist_ok=True)
    ssh_config.write_text("Host cluster-login\n  HostName cluster.test\n", encoding="utf-8")
    compute_config = install_root / ".pi" / "compute.toml"
    compute_config.write_text(
        f'''default_environment = "cluster_1w"
[environments.cluster_1w]
kind = "remote"
ssh_host = "cluster-login"
ssh_config = "{ssh_config}"
scheduler = "torque"
remote_root = "/remote/ts"
allowed_queues = ["batch"]
max_nodes = 1
[environments.cluster_1w.backends.xtb]
command = ["xtb"]
''',
        encoding="utf-8",
    )
    diagnostic = _installed_package_root(install_root) / "scripts" / "ts_compute.py"
    diagnostic.write_text("raise SystemExit('remote probe must not run')\n", encoding="utf-8")
    write_test_runtime_manifest(_installed_package_root(install_root), install_root)
    fake_pi = _fake_pi(
        tmp_path / "fake-pi.py",
        "import json, os\nprint(json.dumps({'config': os.environ['TS_COMPUTE_CONFIG'], 'display': os.environ['TS_REMOTE_DISPLAY_TARGET']}))\n",
    )

    completed = _run_tspi(launcher, "--workspace", "no-probe", pi_bin=fake_pi)

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"config": str(compute_config), "display": "cluster-login · Torque"}
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


@pytest.mark.parametrize("provider_field", ["provider", "binding"])
def test_tspi_loads_smtp_notification_config_without_clawemail(
    tmp_path: Path,
    provider_field: str,
) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    config = install_root / ".pi" / "notifications.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "[notifications.email]\n"
        "enabled = true\n"
        f'{provider_field} = "smtp"\n'
        'preset = "163"\n'
        'recipient = "researcher@example.org"\n'
        'username = "researcher@163.com"\n'
        'password_env = "TSPI_EMAIL_PASSWORD"\n',
        encoding="utf-8",
    )
    config.chmod(0o600)
    fake_pi = _fake_pi(
        tmp_path / "fake-pi.py",
        "import json, os\nprint(json.dumps({'config': os.environ['TS_NOTIFICATION_CONFIG'], 'display': os.environ['TS_NOTIFICATION_DISPLAY_TARGET']}))\n",
    )

    completed = _run_tspi(launcher, "--workspace", "notify", pi_bin=fake_pi)

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"config": str(config), "display": "researcher@example.org"}


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
    for name in ("_bootstrap.py", "tspi_launcher.py"):
        shutil.copy2(ROOT / "scripts" / name, install_root / "scripts" / name)

    completed = _run_tspi(launcher, "--workspace", "release-required")

    assert completed.returncode == 1
    assert "no installed Agent component" in completed.stderr
    assert "install a validated TSPi Package" in completed.stderr


def test_tspi_check_remote_runs_one_strict_diagnostic(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    ssh_config = install_root / ".pi" / "ssh_config"
    ssh_config.parent.mkdir(parents=True, exist_ok=True)
    ssh_config.write_text("Host cluster-login\n  HostName cluster.test\n", encoding="utf-8")
    config = install_root / ".pi" / "compute.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        f'default_environment = "cluster"\n[environments.cluster]\nkind = "remote"\nssh_host = "cluster-login"\nssh_config = "{ssh_config}"\nscheduler = "torque"\nremote_root = "/remote/ts"\nallowed_queues = ["batch"]\nmax_nodes = 1\n[environments.cluster.backends.xtb]\ncommand = ["xtb"]\n',
        encoding="utf-8",
    )
    diagnostic = _installed_package_root(install_root) / "scripts" / "ts_compute.py"
    invocation = tmp_path / "diagnostic-argv.json"
    diagnostic.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        f"Path({str(invocation)!r}).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
        "print('{\"ok\": true}')\n",
        encoding="utf-8",
    )
    write_test_runtime_manifest(_installed_package_root(install_root), install_root)

    completed = _run_tspi(launcher, "--check-remote")

    assert completed.returncode == 0, completed.stderr
    assert "remote check passed (cluster-login · Torque)" in completed.stdout
    assert json.loads(invocation.read_text(encoding="utf-8")) == [
        "remote-diagnostic",
        "--mode",
        "doctor",
    ]
    assert not (install_root / "workspaces").exists()


def test_tspi_remote_diagnostic_preserves_structured_failure(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    ssh_config = install_root / ".pi" / "ssh_config"
    ssh_config.parent.mkdir(parents=True, exist_ok=True)
    ssh_config.write_text("Host cluster-login\n  HostName cluster.test\n", encoding="utf-8")
    config = install_root / ".pi" / "compute.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        f'default_environment = "cluster"\n[environments.cluster]\nkind = "remote"\nssh_host = "cluster-login"\nssh_config = "{ssh_config}"\nscheduler = "torque"\nremote_root = "/remote/ts"\nallowed_queues = ["batch"]\nmax_nodes = 1\n[environments.cluster.backends.xtb]\ncommand = ["xtb"]\n',
        encoding="utf-8",
    )
    diagnostic = _installed_package_root(install_root) / "scripts" / "ts_compute.py"
    diagnostic.write_text(
        "print('{\"ok\": false, \"error\": {\"class\": \"ssh_unreachable\"}}')\nraise SystemExit(3)\n",
        encoding="utf-8",
    )
    write_test_runtime_manifest(_installed_package_root(install_root), install_root)

    completed = _run_tspi(launcher, "--check-remote")

    assert completed.returncode == 1
    assert "ssh_unreachable" in completed.stderr


def test_tspi_rejects_a_symlinked_remote_config(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    target = tmp_path / "compute.toml"
    target.write_text("default_environment = 'cluster'\n", encoding="utf-8")
    config = install_root / ".pi" / "compute.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.symlink_to(target)

    completed = _run_tspi(launcher, "--check-remote")

    assert completed.returncode == 1
    assert "invalid TS_COMPUTE_CONFIG" in completed.stderr


def test_tspi_runs_host_client_with_bootstrapped_workspace_and_install_runtime(tmp_path: Path) -> None:
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
        "compute_config": os.environ.get("TS_COMPUTE_CONFIG"),
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
    assert result["runtime_home"] == str(install_root / ".agents" / "runtime" / "tspi")
    assert result["runtime_manifest"] == str(
        install_root / ".agents" / "runtime" / "tspi" / "env.json"
    )
    assert result["env_root"] == str(install_root / ".agents" / "envs" / "tspi")
    managed_python = Path(result["managed_python"]).resolve()
    assert managed_python == install_root / ".test-python-runtime" / "kernel" / "bin" / "python"
    assert Path(result["path_python"]).resolve() == managed_python
    assert Path(result["path_python3"]).resolve().parent == managed_python.parent
    assert result["no_user_site"] == "1"
    assert result["python_cache"] == str(install_root / ".pi" / "runtime-cache" / "python" / "reaction-a")
    assert result["pytest_options"].endswith(
        f"--cache-dir={install_root / '.pi' / 'runtime-cache' / 'pytest' / 'reaction-a'}"
    )
    assert result["compute_config"] is None
    assert result["remote_display"] == "not configured"
    # The default path is the Host adapter, which selects/creates the durable
    # Harness session before exec'ing Pi's native remote client. It must not
    # start an ordinary local Pi loop or a second session writer.
    assert result["argv"][0].endswith("/apps/app-server/tspi-terminal-client.mjs")
    socket_path = result["argv"][result["argv"].index("--socket-path") + 1]
    assert socket_path.endswith(".sock")
    assert result["argv"][result["argv"].index("--workspace-id") + 1] == "reaction-a"
    assert result["argv"][result["argv"].index("--workspace-root") + 1] == str(workspace)
    assert result["argv"][result["argv"].index("--package-root") + 1].endswith("/agent")
    assert "--connect" not in result["argv"]
    assert "--session-dir" not in result["argv"]
    assert "--session-id" not in result["argv"]
    # The remote client does not take the ordinary local writer lock; the
    # installation Host/Pi server owns the durable session lifecycle instead.
    assert not (workspace / ".pi" / "root-agent.lock").exists()
    assert json.loads((workspace / ".pi" / "settings.json").read_text(encoding="utf-8")) == {"quietStartup": True}
    research_map = json.loads((workspace / "research_map.json").read_text(encoding="utf-8"))
    assert research_map["schema_version"] == "research-map/1"
    assert research_map["map_id"] == json.loads((workspace / "workspace.json").read_text(encoding="utf-8"))["workspace_id"]
    assert (workspace / ".agents" / "workspace-identity.json").is_file()


def test_tspi_fails_closed_without_managed_runtime_manifest(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    manifest = install_root / ".agents" / "runtime" / "tspi" / "env.json"
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
    assert (install_root / "workspaces" / "existing" / "research_map.json").is_file()


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
    (install_root / ".pi").mkdir(mode=0o700, exist_ok=True)
    (install_root / ".pi").chmod(0o700)
    blocking_pi = _fake_pi(
        tmp_path / "blocking-pi.py",
        "print('ready', flush=True)\ninput()\n",
    )
    command = [str(launcher), "--host"]
    env = {**os.environ, "PI_BIN": str(blocking_pi)}
    env["TSPI_SYSTEMD_HOST"] = "1"
    env["PATH"] = f"{install_root / 'fake-bin'}:{env.get('PATH', '')}"
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
    finally:
        assert holder.stdin is not None
        holder.stdin.write("release\n")
        holder.stdin.flush()
        holder.communicate(timeout=5)

    assert (install_root / ".pi" / "app-server-host" / "workspace" / ".pi" / "root-agent.lock").is_file()


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
