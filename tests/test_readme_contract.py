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
SKILL_ROOT = ROOT / "skills" / "transition-state-workflow"
SKILL = SKILL_ROOT / "SKILL.md"
REFERENCES = SKILL_ROOT / "references"
TEMPLATES = SKILL_ROOT / "assets" / "templates"
FINAL_REPORT = TEMPLATES / "ts_final_report.md"


PUBLIC_DOCS = (README, ARCHITECTURE, INSTALLATION, MAINTAINER)


def test_readme_routes_each_reader_to_the_public_contracts() -> None:
    text = README.read_text(encoding="utf-8")

    for phrase in [
        "This branch supports Pi Agent only.",
        "docs/INSTALLATION.md",
        "docs/ARCHITECTURE.md",
        "docs/MAINTAINER_GUIDE.md",
        "scripts/build_release.py",
        "scripts/install_release.py",
        ".pi/packages/ts-agent/current",
        "never loads that checkout directly",
        "./TSPi --workspace reaction-a",
        "./TSPi --workspace reaction-a --continue",
        "/ts-subagent-history",
        "ts_workspace_decision_apply",
        "ts_subagent_review",
        "ts_subagent_compute",
        "ts_notify_user",
        "eleven tools",
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
        "## Upgrade",
        "## Rollback",
        "## Operational Recovery",
    ]:
        assert heading in installation

    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    for heading in [
        "## Authority Matrix",
        "## Scientific State Model",
        "## TSPi Lifecycle",
        "## Review Agent Runtime",
        "## Bounded Operator Sessions",
        "## Run Journals And Result Delivery",
        "## Contract Locations",
    ]:
        assert heading in architecture

    maintainer = MAINTAINER.read_text(encoding="utf-8")
    assert "## Documentation Ownership" in maintainer
    assert "## Contract Change Matrix" in maintainer
    assert "## Release Procedure" in maintainer
    assert "## Rollback Discipline" in maintainer


def test_public_markdown_relative_links_resolve_inside_the_package() -> None:
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for path in (*PUBLIC_DOCS, SKILL):
        for raw_target in link_pattern.findall(path.read_text(encoding="utf-8")):
            target = raw_target.strip().strip("<>")
            if target.startswith("#") or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                continue
            relative = unquote(target.split("#", 1)[0].split("?", 1)[0])
            resolved = (path.parent / relative).resolve()
            assert resolved.is_relative_to(ROOT), (path, target)
            assert resolved.exists(), (path, target)


def test_public_docs_state_the_v3_authority_boundary() -> None:
    texts = {
        "readme": README.read_text(encoding="utf-8"),
        "architecture": ARCHITECTURE.read_text(encoding="utf-8"),
        "skill": SKILL.read_text(encoding="utf-8"),
        "maintainer": MAINTAINER.read_text(encoding="utf-8"),
        "state": (REFERENCES / "state_model.md").read_text(encoding="utf-8"),
    }

    assert "Root Agent chooses the research path" in texts["readme"]
    assert "Tags are for display and search only" in texts["readme"]
    assert "Only `ts_workspace_decision_apply` may mutate canonical scientific state" in texts["architecture"]
    assert "Review is the only child whose intended result depends on independent scientific" in texts["architecture"]
    assert "Treat Node tags as display/search metadata only" in texts["skill"].replace("`", "")
    assert "Node tags must never select an allowed action" in texts["maintainer"]
    assert "Evidence has no workflow role or layer" in " ".join(texts["state"].split())


def test_normal_runtime_docs_use_v3_contracts_only() -> None:
    paths = [
        *PUBLIC_DOCS,
        SKILL,
        *sorted(REFERENCES.glob("*.md")),
    ]
    forbidden = [
        "ts-decision/2",
        "ts-node/2",
        "candidate_plan",
        "validation_scope",
        "audit_scope",
        "mechanism_action",
        "solution_ref",
        "pathway_ref",
        "previous_attempt_summary",
        "endpoint_identity_gate",
        "stereochemical_connectivity_gate",
        "candidate_search",
        "validation/connectivity",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for term in forbidden:
            assert term not in text, (path, term)


def test_workspace_docs_match_bootstrap_canonical_file_names() -> None:
    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    contract = (REFERENCES / "workspace_contract.md").read_text(encoding="utf-8")

    for text in (architecture, contract):
        assert "evidence_registry.json" in text
        assert "\nevidence.json\n" not in text
    assert "A complete v3 workspace is only validated" in contract
    assert "Partial v3 state and invalid v3 state fail closed" in contract


def test_skill_routes_details_through_focused_references() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert len(text.splitlines()) < 260
    for ref in [
        "references/state_model.md",
        "references/workspace_contract.md",
        "references/decision_contract.md",
        "references/candidate_generation.md",
        "references/compute_operator.md",
        "references/pi_agent_adapter.md",
        "references/agent_decision_protocol.md",
        "references/artifact_operators.md",
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
    assert "Gaussian is a first-class candidate-generation backend" in candidate
    assert "Do not default to QST2/QST3" in candidate
    assert "The catalog is not a priority list" in backend


def test_final_report_template_projects_v3_scientific_objects() -> None:
    text = FINAL_REPORT.read_text(encoding="utf-8")

    for phrase in [
        "Scientific Claims",
        "Deterministic Gate Results",
        "Research Nodes",
        "Accepted Artifacts",
        "Evidence Appendix",
        "Operational Follow-Up",
        "{{claim_id}}",
        "{{gate_result_id}}",
        "{{evidence_id}}",
    ]:
        assert phrase in text
    for legacy in ("{{node_type}}", "{{hypothesis_id}}", "{{evidence_role}}"):
        assert legacy not in text


def test_decision_assets_are_generic_kernel_draft_examples() -> None:
    decision_dir = TEMPLATES / "decision"
    readme = (decision_dir / "README.md").read_text(encoding="utf-8")
    files = {path.name for path in decision_dir.glob("*.json")}

    assert "not a prescribed research sequence" in readme
    assert "argument objects for `ts_workspace_decision_draft`" in readme
    assert files == {
        "append_claim.json",
        "append_evidence.json",
        "end_audit.json",
        "end_node.json",
        "evaluate_gate.json",
        "link_operation.json",
        "start_node.json",
    }
    for path in decision_dir.glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        assert value["action"] in {"start_node", "update_workspace", "end_node"}
        assert "basisRefs" in value
        assert "decision_id" not in value
        assert "report_ref" not in value
