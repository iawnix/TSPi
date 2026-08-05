from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "transition-state-workflow"
AGENTS_ROOT = ROOT / "src" / "agents"
EXPECTED_FILES = [
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
    "extensions/ts-workflow-context/*.ts",
    "extensions/ts-workflow-context/*.cjs",
    "extensions/ts-workflow-subagent/*.ts",
    "scripts/*.py",
    "skills/",
    "src/agent-core/*.cjs",
    "src/agents/review/*.ts",
    "src/agents/review/*.cjs",
    "src/agents/review/prompts/*.md",
    "src/agents/compute/*.ts",
    "src/agents/compute/*.cjs",
    "src/agents/compute/*.md",
    "src/agents/compute/private-skills/*/SKILL.md",
    "src/agents/artifacts/*.ts",
    "src/agents/artifacts/*.cjs",
    "src/agents/artifacts/*.md",
    "src/agents/artifacts/private-skills/*/SKILL.md",
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
    assert (ROOT / "src" / "agent-core" / "agent-protocol.cjs").is_file()
    assert (AGENTS_ROOT / "review" / "runtime.ts").is_file()
    assert (AGENTS_ROOT / "compute" / "runtime.ts").is_file()
    assert (AGENTS_ROOT / "artifacts" / "runtime.ts").is_file()
    for legacy in ("agent-core", "review-agent", "compute-agent", "artifact-agent", "agent-skills"):
        assert not (ROOT / legacy).exists()


def test_private_skills_are_owned_by_their_only_consuming_agent() -> None:
    compute = {
        path.parent.name
        for path in (AGENTS_ROOT / "compute" / "private-skills").glob("*/SKILL.md")
    }
    artifacts = {
        path.parent.name
        for path in (AGENTS_ROOT / "artifacts" / "private-skills").glob("*/SKILL.md")
    }
    assert compute == {"backend-ase", "backend-gaussian", "backend-qbics", "backend-rdkit", "backend-xtb"}
    assert artifacts == {"email", "render", "research-report"}
    assert compute.isdisjoint(artifacts)


def test_package_manifest_exposes_only_the_public_skill_and_allowlisted_runtime() -> None:
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert manifest["pi"]["skills"] == ["./skills/transition-state-workflow"]
    assert manifest["files"] == EXPECTED_FILES
    assert manifest["private"] is True
    assert "tests/" not in manifest["files"]
    assert "docs/" not in manifest["files"]
    assert "src/agents/compute/private-skills" not in manifest["pi"]["skills"]
    assert "src/agents/artifacts/private-skills" not in manifest["pi"]["skills"]
