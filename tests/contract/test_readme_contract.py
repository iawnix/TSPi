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
ADR = ROOT / "docs" / "archive" / "adr" / "0001-phase-node-research-state.md"
SKILL_ROOT = ROOT / "skills" / "research-memory"
SKILL = SKILL_ROOT / "SKILL.md"
REFERENCES = SKILL_ROOT / "references"
ORCHESTRATION_ROOT = ROOT / "skills" / "research-workflow"
FOCUSED_SKILLS = {
    "research-workflow": ORCHESTRATION_ROOT,
    **{name: ROOT / "domains" / "chemical" / "skills" / name for name in (
        "candidate-generation", "validation", "irc", "energetics", "method-selection",
        "cf22d", "xtb", "crest", "qbics", "gaussian", "mechanism-reasoning", "chemical-input",
    )},
    "email": ROOT / "skills" / "email",
}


PUBLIC_DOCS = (
    README, README_ZH, ARCHITECTURE, ARCHITECTURE_ZH, TERMINAL, TERMINAL_ZH,
    INSTALLATION, MAINTAINER, ADR,

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
        "## Configure execution targets",
        "## Configure Notifications",
        "## Start The Installation Host",
        "## Workspace Bootstrap",
        "## Run The Research Explorer",
        "## Upgrade",
        "## Installation Failure Recovery",
        "## Operational Recovery",
    ]:
        assert heading in installation

    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    for heading in [
        "## Ownership",
        "## Workspace and storage",
        "## Model-facing interface",
        "## Context and next_run",
        "## Skills and delivery",
    ]:
        assert heading in architecture

    maintainer = MAINTAINER.read_text(encoding="utf-8")
    for heading in [
        "## Research Memory and Execution Boundaries",
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
        "ts-research-state/4",
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


def test_normal_runtime_docs_use_canonical_tool_names() -> None:
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
    legacy_tool_names = ["ts_" + name for name in ("render", "report", "email", "compute", "agent")]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for name in legacy_tool_names:
            assert name not in text, (path, name)


def test_workspace_docs_match_bootstrap_canonical_file_names() -> None:
    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    contract = (REFERENCES / "storage.md").read_text(encoding="utf-8")

    for text in (architecture, contract):
        for name in ["research_workspace/2", "research/nodes/", "artifacts/<id>/payload"]:
            assert name in text


def test_skill_routes_details_through_focused_references():
    text=SKILL.read_text()
    assert len(text.splitlines()) < 100
    assert "references/storage.md" in text
    orchestration=(ORCHESTRATION_ROOT/"SKILL.md").read_text()
    for ref in ["references/tools.md", "references/skills.md", "references/public_contract.md"]:
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


def test_compute_reference_describes_the_generic_job_runtime() -> None:
    compute = (ORCHESTRATION_ROOT / "references" / "tools.md").read_text(encoding="utf-8")

    assert "Job Runtime" in compute
    assert "job_start" in compute


def test_static_research_map_templates_are_removed() -> None:
    assert not list((ROOT / "skills").glob("*/assets/templates/research_map"))
