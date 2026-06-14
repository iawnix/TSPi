"""Shared ASE NEB workspace context and naming helpers."""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
from pathlib import Path
import re
from typing import Any


VALID_NODE_STATUSES = {
    "pending",
    "running",
    "succeeded",
    "failed",
    "ambiguous",
    "accepted",
    "closed",
}
ACTIVE_NODE_STATUSES = {"pending", "running", "ambiguous"}


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
    params = calc_cfg.get("params") if isinstance(calc_cfg.get("params"), dict) else {}
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


__all__ = [
    "ACTIVE_NODE_STATUSES",
    "ProjectContext",
    "VALID_NODE_STATUSES",
    "input_node_id",
    "level_slug_from_calculator",
    "level_slug_from_gaussian_config",
    "neb_node_id",
    "project_context",
    "safe_slug",
    "utc_timestamp",
]
