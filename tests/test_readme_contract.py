from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
ARCHITECTURE = ROOT / "docs" / "ARCHITECTURE.md"
INSTALLATION = ROOT / "docs" / "INSTALLATION.md"
MAINTAINER = ROOT / "docs" / "MAINTAINER_GUIDE.md"
ADR = ROOT / "docs" / "adr" / "0001-phase-node-research-kernel.md"
SKILL_ROOT = ROOT / "skills" / "transition-state-workflow"
SKILL = SKILL_ROOT / "SKILL.md"
REFERENCES = SKILL_ROOT / "references"
TEMPLATES = SKILL_ROOT / "assets" / "templates"


PUBLIC_DOCS = (README, ARCHITECTURE, INSTALLATION, MAINTAINER, ADR)


def test_readme_routes_each_reader_to_the_public_contracts() -> None:
    text = README.read_text(encoding="utf-8")

    for phrase in [
        "one workspace contract",
        "docs/INSTALLATION.md",
        "docs/ARCHITECTURE.md",
        "docs/MAINTAINER_GUIDE.md",
        "docs/adr/0001-phase-node-research-kernel.md",
        "scripts/build_package.py",
        "scripts/install_package.py",
        ".pi/packages/tspi/current",
        "TSPhoneServer",
        "./TSPi --workspace reaction-a",
        "./TSPi --workspace reaction-a --continue",
        "scripts/ts_web.py",
        "ResearchPhase roadmap",
        "/ts-subagent-history",
        "ts_workspace_decision_apply",
        "ts_subagent_review",
        "ts_subagent_compute",
        "ts_structure_seed",
        "ts_structure_compare",
        "ts_artifact_import",
        "ts_render",
        "ts_report",
        "ts_notify_user",
        "fourteen public tools",
    ]:
        assert phrase in text


def test_public_document_set_covers_install_architecture_and_maintenance() -> None:
    for path in PUBLIC_DOCS:
        assert path.is_file()
        assert path.read_text(encoding="utf-8").startswith("# ")

    installation = INSTALLATION.read_text(encoding="utf-8")
    for heading in [
        "## Prerequisites",
        "## Install Or Select A Release",
        "## Install The Python Runtime",
        "## Configure Remote Execution",
        "## Configure Notifications",
        "## Start And Resume Workspaces",
        "## Workspace Bootstrap",
        "## Run The Research Explorer",
        "## Upgrade",
        "## Rollback",
        "## Operational Recovery",
    ]:
        assert heading in installation

    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    for heading in [
        "## Authority Matrix",
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
    for path in (*PUBLIC_DOCS, SKILL, *sorted(REFERENCES.glob("*.md"))):
        for raw_target in link_pattern.findall(path.read_text(encoding="utf-8")):
            target = raw_target.strip().strip("<>")
            if target.startswith("#") or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                continue
            relative = unquote(target.split("#", 1)[0].split("?", 1)[0])
            resolved = (path.parent / relative).resolve()
            assert resolved.is_relative_to(ROOT), (path, target)
            assert resolved.exists(), (path, target)


def test_public_docs_state_the_authority_boundary() -> None:
    texts = {
        "readme": README.read_text(encoding="utf-8"),
        "architecture": ARCHITECTURE.read_text(encoding="utf-8"),
        "skill": SKILL.read_text(encoding="utf-8"),
        "maintainer": MAINTAINER.read_text(encoding="utf-8"),
        "state": (REFERENCES / "state_model.md").read_text(encoding="utf-8"),
    }

    assert "The DAG records what happened; it does not prescribe what must happen next" in texts["readme"]
    assert "Compute and Review use isolated child model sessions" in texts["readme"]
    assert "Only `ts_workspace_decision_apply` may mutate canonical scientific state" in texts["architecture"]
    assert "Every compute action, structure seed" in texts["architecture"]
    assert "Treat Claim relations, Node dependencies, and tags as recorded context only" in texts["skill"]
    assert "Compute may orchestrate only its closed" in texts["maintainer"]
    assert "checks refs and acyclicity" in texts["state"]
    assert "label to a next action" in texts["state"]


def test_normal_runtime_docs_expose_only_current_contracts() -> None:
    paths = [README, ARCHITECTURE, INSTALLATION, MAINTAINER, SKILL, *sorted(REFERENCES.glob("*.md"))]
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
        "gate_results.json",
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
        "validation_specs.json",
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
        "references/candidate_generation.md",
        "references/compute_tools.md",
        "references/pi_agent_adapter.md",
        "references/agent_decision_protocol.md",
        "references/artifact_tools.md",
        "references/package_sources.md",
        "references/remote_contract.md",
        "references/report_template.md",
    ]:
        assert ref in text


def test_skill_progressive_disclosure_routes_every_reference() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    for path in sorted(REFERENCES.glob("*.md")):
        assert f"references/{path.name}" in skill, path
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > 100:
            assert "## Contents" in lines, path


def test_candidate_strategy_remains_root_selected() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    candidate = (REFERENCES / "candidate_generation.md").read_text(encoding="utf-8")
    backend = (REFERENCES / "backend_selection.md").read_text(encoding="utf-8")

    assert "Do not impose a universal" in skill
    assert "Choose among chemically informed construction" in candidate
    assert "Before QST2/QST3" in candidate
    assert "The capability catalog is not a priority list" in backend


def test_compute_reference_uses_the_registered_gaussian_input_role() -> None:
    compute = (REFERENCES / "compute_tools.md").read_text(encoding="utf-8")

    assert '"inputRole": "gjf"' in compute
    assert '"inputRole": "structure"' not in compute


def test_final_report_builder_projects_phase_node_and_scientific_objects() -> None:
    text = (ROOT / "python" / "ts_agent" / "report" / "builder.py").read_text(encoding="utf-8")

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
        "spec['spec_id']",
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
        "evaluate_validation.json",
        "freeze_validation_spec.json",
        "record_finding.json",
        "record_observation.json",
        "relate_claims.json",
        "start_node.json",
        "update_claim.json",
    }
    for path in decision_dir.glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(value.get("op"), str)
        assert "decision_id" not in value
        assert "context_ref" not in value
