from pathlib import Path

import pytest

from tools.lint_public_surface import check_public_surface, lint_text


ROOT = Path(__file__).resolve().parents[2]


def test_public_terminology_is_current() -> None:
    assert check_public_surface(ROOT) == []


@pytest.mark.parametrize("term", ["required_gates", "Evidence layer", "evidence roles", "ts-reviewers", "stage_router"])
def test_retired_public_terms_report_their_line(term: str) -> None:
    assert lint_text(f"# Example\nUse {term} here.")[0][0] == 2


def test_scientific_vocabulary_and_execution_terms_remain_open() -> None:
    assert lint_text("Reaction coordinate, catalytic cycle, and competing hypotheses.\n"
                     "A scheduler stage and transaction commit are operational details.\n"
                     "A ClaimGate evaluates FactFindings.") == []


def test_private_code_and_historical_docs_are_outside_public_lint(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("Use ts_review.", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/old-contract.md").write_text("Retired required_gates.", encoding="utf-8")
    assert check_public_surface(tmp_path) == []
