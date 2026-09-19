from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
README_ZH = ROOT / "README.zh-CN.md"
ARCHITECTURE = ROOT / "docs" / "ARCHITECTURE.md"
ARCHITECTURE_ZH = ROOT / "docs" / "ARCHITECTURE.zh-CN.md"
TERMINAL = ROOT / "docs" / "TERMINAL.md"
TERMINAL_ZH = ROOT / "docs" / "TERMINAL.zh-CN.md"
INSTALLATION = ROOT / "docs" / "INSTALLATION.md"
MAINTAINER = ROOT / "docs" / "MAINTAINER_GUIDE.md"
ADR = ROOT / "docs" / "adr" / "0001-phase-node-research-kernel.md"
SKILL_ROOT = ROOT / "skills" / "tspi-research-kernel"
SKILL = SKILL_ROOT / "SKILL.md"
REFERENCES = SKILL_ROOT / "references"
ORCHESTRATION_ROOT = ROOT / "skills" / "tspi-orchestration"
FOCUSED_SKILLS = {
    "tspi-orchestration": ORCHESTRATION_ROOT,
    "tspi-ts-candidate-generation": ROOT / "skills" / "tspi-ts-candidate-generation",
    "tspi-ts-validation": ROOT / "skills" / "tspi-ts-validation",
    "tspi-irc": ROOT / "skills" / "tspi-irc",
    "tspi-energetics": ROOT / "skills" / "tspi-energetics",
    "tspi-method-selection": ROOT / "skills" / "tspi-method-selection",
    "tspi-xtb": ROOT / "skills" / "tspi-xtb",
    "tspi-crest": ROOT / "skills" / "tspi-crest",
    "tspi-qbics": ROOT / "skills" / "tspi-qbics",
    "tspi-gaussian": ROOT / "skills" / "tspi-gaussian",
    "tspi-render": ROOT / "skills" / "tspi-render",
    "tspi-report": ROOT / "skills" / "tspi-report",
    "tspi-email": ROOT / "skills" / "tspi-email",
    "tspi-mechanism-reasoning": ROOT / "skills" / "tspi-mechanism-reasoning",
}


PUBLIC_DOCS = (
    README, README_ZH, ARCHITECTURE, ARCHITECTURE_ZH, TERMINAL, TERMINAL_ZH,
    INSTALLATION, MAINTAINER, ADR,
    ROOT / "skills" / "README.md", ROOT / "skills" / "README.zh-CN.md",
)


def test_readmes_link_to_setup_usage_and_developer_guides() -> None:
    for path in (README, README_ZH):
        targets = set(re.findall(r"\[[^\]]+\]\(([^)]+)\)", path.read_text(encoding="utf-8")))
        for target in (
            "README.md",
            "README.zh-CN.md",
            "docs/INSTALLATION.md",
            "docs/TERMINAL.zh-CN.md" if path == README_ZH else "docs/TERMINAL.md",
            "docs/ARCHITECTURE.md",
            "docs/ARCHITECTURE.zh-CN.md",
            "docs/MAINTAINER_GUIDE.md",
        ):
            assert target in targets, (path, target)


def test_public_document_set_covers_install_architecture_and_maintenance() -> None:
    for path in PUBLIC_DOCS:
        assert path.is_file()
        assert path.read_text(encoding="utf-8").startswith("# ")

    installation = INSTALLATION.read_text(encoding="utf-8")
    for heading in [
        "## Prerequisites",
        "## Install Or Select A Release",
        "## Managed Python Runtime",
        "## Configure Remote Execution",
        "## Configure Notifications",
        "## Start The Installation Host",
        "## Workspace Bootstrap",
        "## Run The Research Explorer",
        "## Upgrade",
        "## Rollback",
        "## Operational Recovery",
    ]:
        assert heading in installation

    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    for heading in [
        "## Component Responsibilities",
        "## Scientific State Model",
        "## ChangeSets And Browser Clients",
        "## TSPi Lifecycle",
        "## Isolated Agent Runtimes",
        "## Deterministic Tool Plane",
        "## Run Journals And Result Delivery",
        "## Contract Locations",
    ]:
        assert heading in architecture

    maintainer = MAINTAINER.read_text(encoding="utf-8")
    for heading in [
        "## Scientific Model",
        "## ResearchMap Validation Rules",
        "## Deterministic Tool Contracts",
        "## Documentation Ownership",
        "## Contract Change Matrix",
        "## Release Procedure",
        "## Rollback Discipline",
    ]:
        assert heading in maintainer


def test_public_markdown_relative_links_resolve_inside_the_package() -> None:
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    focused_files = [
        path
        for root in FOCUSED_SKILLS.values()
        for path in (root / "SKILL.md", root / "SKILL.zh-CN.md", *sorted((root / "references").glob("*.md")))
    ]
    for path in (*PUBLIC_DOCS, SKILL, SKILL_ROOT / "SKILL.zh-CN.md", *sorted(REFERENCES.glob("*.md")), *focused_files):
        for raw_target in link_pattern.findall(path.read_text(encoding="utf-8")):
            target = raw_target.strip().strip("<>")
            if target.startswith("#") or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                continue
            relative = unquote(target.split("#", 1)[0].split("?", 1)[0])
            resolved = (path.parent / relative).resolve()
            assert resolved.is_relative_to(ROOT), (path, target)
            assert resolved.exists(), (path, target)


