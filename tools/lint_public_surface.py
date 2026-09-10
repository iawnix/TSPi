#!/usr/bin/env python3
"""Reject retired terminology in the public README and public Skill text."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_PATTERNS = ("README.md", "skills/**/*.md")
RULES = (
    (re.compile(r"\b(?:gate_results|required_gates)\b", re.I),
     "retired fields: describe ProofSpec and ValidationResult contracts"),
    (re.compile(r"\bevidence\s+(?:layers?|roles?)\b", re.I),
     "ambiguous evidence category: name Artifact, Observation, Finding, or ValidationResult"),
    (re.compile(r"\bts-reviewers\b", re.I),
     "unregistered public name: use Review or ts_review"),
    (re.compile(r"\b(?:stage_router|gate_router)\b", re.I),
     "retired routing concept: Root chooses the next research action"),
)


def public_files(root: Path) -> list[Path]:
    return sorted({path for pattern in PUBLIC_PATTERNS for path in root.glob(pattern) if path.is_file()})


def lint_text(text: str) -> list[tuple[int, str]]:
    findings = []
    for line_number, line in enumerate(text.splitlines(), 1):
        for pattern, reason in RULES:
            if pattern.search(line):
                findings.append((line_number, reason))
    return findings


def check_public_surface(root: Path) -> list[str]:
    findings = []
    for path in public_files(root):
        findings.extend(
            f"{path.relative_to(root)}:{line}: {reason}"
            for line, reason in lint_text(path.read_text(encoding="utf-8"))
        )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    if not (root / "README.md").is_file() or not (root / "skills/tspi-orchestration/SKILL.md").is_file():
        parser.error("root must contain README.md and the orchestration Skill")
    findings = check_public_surface(root)
    if findings:
        print("\n".join(findings))
        return 1
    print(f"public terminology check passed: {len(public_files(root))} documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
