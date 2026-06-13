#!/usr/bin/env python3
"""Prepare a Gaussian TS/frequency input from an XYZ-like structure file."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from transition_state_workflow.util.cli import emit_json, run_cli, warn


Coord = tuple[str, float, float, float]
Frame = tuple[str, list[Coord]]


def read_xyz_frames(path: Path) -> list[Frame]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"{path} is empty")

    frames: list[Frame] = []
    i = 0
    while i < len(lines):
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i >= len(lines):
            break
        try:
            natoms = int(lines[i].strip())
        except ValueError as exc:
            raise ValueError(
                f"{path} is not a standard XYZ/extXYZ file: line {i + 1} is not an atom count"
            ) from exc
        if natoms <= 0:
            raise ValueError(f"Bad atom count on line {i + 1}: {natoms}")

        title_line = i + 1
        title = lines[title_line].strip() if title_line < len(lines) and lines[title_line].strip() else path.stem
        coord_start = i + 2
        coord_end = coord_start + natoms
        if coord_end > len(lines):
            raise ValueError(f"Frame {len(frames)} expected {natoms} atoms, but file ended early")

        coords: list[Coord] = []
        for lineno, line in enumerate(lines[coord_start:coord_end], start=coord_start + 1):
            parts = line.split()
            if len(parts) < 4:
                raise ValueError(f"Bad coordinate line {lineno}: {line!r}")
            try:
                coords.append((parts[0], float(parts[1]), float(parts[2]), float(parts[3])))
            except ValueError as exc:
                raise ValueError(f"Bad coordinate value on line {lineno}: {line!r}") from exc
        frames.append((title, coords))
        i = coord_end

    if not frames:
        raise ValueError(f"{path} does not contain any XYZ frames")
    return frames


def select_frame(frames: list[Frame], selector: str) -> tuple[int, str, list[Coord]]:
    selector = selector.strip().lower()
    if selector == "only":
        if len(frames) != 1:
            raise ValueError(
                f"Input contains {len(frames)} XYZ frames; use --frame first, --frame last, "
                "or --frame <zero-based-index> to choose the TS candidate explicitly"
            )
        index = 0
    elif selector == "first":
        index = 0
    elif selector == "last":
        index = len(frames) - 1
    else:
        try:
            index = int(selector)
        except ValueError as exc:
            raise ValueError("Frame selector must be 'only', 'first', 'last', or an integer index") from exc
        if index < 0:
            index += len(frames)
        if not 0 <= index < len(frames):
            raise ValueError(f"Frame index {selector!r} is out of range for {len(frames)} frames")
    title, coords = frames[index]
    return index, title, coords


def read_xyz(path: Path, frame: str = "only") -> tuple[int, str, list[Coord]]:
    return select_frame(read_xyz_frames(path), frame)


def normalize_route(route: str) -> str:
    route = route.strip()
    if not route:
        raise ValueError("Gaussian route section cannot be empty")
    if route.startswith("#"):
        return route
    return f"#P {route}"


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
    if nproc <= 0:
        raise ValueError("--nproc must be positive")
    if multiplicity <= 0:
        raise ValueError("--multiplicity must be positive")

    lines = [
        f"%chk={chk}",
        f"%nprocshared={nproc}",
        f"%mem={mem}",
        normalize_route(route),
        "",
        title,
        "",
        f"{charge} {multiplicity}",
    ]
    for element, x, y, z in coords:
        lines.append(f"{element:<3s} {x:16.8f} {y:16.8f} {z:16.8f}")
    lines.append("")
    for section in extra_sections:
        section_lines = section.rstrip().splitlines()
        if section_lines:
            lines.extend(section_lines)
            lines.append("")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def read_extra_sections(paths: list[Path]) -> list[str]:
    return [path.read_text(encoding="utf-8") for path in paths]


def route_requires_extra_section(route: str) -> bool:
    normalized = normalize_route(route).lower()
    return bool(re.search(r"(^|[\s/#(),])gen(ecp)?($|[\s/#(),])", normalized))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
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
    return parser


def _run(argv: list[str] | None) -> int:
    args = build_parser().parse_args(argv)
    frame_index, source_title, coords = read_xyz(args.xyz, args.frame)
    title = args.title or source_title or args.output.stem
    chk = args.chk or f"{args.output.stem}.chk"
    extra_sections = read_extra_sections(args.append_section)
    if route_requires_extra_section(args.route) and not extra_sections:
        warn("route appears to use Gen/GenECP but no --append-section was provided")
    write_gjf(
        path=args.output,
        title=title,
        coords=coords,
        route=args.route,
        charge=args.charge,
        multiplicity=args.multiplicity,
        nproc=args.nproc,
        mem=args.mem,
        chk=chk,
        extra_sections=extra_sections,
    )
    emit_json(
        {
            "output": str(args.output),
            "atoms": len(coords),
            "frame": frame_index,
            "chk": chk,
        }
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(_run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
