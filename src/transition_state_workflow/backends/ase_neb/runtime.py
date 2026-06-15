"""ASE NEB calculator construction and optimizer runtime."""

from __future__ import annotations

import contextlib
import os
import shlex
from pathlib import Path
from typing import Any, Iterator

from transition_state_workflow.backends.ase import (
    import_ase_bits,
    require_gaussian_calculator,
    require_xtb,
)
from transition_state_workflow.backends.xtb import xtb_ase_calculator_params

from .contracts import AseNebConfigError, AseNebRuntimeRequest, ExternalGaussianNebRuntimeRequest
from .gaussian_external import (
    ExternalGaussianForceCalculator,
    extract_gaussian_tail_from_template,
    require_external_gaussian_force_route,
)
from .images import read_image_set, write_image_set
from .results import (
    evaluate_neb_candidate_quality,
    write_candidate_quality_artifacts,
    write_path_summary,
)


def create_calculator(calc_cfg: dict[str, Any], image_index: int, calc_root: Path) -> Any:
    calc_type = calc_cfg["type"]
    params = dict(calc_cfg.get("params", {}))
    calc_root.mkdir(parents=True, exist_ok=True)

    if calc_type == "xtb":
        require_xtb()
        from xtb.ase.calculator import XTB

        return XTB(**xtb_ase_calculator_params(calc_cfg))

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


def run_ase_neb_candidate_path(
    *,
    node_dir: Path,
    runtime: AseNebRuntimeRequest,
) -> dict[str, Any]:
    """Run a prepared endpoint-based ASE NEB path and write backend result artifacts."""

    cfg = runtime.cfg
    images = read_image_set(node_dir, "initial", int(cfg["images"]))
    attach_calculators(cfg, images, node_dir)
    neb = make_neb_object(cfg, images)

    bits = import_ase_bits()
    optimizer_name = runtime.optimizer_cfg["name"]
    try:
        optimizer_cls = bits["optimizers"][optimizer_name]
    except KeyError as exc:
        raise AseNebConfigError(f"unsupported ASE optimizer: {optimizer_name}") from exc

    (node_dir / "logs").mkdir(parents=True, exist_ok=True)
    opt = optimizer_cls(
        neb,
        trajectory=str(node_dir / "trajectories" / runtime.trajectory_name),
        logfile=str(node_dir / "logs" / runtime.logfile_name),
    )
    with temporary_env(runtime.env):
        optimizer_converged = bool(
            opt.run(
                fmax=float(runtime.optimizer_cfg["fmax"]),
                steps=int(runtime.optimizer_cfg["steps"]),
            )
        )

    write_image_set(images, node_dir, "final")
    summary = write_path_summary(node_dir, images, status="succeeded")
    summary["optimizer_converged"] = optimizer_converged
    summary["candidate_quality"] = evaluate_neb_candidate_quality(
        summary,
        cfg,
        optimizer_converged=optimizer_converged,
    )
    write_candidate_quality_artifacts(node_dir, summary)
    return summary


def run_external_gaussian_neb_continuation(
    *,
    node_dir: Path,
    images: list[Any],
    runtime: ExternalGaussianNebRuntimeRequest,
) -> dict[str, Any]:
    """Run ASE NEB using external Gaussian force calculators and write result artifacts."""

    require_external_gaussian_force_route(runtime.calculator_request.route)
    if len(images) < 2:
        raise AseNebConfigError("external Gaussian NEB continuation needs at least two images")
    write_image_set(images, node_dir, "initial")
    tail = runtime.calculator_request.tail()
    calc_root = node_dir / "calculators"
    for index, image in enumerate(images):
        image.calc = runtime.calculator_request.calculator(
            image_index=index,
            image_dir=calc_root / f"image_{index:03d}",
            tail=tail,
        )

    neb = make_neb_object({"neb": runtime.neb_cfg}, images)
    bits = import_ase_bits()
    optimizer_name = runtime.optimizer_cfg["name"]
    try:
        optimizer_cls = bits["optimizers"][optimizer_name]
    except KeyError as exc:
        raise AseNebConfigError(f"unsupported ASE optimizer: {optimizer_name}") from exc

    (node_dir / "logs").mkdir(parents=True, exist_ok=True)
    opt = optimizer_cls(
        neb,
        trajectory=str(node_dir / "trajectories" / "gaussian_external_neb.traj"),
        logfile=str(node_dir / "logs" / "gaussian_external_neb.log"),
    )
    optimizer_converged = bool(
        opt.run(
            fmax=float(runtime.optimizer_cfg["fmax"]),
            steps=int(runtime.optimizer_cfg["steps"]),
        )
    )
    write_image_set(images, node_dir, "final")
    summary = write_path_summary(node_dir, images, status="succeeded")
    summary["optimizer_converged"] = optimizer_converged
    summary["candidate_quality"] = evaluate_neb_candidate_quality(
        summary,
        runtime.quality_config(),
        optimizer_converged=optimizer_converged,
    )
    write_candidate_quality_artifacts(node_dir, summary)
    return summary


__all__ = [
    "create_calculator",
    "temporary_env",
    "make_neb_object",
    "attach_calculators",
    "run_ase_neb_candidate_path",
    "run_external_gaussian_neb_continuation",
]
