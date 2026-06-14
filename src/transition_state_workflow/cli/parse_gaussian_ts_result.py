#!/usr/bin/env python3
"""CLI for parsing Gaussian TS/frequency logs into validation artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from transition_state_workflow.backends.gaussian import (
    STANDARD_FREQUENCY_LINE,
    final_gaussian_geometry,
    orientation_blocks,
    parse_convergence_value,
    parse_float,
    parse_gaussian_convergence,
    parse_gaussian_frequencies,
    parse_gaussian_tsfreq_log,
    select_gaussian_job_section,
    split_gaussian_job_sections,
)
from transition_state_workflow.util.cli import CLIBase, CLIResult


split_job_sections = split_gaussian_job_sections
select_job_section = select_gaussian_job_section
parse_frequencies = parse_gaussian_frequencies
parse_convergence = parse_gaussian_convergence
final_geometry = final_gaussian_geometry


def write_xyz(path: Path, atoms: list[tuple[str, float, float, float]], comment: str) -> None:
    lines = [str(len(atoms)), comment]
    for element, x, y, z in atoms:
        lines.append(f"{element:<3s} {x:16.8f} {y:16.8f} {z:16.8f}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_log(log_path: Path, section_index: int | None = None) -> dict[str, object]:
    """Compatibility wrapper for the Gaussian backend TS/Freq parser."""

    return parse_gaussian_tsfreq_log(log_path, section_index=section_index)


class ParseGaussianTSResultCLI(CLIBase):
    """Gaussian TS/Freq parser artifact writer command."""

    description = __doc__

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("log", type=Path, help="Gaussian output file (.out, or legacy .log)")
        parser.add_argument("-o", "--output-dir", type=Path, default=None, help="Directory for parsed artifacts")
        parser.add_argument("--section-index", type=int, default=None, help="Evaluate a specific zero-based job section")
        parser.add_argument("--strict", action="store_true", help="Return a non-zero exit code if TS validation fails")

    def execute(self, args: argparse.Namespace) -> CLIResult:
        output_dir = args.output_dir or args.log.with_suffix("").with_name(f"{args.log.stem}_parsed")
        output_dir.mkdir(parents=True, exist_ok=True)

        parsed = parse_log(args.log, section_index=args.section_index)
        summary = parsed["summary"]
        frequencies = parsed["frequencies"]
        atoms = parsed["atoms"]

        (output_dir / "validation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        (output_dir / "frequencies_cm-1.txt").write_text(
            "\n".join(f"{freq:.6f}" for freq in frequencies) + ("\n" if frequencies else ""),
            encoding="utf-8",
        )
        if atoms:
            final_xyz = output_dir / f"{args.log.stem}_final.xyz"
            write_xyz(final_xyz, atoms, f"Final geometry extracted from {args.log.name}")

        exit_code = 2 if args.strict and summary["status"] != "validated_ts" else 0
        return CLIResult(exit_code=exit_code, payload={"output_dir": str(output_dir), "summary": summary})


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for compatibility with older imports."""

    return ParseGaussianTSResultCLI().build_parser()


def main(argv: list[str] | None = None) -> int:
    return ParseGaussianTSResultCLI().main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
