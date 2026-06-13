"""Lazy ASE/calculator loading and the external-Gaussian force calculator.

Chemistry-stack imports stay lazy so config validation and input generation work
on machines without ASE/xTB installed. This module owns calculator construction
(xTB, the ASE Gaussian calculator, and the external-Gaussian force calculator)
plus the Gaussian energy/force parsers those calculators rely on.
"""

from __future__ import annotations

import contextlib
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterator

from transition_state_workflow.tool.ase_neb.constants import (
    HARTREE_PER_BOHR_TO_EV_PER_ANG,
    HARTREE_TO_EV,
)
from transition_state_workflow.tool.ase_neb.errors import ConfigError


def require_ase() -> None:
    try:
        import ase  # noqa: F401
    except ModuleNotFoundError as exc:
        raise SystemExit("ASE is required for prepare/run; install ase first") from exc


def require_xtb() -> None:
    try:
        import xtb  # noqa: F401
    except ModuleNotFoundError as exc:
        raise SystemExit("xTB Python bindings are required for calculator.type=xtb") from exc


def require_gaussian_calculator() -> None:
    try:
        from ase.calculators.gaussian import Gaussian  # noqa: F401
    except ModuleNotFoundError as exc:
        raise SystemExit("ASE Gaussian calculator is required for calculator.type=gaussian") from exc


def import_ase_bits() -> dict[str, Any]:
    require_ase()
    from ase.io import read, write
    from ase.optimize import BFGS, FIRE, LBFGS, MDMin

    try:
        from ase.mep import DyNEB, NEB
    except ImportError:  # pragma: no cover - older ASE fallback
        from ase.neb import NEB  # type: ignore[no-redef]

        DyNEB = None

    return {
        "read": read,
        "write": write,
        "NEB": NEB,
        "DyNEB": DyNEB,
        "optimizers": {"FIRE": FIRE, "BFGS": BFGS, "LBFGS": LBFGS, "MDMin": MDMin},
    }


def parse_gaussian_energy_hartree(output_path: Path) -> float:
    scf_re = re.compile(
        r"SCF Done:\s+E\([^)]+\)\s+=\s+([-+]?\d+\.\d+(?:[DEde][-+]?\d+)?)"
    )
    energy = None
    with output_path.open("r", errors="ignore") as handle:
        for line in handle:
            match = scf_re.search(line)
            if match:
                energy = float(match.group(1).replace("D", "E").replace("d", "E"))
    if energy is None:
        raise RuntimeError(f"cannot find SCF Done energy in Gaussian output: {output_path}")
    return energy


def parse_gaussian_forces_hartree_per_bohr(output_path: Path, natoms: int) -> Any:
    import numpy as np

    lines = output_path.read_text(errors="ignore").splitlines()
    starts = [
        index
        for index, line in enumerate(lines)
        if "Forces (Hartrees/Bohr)" in line
    ]
    if not starts:
        raise RuntimeError(f"cannot find Gaussian force block: {output_path}")

    force_line_re = re.compile(
        r"^\s*\d+\s+\d+\s+"
        r"([-+]?\d+\.\d+(?:[DEde][-+]?\d+)?)\s+"
        r"([-+]?\d+\.\d+(?:[DEde][-+]?\d+)?)\s+"
        r"([-+]?\d+\.\d+(?:[DEde][-+]?\d+)?)"
    )
    data: list[list[float]] = []
    for line in lines[starts[-1] :]:
        match = force_line_re.match(line)
        if not match:
            continue
        data.append(
            [
                float(match.group(1).replace("D", "E").replace("d", "E")),
                float(match.group(2).replace("D", "E").replace("d", "E")),
                float(match.group(3).replace("D", "E").replace("d", "E")),
            ]
        )
        if len(data) == natoms:
            break
    if len(data) != natoms:
        raise RuntimeError(
            f"Gaussian force block incomplete in {output_path}: "
            f"got {len(data)} rows, expected {natoms}"
        )
    return np.array(data, dtype=float)


