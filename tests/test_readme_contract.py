from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
README_ZH = ROOT / "README.zh-CN.md"
ARCHITECTURE = ROOT / "docs" / "ARCHITECTURE.md"
ARCHITECTURE_ZH = ROOT / "docs" / "ARCHITECTURE.zh-CN.md"
TERMINAL = ROOT / "docs" / "TERMINAL.md"
TERMINAL_ZH = ROOT / "docs" / "TERMINAL.zh-CN.md"
INSTALLATION = ROOT / "docs" / "INSTALLATION.md"
MAINTAINER = ROOT / "docs" / "MAINTAINER_GUIDE.md"
ADR = ROOT / "docs" / "adr" / "0001-phase-node-research-kernel.md"
SKILL_ROOT = ROOT / "skills" / "tspi-orchestration"
SKILL = SKILL_ROOT / "SKILL.md"
REFERENCES = SKILL_ROOT / "references"
TEMPLATES = SKILL_ROOT / "assets" / "templates"
FOCUSED_SKILLS = {
    "tspi-transition-state-search": ROOT / "skills" / "tspi-transition-state-search",
    "tspi-xtb": ROOT / "skills" / "tspi-xtb",
    "tspi-gaussian": ROOT / "skills" / "tspi-gaussian",
    "tspi-connectivity": ROOT / "skills" / "tspi-connectivity",
    "tspi-mechanism": ROOT / "skills" / "tspi-mechanism",
    "tspi-render": ROOT / "skills" / "tspi-render",
    "tspi-report": ROOT / "skills" / "tspi-report",
    "tspi-email": ROOT / "skills" / "tspi-email",
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
        "## Decision Transaction",
        "## Validation Engine",
        "## Context Compiler",
        "## Read-Only Web Projection",
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
        "## Validation Engine Rules",
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
        "research_state.json",
        "phases.json",
        "claims.json",
        "claim_relations.json",
        "research_nodes.json",
        "observations.json",
        "proof_specs.json",
        "validation_results.json",
        "findings.json",
        "acceptances/<acceptance_id>.json",
    ]
    for text in (architecture, contract):
        for name in required:
            assert name in text
    assert "complete workspace is validated without canonical rewrites" in contract
    assert "Bootstrap does not rewrite unsupported state" in contract


def test_skill_routes_details_through_focused_references() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert len(text.splitlines()) < 260
    for ref in [
        "references/state_model.md",
        "references/workspace_contract.md",
        "references/decision_contract.md",
        "references/compute_tools.md",
        "references/pi_agent_adapter.md",
        "references/agent_decision_protocol.md",
        "references/artifact_tools.md",
        "references/package_sources.md",
        "references/remote_contract.md",
    ]:
        assert ref in text
    for ref in (
        "tspi-render/references/render_contract.md",
        "tspi-report/references/report_template.md",
        "tspi-email/references/email_delivery.md",
    ):
        assert ref in text


def test_skill_progressive_disclosure_routes_every_reference() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    for path in sorted(REFERENCES.glob("*.md")):
        assert f"references/{path.name}" in skill, path
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > 100:
            assert "## Contents" in lines, path


def test_focused_skills_have_bilingual_entrypoints_and_route_their_references() -> None:
    for name, root in FOCUSED_SKILLS.items():
        english = root / "SKILL.md"
        chinese = root / "SKILL.zh-CN.md"
        assert english.is_file()
        assert chinese.is_file()
        assert f"name: {name}" in english.read_text(encoding="utf-8")
        assert f"name: {name}" in chinese.read_text(encoding="utf-8")
        for entrypoint in (english, chinese):
            skill_text = entrypoint.read_text(encoding="utf-8")
            for reference in root.glob("references/*.md"):
                assert f"references/{reference.name}" in skill_text, (entrypoint, reference)


def test_compute_reference_uses_the_registered_gaussian_input_role() -> None:
    compute = (REFERENCES / "compute_tools.md").read_text(encoding="utf-8")

    assert '"inputRole": "gjf"' in compute
    assert '"inputRole": "structure"' not in compute


def test_final_report_builder_projects_phase_node_and_scientific_objects() -> None:
    text = (ROOT / "packages" / "ts-agent-kernel" / "ts_agent" / "report" / "builder.py").read_text(encoding="utf-8")

    for phrase in [
        "Research Roadmap",
        "Scientific Conclusions",
        "ResearchNode Records",
        "Semantic Observations",
        "Frozen Validation",
        "Claim Acceptance",
        "Operational Follow-up",
        "phase['phase_id']",
        "claim['claim_id']",
        "node['node_id']",
        "observation['observation_id']",
        "spec['proof_id']",
        "finding['finding_id']",
        "acceptance['acceptance_id']",
    ]:
        assert phrase in text
    for removed in ('"act_id"', "evidence_id", "gate_result_id", "required_gates"):
        assert removed not in text


def test_decision_assets_are_generic_operation_examples() -> None:
    decision_dir = TEMPLATES / "decision"
    readme = (decision_dir / "README.md").read_text(encoding="utf-8")
    files = {path.name for path in decision_dir.glob("*.json")}

    assert "not a prescribed research sequence" in readme
    assert "operations` array accepted by" in readme
    assert files == {
        "accept_claim.json",
        "complete_node.json",
        "create_phase.json",
        "create_claim.json",
        "evaluate_proof.json",
        "evaluate_gate.json",
        "freeze_gate.json",
        "freeze_proof_spec.json",
        "record_finding.json",
        "record_observation.json",
        "record_observation_candidate.json",
        "relate_claims.json",
        "resolve_finding.json",
        "set_focus.json",
        "start_node.json",
        "update_claim.json",
    }
    for path in decision_dir.glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(value.get("op"), str)
        assert "decision_id" not in value
        assert "context_ref" not in value
