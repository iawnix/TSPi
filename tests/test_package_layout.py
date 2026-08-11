from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "transition-state-workflow"
AGENTS_ROOT = ROOT / "src" / "agents"
THEME_PATH = ROOT / "themes" / "ts-theme.json"
TSPI_LAUNCHER = ROOT / "TSPi"
EXPECTED_FILES = [
    "TSPi",
    "README.md",
    "environment.yml",
    "cluster_mcp/*.py",
    "cluster_mcp/schedulers/*.py",
    "cluster_mcp/*.example.toml",
    "contracts/*.json",
    "extensions/shared/*.ts",
    "extensions/ts-workflow-artifacts/*.ts",
    "extensions/ts-workflow-compute/*.ts",
    "extensions/ts-workflow-compute/*.cjs",
    "extensions/ts-workflow-control/*.ts",
    "extensions/ts-workflow-control/*.cjs",
    "extensions/ts-workflow-review/*.ts",
    "extensions/ts-workflow-ui/*.ts",
    "scripts/*.py",
    "skills/",
    "themes/*.json",
    "src/agent-core/*.cjs",
    "src/agents/review/*.ts",
    "src/agents/review/*.cjs",
    "src/agents/review/prompts/*.md",
    "src/agents/compute/*.ts",
    "src/agents/compute/*.cjs",
    "src/agents/compute/*.md",
    "src/agents/compute/backends/*.md",
    "src/agents/artifacts/*.ts",
    "src/agents/artifacts/*.cjs",
    "src/agents/artifacts/*.md",
    "src/agents/artifacts/roles/*.md",
    "ts_backends/*.py",
    "ts_compute/*.py",
    "ts_compute/contracts/*.json",
    "ts_email/*.py",
    "ts_remote/*.py",
    "ts_render/*.py",
    "ts_report/*.py",
    "ts_runtime/*.py",
    "ts_structures/*.py",
    "ts_web/*.py",
    "ts_web/static/*.html",
    "ts_workspace/*.py",
    "ts_workspace/contracts/*.json",
    "ts_workspace/finalizers/*.py",
    "ts_workspace/readers/*.py",
    "ts_workspace/validators/*.py",
]


def _copy_tspi_install(tmp_path: Path) -> tuple[Path, Path]:
    install_root = tmp_path / "tspi-install"
    launcher = install_root / "TSPi"
    package_root = install_root / ".pi" / "git" / "github.com" / "iawnix" / "TSAgentSkill"
    package_root.mkdir(parents=True)
    shutil.copy2(TSPI_LAUNCHER, launcher)
    launcher.chmod(0o755)
    return install_root, launcher


def test_public_skill_uses_nested_pi_skill_layout() -> None:
    assert (SKILL_ROOT / "SKILL.md").is_file()
    assert (SKILL_ROOT / "agents" / "openai.yaml").is_file()
    assert (SKILL_ROOT / "references" / "research_node_ontology.md").is_file()
    assert (SKILL_ROOT / "assets" / "templates" / "ts_final_report.md").is_file()
    assert not (ROOT / "SKILL.md").exists()
    assert not (ROOT / "references").exists()
    assert not (ROOT / "templates").exists()


def test_agent_sources_have_explicit_ownership_boundaries() -> None:
    assert (ROOT / "extensions" / "shared" / "tool-catalog.ts").is_file()
    assert not (ROOT / "extensions" / "ts-workflow-context").exists()
    assert not (ROOT / "extensions" / "ts-workflow-subagent").exists()
    assert (ROOT / "src" / "agent-core" / "agent-protocol.cjs").is_file()
    assert (ROOT / "src" / "agent-core" / "fact-kinds.cjs").is_file()
    assert (ROOT / "src" / "agent-core" / "failure-taxonomy.cjs").is_file()
    assert (AGENTS_ROOT / "review" / "runtime.ts").is_file()
    assert (AGENTS_ROOT / "review" / "prompts" / "core.md").is_file()
    assert (AGENTS_ROOT / "compute" / "runtime.ts").is_file()
    assert (AGENTS_ROOT / "compute" / "policy-loader.cjs").is_file()
    assert (AGENTS_ROOT / "compute" / "policy.md").is_file()
    assert (AGENTS_ROOT / "artifacts" / "runtime.ts").is_file()
    assert (AGENTS_ROOT / "artifacts" / "policy-loader.cjs").is_file()
    assert (AGENTS_ROOT / "artifacts" / "policy.md").is_file()
    assert (AGENTS_ROOT / "artifacts" / "roles" / "report.md").is_file()
    assert (ROOT / "ts_workspace" / "evidence_lifecycle.py").is_file()
    for legacy in ("agent-core", "review-agent", "compute-agent", "artifact-agent", "agent-skills"):
        assert not (ROOT / legacy).exists()


