from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
SKILL = ROOT / "SKILL.md"
CANDIDATE_GENERATION = ROOT / "references" / "candidate_generation.md"
GAUSSIAN_VALIDATION = ROOT / "references" / "gaussian_validation.md"
MECHANISM_REFLECTION = ROOT / "references" / "mechanism_reflection.md"
UPDATE_CANDIDATE_EVIDENCE = ROOT / "templates" / "decision" / "update_candidate_evidence.json"
UPDATE_TSFREQ_EVIDENCE = ROOT / "templates" / "decision" / "update_tsfreq_evidence.json"


def test_readme_documents_install_and_agent_entrypoints() -> None:
    text = README.read_text(encoding="utf-8")

    for phrase in [
        "TSAgentSkill",
        "python scripts/install_env.py --conda-root /path/to/miniforge3 --with-render --json",
        "Codex Usage",
        "Pi Agent Usage",
        "templates/ts_final_report.md",
    ]:
        assert phrase in text


def test_readme_keeps_render_dependency_boundary_explicit() -> None:
    text = README.read_text(encoding="utf-8")

    assert "`ts_render` uses `xyzrender` only" in text
    assert "does not require or probe Blender, FFmpeg, OpenBabel, Mayavi, or" in text


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
    candidate_template = UPDATE_CANDIDATE_EVIDENCE.read_text(encoding="utf-8")
    tsfreq_template = UPDATE_TSFREQ_EVIDENCE.read_text(encoding="utf-8")

    assert "local geometry and electronic structure" in mechanism_text
    assert "Every candidate-generation and TS/Freq reflection" in mechanism_text
    assert "A candidate that only satisfies target bond distances is not automatically" in normalized_candidate
    assert "local_geometry_consistency" in candidate_template
    assert "electronic_structure_consistency" in candidate_template
    assert "the final local geometry and available electronic diagnostics must not contradict" in normalized_gaussian
    assert "Do not start IRC from a TS/Freq result whose mechanism-consistency review is refuted" in normalized_gaussian
    assert "connectivity_claim_allowed_without_irc" in tsfreq_template
