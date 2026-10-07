"""Load the installation job.toml into Job Runtime platforms."""
from __future__ import annotations

from pathlib import Path
import os
import tomllib
from typing import Any

from .local import LocalProcessPlatform
from .remote import TorqueSSHPlatform
from .platform import ExecutionPlatform


from .config_contract import load_job_config


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
    if "remote" not in platforms:
        remote_names = [
            name for name, environment in value["environments"].items()
            if isinstance(environment, dict) and environment.get("kind") == "remote"
        ]
        if remote_names:
            # ``remote`` is the stable public target used by generic workflow
            # requests; the configured environment name remains available for
            # explicit queue/cluster selection.
            platforms["remote"] = platforms[remote_names[0]]
    default = str(value["default_environment"])
    return platforms, default
