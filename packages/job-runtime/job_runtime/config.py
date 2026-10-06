"""Load the installation job.toml into Job Runtime platforms."""
from __future__ import annotations

from pathlib import Path
import os
import tomllib
from typing import Any

from .local import LocalProcessPlatform
from .remote import TorqueSSHPlatform
from .platform import ExecutionPlatform


def load_job_config(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    with source.open("rb") as handle:
        value = tomllib.load(handle)
    if not isinstance(value, dict):
        raise ValueError("job config must be a TOML table")
    environments = value.get("environments")
    default = value.get("default_environment")
    if not isinstance(environments, dict) or not environments:
        raise ValueError("job config must define environments")
    if not isinstance(default, str) or default not in environments:
        raise ValueError("job config default_environment is invalid")
    for name, item in environments.items():
        if not isinstance(name, str) or not isinstance(item, dict) or item.get("kind") not in {"local", "remote"}:
            raise ValueError("job config environments must declare kind=local or kind=remote")
    return value


def platforms_from_config(path: str | Path | None = None) -> tuple[dict[str, ExecutionPlatform], str]:
    configured = path or os.environ.get("TS_JOB_CONFIG")
    if not configured:
        return {"local": LocalProcessPlatform()}, "local"
    value = load_job_config(configured)
    platforms: dict[str, ExecutionPlatform] = {}
    for name, environment in value["environments"].items():
        kind = environment["kind"]
        if kind == "local":
            platforms[name] = LocalProcessPlatform()
        else:
            platforms[name] = TorqueSSHPlatform(environment, platform_name=name)
    if "local" not in platforms:
        # A local target remains useful for doctor/probe even when the selected
        # installation only declares remote environments.
        platforms["local"] = LocalProcessPlatform()
    default = str(value["default_environment"])
    return platforms, default

