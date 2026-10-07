"""Command-line entrypoint for the bound PySCF/CF22D runtime."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from dataclasses import replace
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
from science import prepare, digest, finite_energy, finish

from runner import build_config, run_pyscf


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one TSPi PySCF/CF22D workflow")
    parser.add_argument("--xyz", required=True)
    parser.add_argument("--task", choices=("sp", "opt", "ts", "freq", "thermo", "opt_freq", "ts_freq", "opt-sp"), required=True)
    parser.add_argument("--output-dir", default=".")
    parser.add_argument("--basis", default="def2-tzvp")
    parser.add_argument("--charge", type=int, default=0)
    parser.add_argument("--spin", type=int, default=0)
    parser.add_argument("--unit", choices=("angstrom",), default="angstrom")
    parser.add_argument("--verbose", type=int, default=4)
    parser.add_argument("--xc", default="CF22D")
    parser.add_argument("--grid-level", type=int, default=6)
    parser.add_argument("--conv-tol", type=float, default=1.0e-10)
    parser.add_argument("--max-cycle", type=int, default=400)
    parser.add_argument("--max-steps", type=int, default=100)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--memory-mb", type=int, default=4000)
    parser.add_argument("--imaginary-threshold-cm", type=float, default=-20.0)
    parser.add_argument("--temperature", type=float, default=298.15)
    parser.add_argument("--pressure", type=float, default=101325.0)
    hessian_group = parser.add_mutually_exclusive_group()
    hessian_group.add_argument("--use-initial-hessian", dest="use_initial_hessian", action="store_true")
    hessian_group.add_argument("--no-use-initial-hessian", dest="use_initial_hessian", action="store_false")
    parser.set_defaults(use_initial_hessian=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out = None
    try:
        out, atoms, result = prepare(args, "CF22D", args.basis)
        original_task = args.task
        geometry = out / "input.xyz"
        for task in (["opt", "sp"] if original_task == "opt-sp" else [original_task]):
            args.task = task
            config = replace(build_config(args), xyz=geometry, output_dir=out/task, keep_scratch=True)
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
