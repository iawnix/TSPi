"""Executable ASE NEB driver backed by the xTB command-line program."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from ase import Atoms, __version__ as ase_version
from ase.calculators.calculator import Calculator, all_changes
from ase.io import read, write
from ase.mep import NEB
from ase.optimize import FIRE
from ase.units import Bohr, Hartree
from .base import configured_backend_command


_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?"
_XTB_VERSION = re.compile(r"\bxtb version\s+(\S+)", flags=re.IGNORECASE)
_SOLVENT = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_TOTAL_ENERGY = re.compile(
    rf"(?:\||::)\s*TOTAL ENERGY\s+({_FLOAT})\s+Eh",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class NebRunConfig:
    reactant: Path
    product: Path
    images: int
    fmax: float
    max_steps: int
    spring_constant: float
    interpolation: str
    method: str
    charge: int
    uhf: int
    climb: bool
    remove_rotation_and_translation: bool
    accuracy: float | None = None
    electronic_temperature: float | None = None
    solvent_model: str | None = None
    solvent: str | None = None


class XtbCliCalculator(Calculator):
    """Minimal ASE calculator using isolated ``xtb --grad`` invocations."""

    implemented_properties = ["energy", "forces"]

    def __init__(
        self,
        *,
        executable: str,
        method: str,
        charge: int,
        uhf: int,
        accuracy: float | None,
        electronic_temperature: float | None,
        solvent_model: str | None,
        solvent: str | None,
    ) -> None:
        super().__init__()
        if not executable or "\x00" in executable:
            raise ValueError("TS_ASE_NEB_XTB must name an xTB executable")
        self.executable = executable
        self.method = method
        self.charge = charge
        self.uhf = uhf
        self.accuracy = accuracy
        self.electronic_temperature = electronic_temperature
        self.solvent_model = solvent_model
        self.solvent = solvent
        self.program_version: str | None = None

    def calculate(
        self,
        atoms: Atoms | None = None,
        properties: Sequence[str] = ("energy", "forces"),
        system_changes: Sequence[str] = all_changes,
    ) -> None:
        super().calculate(atoms, properties, system_changes)
        if self.atoms is None:
            raise RuntimeError("xTB calculator received no atoms")
        with tempfile.TemporaryDirectory(prefix="ase-neb-xtb-") as directory:
            work_dir = Path(directory)
            input_path = work_dir / "input.xyz"
            write(input_path, self.atoms, format="xyz")
            command = [
                self.executable,
                input_path.name,
                "--grad",
                "--chrg",
                str(self.charge),
                "--uhf",
                str(self.uhf),
                "--gfn",
                self.method.removeprefix("gfn"),
            ]
            if self.accuracy is not None:
                command.extend(["--acc", format(self.accuracy, ".15g")])
            if self.electronic_temperature is not None:
                command.extend(["--etemp", format(self.electronic_temperature, ".15g")])
            if self.solvent_model is not None and self.solvent is not None:
                command.extend([f"--{self.solvent_model}", self.solvent])
            completed = subprocess.run(
                command,
                cwd=work_dir,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            output = completed.stdout
            if completed.returncode != 0:
                detail = (completed.stderr or output)[-4096:].strip()
                raise RuntimeError(f"xTB gradient calculation failed ({completed.returncode}): {detail}")
            if "* finished run on" not in output:
                raise RuntimeError("xTB gradient calculation did not reach its completion marker")
            energy_matches = list(_TOTAL_ENERGY.finditer(output))
            if not energy_matches:
                raise RuntimeError("xTB gradient calculation returned no total energy")
            energy_hartree = _number(energy_matches[-1].group(1))
            gradient = _read_gradient(work_dir / "gradient", len(self.atoms))
            version_match = _XTB_VERSION.search(output)
            if version_match:
                self.program_version = version_match.group(1)
            self.results = {
                "energy": energy_hartree * Hartree,
                "forces": -gradient * Hartree / Bohr,
            }


def run_ase_neb(
    config: NebRunConfig,
    *,
    output_dir: Path = Path("."),
    calculator_factory: Callable[[int], Calculator] | None = None,
) -> dict[str, Any]:
    _validate_config(config)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [output_dir / name for name in ("neb.traj", "neb_path.xyz", "neb_summary.json")]
    if any(path.exists() or path.is_symlink() for path in outputs):
        raise RuntimeError("ASE NEB refuses to overwrite an existing output artifact")

    reactant_frames = read(config.reactant, index=":")
    product_frames = read(config.product, index=":")
    if len(reactant_frames) != 1 or len(product_frames) != 1:
        raise ValueError("ASE NEB endpoints must each resolve to exactly one atomic structure")
    reactant = reactant_frames[0]
    product = product_frames[0]
    if len(reactant) < 1 or reactant.get_atomic_numbers().tolist() != product.get_atomic_numbers().tolist():
        raise ValueError("ASE NEB endpoints must have identical atom identities and ordering")
    if np.array_equal(reactant.positions, product.positions):
        raise ValueError("ASE NEB endpoints must not have identical coordinates")

    images = [reactant]
    images.extend(reactant.copy() for _ in range(config.images - 2))
    images.append(product)
    neb = NEB(
        images,
        k=config.spring_constant,
        climb=config.climb,
        parallel=False,
        remove_rotation_and_translation=config.remove_rotation_and_translation,
        method="aseneb",
    )
    neb.interpolate(method=config.interpolation)

    if calculator_factory is None:
        executable = os.environ.get("TS_ASE_NEB_XTB") or configured_backend_command("ase_neb_xtb", "xtb")

        def calculator_factory(_index: int) -> Calculator:
            return XtbCliCalculator(
                executable=executable,
                method=config.method,
                charge=config.charge,
                uhf=config.uhf,
                accuracy=config.accuracy,
                electronic_temperature=config.electronic_temperature,
                solvent_model=config.solvent_model,
                solvent=config.solvent,
            )

    calculators: list[Calculator] = []
    for index, image in enumerate(images):
        calculator = calculator_factory(index)
        calculators.append(calculator)
        image.calc = calculator

    optimizer = FIRE(neb, logfile="-")
    converged = bool(optimizer.run(fmax=config.fmax, steps=config.max_steps))
    energies = [float(image.get_potential_energy()) for image in images]
    forces = np.asarray(neb.get_forces(), dtype=float)
    max_force = float(np.linalg.norm(forces, axis=1).max()) if forces.size else 0.0
    if not all(math.isfinite(value) for value in [*energies, max_force]):
        raise RuntimeError("ASE NEB produced non-finite energies or forces")
    highest = max(range(len(energies)), key=energies.__getitem__)

    write(outputs[0], images)
    _write_path_xyz(outputs[1], images, energies)
    calculator_versions = {
        version
        for calculator in calculators
        if isinstance((version := getattr(calculator, "program_version", None)), str) and version
    }
    calculator_version = next(iter(calculator_versions)) if len(calculator_versions) == 1 else None
    summary = {
        "schema_version": "ase-neb-run/1",
        "backend": "ase_neb",
        "task_type": "neb",
        "execution_completed": True,
        "ase_version": ase_version,
        "calculator": "xtb_cli",
        "calculator_version": calculator_version,
        "method": config.method,
        "charge": config.charge,
        "uhf": config.uhf,
        "accuracy": config.accuracy,
        "electronic_temperature": config.electronic_temperature,
        "solvent_model": config.solvent_model,
        "solvent": config.solvent,
        "optimizer": "FIRE",
        "interpolation": config.interpolation,
        "climb": config.climb,
        "remove_rotation_and_translation": config.remove_rotation_and_translation,
        "spring_constant_ev_per_angstrom2": config.spring_constant,
        "fmax_ev_per_angstrom": config.fmax,
        "max_steps": config.max_steps,
        "steps": int(optimizer.nsteps),
        "converged": converged,
        "atom_count": len(images[0]),
        "image_count": len(images),
        "image_energies_ev": energies,
        "highest_energy_image_index": highest,
        "barrier_forward_ev": energies[highest] - energies[0],
        "barrier_reverse_ev": energies[highest] - energies[-1],
        "max_neb_force_ev_per_angstrom": max_force,
    }
    outputs[2].write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(
        "ASE_NEB_RUN_COMPLETED "
        + json.dumps(
            {
                "converged": converged,
                "images": len(images),
                "steps": optimizer.nsteps,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one bounded ASE NEB calculation")
    parser.add_argument("--reactant", type=Path, required=True)
    parser.add_argument("--product", type=Path, required=True)
    parser.add_argument("--images", type=int, required=True)
    parser.add_argument("--fmax", type=float, required=True)
    parser.add_argument("--max-steps", type=int, required=True)
    parser.add_argument("--spring-constant", type=float, required=True)
    parser.add_argument("--interpolation", choices=("linear", "idpp"), required=True)
    parser.add_argument("--method", choices=("gfn1", "gfn2"), required=True)
    parser.add_argument("--charge", type=int, required=True)
    parser.add_argument("--uhf", type=int, required=True)
    parser.add_argument("--climb", type=_parse_bool, required=True)
    parser.add_argument("--remove-rotation-and-translation", type=_parse_bool, required=True)
    parser.add_argument("--accuracy", type=float)
    parser.add_argument("--electronic-temperature", type=float)
    parser.add_argument("--solvent-model", choices=("alpb", "gbsa"))
    parser.add_argument("--solvent")
    args = parser.parse_args(argv)
    config = NebRunConfig(
        reactant=args.reactant,
        product=args.product,
        images=args.images,
        fmax=args.fmax,
        max_steps=args.max_steps,
        spring_constant=args.spring_constant,
        interpolation=args.interpolation,
        method=args.method,
        charge=args.charge,
        uhf=args.uhf,
        climb=args.climb,
        remove_rotation_and_translation=args.remove_rotation_and_translation,
        accuracy=args.accuracy,
        electronic_temperature=args.electronic_temperature,
        solvent_model=args.solvent_model,
        solvent=args.solvent,
    )
    _validate_config(config)
    run_ase_neb(config)
    return 0


def _validate_config(config: NebRunConfig) -> None:
    if not 3 <= config.images <= 32:
        raise ValueError("images must be between 3 and 32")
    if not 0.0 < config.fmax <= 10.0 or not math.isfinite(config.fmax):
        raise ValueError("fmax must be finite, positive, and at most 10")
    if not 1 <= config.max_steps <= 100_000:
        raise ValueError("max_steps must be between 1 and 100000")
    if not 0.0 < config.spring_constant <= 10.0 or not math.isfinite(config.spring_constant):
        raise ValueError("spring_constant must be finite, positive, and at most 10")
    if (config.solvent is None) != (config.solvent_model is None):
        raise ValueError("solvent and solvent_model must be provided together")
    if config.method not in {"gfn1", "gfn2"}:
        raise ValueError("method must be gfn1 or gfn2")
    if config.interpolation not in {"linear", "idpp"}:
        raise ValueError("interpolation must be linear or idpp")
    if not -100 <= config.charge <= 100 or not 0 <= config.uhf <= 100:
        raise ValueError("charge or uhf is outside the supported range")
    if config.solvent is not None and _SOLVENT.fullmatch(config.solvent) is None:
        raise ValueError("solvent must be a safe xTB solvent name")
    for value, label, allow_zero in (
        (config.accuracy, "accuracy", False),
        (config.electronic_temperature, "electronic_temperature", True),
    ):
        if value is not None and (
            not math.isfinite(value)
            or value < 0.0
            or (value == 0.0 and not allow_zero)
            or (label == "accuracy" and value > 100.0)
            or (label == "electronic_temperature" and value > 1_000_000.0)
        ):
            raise ValueError(f"{label} must be finite and non-negative")


def _read_gradient(path: Path, atom_count: int) -> np.ndarray:
    if not path.is_file():
        raise RuntimeError("xTB gradient calculation did not create gradient")
    blocks: list[list[list[float]]] = []
    current: list[list[float]] | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.lower() == "$grad":
            current = []
            continue
        if stripped.lower() == "$end":
            if current is not None:
                blocks.append(current)
            current = None
            continue
        if current is None:
            continue
        fields = stripped.split()
        if len(fields) != 3:
            continue
        try:
            triple = [_number(field) for field in fields]
        except ValueError:
            continue
        if all(math.isfinite(value) for value in triple):
            current.append(triple)
    if not blocks or len(blocks[-1]) < atom_count:
        raise RuntimeError("xTB gradient artifact contains no complete gradient block")
    gradient = np.asarray(blocks[-1][-atom_count:], dtype=float)
    if gradient.shape != (atom_count, 3):
        raise RuntimeError("xTB gradient artifact has an invalid shape")
    return gradient


def _write_path_xyz(path: Path, images: list[Atoms], energies_ev: list[float]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        for index, (image, energy_ev) in enumerate(zip(images, energies_ev)):
            handle.write(f"{len(image)}\n")
            handle.write(f"image: {index} energy_ev: {energy_ev:.15g}\n")
            for symbol, position in zip(image.get_chemical_symbols(), image.positions):
                handle.write(
                    f"{symbol} {position[0]:.12f} {position[1]:.12f} {position[2]:.12f}\n"
                )


def _parse_bool(value: str) -> bool:
    normalized = value.lower()
    if normalized not in {"true", "false"}:
        raise argparse.ArgumentTypeError("expected true or false")
    return normalized == "true"


def _number(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "e"))


if __name__ == "__main__":
    raise SystemExit(main())
