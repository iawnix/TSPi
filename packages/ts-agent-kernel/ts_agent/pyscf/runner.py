"""TSPi-native PySCF/CF22D workflow runner.

The runner accepts explicit argv instead of the source project's YAML file so
that local workers and remote schedulers can safely rewrite staged input
basenames.  All output names are fixed for the calculation Attempt.
"""

from __future__ import annotations

import json
import io
import importlib
import importlib.metadata
import math
import os
import re
import shutil
import sys
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from ts_agent.backends.pyscf import (
    PYSCF_ARTIFACTS,
    normalize_pyscf_settings,
)


@dataclass(frozen=True)
class PyscfRunConfig:
    xyz: Path
    task_type: str
    output_dir: Path
    basis: str = "def2-tzvp"
    charge: int = 0
    spin: int = 0
    unit: str = "angstrom"
    verbose: int = 4
    xc: str = "CF22D"
    grid_level: int = 6
    conv_tol: float = 1.0e-10
    max_cycle: int = 400
    max_steps: int = 100
    threads: int = 1
    memory_mb: int = 4000
    imaginary_threshold_cm: float = -20.0
    temperature: float = 298.15
    pressure: float = 101325.0
    # ``None`` preserves the source runner's task-specific defaults when the
    # Python API is used directly.  The CLI/adapter may still pass an explicit
    # true/false override.
    use_initial_hessian: bool | None = None
    keep_scratch: bool = False


