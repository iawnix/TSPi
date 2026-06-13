"""NEB configuration: parsing, normalization, validation, and node naming.

Reads JSON/TOML/YAML configs into a normalized dict, derives node ids and level
slugs, and validates a config without importing the chemistry stack (dependency
checks are opt-in via ``require_deps``).
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from transition_state_workflow.config.state_contract import TREE_SCHEMA
from transition_state_workflow.tool.ase_neb.coerce import as_mapping, as_positive_int
from transition_state_workflow.tool.ase_neb.constants import (
    CONFIG_VERSION,
    OPTIMIZER_NAMES,
    SUPPORTED_CALCULATORS,
    SUPPORTED_INTERPOLATION,
)
from transition_state_workflow.tool.ase_neb.errors import ConfigError
from transition_state_workflow.tool.ase_neb.gaussian_calc import (
    require_ase,
    require_gaussian_calculator,
    require_xtb,
)


@dataclass(frozen=True)
class ProjectContext:
    root: Path
    input_node_id: str
    neb_node_id: str
    input_node: Path
    neb_node: Path


def safe_slug(value: Any, default: str = "item") -> str:
    text = str(value).strip().lower()
    text = text.replace("+", "p").replace("*", "")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or default


def utc_timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def level_slug_from_calculator(calc_cfg: dict[str, Any]) -> str:
    calc_type = calc_cfg.get("type", "xtb")
    params = as_mapping(calc_cfg.get("params"), "calculator.params")
    if calc_type == "xtb":
        return safe_slug(calc_cfg.get("method") or params.get("method") or "gfn2xtb")
    if calc_type == "gaussian":
        parts = [
            params.get("method"),
            params.get("basis"),
            params.get("xc"),
            params.get("basisfile"),
        ]
        return safe_slug("_".join(str(part) for part in parts if part) or "gaussian")
    return safe_slug(calc_type)


def level_slug_from_gaussian_config(gaussian_cfg: dict[str, Any]) -> str:
    route = str(gaussian_cfg.get("route", ""))
    match = re.search(r"#\s*([A-Za-z0-9+\-.]+)\s*/\s*([A-Za-z0-9+\-().,]+)", route)
    if match:
        return safe_slug(f"{match.group(1)}_{match.group(2)}")
    return safe_slug(gaussian_cfg.get("level") or "gaussian")


def input_node_id() -> str:
    return "n000_input_check"


def neb_node_id(cfg: dict[str, Any]) -> str:
    calc = cfg["calculator"]
    parts = [
        "n010",
        "neb",
        calc["type"],
        level_slug_from_calculator(calc),
        cfg["interpolation"],
    ]
    if cfg["neb"].get("climb", False):
        parts.append("ci")
    node_suffix = cfg.get("project", {}).get("node_suffix")
    if node_suffix:
        parts.append(node_suffix)
    return "_".join(safe_slug(part) for part in parts)


def project_context(cfg: dict[str, Any]) -> ProjectContext:
    root = Path(str(cfg["output"]))
    input_id = input_node_id()
    neb_id = neb_node_id(cfg)
    return ProjectContext(
        root=root,
        input_node_id=input_id,
        neb_node_id=neb_id,
        input_node=root / "nodes" / input_id,
        neb_node=root / "nodes" / neb_id,
    )


def read_text_config(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
    elif suffix == ".toml":
        try:
            import tomllib
        except ModuleNotFoundError as exc:  # pragma: no cover - Python < 3.11
            raise ConfigError("TOML config needs Python 3.11+ tomllib") from exc
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    elif suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore[import-untyped]
        except ModuleNotFoundError as exc:
            raise ConfigError("YAML config needs PyYAML; use JSON or TOML otherwise") from exc
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        data = loaded if loaded is not None else {}
    else:
        raise ConfigError(f"unsupported config suffix: {path.suffix}")

    if not isinstance(data, dict):
        raise ConfigError("config root must be a mapping")
    return data


def normalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(raw)
    cfg.setdefault("version", CONFIG_VERSION)
    if cfg["version"] != CONFIG_VERSION:
        raise ConfigError(f"unsupported config version: {cfg['version']}")

    for key in ("reactant", "product"):
        if not isinstance(cfg.get(key), str) or not cfg[key].strip():
            raise ConfigError(f"{key} must be a non-empty path string")

    output = cfg.get("output", "neb_run")
    if not isinstance(output, str) or not output.strip():
        raise ConfigError("output must be a non-empty path string")
    cfg["output"] = output

    project = as_mapping(cfg.get("project"), "project")
    project.setdefault("system_slug", safe_slug(Path(output).name, "system"))
    project["system_slug"] = safe_slug(project["system_slug"], "system")
    project.setdefault("schema", TREE_SCHEMA)
    cfg["project"] = project

    images = as_positive_int(cfg.get("images", 7), "images")
    if images < 3:
        raise ConfigError("images must include endpoints; use at least 3")
    cfg["images"] = images

    interpolation = cfg.get("interpolation", "idpp")
    if interpolation not in SUPPORTED_INTERPOLATION:
        raise ConfigError(f"interpolation must be one of {sorted(SUPPORTED_INTERPOLATION)}")
    cfg["interpolation"] = interpolation

    neb = as_mapping(cfg.get("neb"), "neb")
    neb.setdefault("climb", False)
    neb.setdefault("k", 0.1)
    neb.setdefault("method", "improvedtangent")
    neb.setdefault("dynamic", False)
    neb.setdefault("remove_rotation_and_translation", False)
    cfg["neb"] = neb

    optimizer = as_mapping(cfg.get("optimizer"), "optimizer")
    optimizer.setdefault("name", "FIRE")
    optimizer.setdefault("fmax", 0.05)
    optimizer.setdefault("steps", 500)
    if optimizer["name"] not in OPTIMIZER_NAMES:
        raise ConfigError(f"optimizer.name must be one of {sorted(OPTIMIZER_NAMES)}")
    cfg["optimizer"] = optimizer

    calculator = as_mapping(cfg.get("calculator"), "calculator")
    calc_type = calculator.get("type", "xtb")
    if calc_type not in SUPPORTED_CALCULATORS:
        raise ConfigError(f"calculator.type must be one of {sorted(SUPPORTED_CALCULATORS)}")
    calculator["type"] = calc_type
    calculator.setdefault("params", {})
    calculator["params"] = as_mapping(calculator.get("params"), "calculator.params")
    calculator.setdefault("env", {})
    calculator["env"] = as_mapping(calculator.get("env"), "calculator.env")
    cfg["calculator"] = calculator

    candidate_selection = as_mapping(cfg.get("candidate_selection"), "candidate_selection")
    candidate_selection.setdefault("min_barrier_ev", 0.03)
    candidate_selection.setdefault("allow_endpoint_candidate", False)
    cfg["candidate_selection"] = candidate_selection

    endpoint_validation = as_mapping(cfg.get("endpoint_validation"), "endpoint_validation")
    endpoint_validation.setdefault("reactant_state", "reference_hypothesis")
    endpoint_validation.setdefault("product_state", "reference_hypothesis")
    endpoint_validation.setdefault("level", "")
    endpoint_validation.setdefault("evidence", "")
    cfg["endpoint_validation"] = endpoint_validation

    refinement = as_mapping(cfg.get("refinement"), "refinement")
    if refinement:
        refinement.setdefault("gaussian", {})
        refinement["gaussian"] = as_mapping(refinement.get("gaussian"), "refinement.gaussian")
    cfg["refinement"] = refinement
    return cfg


def resolve_config_paths(cfg: dict[str, Any], config_path: Path) -> dict[str, Any]:
    base = config_path.resolve().parent
    out = dict(cfg)
    for key in ("reactant", "product", "output"):
        value = Path(str(out[key]))
        out[key] = str(value if value.is_absolute() else base / value)
    calculator = as_mapping(out.get("calculator"), "calculator")
    for key in ("template_gjf", "tail_file"):
        if calculator.get(key):
            value = Path(str(calculator[key]))
            calculator[key] = str(value if value.is_absolute() else base / value)
    out["calculator"] = calculator
    return out


def validate_config(
    cfg: dict[str, Any],
    *,
    strict_files: bool = False,
    require_deps: bool = False,
) -> list[str]:
    warnings: list[str] = []
    output_name = Path(str(cfg["output"])).name
    if output_name != safe_slug(output_name):
        warnings.append(
            f"output directory name '{output_name}' is not normalized; generated child names are safe"
        )
    for key in ("reactant", "product"):
        path = Path(str(cfg[key]))
        if strict_files and not path.exists():
            raise ConfigError(f"{key} does not exist: {path}")

    calc_type = cfg["calculator"]["type"]
    if calc_type in {"gaussian", "gaussian_external"} and not cfg["calculator"].get("allow_neb", False):
        warnings.append(
            "Gaussian NEB is expensive; run requires --allow-gaussian-neb "
            "or calculator.allow_neb=true"
        )
    if calc_type == "gaussian_external" and not cfg["calculator"].get("route"):
        raise ConfigError("calculator.type=gaussian_external requires calculator.route")
    if calc_type == "gaussian_external" and "force" not in str(cfg["calculator"].get("route", "")).lower():
        raise ConfigError("calculator.type=gaussian_external route must include force")

    if cfg["interpolation"] == "idpp":
        warnings.append("IDPP interpolation requires ASE at runtime")

    if require_deps:
        require_ase()
        if calc_type == "xtb":
            require_xtb()
        elif calc_type == "gaussian":
            require_gaussian_calculator()
    return warnings


__all__ = [
    "ProjectContext",
    "safe_slug",
    "utc_timestamp",
    "level_slug_from_calculator",
    "level_slug_from_gaussian_config",
    "input_node_id",
    "neb_node_id",
    "project_context",
    "read_text_config",
    "normalize_config",
    "resolve_config_paths",
    "validate_config",
]
