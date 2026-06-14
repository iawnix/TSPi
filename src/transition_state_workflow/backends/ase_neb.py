"""ASE-managed NEB backend primitives.

This module owns ASE runtime operations for NEB candidate generation:
image loading/interpolation, NEB object construction, calculator attachment,
external-Gaussian force evaluation, and backend-produced path artifacts. It
does not write TS-search workspace state; core orchestration owns node, tree,
evidence, report, and reflection updates.
"""

from __future__ import annotations

import contextlib
import csv
from dataclasses import dataclass
import json
import math
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterator

from transition_state_workflow.backends.ase import (
    import_ase_bits,
    require_ase,
    require_gaussian_calculator,
    require_xtb,
)
from transition_state_workflow.backends.gaussian import (
    parse_gaussian_energy_hartree,
    parse_gaussian_forces_hartree_per_bohr,
)
from transition_state_workflow.chem.mechanism import endpoint_readiness_summary
from transition_state_workflow.util.json_io import write_json_object


HARTREE_TO_EV = 27.211386245988
BOHR_TO_ANG = 0.529177210903
HARTREE_PER_BOHR_TO_EV_PER_ANG = HARTREE_TO_EV / BOHR_TO_ANG


class AseNebConfigError(ValueError):
    """Raised when ASE NEB backend input is invalid."""


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

    raise AseNebConfigError(f"unsupported calculator: {calc_type}")


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


def load_endpoint_images(cfg: dict[str, Any]) -> tuple[Any, Any]:
    bits = import_ase_bits()
    read = bits["read"]
    reactant = read(cfg["reactant"])
    product = read(cfg["product"])
    r_symbols = reactant.get_chemical_symbols()
    p_symbols = product.get_chemical_symbols()
    if r_symbols != p_symbols:
        raise AseNebConfigError("reactant/product atom order mismatch; map atoms first before running NEB")
    return reactant, product


def build_images_from_endpoints(cfg: dict[str, Any], reactant: Any, product: Any) -> list[Any]:
    bits = import_ase_bits()
    images = [reactant]
    images.extend(reactant.copy() for _ in range(cfg["images"] - 2))
    images.append(product)

    neb_cls = bits["NEB"]
    neb = neb_cls(images)
    if cfg["interpolation"] == "idpp":
        neb.interpolate(method="idpp")
    else:
        neb.interpolate()
    return images


def build_images(cfg: dict[str, Any]) -> list[Any]:
    reactant, product = load_endpoint_images(cfg)
    return build_images_from_endpoints(cfg, reactant, product)


def write_image_set(images: list[Any], node_dir: Path, prefix: str) -> None:
    bits = import_ase_bits()
    write = bits["write"]
    image_dir = node_dir / "images"
    traj_dir = node_dir / "trajectories"
    image_dir.mkdir(parents=True, exist_ok=True)
    traj_dir.mkdir(parents=True, exist_ok=True)
    for index, image in enumerate(images):
        write(image_dir / f"{prefix}_image_{index:02d}.xyz", image)
    write(traj_dir / f"{prefix}_path.xyz", images)


def natural_path_key(path: Path) -> list[Any]:
    key: list[Any] = []
    for part in re.split(r"(\d+)", path.name):
        key.append(int(part) if part.isdigit() else part.lower())
    return key


def check_image_consistency(images: list[Any], files: list[Path]) -> None:
    if len(images) < 2:
        raise AseNebConfigError("NEB continuation needs at least two images")
    ref_symbols = images[0].get_chemical_symbols()
    ref_n = len(images[0])
    for index, image in enumerate(images):
        if len(image) != ref_n:
            raise AseNebConfigError(
                f"image atom count mismatch at {files[index]}: " f"{len(image)} != {ref_n}"
            )
        if image.get_chemical_symbols() != ref_symbols:
            raise AseNebConfigError(
                f"image element/order mismatch at {files[index]}; "
                "all images must use identical atom order"
            )


def read_xyz_images_from_dir(xyz_dir: Path, pattern: str, *, index: Any = 0) -> tuple[list[Any], list[Path]]:
    bits = import_ase_bits()
    read = bits["read"]
    if not xyz_dir.is_dir():
        raise AseNebConfigError(f"xyz image directory not found: {xyz_dir}")
    files = sorted(xyz_dir.glob(pattern), key=natural_path_key)
    if len(files) < 2:
        raise AseNebConfigError(f"need at least 2 xyz images in {xyz_dir} matching {pattern}")
    images = [read(path, index=index) for path in files]
    check_image_consistency(images, files)
    return images, files


@dataclass(frozen=True)
class AseNebCandidateArtifact:
    """Metadata for the candidate geometry selected from a NEB path."""

    candidate_id: str
    source_image: int
    xyz: Path
    energy_ev: float
    relative_energy_ev: float

    def to_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "source_image": self.source_image,
            "source": "neb_maximum",
            "candidate_state": "candidate",
            "xyz": str(self.xyz),
            "energy_ev": self.energy_ev,
            "relative_energy_ev": self.relative_energy_ev,
            "note": "Candidate requires Gaussian TS/Freq and connectivity validation.",
        }