def test_normal_runtime_docs_expose_only_current_contracts() -> None:
    focused_files = [
        path
        for root in FOCUSED_SKILLS.values()
        for path in (root / "SKILL.md", root / "SKILL.zh-CN.md", *sorted((root / "references").glob("*.md")))
    ]
    paths = [
        README,
        README_ZH,
        ARCHITECTURE,
        ARCHITECTURE_ZH,
        INSTALLATION,
        MAINTAINER,
        SKILL,
        SKILL_ROOT / "SKILL.zh-CN.md",
        *sorted(REFERENCES.glob("*.md")),
        *focused_files,
    ]
    forbidden = [
        "ts-research-kernel/4",
        "ts-workspace/4",
        "ts-research-decision/1",
        "research_acts.json",
        "start_act",
        "complete_act",
        "createdByAct",
        "actRefs",
        "focus_act_refs",
        "evidence_registry.json",
        "required_gates",
        "solution_ref",
        "previous_attempt_summary",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for term in forbidden:
            assert term not in text, (path, term)


def test_workspace_docs_match_bootstrap_canonical_file_names() -> None:
    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    contract = (REFERENCES / "workspace_contract.md").read_text(encoding="utf-8")

    required = [
        "workspace.json",
        "research_map.json",
        "transactions.jsonl",
        "nodes/<node_id>/",
    ]
    for text in (architecture, contract):
        for name in required:
            assert name in text
    assert "Bootstrap rejects an unsupported workspace without rewriting it" in contract


def test_skill_routes_details_through_focused_references() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert len(text.splitlines()) < 260
    for ref in [
        "references/state_model.md",
        "references/workspace_contract.md",
        "references/decision_contract.md",
        "references/glossary.md",
    ]:
        assert ref in text
    orchestration = (ORCHESTRATION_ROOT / "SKILL.md").read_text(encoding="utf-8")
    for ref in (
        "references/compute_tools.md",
        "references/pi_agent_adapter.md",
        "references/agent_decision_protocol.md",
        "references/artifact_tools.md",
        "references/package_sources.md",
        "references/program_runtime_failures.md",
    ):
        assert ref in orchestration


def test_skill_progressive_disclosure_routes_every_reference() -> None:
    for root in [SKILL_ROOT, *FOCUSED_SKILLS.values()]:
        english_skill = (root / "SKILL.md").read_text(encoding="utf-8")
        chinese_skill = (root / "SKILL.zh-CN.md").read_text(encoding="utf-8")
        references = sorted((root / "references").glob("*.md"))
        english_references = [path for path in references if not path.name.endswith(".zh-CN.md")]
        chinese_references = [path for path in references if path.name.endswith(".zh-CN.md")]

        expected_chinese_names = {
            f"{path.stem}.zh-CN.md" for path in english_references
        }
        assert {path.name for path in chinese_references} == expected_chinese_names, root

        for path in english_references:
            translated = path.with_name(f"{path.stem}.zh-CN.md")
            assert translated.is_file(), path
            assert f"references/{path.name}" in english_skill, path
            assert f"references/{translated.name}" in chinese_skill, translated
            assert f"references/{translated.name}" not in english_skill, translated
            assert f"references/{path.name}" not in chinese_skill, path

        for path in references:
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) > 100:
                contents_heading = "## 内容" if path.name.endswith(".zh-CN.md") else "## Contents"
                assert contents_heading in lines, path


def test_focused_skills_have_bilingual_entrypoints_and_route_their_references() -> None:
    for name, root in FOCUSED_SKILLS.items():
        english = root / "SKILL.md"
        chinese = root / "SKILL.zh-CN.md"
        assert english.is_file()
        assert chinese.is_file()
        english_skill = english.read_text(encoding="utf-8")
        chinese_skill = chinese.read_text(encoding="utf-8")
        assert f"name: {name}" in english_skill
        assert f"name: {name}" in chinese_skill
        for reference in root.glob("references/*.md"):
            target = f"references/{reference.name}"
            if reference.name.endswith(".zh-CN.md"):
                assert target in chinese_skill, (chinese, reference)
                assert target not in english_skill, (english, reference)
            else:
                assert target in english_skill, (english, reference)
                assert target not in chinese_skill, (chinese, reference)


def test_compute_reference_uses_the_registered_gaussian_input_role() -> None:
    compute = (ORCHESTRATION_ROOT / "references" / "compute_tools.md").read_text(encoding="utf-8")

    assert '"inputRole": "gjf"' in compute
    assert '"inputRole": "structure"' not in compute


def test_final_report_builder_renders_phase_node_and_scientific_objects() -> None:
    text = (ROOT / "packages" / "ts-agent-kernel" / "ts_agent" / "report" / "builder.py").read_text(encoding="utf-8")

    for phrase in [
        "Research Roadmap",
        "ResearchNode Records",
        "## Findings",
        "## Gates",
        "Operational Follow-up",
        "phase[\"id\"]",
        "claim['id']",
        "node['id']",
        "finding['id']",
        "gate['id']",
    ]:
        assert phrase in text
    for removed in ('"act_id"', "evidence_id", "gate_result_id", "required_gates"):
        assert removed not in text


def test_static_research_map_templates_are_removed() -> None:
    assert not list((ROOT / "skills").glob("*/assets/templates/research_map"))
