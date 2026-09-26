from __future__ import annotations

from tools.lint_skills import validate_skills


def test_all_public_skills_follow_progressive_disclosure_contract() -> None:
    assert validate_skills() == []
