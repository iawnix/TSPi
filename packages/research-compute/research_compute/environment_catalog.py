"""Public read models for configured local and remote compute environments."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from tspi_foundation.io import sha256_json

from .platforms import EnvironmentBroker, EnvironmentConfigurationError, EnvironmentRequirement, load_config


def environment_catalog(*, detail: bool = False) -> dict[str, Any]:
    try:
        config = load_config()
    except EnvironmentConfigurationError as exc:
        return {
            "schema_version": "compute-environment-catalog/1",
            "configured": False,
            "detail": detail,
            "error": str(exc),
            "source": None,
            "source_digest": None,
            "catalog_digest": None,
            "default": None,
            "environments": [],
        }
    source_digest = _file_digest(config.source)
    environments = []
    for environment in sorted(config.environments.values(), key=lambda item: item.name):
        platform = environment.platform
        item: dict[str, Any] = {
            "name": environment.name,
            "kind": environment.kind,
            "default": environment.name == config.default_environment,
            "backends": sorted(environment.backends),
            "readiness": {"state": "configured", "backend_count": len(environment.backends)},
            "platform": {
                "kind": "ssh_torque",
                "ssh_host": platform.ssh_host,
                "scheduler": platform.scheduler,
                "remote_root": platform.remote_root,
                "allowed_queues": list(platform.allowed_queues),
                "max_nodes": platform.max_nodes,
            } if platform else {"kind": "local"},
        }
        if detail:
            broker = EnvironmentBroker(config)
            item["backends"] = {
                backend: broker.bind(EnvironmentRequirement((backend,), kind=environment.kind), environment.name).public()
                for backend in sorted(environment.backends)
            }
        else:
            item["platform"] = {"kind": "ssh_torque" if platform else "local"}
        item["identity_digest"] = sha256_json({
            "name": item["name"],
            "kind": item["kind"],
            "default": item["default"],
            "backends": sorted(environment.backends),
            "platform": item["platform"].get("kind"),
        })
        environments.append(item)
    return {
        "schema_version": "compute-environment-catalog/1",
        "configured": True,
        "detail": detail,
        "source": str(config.source),
        "source_digest": source_digest,
        "default": config.default_environment,
        "catalog_digest": sha256_json({"source_digest": source_digest, "environments": environments}),
        "environments": environments,
    }


def _file_digest(path: str | Path) -> str | None:
    try:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except (OSError, TypeError):
        return None
    return f"sha256:{digest}"
