#!/usr/bin/env python3
"""Preflight and optionally repair Gaussian Gen/GenECP inputs."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from transition_state_workflow.util.cli import emit_json, run_cli


def route_indices(lines: list[str]) -> tuple[int | None, int | None]:
    start = next((i for i, line in enumerate(lines) if line.lstrip().startswith("#")), None)
    if start is None:
        return None, None
    end = start
    while end + 1 < len(lines) and lines[end + 1].strip():
        end += 1
    return start, end


def split_tail(lines: list[str]) -> list[str]:
    route_start, route_end = route_indices(lines)
    if route_start is None or route_end is None:
        return []
    i = route_end + 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    while i < len(lines) and lines[i].strip():
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines):
        i += 1
    while i < len(lines) and lines[i].strip():
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    return lines[i:]


def link0_end(lines: list[str]) -> int:
    i = 0
    while i < len(lines) and lines[i].lstrip().startswith("%"):
        i += 1
    return i


def warnings_for(lines: list[str]) -> list[str]:
    warnings: list[str] = []
    route_start, route_end = route_indices(lines)
    link0 = lines[: link0_end(lines)]
    route = " ".join(line.strip() for line in lines[route_start : route_end + 1]) if route_start is not None else ""
    tail = split_tail(lines)

    if not any(line.lower().lstrip().startswith("%chk") for line in link0):
        warnings.append("missing %chk")

    if "/gen" in route.lower():
        first_basis_line = next((line.strip() for line in tail if line.strip()), "")
        if any(part.startswith("-") for part in first_basis_line.split()[:-1]):
            warnings.append("Gen center line contains leading '-' labels")

    if "/genecp" in route.lower():
        stars = [i for i, line in enumerate(tail) if line.strip() == "****"]
        if not stars:
            warnings.append("route uses genecp but no basis terminator was found")
        elif not any(line.strip() for line in tail[stars[-1] + 1 :]):
            warnings.append("route uses genecp but no ECP block follows the basis block")

    if len(lines) < 2 or lines[-1].strip() or lines[-2].strip():
        warnings.append("input does not end with two blank lines")
    return warnings


def fix_lines(lines: list[str], chk: str, nproc: int | None, mem: str | None) -> list[str]:
    out = list(lines)
    end = link0_end(out)
    seen_chk = False
    seen_mem = False
    seen_nproc = False
    fixed_link0: list[str] = []
    for line in out[:end]:
        key = line.split("=", 1)[0].strip().lower()
        if key == "%chk":
            fixed_link0.append(f"%chk={chk}")
            seen_chk = True
        elif key == "%mem" and mem:
            fixed_link0.append(f"%mem={mem}")
            seen_mem = True
        elif key == "%nprocshared" and nproc:
            fixed_link0.append(f"%nprocshared={nproc}")
            seen_nproc = True
        else:
            fixed_link0.append(line)
    inserts: list[str] = []
    if not seen_chk:
        inserts.append(f"%chk={chk}")
    if mem and not seen_mem:
        inserts.append(f"%mem={mem}")
    if nproc and not seen_nproc:
        inserts.append(f"%nprocshared={nproc}")
    out = [*inserts, *fixed_link0, *out[end:]]

    route_start, route_end = route_indices(out)
    if route_start is not None and route_end is not None:
        route = " ".join(line.strip() for line in out[route_start : route_end + 1])
        tail = split_tail(out)
        if "/genecp" in route.lower():
            stars = [i for i, line in enumerate(tail) if line.strip() == "****"]
            if stars and not any(line.strip() for line in tail[stars[-1] + 1 :]):
                route = re.sub(r"/genecp\b", "/gen", route, flags=re.IGNORECASE)
        out[route_start : route_end + 1] = [route]

    for i, line in enumerate(out):
        parts = line.split()
        if len(parts) >= 2 and parts[-1] == "0" and any(part.startswith("-") for part in parts[:-1]):
            out[i] = " ".join([*(part[1:] if part.startswith("-") else part for part in parts[:-1]), "0"])

    while out and not out[-1].strip():
        out.pop()
    out.extend(["", ""])
    return out


def _run(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fix", action="store_true")
    parser.add_argument("--chk")
    parser.add_argument("--nproc", type=int)
    parser.add_argument("--mem")
    args = parser.parse_args(argv)

    lines = args.input.read_text(encoding="utf-8", errors="replace").splitlines()
    warnings = warnings_for(lines)
    result: dict[str, object] = {"warnings": warnings, "fixed": False, "output": None}
    if args.fix:
        output = args.output or args.input.with_suffix(".fixed.gjf")
        chk = args.chk or f"{output.stem}.chk"
        output.write_text("\n".join(fix_lines(lines, chk, args.nproc, args.mem)), encoding="utf-8")
        result["fixed"] = True
        result["output"] = str(output)
    emit_json(result)
    return 1 if warnings and not args.fix else 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(_run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
