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
ADR = ROOT / "docs" / "adr" / "0001-dag-research-kernel-v4.md"
SKILL_ROOT = ROOT / "skills" / "transition-state-workflow"
SKILL = SKILL_ROOT / "SKILL.md"
REFERENCES = SKILL_ROOT / "references"
TEMPLATES = SKILL_ROOT / "assets" / "templates"
FINAL_REPORT = TEMPLATES / "ts_final_report.md"


PUBLIC_DOCS = (README, ARCHITECTURE, INSTALLATION, MAINTAINER, ADR)


def test_readme_routes_each_reader_to_the_v4_public_contracts() -> None:
    text = README.read_text(encoding="utf-8")

    for phrase in [
        "protocol v4",
        "docs/INSTALLATION.md",
        "docs/ARCHITECTURE.md",
        "docs/MAINTAINER_GUIDE.md",
        "docs/adr/0001-dag-research-kernel-v4.md",
        "scripts/build_release.py",
        "scripts/install_release.py",
        ".pi/packages/ts-agent/current",
        "./TSPi --workspace reaction-a",
        "./TSPi --workspace reaction-a --continue",
        "/ts-subagent-history",
        "ts_workspace_decision_apply",
        "ts_subagent_review",
        "ts_compute",
        "ts_render",
        "ts_report",
        "ts_notify_user",
        "eleven public tools",
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
        "## TSPi Lifecycle",
        "## Review Agent Runtime",
        "## Deterministic Tool Plane",
        "## Run Journals And Result Delivery",
        "## Contract Locations",
    ]:
        assert heading in architecture

    maintainer = MAINTAINER.read_text(encoding="utf-8")
    for heading in [
        "## V4 Scientific Model",
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


def test_public_docs_state_the_v4_authority_boundary() -> None:
    texts = {
        "readme": README.read_text(encoding="utf-8"),
        "architecture": ARCHITECTURE.read_text(encoding="utf-8"),
        "skill": SKILL.read_text(encoding="utf-8"),
        "maintainer": MAINTAINER.read_text(encoding="utf-8"),
        "state": (REFERENCES / "state_model.md").read_text(encoding="utf-8"),
    }

    assert "The DAG records what happened; it does not prescribe what must happen next" in texts["readme"]
    assert "Review is the only child model session" in texts["readme"]
    assert "Only `ts_workspace_decision_apply` may mutate canonical scientific state" in texts["architecture"]
    assert "Compute, Render, Report, remote inspection" in texts["architecture"]
    assert "Treat Claim relations, Act dependencies, and tags as recorded context only" in texts["skill"]
    assert "model dispatchers around deterministic actions" in texts["maintainer"]
    assert "checks refs and acyclicity" in texts["state"]
    assert "label to a next action" in texts["state"]


def test_normal_runtime_docs_expose_only_v4_contracts() -> None:
    paths = [README, ARCHITECTURE, INSTALLATION, MAINTAINER, SKILL, *sorted(REFERENCES.glob("*.md"))]
    forbidden = [
        "ts-decision/2",
        "ts-decision/3",
        "ts-node/2",
        "ts-node/3",
        "ts-calculation-intent/3",
        "ts_subagent_compute",
        "ts_subagent_render",
        "ts_subagent_report",
        "migrate_workspace_v2_to_v3.py",
        "evidence_registry.json",
        "gate_results.json",
        "start_node",
        "end_node",
        "required_gates",
        "solution_ref",
        "previous_attempt_summary",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for term in forbidden:
            assert term not in text, (path, term)


def test_workspace_docs_match_v4_bootstrap_canonical_file_names() -> None:
    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    contract = (REFERENCES / "workspace_contract.md").read_text(encoding="utf-8")

    required = [
        "workspace.json",
        "research_state.json",
        "claims.json",
        "claim_relations.json",
        "research_acts.json",
        "observations.json",
        "validation_specs.json",
        "validation_results.json",
        "findings.json",
        "acceptances/<acceptance_id>.json",
    ]
    for text in (architecture, contract):
        for name in required:
            assert name in text
    assert "complete v4 workspace is validated without canonical rewrites" in contract
    assert "There is no legacy reader or migration command" in contract


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


def test_final_report_template_projects_v4_scientific_objects() -> None:
    text = FINAL_REPORT.read_text(encoding="utf-8")

    for phrase in [
        "Claims And Relations",
        "ResearchAct DAG",
        "Semantic Observations",
        "Frozen Validation",
        "Findings And Claim Acceptance",
        "Operational Follow-Up",
        "{{claim_id}}",
        "{{act_id}}",
        "{{observation_id}}",
        "{{spec_id}}",
        "{{result_id}}",
        "{{finding_id}}",
    ]:
        assert phrase in text
    for legacy in ("{{node_id}}", "{{evidence_id}}", "{{gate_result_id}}", "{{required_gates}}"):
        assert legacy not in text


def test_decision_assets_are_generic_v4_operation_examples() -> None:
    decision_dir = TEMPLATES / "decision"
    readme = (decision_dir / "README.md").read_text(encoding="utf-8")
    files = {path.name for path in decision_dir.glob("*.json")}

    assert "not a prescribed research sequence" in readme
    assert "operations` array accepted by" in readme
    assert files == {
        "accept_claim.json",
        "complete_act.json",
        "create_claim.json",
        "evaluate_validation.json",
        "freeze_validation_spec.json",
        "record_finding.json",
        "record_observation.json",
        "relate_claims.json",
        "start_act.json",
        "update_claim.json",
    }
    for path in decision_dir.glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(value.get("op"), str)
        assert "decision_id" not in value
        assert "context_ref" not in value
