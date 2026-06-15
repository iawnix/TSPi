"""xTB backend adapter and lightweight output parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from transition_state_workflow.backends.base import FilesystemBackendAdapter
from transition_state_workflow.backends.contracts import BackendInput, BackendOutput


XTB_KNOWN_ARTIFACT_NAMES = (
    "xtbopt.xyz",
    "xtb.trj",
    "xtbrestart",
    "charges",
    "wbo",
    "gradient",
    "hessian",
    "energy",
    "coord",
)
XTB_LOG_SUFFIXES = (".out", ".log")


@dataclass(frozen=True)
class XtbMethod:
    """Normalized xTB method naming for CLI and ASE calculator use."""

    label: str
    ase_method: str
    cli_flags: tuple[str, ...]


@dataclass(frozen=True)
class XtbCommandRequest:
    """Typed request for one direct xTB command-line run."""

    input_file: Path
    task: str = "singlepoint"
    executable: str = "xtb"
    method: str | int | None = None
    charge: int | str | None = None
    multiplicity: int | str | None = None
    uhf: int | str | None = None
    accuracy: float | str | None = None
    iterations: int | str | None = None
    electronic_temperature: float | str | None = None
    solvent: str | None = None
    solvent_model: str = "alpb"
    extra_args: tuple[str, ...] = ()


def normalize_xtb_method(value: str | int | None = None) -> XtbMethod:
    """Return stable xTB method labels and flags."""

    if value is None or str(value).strip() == "":
        raw = "gfn2"
    else:
        raw = str(value).strip().lower().replace("_", "-").replace(" ", "")
    aliases = {
        "0": ("GFN0-xTB", "GFN0-xTB", ("--gfn", "0")),
        "gfn0": ("GFN0-xTB", "GFN0-xTB", ("--gfn", "0")),
        "gfn0-xtb": ("GFN0-xTB", "GFN0-xTB", ("--gfn", "0")),
        "1": ("GFN1-xTB", "GFN1-xTB", ("--gfn", "1")),
        "gfn1": ("GFN1-xTB", "GFN1-xTB", ("--gfn", "1")),
        "gfn1-xtb": ("GFN1-xTB", "GFN1-xTB", ("--gfn", "1")),
        "2": ("GFN2-xTB", "GFN2-xTB", ("--gfn", "2")),
        "gfn2": ("GFN2-xTB", "GFN2-xTB", ("--gfn", "2")),
        "gfn2-xtb": ("GFN2-xTB", "GFN2-xTB", ("--gfn", "2")),
        "ff": ("GFN-FF", "GFN-FF", ("--gfnff",)),
        "gfnff": ("GFN-FF", "GFN-FF", ("--gfnff",)),
        "gfn-ff": ("GFN-FF", "GFN-FF", ("--gfnff",)),
    }
    try:
        label, ase_method, cli_flags = aliases[raw]
    except KeyError as exc:
        raise ValueError(f"unsupported xTB method: {value!r}") from exc
    return XtbMethod(label=label, ase_method=ase_method, cli_flags=cli_flags)


def normalize_xtb_charge(value: int | str | None) -> int:
    """Return an integer molecular charge for xTB."""

    if value is None or str(value).strip() == "":
        return 0
    return int(value)


def normalize_xtb_uhf(
    *,
    multiplicity: int | str | None = None,
    uhf: int | str | None = None,
    unpaired: int | str | None = None,
) -> int:
    """Return xTB unpaired-electron count from UHF or multiplicity fields."""

    if uhf is not None and str(uhf).strip() != "":
        value = int(uhf)
    elif unpaired is not None and str(unpaired).strip() != "":
        value = int(unpaired)
    elif multiplicity is not None and str(multiplicity).strip() != "":
        value = int(multiplicity) - 1
    else:
        value = 0
    if value < 0:
        raise ValueError("xTB UHF/unpaired electron count must be nonnegative")
    return value


def normalize_xtb_task(value: str | None) -> str:
    """Return the stable xTB task name used in metadata."""

    raw = (value or "singlepoint").strip().lower().replace("-", "_")
    aliases = {
        "sp": "singlepoint",
        "single": "singlepoint",
        "single_point": "singlepoint",
        "singlepoint": "singlepoint",
        "opt": "optimization",
        "optimize": "optimization",
        "optimization": "optimization",
    }
    try:
        return aliases[raw]
    except KeyError as exc:
        raise ValueError(f"unsupported xTB task: {value!r}") from exc


def xtb_ase_calculator_params(calc_cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Return normalized params for ``xtb.ase.calculator.XTB``."""

    params = dict(calc_cfg.get("params", {}))
    method_source = calc_cfg.get("method", params.get("method"))
    params["method"] = normalize_xtb_method(method_source).ase_method
    if "charge" in calc_cfg and "charge" not in params:
        params["charge"] = normalize_xtb_charge(calc_cfg.get("charge"))
    elif "charge" in params:
        params["charge"] = normalize_xtb_charge(params.get("charge"))
    if "uhf" in calc_cfg and "uhf" not in params:
        params["uhf"] = normalize_xtb_uhf(uhf=calc_cfg.get("uhf"))
    elif "unpaired" in calc_cfg and "uhf" not in params:
        params["uhf"] = normalize_xtb_uhf(unpaired=calc_cfg.get("unpaired"))
    elif "multiplicity" in calc_cfg and "uhf" not in params:
        params["uhf"] = normalize_xtb_uhf(multiplicity=calc_cfg.get("multiplicity"))
    elif "uhf" in params:
        params["uhf"] = normalize_xtb_uhf(uhf=params.get("uhf"))
    if "solvent" in calc_cfg and "solvent" not in params:
        params["solvent"] = calc_cfg["solvent"]
    return params


