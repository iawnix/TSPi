"""Command-line entrypoint for the bound PySCF/CF22D runtime."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from dataclasses import replace
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
from science import prepare, digest, finite_energy, finish, read_xyz

from runner import build_config, run_pyscf


from cli import build_parser, parse_arguments


def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(argv)
    out = None
    try:
        out, atoms, result = prepare(args, "CF22D", args.basis)
        original_task = args.task
        geometry = out / "input.xyz"
        for task in (["opt", "sp"] if original_task == "opt-sp" else [original_task]):
            args.task = task
            config = replace(build_config(args), xyz=geometry, output_dir=out/task, keep_scratch=False)
            config.output_dir.mkdir()
            # PySCF's scientific log remains distinct from Job stdout/stderr.
            with (config.output_dir/"pyscf.out").open("w") as log:
                from contextlib import redirect_stdout
                with redirect_stdout(log):
                    value = run_pyscf(config)
            summary = value["summary"]
            if not value["execution_completed"] or summary["scf_converged"] is not True:
                raise ValueError("CF22D did not complete with converged SCF")
            if task in {"opt", "opt_freq", "ts", "ts_freq"}:
                if summary["optimization_converged"] is not True:
                    raise ValueError("CF22D optimization did not converge")
                next_geometry = config.output_dir/"pyscf_geometry.xyz"
                if [atom[0] for atom in read_xyz(next_geometry)] != [atom[0] for atom in atoms]:
                    raise ValueError("optimized geometry atom order changed")
            else:
                next_geometry = geometry
            result["steps"].append({"task":task, "input_sha256":digest(geometry),
                "energy_hartree":finite_energy(summary["electronic_energy_hartree"]),
                "geometry_sha256":digest(next_geometry), "summary":summary,
                "program_version":value["pyscf_version"]})
            geometry = next_geometry
        import shutil
        shutil.copyfile(geometry, out/"geometry.xyz")
        finish(out, result, __file__)
        return 0
    except Exception as exc:
        if out is not None: finish(out, result, __file__, exc)
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