def test_operator_policies_are_owned_by_their_only_consuming_agent() -> None:
    compute = {path.stem for path in (AGENTS_ROOT / "compute" / "backends").glob("*.md")}
    artifacts = {path.stem for path in (AGENTS_ROOT / "artifacts" / "roles").glob("*.md")}
    assert compute == {"ase", "crest", "gaussian", "qbics", "rdkit", "xtb"}
    assert artifacts == {"email", "render", "report"}
    assert compute.isdisjoint(artifacts)
    assert not list(AGENTS_ROOT.rglob("SKILL.md"))
    assert not (AGENTS_ROOT / "compute" / "private-skills").exists()
    assert not (AGENTS_ROOT / "artifacts" / "private-skills").exists()


def test_operator_policy_loaders_compose_common_and_selected_policy() -> None:
    compute_loader = AGENTS_ROOT / "compute" / "policy-loader.cjs"
    artifact_loader = AGENTS_ROOT / "artifacts" / "policy-loader.cjs"
    script = f"""
const compute = require({json.dumps(str(compute_loader))});
const artifacts = require({json.dumps(str(artifact_loader))});
let computeError;
let artifactError;
try {{ compute.loadComputePolicy("missing"); }} catch (error) {{ computeError = error.message; }}
try {{ artifacts.loadArtifactPolicy("missing"); }} catch (error) {{ artifactError = error.message; }}
process.stdout.write(JSON.stringify({{
  compute: compute.loadComputePolicy("gaussian"),
  artifact: artifacts.loadArtifactPolicy("email"),
  computeFiles: compute.BACKEND_POLICY_FILES,
  roleFiles: artifacts.ROLE_POLICY_FILES,
  computeError,
  artifactError,
}}));
"""
    completed = subprocess.run(
        ["node", "--eval", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert "# Compute Operator Policy" in result["compute"]
    assert "# Gaussian Backend Policy" in result["compute"]
    assert "# xTB Backend Policy" not in result["compute"]
    assert "# Artifact Operator Policy" in result["artifact"]
    assert "# Email Role Policy" in result["artifact"]
    assert "# Render Role Policy" not in result["artifact"]
    assert "---" not in result["compute"] + result["artifact"]
    assert set(result["computeFiles"]) == {
        "gaussian",
        "ase_neb",
        "crest",
        "rdkit",
        "xtb",
        "qbics_dmecp",
    }
    assert set(result["roleFiles"]) == {"render", "report", "email"}
    assert result["computeError"] == "No compute backend policy is registered for: missing"
    assert result["artifactError"] == "No artifact role policy is registered for: missing"


def test_package_manifest_exposes_only_the_public_skill_and_allowlisted_runtime() -> None:
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert manifest["pi"]["skills"] == ["./skills/transition-state-workflow"]
    assert manifest["pi"]["themes"] == ["./themes/ts-theme.json"]
    assert manifest["files"] == EXPECTED_FILES
    assert manifest["private"] is True
    assert "tests/" not in manifest["files"]
    assert "docs/" not in manifest["files"]
    assert all("src/agents" not in entry for entry in manifest["pi"]["skills"])


def test_tspi_launcher_is_packaged_executable_and_shell_valid() -> None:
    completed = subprocess.run(
        ["bash", "-n", str(TSPI_LAUNCHER)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert TSPI_LAUNCHER.stat().st_mode & 0o111
    source = TSPI_LAUNCHER.read_text(encoding="utf-8")
    assert 'readonly INSTALL_ROOT="$LAUNCHER_DIR"' in source
    assert 'readonly TS_WORKSPACES_ROOT="$INSTALL_ROOT/workspaces"' in source
    assert "mcp_protocol_is_healthy" in source
    assert "TS_MCP_CONTROL_SOCKET" in source
    assert "TS_MCP_LOCK_FILE" in source
    assert 'export TS_EMAIL_POLICY_ROOT="$INSTALL_ROOT"' in source
    assert 'export TS_AGENT_RUNTIME_HOME="$TS_AGENT_INSTALL_RUNTIME_HOME"' in source
    assert 'export TS_WORKSPACE_ROOT="$WORKSPACE_ROOT"' in source
    assert "acquire_root_agent_lock" in source
    assert "refusing to terminate an unknown process" in source
    assert "--workspace" in source
    assert "--check-mcp" in source


def test_tspi_reuses_a_healthy_shared_managed_tunnel(tmp_path: Path) -> None:
    _, launcher = _copy_tspi_install(tmp_path)
    script = r'''source "$1"
probe_calls=0
starts=0
stops=0
mcp_protocol_is_healthy() { ((probe_calls += 1)); return 0; }
mcp_tunnel_is_open() { return 0; }
mcp_control_is_open() { return 0; }
stop_managed_mcp_tunnel() { ((stops += 1)); }
start_managed_mcp_tunnel() { ((starts += 1)); }
ensure_mcp_connection
printf '%s %s %s\n' "$probe_calls" "$starts" "$stops"
'''
    completed = subprocess.run(
        ["bash", "-c", script, "bash", str(launcher)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "1 0 0"


def test_tspi_does_not_restart_a_managed_tunnel_on_protocol_failure(tmp_path: Path) -> None:
    _, launcher = _copy_tspi_install(tmp_path)
    script = r'''source "$1"
starts=0
stops=0
mcp_protocol_is_healthy() { MCP_PROTOCOL_DIAGNOSTIC="application timeout"; return 1; }
mcp_tunnel_is_open() { return 0; }
mcp_control_is_open() { return 0; }
stop_managed_mcp_tunnel() { ((stops += 1)); }
start_managed_mcp_tunnel() { ((starts += 1)); }
if ensure_mcp_connection; then status=0; else status=$?; fi
printf '%s %s %s\n' "$status" "$starts" "$stops"
'''
    completed = subprocess.run(
        ["bash", "-c", script, "bash", str(launcher)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "1 0 0"
    assert "application timeout" in completed.stderr
    assert "managed SSH tunnel is healthy and was not restarted" in completed.stderr


def test_tspi_starts_an_absent_shared_tunnel_once(tmp_path: Path) -> None:
    _, launcher = _copy_tspi_install(tmp_path)
    script = r'''source "$1"
port_open=0
control_open=0
starts=0
mcp_protocol_is_healthy() { return 0; }
mcp_tunnel_is_open() { [[ $port_open == 1 ]]; }
mcp_control_is_open() { [[ $control_open == 1 ]]; }
stop_managed_mcp_tunnel() { port_open=0; control_open=0; }
start_managed_mcp_tunnel() { ((starts += 1)); port_open=1; control_open=1; }
ensure_mcp_connection
ensure_mcp_connection
printf '%s\n' "$starts"
'''
    completed = subprocess.run(
        ["bash", "-c", script, "bash", str(launcher)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "1"


def test_tspi_protocol_diagnostic_preserves_context_and_redacts_token(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    diagnostic_script = install_root / ".pi/git/github.com/iawnix/TSAgentSkill/scripts/ts_compute.py"
    diagnostic_script.parent.mkdir(parents=True)
    diagnostic_script.write_text(
        """import sys
sys.stderr.write("Authorization: Bearer test-secret-token-value\\n")
print('{"ok": false, "token": "test-secret-token-value", "error": "registry unavailable"}')
raise SystemExit(3)
""",
        encoding="utf-8",
    )
    script = r'''source "$1"
if mcp_protocol_is_healthy; then status=0; else status=$?; fi
printf '%s\n%s\n' "$status" "$MCP_PROTOCOL_DIAGNOSTIC"
'''
    completed = subprocess.run(
        ["bash", "-c", script, "bash", str(launcher)],
        cwd=ROOT,
        env={**os.environ, "TS_CLUSTER_MCP_TOKEN": "test-secret-token-value"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines()[0] == "1"
    assert "registry unavailable" in completed.stdout
    assert "[REDACTED]" in completed.stdout
    assert "test-secret-token-value" not in completed.stdout


def test_tspi_refuses_to_kill_an_unmanaged_listener(tmp_path: Path) -> None:
    _, launcher = _copy_tspi_install(tmp_path)
    script = r'''source "$1"
MCP_PROTOCOL_DIAGNOSTIC="invalid response"
mcp_protocol_is_healthy() { return 1; }
mcp_tunnel_is_open() { return 0; }
mcp_control_is_open() { return 1; }
ensure_mcp_connection
'''
    completed = subprocess.run(
        ["bash", "-c", script, "bash", str(launcher)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 1
    assert "refusing to terminate an unknown process" in completed.stderr


def test_tspi_runs_pi_with_workspace_local_state_and_install_runtime(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    fake_pi = tmp_path / "fake-pi.py"
    fake_pi.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
print(json.dumps({
    "argv": sys.argv[1:],
    "cwd": os.getcwd(),
    "workspace": os.environ["TS_WORKSPACE_ROOT"],
    "email_policy": os.environ["TS_EMAIL_POLICY_ROOT"],
    "runtime_home": os.environ["TS_AGENT_RUNTIME_HOME"],
    "runtime_manifest": os.environ["TS_AGENT_RUNTIME_MANIFEST"],
    "env_root": os.environ["TS_AGENT_ENV_ROOT"],
    "mcp_startup_status": os.environ["TS_CLUSTER_MCP_STARTUP_STATUS"],
}))
""",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)
    script = r'''source "$1"
mcp_protocol_is_healthy() { return 0; }
mcp_tunnel_is_open() { return 0; }
mcp_control_is_open() { return 0; }
mcp_ssh_display_target() { printf 'test.example via SSH'; }
main "${@:2}"
'''
    completed = subprocess.run(
        ["bash", "-c", script, "bash", str(launcher), "--workspace", "reaction-a", "--model", "test"],
        cwd=ROOT,
        env={
            **os.environ,
            "PI_BIN": str(fake_pi),
            "TS_EMAIL_POLICY_ROOT": "/tmp/old-workspace",
            "TS_AGENT_RUNTIME_HOME": "/tmp/old-runtime",
            "TS_AGENT_RUNTIME_MANIFEST": "/tmp/old-runtime/env.json",
            "TS_AGENT_ENV_ROOT": "/tmp/old-env",
        },
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    workspace = install_root / "workspaces" / "reaction-a"
    assert result["cwd"] == str(workspace)
    assert result["workspace"] == str(workspace)
    assert result["email_policy"] == str(install_root)
    assert result["runtime_home"] == str(install_root / ".agents/runtime/transition-state-workflow")
    assert result["runtime_manifest"] == str(install_root / ".agents/runtime/transition-state-workflow/env.json")
    assert result["env_root"] == str(install_root / ".agents/envs/transition-state-workflow")
    assert result["mcp_startup_status"] == "ready"
    session_index = result["argv"].index("--session-dir")
    assert result["argv"][session_index + 1] == str(workspace / ".pi/sessions")
    assert (workspace / ".pi/root-agent.lock").is_file()


def test_tspi_workspace_launch_continues_when_mcp_is_unavailable(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    fake_pi = tmp_path / "fake-pi.py"
    fake_pi.write_text(
        """#!/usr/bin/env python3
import json
import os
print(json.dumps({
    "cwd": os.getcwd(),
    "mcp_startup_status": os.environ["TS_CLUSTER_MCP_STARTUP_STATUS"],
}))
""",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)
    script = r'''source "$1"
ensure_mcp_connection() { return 1; }
mcp_ssh_display_target() { printf 'test.example via SSH'; }
main "${@:2}"
'''
    completed = subprocess.run(
        ["bash", "-c", script, "bash", str(launcher), "--workspace", "offline-research"],
        cwd=ROOT,
        env={**os.environ, "PI_BIN": str(fake_pi)},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["cwd"] == str(install_root / "workspaces/offline-research")
    assert result["mcp_startup_status"] == "unavailable"
    assert "continuing with remote compute unavailable" in completed.stderr


def test_tspi_check_mcp_remains_strict_when_mcp_is_unavailable(tmp_path: Path) -> None:
    _, launcher = _copy_tspi_install(tmp_path)
    script = r'''source "$1"
ensure_mcp_connection() { return 1; }
mcp_ssh_display_target() { printf 'test.example via SSH'; }
main --check-mcp
'''
    completed = subprocess.run(
        ["bash", "-c", script, "bash", str(launcher)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 1
    assert "MCP check passed" not in completed.stdout


def test_tspi_requires_a_safe_workspace_name(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    no_workspace = subprocess.run(
        ["bash", str(launcher)],
        cwd=install_root,
        env={**os.environ, "PI_BIN": "/bin/true"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert no_workspace.returncode == 2
    assert "a research workspace is required" in no_workspace.stderr

    script = r'''source "$1"
prepare_workspace "$2"
'''
    traversal = subprocess.run(
        ["bash", "-c", script, "bash", str(launcher), "../escaped"],
        cwd=install_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert traversal.returncode == 1
    assert "invalid workspace name" in traversal.stderr
    assert not (install_root.parent / "escaped").exists()


def test_tspi_root_lock_rejects_a_second_writer(tmp_path: Path) -> None:
    install_root, launcher = _copy_tspi_install(tmp_path)
    holder_script = r'''source "$1"
prepare_workspace "$2"
acquire_root_agent_lock
printf 'ready\n'
read -r _release
'''
    holder = subprocess.Popen(
        ["bash", "-c", holder_script, "bash", str(launcher), "lock-test"],
        cwd=ROOT,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "ready"
        contender = subprocess.run(
            ["bash", "-c", holder_script, "bash", str(launcher), "lock-test"],
            cwd=ROOT,
            input="release\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert contender.returncode == 1
        assert "another Root Agent already owns workspace" in contender.stderr
        independent = subprocess.run(
            ["bash", "-c", holder_script, "bash", str(launcher), "independent-test"],
            cwd=ROOT,
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

    assert (install_root / "workspaces/lock-test/.pi/root-agent.lock").is_file()
    assert (install_root / "workspaces/independent-test/.pi/root-agent.lock").is_file()


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
