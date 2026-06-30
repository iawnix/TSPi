from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
SKILL = ROOT / "SKILL.md"
CANDIDATE_GENERATION = ROOT / "references" / "candidate_generation.md"


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
