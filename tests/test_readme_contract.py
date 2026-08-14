from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
SKILL_ROOT = ROOT / "skills" / "transition-state-workflow"
REFERENCES = SKILL_ROOT / "references"
TEMPLATES = SKILL_ROOT / "assets" / "templates"
SKILL = SKILL_ROOT / "SKILL.md"
CANDIDATE_GENERATION = REFERENCES / "candidate_generation.md"
GAUSSIAN_VALIDATION = REFERENCES / "gaussian_validation.md"
MECHANISM_REFLECTION = REFERENCES / "mechanism_reflection.md"
AGENT_DECISION_PROTOCOL = REFERENCES / "agent_decision_protocol.md"
DECISION_CONTRACT = REFERENCES / "decision_contract.md"
PATHWAY_MODEL = REFERENCES / "pathway_model.md"
REPORT_TEMPLATE = REFERENCES / "report_template.md"
WORKSPACE_CONTRACT = REFERENCES / "workspace_contract.md"
REMOTE_CONTRACT = REFERENCES / "remote_contract.md"
TEMPLATE_README = TEMPLATES / "decision" / "README.md"
UPDATE_EVIDENCE = TEMPLATES / "decision" / "update_evidence.json"
FINAL_REPORT = TEMPLATES / "ts_final_report.md"


def test_readme_documents_install_and_agent_entrypoints() -> None:
    text = README.read_text(encoding="utf-8")

    for phrase in [
        "TSAgentSkill",
        "This branch supports Pi Agent only.",
        "pi install -l git:github.com/iawnix/TSAgentSkill@pi_ts_subagents --approve",
        "$PWD/.pi/git/github.com/iawnix/TSAgentSkill",
        "--workspace-root \"$TS_WORKSPACE_ROOT\"",
        "TS_WORKSPACE_ROOT=/path/to/ts-workspace npm run install-env",
        "Pi Agent Usage",
        "eleven-tool Root Agent inventory",
        "`/ts-subagent-history` opens a read-only, paginated browser",
        "skills/transition-state-workflow/assets/templates/ts_final_report.md",
    ]:
        assert phrase in text

    assert "Codex Usage" not in text


def test_public_agent_contract_is_pi_only() -> None:
    paths = [
        README,
        SKILL,
        REFERENCES / "runtime_environment.md",
        REFERENCES / "pi_agent_adapter.md",
        REFERENCES / "decision_contract.md",
    ]

    for path in paths:
        assert "Codex" not in path.read_text(encoding="utf-8"), path


def test_final_report_template_uses_v2_node_vocabulary() -> None:
    text = FINAL_REPORT.read_text(encoding="utf-8")

    assert "| Node | Node type / scope |" in text
    assert "{{node_type}} / {{scope}}" in text
    for legacy_term in ("{{phase}}", "Claim verdict", "Program status"):
        assert legacy_term not in text


def test_readme_keeps_render_dependency_boundary_explicit() -> None:
    text = README.read_text(encoding="utf-8")

    assert "`ts_render` uses `xyzrender` only" in text
    assert "does not require or probe Blender, FFmpeg, OpenBabel, Mayavi, or" in text


def test_remote_documentation_covers_profile_lifecycle_and_diagnostics() -> None:
    readme_text = README.read_text(encoding="utf-8")
    remote_text = REMOTE_CONTRACT.read_text(encoding="utf-8")
    normalized_remote = " ".join(remote_text.split())

    assert "`ts_remote` binds one `submission_id`" in readme_text
    for phrase in [
        "`ts_remote` is the only remote-compute subsystem",
        "## Request Shape",
        "## Installation Configuration",
        "TS_REMOTE_CONFIG",
        "<remote_root>/workspaces/<workspace_id>/runs/<node_id>/<intent_id>",
        "## Lifecycle",
        ".ts-remote/submission.env",
        "Collect verifies the prepared manifest",
        "submission_ambiguous",
        "/ts-remote doctor",
        "Ordinary TSPi startup does not probe the cluster",
    ]:
        assert phrase in normalized_remote


def test_candidate_generation_does_not_default_to_qst_from_endpoints() -> None:
    skill_text = SKILL.read_text(encoding="utf-8")
    reference_text = CANDIDATE_GENERATION.read_text(encoding="utf-8")

    assert "Do not default to QST2/QST3 merely because R/P endpoints" in skill_text
    assert "are available; justify QST use" in skill_text
    assert "default to QST2/QST3 merely because reactant and product structures are" in reference_text
    assert "available. Prefer QST2/QST3 only when the endpoints are optimized" in reference_text
    assert "Reactant/product endpoints define the target connectivity basins" in reference_text


def test_mechanism_reflection_requires_geometry_and_electronic_checks() -> None:
    mechanism_text = MECHANISM_REFLECTION.read_text(encoding="utf-8")
    candidate_text = CANDIDATE_GENERATION.read_text(encoding="utf-8")
    normalized_candidate = " ".join(candidate_text.split())
    gaussian_text = GAUSSIAN_VALIDATION.read_text(encoding="utf-8")
    normalized_gaussian = " ".join(gaussian_text.split())
    evidence_template = UPDATE_EVIDENCE.read_text(encoding="utf-8")

    assert "local geometry and electronic structure" in mechanism_text
    assert "Every candidate-generation and TS/Freq reflection" in mechanism_text
    assert "A candidate that only satisfies target bond distances is not automatically" in normalized_candidate
    assert '"node_id": "${NODE_ID}"' in evidence_template
    assert '"evidence_tier": "manual_observation"' in evidence_template
    assert "the final local geometry and available electronic diagnostics must not contradict" in normalized_gaussian
    assert "Do not start IRC from a TS/Freq result whose mechanism-consistency review is refuted" in normalized_gaussian


def test_skill_links_agent_decision_protocol_for_failed_exploration() -> None:
    skill_text = SKILL.read_text(encoding="utf-8")
    protocol_text = AGENT_DECISION_PROTOCOL.read_text(encoding="utf-8")

    assert "references/agent_decision_protocol.md" in skill_text
    assert "previous failed exploration" in protocol_text
    assert "report_workspace.node_index" in protocol_text
    assert "nodes/<failed_node>/node.json" in protocol_text
    assert "Across independent repeated studies" in protocol_text


def test_pathway_audit_contract_is_explicit_for_agents() -> None:
    texts = {
        "skill": SKILL.read_text(encoding="utf-8"),
        "protocol": AGENT_DECISION_PROTOCOL.read_text(encoding="utf-8"),
        "decision": DECISION_CONTRACT.read_text(encoding="utf-8"),
        "pathway": PATHWAY_MODEL.read_text(encoding="utf-8"),
        "report": REPORT_TEMPLATE.read_text(encoding="utf-8"),
        "workspace": WORKSPACE_CONTRACT.read_text(encoding="utf-8"),
        "templates": TEMPLATE_README.read_text(encoding="utf-8"),
    }

    assert "For `node_type=audit, audit_scope=pathway`, `payload.pathway_ref` is mandatory" in texts["skill"]
    assert "running node must already have `node.pathway_ref`" in texts["protocol"]
    assert "quality.strict_pathway_decision=pathway_not_accepted" in texts["protocol"]
    assert "For `node_type=audit, audit_scope=pathway`, `payload.pathway_ref` is mandatory" in texts["decision"]
    assert "Every pathway audit start decision" in texts["pathway"]
    assert "must include `payload.pathway_ref`" in texts["pathway"]
    assert "do not infer it from" in texts["report"]
    assert "quality.strict_pathway_decision" in texts["workspace"]
    assert "Every post-`n000` start carries explicit `branch_context`" in texts["templates"]
