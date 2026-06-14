"""External-Gaussian force calculator support for ASE NEB."""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from transition_state_workflow.backends.gaussian import (
    parse_gaussian_energy_hartree,
    parse_gaussian_forces_hartree_per_bohr,
)

from .contracts import (
    HARTREE_PER_BOHR_TO_EV_PER_ANG,
    HARTREE_TO_EV,
    AseNebConfigError,
    ExternalGaussianCalculatorRequest,
)
from .images import write_image_set


def require_external_gaussian_force_route(route: str) -> None:
    """Validate that an external-Gaussian NEB route requests forces."""

    if "force" not in route.lower():
        raise AseNebConfigError("external Gaussian NEB route must include force")


def extract_gaussian_tail_from_template(template_path: Path) -> str:
    if not template_path.is_file():
        raise AseNebConfigError(f"Gaussian template not found: {template_path}")
    lines = template_path.read_text(errors="ignore").splitlines()
    charge_mult_re = re.compile(r"^\s*[-+]?\d+\s+[-+]?\d+\s*$")
    charge_mult_idx = None
    for index, line in enumerate(lines):
        if charge_mult_re.match(line):
            charge_mult_idx = index
            break
    if charge_mult_idx is None:
        raise AseNebConfigError(f"cannot find charge/multiplicity line in template: {template_path}")
    coord_start = charge_mult_idx + 1
    coord_end = None
    for index in range(coord_start, len(lines)):
        if not lines[index].strip():
            coord_end = index
            break
    if coord_end is None:
        raise AseNebConfigError(f"cannot find blank line after template coordinates: {template_path}")
    tail_lines = lines[coord_end + 1 :]
    while tail_lines and not tail_lines[0].strip():
        tail_lines = tail_lines[1:]
    tail = "\n".join(tail_lines).rstrip()
    if not tail:
        raise AseNebConfigError(f"no post-coordinate Gaussian section found in template: {template_path}")
    return tail + "\n"