def build_xtb_cli_argv(request: XtbCommandRequest) -> tuple[str, ...]:
    """Build an argv-only xTB command without shell syntax."""

    method = normalize_xtb_method(request.method)
    task = normalize_xtb_task(request.task)
    charge = normalize_xtb_charge(request.charge)
    uhf = normalize_xtb_uhf(multiplicity=request.multiplicity, uhf=request.uhf)
    argv: list[str] = [request.executable, str(request.input_file), *method.cli_flags]
    if task == "optimization":
        argv.append("--opt")
    if charge:
        argv.extend(("--chrg", str(charge)))
    if uhf:
        argv.extend(("--uhf", str(uhf)))
    if request.accuracy is not None:
        argv.extend(("--acc", str(request.accuracy)))
    if request.iterations is not None:
        argv.extend(("--iterations", str(int(request.iterations))))
    if request.electronic_temperature is not None:
        argv.extend(("--etemp", str(request.electronic_temperature)))
    if request.solvent:
        solvent_model = request.solvent_model.strip().lower()
        if solvent_model not in {"alpb", "gbsa"}:
            raise ValueError(f"unsupported xTB solvent model: {request.solvent_model!r}")
        argv.extend((f"--{solvent_model}", request.solvent))
    argv.extend(request.extra_args)
    return tuple(argv)


def request_from_mapping(request: Mapping[str, Any]) -> XtbCommandRequest:
    """Create an :class:`XtbCommandRequest` from backend-neutral mapping fields."""

    input_value = (
        request.get("input_file")
        or request.get("input_path")
        or request.get("xyz")
        or request.get("structure")
    )
    if input_value is None:
        files = tuple(request.get("files", ()))
        if files:
            input_value = files[0]
    if input_value is None:
        raise ValueError("xTB backend request requires input_file, xyz, structure, or files[0]")
    return XtbCommandRequest(
        input_file=Path(str(input_value)),
        task=str(request.get("task", request.get("job", "singlepoint"))),
        executable=str(request.get("executable", "xtb")),
        method=request.get("method"),
        charge=request.get("charge"),
        multiplicity=request.get("multiplicity"),
        uhf=request.get("uhf", request.get("unpaired")),
        accuracy=request.get("accuracy", request.get("acc")),
        iterations=request.get("iterations", request.get("max_iterations")),
        electronic_temperature=request.get("electronic_temperature", request.get("etemp")),
        solvent=request.get("solvent"),
        solvent_model=str(request.get("solvent_model", "alpb")),
        extra_args=tuple(str(item) for item in request.get("extra_args", ())),
    )


def discover_xtb_artifacts(paths: Sequence[Path]) -> tuple[Path, ...]:
    """Return explicit and directory-discovered xTB artifacts in stable order."""

    discovered: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        normalized = path
        if normalized not in seen:
            seen.add(normalized)
            discovered.append(normalized)

    for path in paths:
        if path.is_dir():
            for name in XTB_KNOWN_ARTIFACT_NAMES:
                candidate = path / name
                if candidate.exists():
                    add(candidate)
            for candidate in sorted(path.iterdir()):
                lower_name = candidate.name.lower()
                if candidate.is_file() and (lower_name.startswith("xtb") or candidate.suffix.lower() in XTB_LOG_SUFFIXES):
                    add(candidate)
        else:
            add(path)
    return tuple(discovered)