@dataclass(frozen=True)
class AseNebPathArtifacts:
    """Structured summary of artifacts produced by one ASE NEB run."""

    run_status: str
    image_count: int
    candidate: AseNebCandidateArtifact
    barrier_ev_relative_to_reactant: float
    reaction_energy_ev: float
    energies_csv: Path
    forces_csv: Path
    candidate_json: Path

    def to_summary_payload(self) -> dict[str, Any]:
        return {
            "run_status": self.run_status,
            "images": self.image_count,
            "candidate_id": self.candidate.candidate_id,
            "ts_candidate_index": self.candidate.source_image,
            "barrier_ev_relative_to_reactant": self.barrier_ev_relative_to_reactant,
            "reaction_energy_ev": self.reaction_energy_ev,
            "energies_csv": str(self.energies_csv),
            "forces_csv": str(self.forces_csv),
            "candidate_json": str(self.candidate_json),
            "ts_candidate_xyz": str(self.candidate.xyz),
            "note": "NEB maximum is a TS candidate, not a validated transition state.",
        }


def force_max(forces: Any) -> float:
    if forces is None:
        return math.nan
    max_force = 0.0
    for vector in forces:
        value = math.sqrt(sum(float(component) ** 2 for component in vector))
        max_force = max(max_force, value)
    return max_force


def collect_path_data(images: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, image in enumerate(images):
        energy = float(image.get_potential_energy())
        try:
            fmax = force_max(image.get_forces())
        except Exception:
            fmax = math.nan
        rows.append({"image": index, "energy_ev": energy, "fmax_ev_a": fmax})
    e0 = rows[0]["energy_ev"]
    for row in rows:
        row["relative_energy_ev"] = row["energy_ev"] - e0
    return rows


def write_json_artifact(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_object(path, payload)
    return path


def write_forces_table(node_dir: Path, images: list[Any]) -> Path:
    path = node_dir / "tables" / "forces.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["image", "atom_index", "symbol", "fx_ev_a", "fy_ev_a", "fz_ev_a"],
        )
        writer.writeheader()
        for image_index, image in enumerate(images):
            symbols = image.get_chemical_symbols()
            try:
                forces = image.get_forces()
            except Exception:
                forces = []
            for atom_index, vector in enumerate(forces):
                writer.writerow(
                    {
                        "image": image_index,
                        "atom_index": atom_index,
                        "symbol": symbols[atom_index],
                        "fx_ev_a": float(vector[0]),
                        "fy_ev_a": float(vector[1]),
                        "fz_ev_a": float(vector[2]),
                    }
                )
    return path


def write_path_summary(node_dir: Path, images: list[Any], *, status: str) -> dict[str, Any]:
    bits = import_ase_bits()
    write = bits["write"]
    rows = collect_path_data(images)
    tables_dir = node_dir / "tables"
    candidates_dir = node_dir / "candidates"
    trajectories_dir = node_dir / "trajectories"
    tables_dir.mkdir(parents=True, exist_ok=True)
    candidates_dir.mkdir(parents=True, exist_ok=True)
    trajectories_dir.mkdir(parents=True, exist_ok=True)
    energy_csv = tables_dir / "energies.csv"
    with energy_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["image", "energy_ev", "relative_energy_ev", "fmax_ev_a"],
        )
        writer.writeheader()
        writer.writerows(rows)

    ts_row = max(rows, key=lambda row: row["relative_energy_ev"])
    ts_index = int(ts_row["image"])
    candidate_id = "cand_001"
    candidate_xyz = candidates_dir / f"{candidate_id}_img{ts_index:02d}.xyz"
    candidate_json = candidates_dir / f"{candidate_id}.json"
    write(trajectories_dir / "final_path.xyz", images)
    write(candidate_xyz, images[ts_index])
    forces_csv = write_forces_table(node_dir, images)
    candidate = AseNebCandidateArtifact(
        candidate_id=candidate_id,
        source_image=ts_index,
        xyz=candidate_xyz,
        energy_ev=ts_row["energy_ev"],
        relative_energy_ev=ts_row["relative_energy_ev"],
    )
    write_json_artifact(candidate_json, candidate.to_payload())
    artifacts = AseNebPathArtifacts(
        run_status=status,
        image_count=len(images),
        candidate=candidate,
        barrier_ev_relative_to_reactant=ts_row["relative_energy_ev"],
        reaction_energy_ev=rows[-1]["relative_energy_ev"],
        energies_csv=energy_csv,
        forces_csv=forces_csv,
        candidate_json=candidate_json,
    )
    summary = artifacts.to_summary_payload()
    write_json_artifact(node_dir / "summary.json", summary)
    return summary