class ExternalGaussianForceCalculator:
    """ASE Calculator that runs an external Gaussian command for energy/forces."""

    implemented_properties = ["energy", "forces"]

    def __init__(
        self,
        *,
        image_index: int,
        image_dir: Path,
        route: str,
        charge: int,
        multiplicity: int,
        mem: str | None = None,
        nprocshared: int | None = None,
        tail: str = "",
        command: str = "g16",
        require_normal_termination: bool = True,
        output_suffix: str = ".out",
    ) -> None:
        from ase.calculators.calculator import Calculator

        class _Calculator(Calculator):
            implemented_properties = ["energy", "forces"]

        self._base = _Calculator()
        self.image_index = int(image_index)
        self.image_dir = image_dir
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self.route = str(route).strip()
        self.charge = int(charge)
        self.multiplicity = int(multiplicity)
        self.mem = mem
        self.nprocshared = nprocshared
        self.tail = tail.rstrip()
        self.command = str(command)
        self.require_normal_termination = bool(require_normal_termination)
        self.output_suffix = output_suffix if output_suffix.startswith(".") else f".{output_suffix}"
        self.base_name = f"gaussian_neb_image_{self.image_index:03d}"
        self.gjf = self.image_dir / f"{self.base_name}.gjf"
        self.out = self.image_dir / f"{self.base_name}{self.output_suffix}"
        self.chk = self.image_dir / f"{self.base_name}.chk"
        self._last_symbols: list[str] | None = None
        self._last_positions: Any = None

    @property
    def atoms(self) -> Any:
        return self._base.atoms

    @property
    def results(self) -> dict[str, Any]:
        return self._base.results

    def write_input(self, atoms: Any) -> None:
        lines: list[str] = [f"%chk={self.chk.name}"]
        if self.mem:
            lines.append(f"%mem={self.mem}")
        if self.nprocshared:
            lines.append(f"%nprocshared={int(self.nprocshared)}")
        lines.extend(
            [
                self.route,
                "",
                f"Gaussian external NEB force image {self.image_index:03d}",
                "",
                f"{self.charge} {self.multiplicity}",
            ]
        )
        for symbol, position in zip(atoms.get_chemical_symbols(), atoms.get_positions()):
            lines.append(
                f" {symbol:<2s}  {float(position[0]):16.10f}  "
                f"{float(position[1]):16.10f}  {float(position[2]):16.10f}"
            )
        lines.append("")
        if self.tail:
            lines.append(self.tail)
        lines.extend(["", ""])
        self.gjf.write_text("\n".join(lines), encoding="utf-8")

    def run_gaussian(self) -> None:
        cmd = shlex.split(self.command) if isinstance(self.command, str) else list(self.command)
        if not cmd:
            raise RuntimeError("Gaussian command is empty")
        with self.gjf.open("r", encoding="utf-8") as stdin, self.out.open("w", encoding="utf-8") as stdout:
            proc = subprocess.run(
                cmd,
                cwd=str(self.image_dir),
                stdin=stdin,
                stdout=stdout,
                stderr=subprocess.PIPE,
                text=True,
            )
        if proc.returncode != 0:
            raise RuntimeError(
                f"Gaussian failed for image {self.image_index:03d} with rc={proc.returncode}; "
                f"stderr={proc.stderr.strip()}; output={self.out}"
            )
        if not self.out.is_file():
            raise RuntimeError(f"Gaussian output not found: {self.out}")
        if self.require_normal_termination:
            tail = self.out.read_text(errors="ignore")[-8000:]
            if "Normal termination of Gaussian" not in tail:
                raise RuntimeError(
                    f"Gaussian did not terminate normally for image {self.image_index:03d}: {self.out}"
                )
        log_link = self.image_dir / f"{self.base_name}.log"
        if log_link != self.out:
            if log_link.exists() or log_link.is_symlink():
                log_link.unlink()
            try:
                log_link.symlink_to(self.out.name)
            except OSError:
                shutil.copyfile(self.out, log_link)

    def calculate(self, atoms=None, properties=("energy", "forces"), system_changes=None) -> None:
        from ase.calculators.calculator import all_changes

        self._base.calculate(atoms, properties, all_changes if system_changes is None else system_changes)
        atoms = self._base.atoms
        self.write_input(atoms)
        self.run_gaussian()
        energy = parse_gaussian_energy_hartree(self.out) * HARTREE_TO_EV
        forces = parse_gaussian_forces_hartree_per_bohr(self.out, len(atoms))
        self._base.results["energy"] = energy
        self._base.results["forces"] = forces * HARTREE_PER_BOHR_TO_EV_PER_ANG
        self._last_symbols = atoms.get_chemical_symbols()
        self._last_positions = atoms.get_positions().copy()

    def calculation_required(self, atoms: Any, properties: tuple[str, ...] = ("energy", "forces")) -> bool:
        import numpy as np

        if self._last_symbols != atoms.get_chemical_symbols():
            return True
        if self._last_positions is None:
            return True
        if not np.allclose(self._last_positions, atoms.get_positions(), rtol=0.0, atol=1.0e-12):
            return True
        return any(prop not in self._base.results for prop in properties)

    def get_potential_energy(self, atoms=None, force_consistent: bool = False) -> float:
        atoms = atoms if atoms is not None else self._base.atoms
        if atoms is None:
            raise RuntimeError("no atoms attached to external Gaussian calculator")
        if self.calculation_required(atoms, ("energy",)):
            self.calculate(atoms, ("energy", "forces"))
        return float(self._base.results["energy"])

    def get_forces(self, atoms=None) -> Any:
        atoms = atoms if atoms is not None else self._base.atoms
        if atoms is None:
            raise RuntimeError("no atoms attached to external Gaussian calculator")
        if self.calculation_required(atoms, ("forces",)):
            self.calculate(atoms, ("energy", "forces"))
        return self._base.results["forces"].copy()


def write_external_gaussian_dry_run_input(
    *,
    node_dir: Path,
    images: list[Any],
    calculator_request: ExternalGaussianCalculatorRequest,
) -> Path:
    """Write initial images and the first external-Gaussian input file."""

    require_external_gaussian_force_route(calculator_request.route)
    if not images:
        raise AseNebConfigError("external Gaussian NEB dry-run needs at least one image")
    write_image_set(images, node_dir, "initial")
    calc = calculator_request.calculator(
        image_index=0,
        image_dir=node_dir / "calculators" / "image_000",
        tail=calculator_request.tail(),
    )
    calc.write_input(images[0])
    return calc.gjf


__all__ = [
    "ExternalGaussianForceCalculator",
    "extract_gaussian_tail_from_template",
    "require_external_gaussian_force_route",
    "write_external_gaussian_dry_run_input",
]
