from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
MAINTAINER = ROOT / "docs" / "MAINTAINER_GUIDE.md"
SKILL_ROOT = ROOT / "skills" / "transition-state-workflow"
SKILL = SKILL_ROOT / "SKILL.md"
REFERENCES = SKILL_ROOT / "references"
TEMPLATES = SKILL_ROOT / "assets" / "templates"
FINAL_REPORT = TEMPLATES / "ts_final_report.md"


def test_readme_documents_pi_install_runtime_and_public_tools() -> None:
    text = README.read_text(encoding="utf-8")

    for phrase in [
        "This branch supports Pi Agent only.",
        "pi install -l git:github.com/iawnix/TSAgentSkill@pi_ts_subagents --approve",
        "$PWD/.pi/git/github.com/iawnix/TSAgentSkill",
        "./TSPi --workspace reaction-a",
        "/ts-subagent-history",
        "ts_workspace_decision_apply",
        "ts_subagent_review",
        "ts_subagent_compute",
        "ts_notify_user",
        "eleven tools",
    ]:
        assert phrase in text


def test_public_docs_state_the_v3_authority_boundary() -> None:
    texts = {
        "readme": README.read_text(encoding="utf-8"),
        "skill": SKILL.read_text(encoding="utf-8"),
        "maintainer": MAINTAINER.read_text(encoding="utf-8"),
        "state": (REFERENCES / "state_model.md").read_text(encoding="utf-8"),
    }

    assert "Root Agent chooses the research path" in texts["readme"]
    assert "Tags are for display and search only" in texts["readme"]
    assert "Treat Node tags as display/search metadata only" in texts["skill"].replace("`", "")
    assert "Node tags must never select an allowed action" in texts["maintainer"]
    assert "Evidence has no workflow role or layer" in " ".join(texts["state"].split())


def test_normal_runtime_docs_use_v3_contracts_only() -> None:
    paths = [
        README,
        SKILL,
        MAINTAINER,
        *(REFERENCES / name for name in [
            "state_model.md",
            "workspace_contract.md",
            "decision_contract.md",
            "agent_decision_protocol.md",
            "candidate_generation.md",
            "backend_selection.md",
            "compute_operator.md",
            "mechanism_reflection.md",
            "pathway_model.md",
            "pi_agent_adapter.md",
            "report_template.md",
        ]),
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
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for term in forbidden:
            assert term not in text, (path, term)


def test_skill_routes_details_through_focused_references() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert len(text.splitlines()) < 260
    for ref in [
        "references/state_model.md",
        "references/workspace_contract.md",
        "references/decision_contract.md",
        "references/candidate_generation.md",
        "references/compute_operator.md",
        "references/remote_contract.md",
        "references/report_template.md",
    ]:
        assert ref in text


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


def test_decision_assets_are_generic_v3_examples() -> None:
    decision_dir = TEMPLATES / "decision"
    readme = (decision_dir / "README.md").read_text(encoding="utf-8")
    files = {path.name for path in decision_dir.glob("*.json")}

    assert "not a prescribed research sequence" in readme
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
        assert '"schema_version": "ts-decision/3"' in path.read_text(encoding="utf-8")