def run_pyscf(config: PyscfRunConfig) -> dict[str, Any]:
    """Execute one workflow and write the fixed Attempt artifacts."""

    config = _apply_task_defaults(config)
    _validate_config(config)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    _reject_existing_outputs(config)
    started = time.time()
    symbols: list[str] = []
    coordinates: list[tuple[float, float, float]] = []
    scratch: Path | None = None
    runtime = None
    pyscf_version: str | None = None
    geometric_version: str | None = None
    dispersion_version: str | None = None
    old_env: dict[str, str | None] = {}
    old_threads: int | None = None
    old_max_memory: Any = None
    old_tmpdir: Any = None
    summary: dict[str, Any] = {
        "atom_count": 0,
        "task_sequence": _task_sequence(config.task_type),
        "electronic_energy_hartree": None,
        "scf_converged": None,
        "optimization_converged": None,
        "optimization_convergence_evidence_present": None,
        "optimization_convergence_satisfied": None,
        "stationary_point_found": None,
        "optimized_geometry_atom_count": None,
        "frequency_count": None,
        "imaginary_frequency_count": None,
        "imaginary_frequencies_cm-1": [],
        "thermochemistry_complete": None,
        "gibbs_hartree": None,
        "stationary_point_valid": None,
    }
    artifacts_written: list[str] = [name for name in PYSCF_ARTIFACTS[config.task_type] if name != "pyscf.out"]
    mol = None
    mf = None
    frequency_data: dict[str, Any] | None = None
    thermo_data: dict[str, Any] | None = None

    try:
        symbols, coordinates = _read_xyz(config.xyz)
        summary["atom_count"] = len(symbols)
        runtime, pyscf_version, geometric_version, dispersion_version = _load_runtime()
        gto, dft, hessian_thermo, geometric_optimize = runtime
        scratch = _make_scratch(config.output_dir)

        from pyscf import lib

        old_threads = int(lib.num_threads())
        old_max_memory = getattr(lib.param, "MAX_MEMORY", None)
        old_tmpdir = getattr(lib.param, "TMPDIR", None)
        for key, value in {
            "OMP_NUM_THREADS": str(config.threads),
            "PYSCF_MAX_MEMORY": str(config.memory_mb),
            "PYSCF_TMPDIR": str(scratch),
        }.items():
            old_env[key] = os.environ.get(key)
            os.environ[key] = value
        lib.num_threads(config.threads)
        lib.param.MAX_MEMORY = config.memory_mb
        lib.param.TMPDIR = str(scratch)

        atom = ";".join(
            f"{symbol} {x:.15g} {y:.15g} {z:.15g}"
            for symbol, (x, y, z) in zip(symbols, coordinates)
        )
        mol = gto.M(
            atom=atom,
            basis=config.basis,
            charge=config.charge,
            spin=config.spin,
            unit=config.unit,
            verbose=config.verbose,
            max_memory=config.memory_mb,
        )
        mol.build()

        sequence = _task_sequence(config.task_type)
        geometry_kind: str | None = None
        if "opt" in sequence:
            mol, optimization_evidence = _run_optimization(
                mol,
                dft,
                geometric_optimize,
                config,
                transition=False,
            )
            geometry_kind = "opt"
            summary.update(optimization_evidence)
            summary["optimization_converged"] = optimization_evidence["optimization_convergence_satisfied"]
            summary["stationary_point_found"] = True
        elif "ts" in sequence:
            mol, optimization_evidence = _run_optimization(
                mol,
                dft,
                geometric_optimize,
                config,
                transition=True,
            )
            geometry_kind = "ts"
            summary.update(optimization_evidence)
            summary["optimization_converged"] = optimization_evidence["optimization_convergence_satisfied"]
            summary["stationary_point_found"] = True

        if geometry_kind is not None:
            geometry_path = config.output_dir / "pyscf_geometry.xyz"
            mol.tofile(str(geometry_path), format="xyz")
            summary["optimized_geometry_atom_count"] = int(mol.natm)

        needs_scf = any(name in sequence for name in ("sp", "opt", "ts", "freq", "thermo"))
        if needs_scf:
            mf = _build_method(dft, mol, config)
            energy = mf.kernel()
            if not bool(getattr(mf, "converged", False)):
                raise RuntimeError("PySCF SCF did not converge")
            summary["electronic_energy_hartree"] = float(energy)
            summary["scf_converged"] = True

        if "freq" in sequence or "thermo" in sequence:
            if mf is None:
                raise RuntimeError("frequency calculation requires a converged SCF")
            hessian = mf.Hessian().kernel()
            frequency_analysis = hessian_thermo.harmonic_analysis(
                mol,
                hessian,
                imaginary_freq=False,
            )
            frequencies = _real_floats(frequency_analysis.get("freq_wavenumber", []))
            imaginary = [value for value in frequencies if value < config.imaginary_threshold_cm]
            frequency_data = {
                "schema_version": "pyscf-frequencies/1",
                "frequencies_cm-1": frequencies,
                "imaginary_frequencies_cm-1": imaginary,
                "imaginary_threshold_cm": config.imaginary_threshold_cm,
                "n_modes": len(frequencies),
                "n_imaginary": len(imaginary),
            }
            (config.output_dir / "pyscf_frequencies.json").write_text(
                json.dumps(frequency_data, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            import numpy as np

            np.save(config.output_dir / "pyscf_hessian.npy", hessian)
            summary.update(
                {
                    "frequency_count": len(frequencies),
                    "imaginary_frequency_count": len(imaginary),
                    "imaginary_frequencies_cm-1": imaginary,
                }
            )
            if geometry_kind == "ts":
                summary["stationary_point_valid"] = len(imaginary) == 1
            elif geometry_kind == "opt":
                summary["stationary_point_valid"] = len(imaginary) == 0

        if "thermo" in sequence:
            if mf is None or frequency_data is None:
                raise RuntimeError("thermochemistry requires a converged frequency calculation")
            raw_thermo = hessian_thermo.thermo(
                mf,
                frequency_analysis["freq_au"],
                temperature=config.temperature,
                pressure=config.pressure,
            )
            thermo_data = _thermo_payload(
                raw_thermo,
                config,
                electronic_energy=summary.get("electronic_energy_hartree"),
            )
            (config.output_dir / "pyscf_thermo.json").write_text(
                json.dumps(thermo_data, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            summary.update(
                {
                    "thermochemistry_complete": True,
                    "gibbs_hartree": thermo_data.get("gibbs_hartree"),
                }
            )

        result = {
            "schema_version": "pyscf-run/1",
            "backend": "pyscf",
            "task_type": config.task_type,
            "execution_completed": True,
            "started_at_unix": started,
            "finished_at_unix": time.time(),
            "pyscf_version": pyscf_version,
            "geometric_version": geometric_version,
            "pyscf_dispersion_version": dispersion_version,
            "settings": _settings_payload(config),
            "summary": summary,
            "artifacts": sorted(artifacts_written),
        }
        _write_result(config.output_dir / "pyscf_result.json", result)
        print(
            "PYSCF_RUN_COMPLETED "
            + json.dumps(
                {
                    "task_type": config.task_type,
                    "scf_converged": summary["scf_converged"],
                    "frequency_count": summary["frequency_count"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return result
    except Exception as exc:
        failure = {
            "schema_version": "pyscf-run/1",
            "backend": "pyscf",
            "task_type": config.task_type,
            "execution_completed": False,
            "started_at_unix": started,
            "finished_at_unix": time.time(),
            "pyscf_version": pyscf_version,
            "geometric_version": geometric_version,
            "pyscf_dispersion_version": dispersion_version,
            "settings": _settings_payload(config),
            "summary": summary,
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "artifacts": sorted(name for name in artifacts_written if (config.output_dir / name).is_file()),
        }
        try:
            _write_result(config.output_dir / "pyscf_result.json", failure)
        except Exception:
            pass
        print(f"PYSCF_RUN_FAILED {json.dumps(failure['error'], sort_keys=True)}", file=sys.stderr, flush=True)
        raise
    finally:
        try:
            from pyscf import lib

            if old_threads is not None:
                lib.num_threads(old_threads)
            if old_max_memory is not None:
                lib.param.MAX_MEMORY = old_max_memory
            if old_tmpdir is not None:
                lib.param.TMPDIR = old_tmpdir
        except Exception:
            pass
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if scratch is not None and not config.keep_scratch:
            shutil.rmtree(scratch, ignore_errors=True)


def build_config(args: Any) -> PyscfRunConfig:
    raw = {
        "basis": args.basis,
        "charge": args.charge,
        "spin": args.spin,
        "unit": args.unit,
        "verbose": args.verbose,
        "xc": args.xc,
        "grid_level": args.grid_level,
        "conv_tol": args.conv_tol,
        "max_cycle": args.max_cycle,
        "max_steps": args.max_steps,
        "threads": args.threads,
        "memory_mb": args.memory_mb,
        "imaginary_threshold_cm": args.imaginary_threshold_cm,
        "temperature": args.temperature,
        "pressure": args.pressure,
        "use_initial_hessian": (
            args.use_initial_hessian
            if args.use_initial_hessian is not None
            else args.task in {"ts", "ts_freq"}
        ),
    }
    settings = normalize_pyscf_settings(
        {key: _format_cli_value(value) for key, value in raw.items()}, args.task
    )
    return PyscfRunConfig(
        xyz=Path(args.xyz),
        task_type=args.task,
        output_dir=Path(args.output_dir),
        **settings,
    )


def _load_runtime():
    try:
        import pyscf
        from pyscf import dft, gto
        from pyscf.hessian import thermo as hessian_thermo
        from pyscf.geomopt.geometric_solver import optimize as geometric_optimize
    except Exception as exc:
        raise RuntimeError(
            "PySCF runtime is unavailable; install PySCF, geomeTRIC, "
            "and pyscf-dispersion in the bound environment"
        ) from exc
    try:
        import geometric

        geometric_version = getattr(geometric, "__version__", "unknown")
    except Exception:
        geometric_version = "unknown"
    # ``pyscf-dispersion`` installs its Python package below the PySCF
    # namespace.  There is intentionally no top-level ``pyscf_dispersion``
    # import; the distribution metadata is the package-presence check.
    try:
        dispersion_module = importlib.import_module("pyscf.dispersion")
        distribution_version = importlib.metadata.version("pyscf-dispersion")
        dispersion_version = getattr(dispersion_module, "__version__", None) or distribution_version
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError("pyscf-dispersion is required for CF22D") from exc
    except Exception as exc:
        raise RuntimeError(
            "pyscf-dispersion could not import its pyscf.dispersion module"
        ) from exc
    # CF22D is a PySCF/LibXC functional.  The dispersion distribution supplies
    # the D3 implementation selected by PySCF's CF22D parser; it does not
    # register a separate top-level functional.
    try:
        from pyscf.scf import dispersion as scf_dispersion

        probe_mol = gto.M(
            atom="H 0 0 0; H 0 0 1.4",
            basis="sto-3g",
            spin=0,
            verbose=0,
        )
        probe_mol.build()
        probe_mf = dft.KS(probe_mol, xc="CF22D")
        if not scf_dispersion.check_disp(probe_mf):
            raise RuntimeError("CF22D did not select its D3 dispersion correction")
        if getattr(scf_dispersion, "dftd3", None) is None:
            raise RuntimeError("PySCF cannot access the installed D3 dispersion implementation")
    except Exception as exc:
        raise RuntimeError("CF22D is unavailable in the selected PySCF runtime") from exc
    return (
        (gto, dft, hessian_thermo, geometric_optimize),
        getattr(pyscf, "__version__", "unknown"),
        geometric_version,
        dispersion_version,
    )


def _build_method(dft: Any, mol: Any, config: PyscfRunConfig) -> Any:
    mf = dft.KS(mol, xc=config.xc)
    mf.grids.level = config.grid_level
    mf.conv_tol = config.conv_tol
    mf.max_cycle = config.max_cycle
    return mf


def _run_optimization(
    mol: Any,
    dft: Any,
    optimize: Any,
    config: PyscfRunConfig,
    *,
    transition: bool,
) -> tuple[Any, dict[str, bool | None]]:
    mf = _build_method(dft, mol, config)
    params = {
        "convergence_energy": 1e-6,
        "convergence_grms": 3e-4,
        "convergence_gmax": 4.5e-4,
        "convergence_drms": 1.2e-3,
        "convergence_dmax": 1.8e-3,
    }
    if config.use_initial_hessian:
        params["hessian"] = True
    with _tee_stdout() as captured:
        if transition:
            params["transition"] = True
            raw_result = mf.Gradients().optimizer(solver="geomeTRIC").kernel(
                {**params, "maxsteps": config.max_steps}
            )
        else:
            raw_result = optimize(mf, maxsteps=config.max_steps, **params)
    result_mol, result_evidence = _unwrap_optimization_result(raw_result)
    text_evidence = _parse_optimization_evidence(captured.getvalue())
    if result_evidence["optimization_convergence_evidence_present"] is not True:
        result_evidence = text_evidence
    return result_mol, result_evidence


class _TeeStream:
    """Mirror optimizer output while retaining a bounded in-process transcript."""

    def __init__(self, primary: Any, mirror: io.StringIO) -> None:
        self.primary = primary
        self.mirror = mirror

    def write(self, value: str) -> int:
        self.primary.write(value)
        self.mirror.write(value)
        return len(value)

    def flush(self) -> None:
        self.primary.flush()
        self.mirror.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.primary, name)


class _TeeStdout:
    def __init__(self) -> None:
        self.previous_stdout: Any = None
        self.previous_stderr: Any = None
        self.buffer = io.StringIO()

    def __enter__(self) -> io.StringIO:
        self.previous_stdout = sys.stdout
        self.previous_stderr = sys.stderr
        # geomeTRIC versions differ in whether progress and convergence lines
        # use stdout or stderr. Keep both streams in the evidence transcript.
        sys.stdout = _TeeStream(self.previous_stdout, self.buffer)
        sys.stderr = _TeeStream(self.previous_stderr, self.buffer)
        return self.buffer

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        sys.stdout = self.previous_stdout
        sys.stderr = self.previous_stderr


def _tee_stdout() -> _TeeStdout:
    return _TeeStdout()


def _unwrap_optimization_result(value: Any) -> tuple[Any, dict[str, bool | None]]:
    """Extract optional convergence metadata without depending on geomeTRIC internals.

    PySCF's public geomeTRIC adapter currently returns a Mole object, while
    some versions/wrappers expose a result object or tuple with a convergence
    flag.  Accept all of those forms and leave evidence unknown when the
    adapter does not expose it.
    """

    candidates: list[Any] = [value]
    result = value
    if isinstance(value, tuple) and value:
        result = value[0]
        candidates.extend(value[1:])
    for candidate in candidates:
        evidence = _candidate_convergence(candidate)
        if evidence["optimization_convergence_evidence_present"] is True:
            return result, evidence
    return result, _parse_optimization_evidence("")


def _candidate_convergence(value: Any) -> dict[str, bool | None]:
    if isinstance(value, bool):
        return {
            "optimization_convergence_evidence_present": True,
            "optimization_convergence_satisfied": value,
        }
    if isinstance(value, dict):
        for key in ("converged", "is_converged", "success"):
            if key in value and isinstance(value[key], bool):
                return {
                    "optimization_convergence_evidence_present": True,
                    "optimization_convergence_satisfied": value[key],
                }
    for key in ("converged", "is_converged", "success"):
        try:
            candidate = getattr(value, key)
        except Exception:
            continue
        if isinstance(candidate, bool):
            return {
                "optimization_convergence_evidence_present": True,
                "optimization_convergence_satisfied": candidate,
            }
    return _parse_optimization_evidence("")


_GEOMETRIC_CONVERGED = re.compile(
    r"(?:Converged!\s*=\s*(YES|NO)|(?:geometry\s+)?optimization\s+(?:has\s+)?(converged|did\s+not\s+converge))",
    re.IGNORECASE,
)


def _parse_optimization_evidence(text: str) -> dict[str, bool | None]:
    matches = list(_GEOMETRIC_CONVERGED.finditer(text))
    if not matches:
        return {
            "optimization_convergence_evidence_present": False,
            "optimization_convergence_satisfied": None,
        }
    match = matches[-1]
    token = next((group for group in match.groups() if group), "").lower()
    satisfied = token in {"yes", "converged"}
    return {
        "optimization_convergence_evidence_present": True,
        "optimization_convergence_satisfied": satisfied,
    }


def _task_sequence(task_type: str) -> tuple[str, ...]:
    if task_type == "opt_freq":
        return ("opt", "sp", "freq")
    if task_type == "ts_freq":
        return ("ts", "sp", "freq")
    if task_type == "freq":
        return ("sp", "freq")
    if task_type == "thermo":
        return ("sp", "freq", "thermo")
    return (task_type,)


def _thermo_payload(
    data: Any,
    config: PyscfRunConfig,
    *,
    electronic_energy: Any = None,
) -> dict[str, Any]:
    def value(name: str) -> float | None:
        try:
            raw = data[name]
            if isinstance(raw, (list, tuple)):
                raw = raw[0]
            return float(raw)
        except (KeyError, TypeError, ValueError, IndexError):
            return None

    electronic = _finite_or_none(electronic_energy)
    thermal = value("E_tot")
    enthalpy = value("H_tot")
    gibbs = value("G_tot")
    payload = {
        "schema_version": "pyscf-thermo/1",
        "temperature_K": config.temperature,
        "pressure_Pa": config.pressure,
        "electronic_energy_hartree": electronic,
        "zpe_hartree": value("ZPE"),
        "energy_0k_hartree": value("E_0K"),
        "thermal_energy_hartree": thermal,
        "enthalpy_hartree": enthalpy,
        "entropy": value("S_tot"),
        "gibbs_hartree": gibbs,
        "thermal_energy_correction_hartree": _difference(thermal, electronic),
        "enthalpy_correction_hartree": _difference(enthalpy, electronic),
        "gibbs_correction_hartree": _difference(gibbs, electronic),
    }
    return payload


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _difference(value: float | None, reference: float | None) -> float | None:
    if value is None or reference is None:
        return None
    return value - reference


def _apply_task_defaults(config: PyscfRunConfig) -> PyscfRunConfig:
    if config.use_initial_hessian is not None:
        return config
    return replace(
        config,
        use_initial_hessian=config.task_type in {"ts", "ts_freq"},
    )


def _settings_payload(config: PyscfRunConfig) -> dict[str, Any]:
    payload = asdict(config)
    payload.pop("xyz", None)
    payload.pop("output_dir", None)
    payload.pop("keep_scratch", None)
    payload.pop("task_type", None)
    return payload


def _read_xyz(path: Path) -> tuple[list[str], list[tuple[float, float, float]]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"PySCF XYZ input is not a regular file: {path}")
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    if len(lines) < 2:
        raise ValueError("PySCF XYZ input is incomplete")
    try:
        count = int(lines[0].strip())
    except ValueError as exc:
        raise ValueError("PySCF XYZ atom count is invalid") from exc
    if count < 1 or len(lines) != count + 2:
        raise ValueError("PySCF XYZ input must contain exactly one complete frame")
    symbols: list[str] = []
    coordinates: list[tuple[float, float, float]] = []
    for line in lines[2:]:
        fields = line.split()
        if len(fields) < 4:
            raise ValueError("PySCF XYZ atom record is invalid")
        try:
            xyz = tuple(float(item) for item in fields[1:4])
        except ValueError as exc:
            raise ValueError("PySCF XYZ coordinates are invalid") from exc
        symbols.append(fields[0])
        coordinates.append(xyz)  # type: ignore[arg-type]
    return symbols, coordinates


def _make_scratch(output_dir: Path) -> Path:
    base = Path(os.environ.get("TMPDIR") or output_dir / ".pyscf-tmp")
    base.mkdir(parents=True, exist_ok=True)
    scratch = base / f"tspi-pyscf-{uuid.uuid4().hex[:12]}"
    scratch.mkdir(mode=0o700)
    return scratch


def _reject_existing_outputs(config: PyscfRunConfig) -> None:
    for name in PYSCF_ARTIFACTS[config.task_type]:
        if name == "pyscf.out":
            continue
        path = config.output_dir / name
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"PySCF refuses to overwrite existing output: {name}")


def _write_result(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "tolist"):
        return value.tolist()
    return str(value)


def _real_floats(values: Iterable[Any]) -> list[float]:
    result: list[float] = []
    for value in values:
        try:
            number = float(getattr(value, "real", value))
        except (TypeError, ValueError):
            continue
        if number == number and abs(number) != float("inf"):
            result.append(number)
    return result


def _validate_config(config: PyscfRunConfig) -> None:
    if config.task_type not in PYSCF_ARTIFACTS:
        raise ValueError(f"unsupported PySCF task_type: {config.task_type}")
    if config.output_dir.is_symlink() or (config.output_dir.exists() and not config.output_dir.is_dir()):
        raise ValueError("PySCF output directory must be a physical directory")
    normalize_pyscf_settings(_settings_as_strings(config), config.task_type)


def _settings_as_strings(config: PyscfRunConfig) -> dict[str, str]:
    return {key: _format_cli_value(value) for key, value in _settings_payload(config).items()}


def _format_cli_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


__all__ = ["PyscfRunConfig", "build_config", "run_pyscf"]
