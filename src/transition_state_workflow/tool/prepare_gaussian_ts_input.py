#!/usr/bin/env python3
"""Prepare a Gaussian TS/frequency input from an XYZ-like structure file."""

from __future__ import annotations

import argparse
from pathlib import Path

from transition_state_workflow.backends.gaussian import (
    GaussianCoord as Coord,
    GaussianFrame as Frame,
    GaussianBackendAdapter,
    GaussianInputRequest,
    normalize_route,
    read_xyz_frame,
    read_xyz_frames,
    route_requires_extra_section,
    select_frame,
    write_gaussian_input,
)
from transition_state_workflow.util.cli import CLIBase, CLIResult, warn


def read_xyz(path: Path, frame: str = "only") -> tuple[int, str, list[Coord]]:
    """Compatibility wrapper for older imports."""

    return read_xyz_frame(path, frame)


def write_gjf(
    path: Path,
    title: str,
    coords: list[Coord],
    route: str,
    charge: int,
    multiplicity: int,
    nproc: int,
    mem: str,
    chk: str,
    extra_sections: list[str],
) -> None:
    """Compatibility wrapper for older imports."""

    write_gaussian_input(
        path,
        GaussianInputRequest(
            title=title,
            coords=coords,
            route=route,
            charge=charge,
            multiplicity=multiplicity,
            nproc=nproc,
            mem=mem,
            chk=chk,
            extra_sections=tuple(extra_sections),
        ),
    )


def read_extra_sections(paths: list[Path]) -> list[str]:
    return [path.read_text(encoding="utf-8") for path in paths]


class PrepareGaussianTSInputCLI(CLIBase):
    """Prepare Gaussian TS/frequency inputs from XYZ-like structures."""

    description = __doc__

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("xyz", type=Path, help="Input XYZ/extXYZ file. Extra columns are ignored.")
        parser.add_argument("output", type=Path, help="Output Gaussian .gjf/.com path.")
        parser.add_argument(
            "--frame",
            default="only",
            help="XYZ frame selector: only, first, last, or zero-based index. Default refuses multi-frame input.",
        )
        parser.add_argument("--title", help="Gaussian title line. Defaults to the XYZ comment or filename.")
        parser.add_argument("--charge", type=int, default=0)
        parser.add_argument("--multiplicity", type=int, default=1)
        parser.add_argument("--nproc", type=int, default=32)
        parser.add_argument("--mem", default="64GB")
        parser.add_argument("--chk", help="Checkpoint filename. Defaults to <output_stem>.chk.")
        parser.add_argument(
            "--route",
            default="#P B3LYP/6-31G(d) opt=(ts,calcfc,noeigen,maxcycles=100) freq",
            help="Gaussian route section. If it does not start with '#', '#P' is prepended.",
        )
        parser.add_argument(
            "--append-section",
            type=Path,
            action="append",
            default=[],
            help="Append an extra Gaussian input section, e.g. Gen/ECP basis blocks. May be repeated.",
        )

    def execute(self, args: argparse.Namespace) -> CLIResult:
        chk = args.chk or f"{args.output.stem}.chk"
        extra_sections = read_extra_sections(args.append_section)
        if route_requires_extra_section(args.route) and not extra_sections:
            warn("route appears to use Gen/GenECP but no --append-section was provided")
        prepared = GaussianBackendAdapter().prepare(
            {
                "xyz": args.xyz,
                "output": args.output,
                "frame": args.frame,
                "title": args.title,
                "route": args.route,
                "charge": args.charge,
                "multiplicity": args.multiplicity,
                "nproc": args.nproc,
                "mem": args.mem,
                "chk": chk,
                "extra_sections": tuple(extra_sections),
            }
        )
        return CLIResult(
            payload={
                "output": str(args.output),
                "atoms": prepared.metadata["atoms"],
                "frame": prepared.metadata["frame"],
                "chk": chk,
            },
            pretty=True,
        )


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for compatibility with older imports."""

    return PrepareGaussianTSInputCLI().build_parser()


def main(argv: list[str] | None = None) -> int:
    return PrepareGaussianTSInputCLI().main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
