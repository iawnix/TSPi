"""Contracts and value objects for the ASE NEB backend."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


HARTREE_TO_EV = 27.211386245988
BOHR_TO_ANG = 0.529177210903
HARTREE_PER_BOHR_TO_EV_PER_ANG = HARTREE_TO_EV / BOHR_TO_ANG


class AseNebConfigError(ValueError):
    """Raised when ASE NEB backend input is invalid."""


@dataclass(frozen=True)
class ExternalGaussianCalculatorRequest:
    """Backend request for one external-Gaussian force-calculator family."""

    route: str
    charge: int
    multiplicity: int
    template_gjf: Path | None
    tail_file: Path | None
    command: str
    mem: str | None
    nprocshared: int | None
    require_normal_termination: bool
    output_suffix: str

    def tail(self) -> str:
        """Resolve the post-coordinate Gaussian section for generated inputs."""

        if self.tail_file:
            return self.tail_file.read_text(encoding="utf-8").rstrip() + "\n"
        if self.template_gjf:
            from .gaussian_external import extract_gaussian_tail_from_template

            return extract_gaussian_tail_from_template(self.template_gjf)
        return ""

    def calculator(
        self,
        *,
        image_index: int,
        image_dir: Path,
        tail: str | None = None,
    ) -> Any:
        """Build an external-Gaussian force calculator for one image."""

        from .gaussian_external import ExternalGaussianForceCalculator

        return ExternalGaussianForceCalculator(
            image_index=image_index,
            image_dir=image_dir,
            route=self.route,
            charge=self.charge,
            multiplicity=self.multiplicity,
            mem=self.mem,
            nprocshared=self.nprocshared,
            tail=self.tail() if tail is None else tail,
            command=self.command,
            require_normal_termination=self.require_normal_termination,
            output_suffix=self.output_suffix,
        )


@dataclass(frozen=True)
class ExternalGaussianNebRuntimeRequest:
    """Backend request for one ASE-managed external-Gaussian NEB run."""

    calculator_request: ExternalGaussianCalculatorRequest
    neb_cfg: dict[str, Any]
    optimizer_cfg: dict[str, Any]
    candidate_selection: dict[str, Any]
    endpoint_validation: dict[str, Any]

    def quality_config(self) -> dict[str, Any]:
        """Return the candidate-quality policy shape shared with normal NEB."""

        return {
            "candidate_selection": self.candidate_selection,
            "endpoint_validation": self.endpoint_validation,
        }


@dataclass(frozen=True)
class AseNebRuntimeRequest:
    """Backend request for one standard ASE-managed NEB candidate run."""

    cfg: dict[str, Any]
    trajectory_name: str = "neb.traj"
    logfile_name: str = "neb.log"

    @property
    def optimizer_cfg(self) -> dict[str, Any]:
        return self.cfg["optimizer"]

    @property
    def env(self) -> dict[str, Any]:
        return self.cfg["calculator"].get("env", {})


@dataclass(frozen=True)
class AseNebPreparationResult:
    """Endpoint/image artifacts produced while preparing one ASE NEB path."""

    reactant: Any
    product: Any
    images: list[Any]

    @property
    def initial_image_count(self) -> int:
        return len(self.images)


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


__all__ = [
    "AseNebConfigError",
    "HARTREE_TO_EV",
    "BOHR_TO_ANG",
    "HARTREE_PER_BOHR_TO_EV_PER_ANG",
    "AseNebRuntimeRequest",
    "AseNebPreparationResult",
    "ExternalGaussianCalculatorRequest",
    "ExternalGaussianNebRuntimeRequest",
    "AseNebCandidateArtifact",
    "AseNebPathArtifacts",
]
