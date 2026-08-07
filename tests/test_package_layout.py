from __future__ import annotations

import json
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
    assert "mcp_protocol_is_healthy" in source
    assert "TS_MCP_CONTROL_SOCKET" in source
    assert "refusing to terminate an unknown process" in source
    assert "--check-mcp" in source


def test_tspi_restarts_one_managed_unhealthy_tunnel() -> None:
    script = r'''source "$1"
probe_calls=0
port_open=1
control_open=1
starts=0
stops=0
mcp_protocol_is_healthy() { ((probe_calls += 1)); [[ $probe_calls -ge 2 ]]; }
mcp_tunnel_is_open() { [[ $port_open == 1 ]]; }
mcp_control_is_open() { [[ $control_open == 1 ]]; }
stop_managed_mcp_tunnel() { ((stops += 1)); port_open=0; control_open=0; }
start_managed_mcp_tunnel() { ((starts += 1)); port_open=1; control_open=1; }
ensure_mcp_connection
printf '%s %s %s\n' "$probe_calls" "$starts" "$stops"
'''
    completed = subprocess.run(
        ["bash", "-c", script, "bash", str(TSPI_LAUNCHER)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "2 1 1"


def test_tspi_refuses_to_kill_an_unmanaged_listener() -> None:
    script = r'''source "$1"
mcp_protocol_is_healthy() { return 1; }
mcp_tunnel_is_open() { return 0; }
mcp_control_is_open() { return 1; }
ensure_mcp_connection
'''
    completed = subprocess.run(
        ["bash", "-c", script, "bash", str(TSPI_LAUNCHER)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 1
    assert "refusing to terminate an unknown process" in completed.stderr


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
