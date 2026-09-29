from __future__ import annotations

import json
from pathlib import Path

import pytest

from ts_agent.platforms import (
    EnvironmentBroker,
    EnvironmentConfigurationError,
    EnvironmentRequirement,
    load_config,
)


def _config(tmp_path: Path) -> Path:
    ssh_config = tmp_path / "ssh_config"
    ssh_config.write_text("Host login.example\n  HostName login.example\n", encoding="utf-8")
    config = tmp_path / "compute.toml"
    config.write_text(
        f"""
default_environment = "local"

[environments.local]
kind = "local"

[environments.local.backends.openmm]
command = "/bin/true"
environment = {{ OPENMM_PLUGIN_DIR = "/opt/openmm/plugins" }}

[environments.remote]
kind = "remote"
ssh_config = "{ssh_config}"
ssh_host = "login.example"
remote_root = "/srv/tspi"
allowed_queues = ["batch"]
max_nodes = 1

[environments.remote.backends.openmm]
command = ["openmm"]
""",
        encoding="utf-8",
    )
    return config


def test_broker_public_binding_hides_installation_command(tmp_path: Path) -> None:
    broker = EnvironmentBroker(load_config(_config(tmp_path)))

    binding = broker.bind(EnvironmentRequirement(("openmm",)))
    public = binding.public()

    assert public["environment"] == "local"
    assert public["kind"] == "local"
    assert public["provider"] == "openmm"
    assert public["binding_digest"].startswith("sha256:")
    assert public["readiness"] == {
        "state": "configured",
        "checks": [{"name": "provider_binding", "state": "configured"}],
    }
    assert "command" not in json.dumps(public)
    assert "OPENMM_PLUGIN_DIR" not in json.dumps(public)
    assert binding.to_backend_binding().command == ("/bin/true",)


def test_broker_readiness_probe_is_explicit(tmp_path: Path) -> None:
    broker = EnvironmentBroker(load_config(_config(tmp_path)))

    ready = broker.readiness(EnvironmentRequirement(("openmm",)))
    assert ready.readiness.state == "ready"
    assert {check["name"] for check in ready.readiness.checks} == {
        "provider_binding",
        "executable",
    }


def test_broker_reports_missing_provider_without_fallback(tmp_path: Path) -> None:
    broker = EnvironmentBroker(load_config(_config(tmp_path)))

    with pytest.raises(EnvironmentConfigurationError, match="backend.amber"):
        broker.bind(EnvironmentRequirement(("amber",)))


def test_broker_preserves_remote_binding_without_local_probe(tmp_path: Path) -> None:
    broker = EnvironmentBroker(load_config(_config(tmp_path)))

    binding = broker.readiness(EnvironmentRequirement(("openmm",), kind="remote"), "remote")

    assert binding.public()["readiness"]["state"] == "unknown"
    assert {check["state"] for check in binding.readiness.checks} == {"configured", "deferred"}


def test_broker_resolves_remote_ssh_host_alias_to_canonical_environment(tmp_path: Path) -> None:
    broker = EnvironmentBroker(load_config(_config(tmp_path)))

    binding = broker.readiness(EnvironmentRequirement(("openmm",), kind="remote"), "login.example")

    assert binding.environment == "remote"
    assert binding.kind == "remote"
    assert binding.readiness.state == "unknown"