def parse_xtb_output_text(text: str) -> dict[str, Any]:
    """Parse stable xTB energy and convergence signals from log text."""

    energy = None
    for pattern in (
        r"total\s+energy\s+([-+]?\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?)\s*(?:Eh|a\.u\.)?",
        r"TOTAL\s+ENERGY\s+([-+]?\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?)",
        r"\bE\(total\)\s*[=:]\s*([-+]?\d+(?:\.\d+)?(?:[EeDd][-+]?\d+)?)",
    ):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            energy = float(match.group(1).replace("D", "E").replace("d", "E"))
    lower_text = text.lower()
    scf_converged = None
    if "scf not converged" in lower_text or "scf does not converge" in lower_text:
        scf_converged = False
    elif "scf converged" in lower_text:
        scf_converged = True
    optimization_converged = None
    if "geometry optimization converged" in lower_text or "convergence criteria satisfied" in lower_text:
        optimization_converged = True
    elif (
        "geometry optimization failed" in lower_text
        or "geometry optimization not converged" in lower_text
        or "optimization did not converge" in lower_text
    ):
        optimization_converged = False
    normal_termination = "normal termination" in lower_text or "finished run" in lower_text
    return {
        "electronic_energy_hartree": energy,
        "scf_converged": scf_converged,
        "optimization_converged": optimization_converged,
        "normal_termination": normal_termination,
    }


def parse_xtb_artifacts(artifacts: Sequence[Path]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Collect xTB artifact metadata plus lightweight parsed log evidence."""

    artifact_list = tuple(artifacts)
    existing = tuple(path for path in artifact_list if path.exists())
    known_by_name = {path.name: str(path) for path in existing if path.name in XTB_KNOWN_ARTIFACT_NAMES}
    log_paths = tuple(
        path
        for path in existing
        if path.is_file() and (path.name.lower().startswith("xtb") or path.suffix.lower() in XTB_LOG_SUFFIXES)
    )
    parsed_logs: dict[str, Any] = {}
    diagnostics: list[str] = []
    for log_path in log_paths:
        parsed = parse_xtb_output_text(log_path.read_text(encoding="utf-8", errors="replace"))
        parsed_logs[str(log_path)] = parsed
        if parsed.get("scf_converged") is False:
            diagnostics.append("xtb_scf_not_converged")
        if parsed.get("optimization_converged") is False:
            diagnostics.append("xtb_optimization_not_converged")
    properties = {
        "artifact_count": len(artifact_list),
        "existing_artifacts": len(existing),
        "known_artifacts": known_by_name,
        "candidate_geometry": known_by_name.get("xtbopt.xyz"),
        "trajectory": known_by_name.get("xtb.trj"),
        "charges": known_by_name.get("charges"),
        "wbo": known_by_name.get("wbo"),
        "logs": tuple(str(path) for path in log_paths),
        "parsed_logs": parsed_logs,
    }
    return properties, tuple(dict.fromkeys(diagnostics))


class XtbBackendAdapter(FilesystemBackendAdapter):
    """Backend boundary for xTB input generation and output parsing."""

    name = "xtb"

    def prepare(self, request: Mapping[str, Any]) -> BackendInput:
        """Prepare a direct xTB command from backend-neutral fields."""

        metadata = request.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise ValueError("backend request metadata must be a mapping")
        command_request = request_from_mapping(request)
        method = normalize_xtb_method(command_request.method)
        task = normalize_xtb_task(command_request.task)
        charge = normalize_xtb_charge(command_request.charge)
        uhf = normalize_xtb_uhf(multiplicity=command_request.multiplicity, uhf=command_request.uhf)
        return BackendInput(
            backend=self.name,
            files=(command_request.input_file,),
            command_argv=build_xtb_cli_argv(command_request),
            metadata={
                **dict(metadata),
                "task": task,
                "method": method.label,
                "charge": charge,
                "uhf": uhf,
                "candidate_only": True,
            },
        )

    def parse(self, artifacts: tuple[Path, ...]) -> BackendOutput:
        """Parse xTB artifacts without making workflow-state decisions."""

        discovered = discover_xtb_artifacts(artifacts)
        properties, diagnostics = parse_xtb_artifacts(discovered)
        return BackendOutput(
            backend=self.name,
            artifacts=discovered,
            properties=properties,
            diagnostics=diagnostics,
        )


__all__ = [
    "XTB_KNOWN_ARTIFACT_NAMES",
    "XtbBackendAdapter",
    "XtbCommandRequest",
    "XtbMethod",
    "build_xtb_cli_argv",
    "discover_xtb_artifacts",
    "normalize_xtb_charge",
    "normalize_xtb_method",
    "normalize_xtb_task",
    "normalize_xtb_uhf",
    "parse_xtb_artifacts",
    "parse_xtb_output_text",
    "request_from_mapping",
    "xtb_ase_calculator_params",
]
