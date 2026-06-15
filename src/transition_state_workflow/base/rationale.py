"""Pre-execution rationale linting for TS-search branch nodes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from transition_state_workflow.util.path_utils import clean_string


HYPOTHESIS_REQUIRED_SECTIONS = (
    "Chemical Hypothesis",
    "Reaction-Center Expectations",
    "Mechanism Analysis Plan / Required Diagnostics",
    "Evidence That Would Support This Hypothesis",
    "Evidence That Would Refute This Hypothesis",
)

DECISION_CARD_REQUIRED_SECTIONS = (
    "Why This Tool",
    "Input / Dependency Nodes",
    "Expected Supporting Evidence",
    "Refutation Criteria",
    "Cost And Risk",
    "Next If Supported",
    "Next If Refuted",
)

PLACEHOLDER_PHRASES = (
    "fill in",
    "explain why",
    "not run yet",
    "pending.",
)

EMPTY_FIELD_LABELS = (
    "reaction type",
    "reaction center",
    "electronic / spin / charge",
    "orbital / population",
    "energy / barrier expectation",
    "compute cost",
    "numerical risk",
    "chemical risk",
)


@dataclass(frozen=True)
class MarkdownLint:
    """Lint result for one rationale markdown file."""

    present: bool
    missing_sections: tuple[str, ...] = ()
    empty_sections: tuple[str, ...] = ()
    placeholder_hits: tuple[str, ...] = ()
    empty_field_hits: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return (
            self.present
            and not self.missing_sections
            and not self.empty_sections
            and not self.placeholder_hits
            and not self.empty_field_hits
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "present": self.present,
            "complete": self.complete,
            "missing_sections": list(self.missing_sections),
            "empty_sections": list(self.empty_sections),
            "placeholder_hits": list(self.placeholder_hits),
            "empty_field_hits": list(self.empty_field_hits),
        }


@dataclass(frozen=True)
class RationaleLint:
    """Combined lint result for a node's pre-execution rationale."""

    status: str
    ok_to_start: bool
    hypothesis: MarkdownLint
    decision_card: MarkdownLint
    legacy_import: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "ok_to_start": self.ok_to_start,
            "legacy_import": self.legacy_import,
            "files": {
                "hypothesis": self.hypothesis.to_dict(),
                "decision_card": self.decision_card.to_dict(),
            },
            "summary": self.summary(),
        }

    def summary(self) -> str:
        if self.legacy_import:
            return "legacy import marked; pre-execution rationale enforcement is bypassed"
        if self.status == "complete":
            return "pre-execution rationale is complete"
        missing = []
        for name, lint in (("hypothesis", self.hypothesis), ("decision_card", self.decision_card)):
            if not lint.present:
                missing.append(f"{name}: missing file")
            if lint.missing_sections:
                missing.append(f"{name}: missing sections {', '.join(lint.missing_sections)}")
            if lint.empty_sections:
                missing.append(f"{name}: empty sections {', '.join(lint.empty_sections)}")
            if lint.placeholder_hits:
                missing.append(f"{name}: placeholder text {', '.join(lint.placeholder_hits)}")
            if lint.empty_field_hits:
                missing.append(f"{name}: empty fields {', '.join(lint.empty_field_hits)}")
        return "; ".join(missing) if missing else "pre-execution rationale is incomplete"


def lint_node_rationale(root: Path, node_id: str, node_payload: dict[str, Any] | None = None) -> RationaleLint:
    """Lint the hypothesis and decision-card markdown for one node."""

    node_dir = root / "nodes" / node_id
    legacy_import = rationale_legacy_import(node_payload or {})
    hypothesis = lint_markdown_file(node_dir / "hypothesis.md", HYPOTHESIS_REQUIRED_SECTIONS)
    decision_card = lint_markdown_file(node_dir / "decision_card.md", DECISION_CARD_REQUIRED_SECTIONS)
    if legacy_import:
        return RationaleLint("legacy_import", True, hypothesis, decision_card, legacy_import=True)
    if not hypothesis.present or not decision_card.present:
        return RationaleLint("missing", False, hypothesis, decision_card)
    if hypothesis.complete and decision_card.complete:
        return RationaleLint("complete", True, hypothesis, decision_card)
    return RationaleLint("draft", False, hypothesis, decision_card)


def rationale_legacy_import(node_payload: dict[str, Any]) -> bool:
    """Return true when a node explicitly declares legacy rationale provenance."""

    contract = node_payload.get("rationale_contract")
    if not isinstance(contract, dict):
        return False
    return clean_string(contract.get("mode")) == "legacy_import"


def lint_markdown_file(path: Path, required_sections: tuple[str, ...]) -> MarkdownLint:
    """Lint one rationale markdown file for required headings and draft markers."""

    if not path.exists():
        return MarkdownLint(present=False, missing_sections=required_sections)
    text = path.read_text(encoding="utf-8", errors="replace")
    sections = markdown_sections(text)
    missing_sections = tuple(section for section in required_sections if section.lower() not in sections)
    empty_sections = tuple(
        section
        for section in required_sections
        if section.lower() in sections and section_body_is_empty(sections[section.lower()])
    )
    placeholder_hits = placeholder_lines(text)
    empty_field_hits = empty_field_lines(text)
    return MarkdownLint(
        present=True,
        missing_sections=missing_sections,
        empty_sections=empty_sections,
        placeholder_hits=placeholder_hits,
        empty_field_hits=empty_field_hits,
    )


def markdown_sections(text: str) -> dict[str, list[str]]:
    """Return level-two markdown sections keyed by normalized heading text."""

    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            current = line[3:].strip().lower()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(raw_line)
    return sections


def section_body_is_empty(lines: list[str]) -> bool:
    """Return true when a markdown section has no substantive body text."""

    substantive = [line.strip() for line in lines if line.strip()]
    if not substantive:
        return True
    return all(line in {"-", "*"} for line in substantive)


def placeholder_lines(text: str) -> tuple[str, ...]:
    """Return lines containing known draft placeholder phrases."""

    hits: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if line and any(phrase in lower for phrase in PLACEHOLDER_PHRASES):
            hits.append(line)
    return tuple(hits)


def empty_field_lines(text: str) -> tuple[str, ...]:
    """Return bullet or field lines whose required label has no value."""

    hits: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        field = stripped.lstrip("-* ").strip()
        if ":" not in field:
            continue
        label, value = field.split(":", 1)
        normalized = label.strip().lower()
        if normalized in EMPTY_FIELD_LABELS and not value.strip():
            hits.append(stripped)
    return tuple(hits)


__all__ = [
    "DECISION_CARD_REQUIRED_SECTIONS",
    "HYPOTHESIS_REQUIRED_SECTIONS",
    "MarkdownLint",
    "RationaleLint",
    "lint_markdown_file",
    "lint_node_rationale",
    "rationale_legacy_import",
]