def extract_gaussian_tail_from_template(template_path: Path) -> str:
    if not template_path.is_file():
        raise ConfigError(f"Gaussian template not found: {template_path}")
    lines = template_path.read_text(errors="ignore").splitlines()
    charge_mult_re = re.compile(r"^\s*[-+]?\d+\s+[-+]?\d+\s*$")
    charge_mult_idx = None
    for index, line in enumerate(lines):
        if charge_mult_re.match(line):
            charge_mult_idx = index
            break
    if charge_mult_idx is None:
        raise ConfigError(f"cannot find charge/multiplicity line in template: {template_path}")
    coord_start = charge_mult_idx + 1
    coord_end = None
    for index in range(coord_start, len(lines)):
        if not lines[index].strip():
            coord_end = index
            break
    if coord_end is None:
        raise ConfigError(f"cannot find blank line after template coordinates: {template_path}")
    tail_lines = lines[coord_end + 1 :]
    while tail_lines and not tail_lines[0].strip():
        tail_lines = tail_lines[1:]
    tail = "\n".join(tail_lines).rstrip()
    if not tail:
        raise ConfigError(f"no post-coordinate Gaussian section found in template: {template_path}")
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
        lines: list[str] = [
            f"%chk={self.chk.name}",
        ]
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


def create_calculator(calc_cfg: dict[str, Any], image_index: int, calc_root: Path) -> Any:
    calc_type = calc_cfg["type"]
    params = dict(calc_cfg.get("params", {}))
    calc_root.mkdir(parents=True, exist_ok=True)

    if calc_type == "xtb":
        require_xtb()
        from xtb.ase.calculator import XTB

        params.setdefault("method", calc_cfg.get("method", "GFN2-xTB"))
        if "charge" in calc_cfg and "charge" not in params:
            params["charge"] = calc_cfg["charge"]
        if "uhf" in calc_cfg and "uhf" not in params:
            params["uhf"] = calc_cfg["uhf"]
        if "solvent" in calc_cfg and "solvent" not in params:
            params["solvent"] = calc_cfg["solvent"]
        return XTB(**params)

    if calc_type == "gaussian":
        require_gaussian_calculator()
        from ase.calculators.gaussian import Gaussian

        image_dir = calc_root / f"image_{image_index:02d}"
        image_dir.mkdir(parents=True, exist_ok=True)
        label = image_dir / "gaussian"
        params.setdefault("label", str(label))
        params.setdefault("chk", f"image_{image_index:02d}.chk")

        command = calc_cfg.get("command")
        executable = calc_cfg.get("executable")
        scratch_root = calc_cfg.get("scratch_root")
        if command is None and executable:
            if scratch_root:
                scratch = Path(str(scratch_root)) / f"image_{image_index:02d}"
                command = (
                    f"mkdir -p {shlex.quote(str(scratch))} && "
                    f"GAUSS_SCRDIR={shlex.quote(str(scratch))} "
                    f"{shlex.quote(str(executable))} < PREFIX.com > PREFIX.out && "
                    "ln -sf PREFIX.out PREFIX.log"
                )
            else:
                command = (
                    f"{shlex.quote(str(executable))} < PREFIX.com > PREFIX.out && "
                    "ln -sf PREFIX.out PREFIX.log"
                )
        if command:
            params.setdefault("command", command)
        return Gaussian(**params)

    if calc_type == "gaussian_external":
        tail = ""
        template = calc_cfg.get("template_gjf")
        if template:
            tail = extract_gaussian_tail_from_template(Path(str(template)))
        if calc_cfg.get("tail_file"):
            tail = Path(str(calc_cfg["tail_file"])).read_text(encoding="utf-8").rstrip() + "\n"
        return ExternalGaussianForceCalculator(
            image_index=image_index,
            image_dir=calc_root / f"image_{image_index:03d}",
            route=str(calc_cfg["route"]),
            charge=int(calc_cfg.get("charge", params.get("charge", 0))),
            multiplicity=int(calc_cfg.get("multiplicity", params.get("multiplicity", 1))),
            mem=calc_cfg.get("mem", params.get("mem")),
            nprocshared=calc_cfg.get("nprocshared", params.get("nprocshared")),
            tail=tail,
            command=str(calc_cfg.get("command") or calc_cfg.get("executable") or "g16"),
            require_normal_termination=bool(calc_cfg.get("require_normal_termination", True)),
            output_suffix=str(calc_cfg.get("output_suffix", ".out")),
        )

    raise ConfigError(f"unsupported calculator: {calc_type}")


@contextlib.contextmanager
def temporary_env(values: dict[str, Any]) -> Iterator[None]:
    old: dict[str, str | None] = {}
    for key, value in values.items():
        old[key] = os.environ.get(key)
        os.environ[key] = str(value)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


__all__ = [
    "require_ase",
    "require_xtb",
    "require_gaussian_calculator",
    "import_ase_bits",
    "parse_gaussian_energy_hartree",
    "parse_gaussian_forces_hartree_per_bohr",
    "extract_gaussian_tail_from_template",
    "ExternalGaussianForceCalculator",
    "create_calculator",
    "temporary_env",
]