def write_candidate_quality_artifacts(node_dir: Path, summary: dict[str, Any]) -> None:
    """Write candidate-quality annotations into backend-owned result artifacts."""

    quality = summary.get("candidate_quality", {})
    candidate_json_value = summary.get("candidate_json")
    if candidate_json_value:
        candidate_json = Path(str(candidate_json_value))
        if candidate_json.is_file():
            candidate_data = json.loads(candidate_json.read_text(encoding="utf-8"))
            candidate_data["candidate_quality"] = quality
            candidate_data["candidate_state"] = (
                "candidate" if quality.get("accepted_for_promotion") else "rejected"
            )
            write_json_artifact(candidate_json, candidate_data)
    write_json_artifact(node_dir / "summary.json", summary)


def make_neb_object(cfg: dict[str, Any], images: list[Any]) -> Any:
    bits = import_ase_bits()
    neb_cfg = cfg["neb"]
    kwargs = {
        "climb": bool(neb_cfg.get("climb", False)),
        "k": neb_cfg.get("k", 0.1),
        "method": neb_cfg.get("method", "improvedtangent"),
        "remove_rotation_and_translation": bool(neb_cfg.get("remove_rotation_and_translation", False)),
    }
    if neb_cfg.get("dynamic", False):
        dyneb = bits["DyNEB"]
        if dyneb is None:
            raise AseNebConfigError("DyNEB requested but this ASE version does not provide it")
        return dyneb(images, **kwargs)
    return bits["NEB"](images, **kwargs)


def attach_calculators(cfg: dict[str, Any], images: list[Any], output: Path) -> None:
    calc_cfg = cfg["calculator"]
    calc_root = output / "calculators"
    for index, image in enumerate(images):
        image.calc = create_calculator(calc_cfg, index, calc_root)


def evaluate_neb_candidate_quality(
    summary: dict[str, Any],
    cfg: dict[str, Any],
    *,
    optimizer_converged: bool,
) -> dict[str, Any]:
    candidate_selection = cfg.get("candidate_selection", {})
    min_barrier = float(candidate_selection.get("min_barrier_ev", 0.03))
    allow_endpoint = bool(candidate_selection.get("allow_endpoint_candidate", False))
    image_count = int(summary["images"])
    ts_index = int(summary["ts_candidate_index"])
    barrier = float(summary["barrier_ev_relative_to_reactant"])
    reasons: list[str] = []
    failure_codes: list[str] = []
    endpoint_validation = endpoint_readiness_summary(cfg.get("endpoint_validation", {}))
    if not endpoint_validation["endpoint_minima_ready"]:
        reasons.append(
            "reactant/product endpoints are not declared as validated_minimum, lower_level_minimum, or constrained_reference"
        )
        failure_codes.append("endpoint_minima_missing")
    if not optimizer_converged:
        reasons.append("NEB optimizer did not report convergence within the configured step limit")
        failure_codes.append("neb_not_converged")
    if ts_index in {0, image_count - 1} and not allow_endpoint:
        reasons.append("maximum-energy image is an endpoint")
        failure_codes.append("neb_endpoint_candidate")
    if barrier < min_barrier:
        reasons.append(f"barrier {barrier:.6f} eV is below min_barrier_ev {min_barrier:.6f}")
        failure_codes.append("neb_no_barrier")
    accepted = not reasons
    failure_type = failure_codes[0] if failure_codes else None
    return {
        "accepted_for_promotion": accepted,
        "outcome_code": failure_type,
        "failure_codes": failure_codes,
        "reasons": reasons or ["internal non-endpoint maximum passed candidate gates"],
        "gates": {
            "optimizer_converged": optimizer_converged,
            "ts_candidate_not_endpoint": ts_index not in {0, image_count - 1} or allow_endpoint,
            "barrier_at_least_minimum": barrier >= min_barrier,
            "min_barrier_ev": min_barrier,
            "allow_endpoint_candidate": allow_endpoint,
            "endpoint_minima_ready": endpoint_validation["endpoint_minima_ready"],
            "endpoint_states": {
                "reactant": endpoint_validation["reactant_state"],
                "product": endpoint_validation["product_state"],
            },
        },
    }


__all__ = [
    "AseNebConfigError",
    "HARTREE_TO_EV",
    "BOHR_TO_ANG",
    "HARTREE_PER_BOHR_TO_EV_PER_ANG",
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
    "load_endpoint_images",
    "build_images_from_endpoints",
    "build_images",
    "write_image_set",
    "natural_path_key",
    "check_image_consistency",
    "read_xyz_images_from_dir",
    "AseNebCandidateArtifact",
    "AseNebPathArtifacts",
    "force_max",
    "collect_path_data",
    "write_json_artifact",
    "write_forces_table",
    "write_path_summary",
    "write_candidate_quality_artifacts",
    "make_neb_object",
    "attach_calculators",
    "evaluate_neb_candidate_quality",
]
