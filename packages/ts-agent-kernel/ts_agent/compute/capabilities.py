"""Self-describing calculation capability catalog.

The catalog is deliberately declarative.  A capability says what an executor
can accept and produce; it never says which capability should be selected for a
Claim.  Scientific strategy remains in the Root Agent and in the rationale of
an action request.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Final

from jsonschema import Draft202012Validator


@dataclass(frozen=True)
class CapabilityDescriptor:
    """The stable, machine-readable envelope for one executor capability."""

    capability: str
    version: str
    backend: str
    task_type: str
    input_roles: frozenset[str]
    output_roles: tuple[str, ...]
    effects: tuple[str, ...]
    parameter_schema: dict[str, Any]
    limits: dict[str, Any]
    parsers: tuple[str, ...]

    def public(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "version": self.version,
            "input_roles": sorted(self.input_roles),
            "output_roles": list(self.output_roles),
            "effects": list(self.effects),
            "parameter_schema": deepcopy(self.parameter_schema),
            "limits": deepcopy(self.limits),
            "parsers": list(self.parsers),
        }


class CapabilityGapError(ValueError):
    """A requested capability is not present in this package."""

    def __init__(self, requested: str, version: str | None = None) -> None:
        self.requested = requested
        self.version = version
        suffix = f"@{version}" if version else ""
        self.payload = {
            "status": "rejected",
            "reason": "capability_unavailable",
            "requested": f"{requested}{suffix}",
            "missing_capability": requested,
            "requested_version": version,
            "retryable": False,
        }
        super().__init__(f"capability unavailable: {requested}{suffix}")


_SCALAR_PARAMETER = {
    "oneOf": [
        {"type": "string", "maxLength": 4096},
        {"type": "number"},
        {"type": "boolean"},
    ]
}


def _parameters(*names: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {name: deepcopy(_SCALAR_PARAMETER) for name in names},
        "additionalProperties": False,
    }


def _ase_neb_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "calculator": {"enum": ["xtb_cli", "gaussian_cli"], "default": "xtb_cli"},
            "images": {"type": "integer", "minimum": 3, "maximum": 32, "default": 7},
            "fmax": {
                "type": "number",
                "exclusiveMinimum": 0,
                "maximum": 10,
                "default": 0.05,
            },
            "max_steps": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100_000,
                "default": 500,
            },
            "spring_constant": {
                "type": "number",
                "exclusiveMinimum": 0,
                "maximum": 10,
                "default": 0.1,
            },
            "interpolation": {"enum": ["linear", "idpp"], "default": "idpp"},
            "neb_method": {
                "enum": ["aseneb", "improvedtangent", "eb", "spline", "string"],
                "default": "aseneb",
            },
            "optimizer": {
                "enum": ["FIRE", "BFGS", "LBFGS", "MDMin"],
                "default": "FIRE",
            },
            "climb": {"type": "boolean", "default": False},
            "ci_neb": {"type": "boolean", "default": False},
            "ci_fmax": {
                "type": "number",
                "exclusiveMinimum": 0,
                "maximum": 10,
            },
            "remove_rotation_and_translation": {"type": "boolean", "default": True},
            "method": {"enum": ["gfn1", "gfn2"], "default": "gfn2"},
            "charge": {"type": "integer", "minimum": -100, "maximum": 100, "default": 0},
            "uhf": {"type": "integer", "minimum": 0, "maximum": 100, "default": 0},
            "accuracy": {"type": "number", "exclusiveMinimum": 0, "maximum": 100},
            "electronic_temperature": {"type": "number", "minimum": 0, "maximum": 1_000_000},
            "solvent_model": {"enum": ["alpb", "gbsa"]},
            "solvent": {
                "type": "string",
                "pattern": "^[A-Za-z][A-Za-z0-9_.-]{0,63}$",
            },
            "gaussian_route": {
                "type": "string",
                "minLength": 1,
                "maxLength": 512,
                "default": "#p HF/3-21G Force",
            },
            "gaussian_multiplicity": {"type": "integer", "minimum": 1, "maximum": 200, "default": 1},
            "gaussian_nproc": {"type": "integer", "minimum": 1, "maximum": 4096, "default": 1},
            "gaussian_mem": {
                "type": "string",
                "pattern": "^[1-9][0-9]*[mMgG][bBwW]$",
                "default": "1GB",
            },
        },
        "dependentRequired": {
            "solvent": ["solvent_model"],
            "solvent_model": ["solvent"],
        },
        "allOf": [
            {
                "if": {"required": ["ci_fmax"]},
                "then": {
                    "required": ["ci_neb"],
                    "properties": {"ci_neb": {"const": True}},
                },
            }
        ],
        "not": {
            "required": ["climb", "ci_neb"],
            "properties": {
                "climb": {"const": True},
                "ci_neb": {"const": True},
            },
        },
        "additionalProperties": False,
    }


def _pyscf_parameters(*, use_initial_hessian_default: bool = False) -> dict[str, Any]:
    """Bound scalar settings for the dedicated PySCF/CF22D runtime."""

    return {
        "type": "object",
        "properties": {
            "basis": {"type": "string", "minLength": 1, "maxLength": 128, "default": "def2-tzvp"},
            "charge": {"type": "integer", "minimum": -100, "maximum": 100, "default": 0},
            "spin": {"type": "integer", "minimum": 0, "maximum": 200, "default": 0},
            "unit": {"enum": ["angstrom", "bohr"], "default": "angstrom"},
            "verbose": {"type": "integer", "minimum": 0, "maximum": 9, "default": 4},
            "xc": {"enum": ["CF22D"], "default": "CF22D"},
            "grid_level": {"type": "integer", "minimum": 0, "maximum": 9, "default": 6},
            "conv_tol": {"type": "number", "exclusiveMinimum": 0, "maximum": 1, "default": 1.0e-10},
            "max_cycle": {"type": "integer", "minimum": 1, "maximum": 100_000, "default": 400},
            "max_steps": {"type": "integer", "minimum": 1, "maximum": 10_000, "default": 100},
            "threads": {"type": "integer", "minimum": 1, "maximum": 4096, "default": 1},
            "memory_mb": {"type": "integer", "minimum": 1, "maximum": 4_000_000, "default": 4000},
            "imaginary_threshold_cm": {
                "type": "number",
                "exclusiveMaximum": 0,
                "default": -20.0,
            },
            "temperature": {"type": "number", "minimum": 0, "maximum": 10_000, "default": 298.15},
            "pressure": {"type": "number", "exclusiveMinimum": 0, "maximum": 10_000_000, "default": 101325.0},
            "use_initial_hessian": {"type": "boolean", "default": use_initial_hessian_default},
        },
        "additionalProperties": False,
    }


def _descriptor(
    capability: str,
    backend: str,
    task_type: str,
    input_roles: frozenset[str],
    output_roles: tuple[str, ...],
    *,
    parser: str | None = None,
    parameter_schema: dict[str, Any] | None = None,
    effects: tuple[str, ...] = ("local_prepare", "local_compute", "local_parse", "remote_compute"),
    limits: dict[str, Any] | None = None,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability=capability,
        version="1",
        backend=backend,
        task_type=task_type,
        input_roles=input_roles,
        output_roles=output_roles,
        effects=effects,
        parameter_schema=parameter_schema or _parameters(),
        limits=limits or {},
        parsers=(parser,) if parser else (),
    )


# This is an executor registry, not a strategy table.  New scientific domains
# add a descriptor and an adapter; they do not edit a hypothesis dispatch map.
CAPABILITY_DESCRIPTORS: Final[tuple[CapabilityDescriptor, ...]] = (
    _descriptor("gaussian.sp", "gaussian", "sp", frozenset({"gjf"}), ("program_output", "energy"), parser="gaussian.output/2"),
    _descriptor("gaussian.opt", "gaussian", "opt", frozenset({"gjf"}), ("program_output", "optimized_geometry"), parser="gaussian.output/2"),
    _descriptor("gaussian.ts", "gaussian", "ts", frozenset({"gjf"}), ("program_output", "optimized_geometry"), parser="gaussian.output/2"),
    _descriptor("gaussian.freq", "gaussian", "freq", frozenset({"gjf"}), ("program_output", "frequencies"), parser="gaussian.output/2"),
    _descriptor("gaussian.opt_freq", "gaussian", "opt_freq", frozenset({"gjf"}), ("program_output", "optimized_geometry", "frequencies"), parser="gaussian.output/2"),
    _descriptor("gaussian.irc", "gaussian", "irc", frozenset({"gjf"}), ("program_output", "reaction_path"), parser="gaussian.irc/2"),
    _descriptor(
        "gaussian.scan",
        "gaussian",
        "scan",
        frozenset({"gjf"}),
        ("program_output", "scan_profile"),
        parser="gaussian.scan/1",
        parameter_schema=_parameters(),
        limits={"minimum_points": 2, "energy_unit": "hartree"},
    ),
    _descriptor(
        "xtb.sp", "xtb", "sp", frozenset({"xyz"}), ("program_output", "energy"),
        parser="xtb.artifacts/2",
        parameter_schema=_parameters("accuracy", "charge", "electronic_temperature", "method", "solvent", "solvent_model", "uhf"),
    ),
    _descriptor(
        "xtb.opt", "xtb", "opt", frozenset({"xyz"}), ("program_output", "optimized_geometry"),
        parser="xtb.artifacts/2",
        parameter_schema=_parameters("accuracy", "charge", "electronic_temperature", "method", "solvent", "solvent_model", "uhf", "max_cycles", "opt_level"),
    ),
    _descriptor(
        "xtb.freq", "xtb", "freq", frozenset({"xyz"}), ("program_output", "frequencies"),
        parser="xtb.artifacts/2",
        parameter_schema=_parameters("accuracy", "charge", "electronic_temperature", "method", "solvent", "solvent_model", "uhf"),
    ),
    _descriptor(
        "xtb.opt_freq", "xtb", "opt_freq", frozenset({"xyz"}), ("program_output", "optimized_geometry", "frequencies"),
        parser="xtb.artifacts/2",
        parameter_schema=_parameters("accuracy", "charge", "electronic_temperature", "method", "solvent", "solvent_model", "uhf", "max_cycles", "opt_level"),
    ),
    _descriptor(
        "xtb.scan", "xtb", "scan", frozenset({"xyz", "control"}), ("program_output", "scan_profile"),
        parser="xtb.artifacts/2",
        parameter_schema=_parameters("accuracy", "charge", "electronic_temperature", "method", "solvent", "solvent_model", "uhf", "max_cycles", "opt_level"),
    ),
    _descriptor(
        "xtb.md", "xtb", "md", frozenset({"xyz", "control"}), ("program_output", "trajectory"),
        parser="xtb.artifacts/2",
        parameter_schema=_parameters("accuracy", "charge", "electronic_temperature", "method", "solvent", "solvent_model", "uhf"),
    ),
    _descriptor(
        "crest.conformer_search", "crest", "conformer_search", frozenset({"xyz"}), ("program_output", "conformer_ensemble"),
        parser="crest.artifacts/2",
        parameter_schema=_parameters("charge", "method", "opt_level", "search_level", "solvent", "solvent_model", "threads", "uhf"),
    ),
    _descriptor(
        "ase.neb",
        "ase_neb",
        "neb",
        frozenset({"reactant", "product"}),
        ("program_output", "reaction_path", "trajectory", "run_summary"),
        parser="ase.neb/1",
        parameter_schema=_ase_neb_parameters(),
        limits={
            "max_images": 32,
            "calculators": ["xtb_cli", "gaussian_cli"],
            "neb_methods": ["aseneb", "improvedtangent", "eb", "spline", "string"],
            "optimizers": ["FIRE", "BFGS", "LBFGS", "MDMin"],
        },
    ),
    _descriptor(
        "pyscf.sp",
        "pyscf",
        "sp",
        frozenset({"xyz"}),
        ("program_output", "energy"),
        parser="pyscf.output/1",
        parameter_schema=_pyscf_parameters(),
        limits={"runtime": "dedicated_python", "default_xc": "CF22D"},
    ),
    _descriptor(
        "pyscf.opt",
        "pyscf",
        "opt",
        frozenset({"xyz"}),
        ("program_output", "optimized_geometry", "energy"),
        parser="pyscf.output/1",
        parameter_schema=_pyscf_parameters(),
        limits={"runtime": "dedicated_python", "default_xc": "CF22D"},
    ),
    _descriptor(
        "pyscf.ts",
        "pyscf",
        "ts",
        frozenset({"xyz"}),
        ("program_output", "optimized_geometry", "energy"),
        parser="pyscf.output/1",
        parameter_schema=_pyscf_parameters(use_initial_hessian_default=True),
        limits={"runtime": "dedicated_python", "default_xc": "CF22D"},
    ),
    _descriptor(
        "pyscf.freq",
        "pyscf",
        "freq",
        frozenset({"xyz"}),
        ("program_output", "frequencies"),
        parser="pyscf.output/1",
        parameter_schema=_pyscf_parameters(),
        limits={"runtime": "dedicated_python", "default_xc": "CF22D"},
    ),
    _descriptor(
        "pyscf.thermo",
        "pyscf",
        "thermo",
        frozenset({"xyz"}),
        ("program_output", "frequencies", "thermochemistry"),
        parser="pyscf.output/1",
        parameter_schema=_pyscf_parameters(),
        limits={"runtime": "dedicated_python", "default_xc": "CF22D"},
    ),
    _descriptor(
        "pyscf.opt_freq",
        "pyscf",
        "opt_freq",
        frozenset({"xyz"}),
        ("program_output", "optimized_geometry", "frequencies"),
        parser="pyscf.output/1",
        parameter_schema=_pyscf_parameters(),
        limits={"runtime": "dedicated_python", "default_xc": "CF22D"},
    ),
    _descriptor(
        "pyscf.ts_freq",
        "pyscf",
        "ts_freq",
        frozenset({"xyz"}),
        ("program_output", "optimized_geometry", "frequencies"),
        parser="pyscf.output/1",
        parameter_schema=_pyscf_parameters(use_initial_hessian_default=True),
        limits={"runtime": "dedicated_python", "default_xc": "CF22D"},
    ),
)

CAPABILITIES_BY_ID: Final[dict[str, CapabilityDescriptor]] = {
    item.capability: item for item in CAPABILITY_DESCRIPTORS
}
CAPABILITY_BY_BACKEND_TASK: Final[dict[tuple[str, str], CapabilityDescriptor]] = {
    (item.backend, item.task_type): item for item in CAPABILITY_DESCRIPTORS
}

# Private adapter metadata retained for the existing executor boundary.  It is
# derived from descriptors and cannot express a scientific preference.
BACKEND_TASK_INPUT_ROLES: Final[dict[str, dict[str, frozenset[str]]]] = {
    backend: {
        task: descriptor.input_roles
        for (candidate_backend, task), descriptor in CAPABILITY_BY_BACKEND_TASK.items()
        if candidate_backend == backend
    }
    for backend in sorted({item.backend for item in CAPABILITY_DESCRIPTORS})
}


def resolve_capability(capability: str, version: str = "1") -> CapabilityDescriptor:
    descriptor = CAPABILITIES_BY_ID.get(capability)
    if descriptor is None or descriptor.version != version:
        raise CapabilityGapError(capability, version)
    return descriptor


def capability_for_backend_task(backend: str, task_type: str) -> CapabilityDescriptor:
    descriptor = CAPABILITY_BY_BACKEND_TASK.get((backend, task_type))
    if descriptor is None:
        raise CapabilityGapError(f"{backend}.{task_type}")
    return descriptor


def validate_capability_parameters(
    descriptor: CapabilityDescriptor,
    parameters: Any,
) -> dict[str, Any]:
    """Validate a Root-authored parameter object against one descriptor."""

    if not isinstance(parameters, dict):
        raise ValueError("capability parameters must be an object")
    errors = sorted(
        Draft202012Validator(descriptor.parameter_schema).iter_errors(parameters),
        key=lambda error: tuple(str(part) for part in error.path),
    )
    if errors:
        details = []
        for error in errors[:3]:
            location = "$" + "".join(f"[{part!r}]" for part in error.path)
            details.append(f"{location}: {error.message}")
        raise ValueError(
            f"invalid parameters for capability {descriptor.capability}@{descriptor.version}; "
            + "; ".join(details)
        )
    return deepcopy(parameters)


def adapter_settings(parameters: dict[str, Any]) -> dict[str, str]:
    """Convert validated JSON scalars to the backend adapter string boundary."""

    settings: dict[str, str] = {}
    for name, value in parameters.items():
        if isinstance(value, bool):
            settings[name] = "true" if value else "false"
        else:
            settings[name] = str(value)
    return settings


def calculation_capabilities() -> dict[str, object]:
    """Return descriptors separately from environment readiness."""

    return {
        "schema_version": "ts-capability-catalog/1",
        "capabilities": [item.public() for item in CAPABILITY_DESCRIPTORS],
        "readiness": {
            "state": "not_probed",
            "meaning": (
                "Descriptor presence does not prove executable, environment, scheduler, "
                "or transport readiness; establish readiness separately with "
                "runtime checks or the installation remote readiness check."
            ),
        },
    }


def resolve_capability_result(capability: str, version: str = "1") -> dict[str, Any]:
    """Return one descriptor or a structured, side-effect-free capability gap."""

    try:
        descriptor = resolve_capability(capability, version)
    except CapabilityGapError as exc:
        return {"schema_version": "ts-capability-gap/1", "ok": False, **exc.payload}
    return {
        "schema_version": "ts-capability-resolution/1",
        "ok": True,
        "descriptor": descriptor.public(),
    }
