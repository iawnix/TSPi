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
    configured = path or os.environ.get("RESEARCH_AGENT_JOB_CONFIG")
    if not configured:
        raise ValueError("job_config_required: configure the installation job.toml explicitly")
    value = load_job_config(configured)
    platforms: dict[str, ExecutionPlatform] = {}
    for name, environment in value["environments"].items():
        kind = environment["kind"]
        if kind == "local":
            platforms[name] = LocalProcessPlatform(supervisor=environment.get("supervisor", "systemd"), platform_name=name)
        else:
            platforms[name] = TorqueSSHPlatform(environment, platform_name=name)
    default = str(value["default_environment"])
    return platforms, default
