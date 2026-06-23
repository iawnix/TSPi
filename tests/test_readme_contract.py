from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


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
