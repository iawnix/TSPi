#!/usr/bin/env python3
"""Emit a private JS capability bridge from the installation compute.toml.

The output is consumed only by the trusted App Server Host.  It intentionally
contains executable bindings and must never be returned through an Agent-facing
catalog or prompt.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from _bootstrap import bootstrap_python_package

bootstrap_python_package(ROOT)

from ts_agent.platforms import EnvironmentBroker, EnvironmentRequirement, load_config  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="research_agent_capability_bridge")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    try:
        result = bridge(Path(args.config).expanduser())
    except Exception as exc:  # Keep the private bridge diagnostic JSON-safe.
        print(json.dumps({
            "schema_version": "research_agent_compute_bridge/1",
            "ok": False,
            "error": str(exc),
        }, sort_keys=True))
        return 0
    print(json.dumps(result, sort_keys=True))
    return 0


def bridge(path: Path) -> dict[str, object]:
    config = load_config(path)
    broker = EnvironmentBroker(config)
    bindings: dict[str, dict[str, object]] = {}
    for provider, backend in (
        ("xtb_local", "xtb"),
        ("gaussian_local", "gaussian"),
        ("pyscf_local", "pyscf"),
    ):
        environment_bindings: dict[str, dict[str, object]] = {}
        for environment_name, environment_config in config.environments.items():
            if backend not in environment_config.backends:
                continue
            try:
                binding = broker.bind(
                    EnvironmentRequirement((backend,), kind=environment_config.kind),
                    environment=environment_name,
                    probe=environment_config.kind == "local",
                )
                private = binding.to_backend_binding()
                activated_environment = (
                    _activation_environment(private.activation_script)
                    if environment_config.kind == "local"
                    else {}
                )
                if backend == "pyscf" and environment_config.kind == "local":
                    activated_environment = _pyscf_environment(activated_environment)
                environment_bindings[environment_name] = _binding_document(
                    binding,
                    private,
                    activated_environment,
                    backend,
                )
            except Exception as exc:
                # Keep the environment visible to Host readiness even when a
                # local executable is unavailable or a remote transport is
                # deferred. The provider must inspect readiness before launch.
                environment_bindings[environment_name] = {
                    "available": False,
                    "backend": backend,
                    "environment_id": environment_name,
                    "environment_kind": environment_config.kind,
                    "error": str(exc),
                }
        try:
            # Capability registration is independent of transport kind. The
            # default environment may be local or remote; the selected
            # provider/transport adapter decides whether execution is ready.
            try:
                binding = broker.bind(EnvironmentRequirement((backend,), kind=None), probe=True)
            except Exception:
                # A default environment without this backend must not hide a
                # capability that is configured in another environment.
                fallback_name = next(
                    (name for name, item in environment_bindings.items() if item.get("available")),
                    None,
                )
                if fallback_name is None:
                    raise
                binding = broker.bind(
                    EnvironmentRequirement((backend,), kind=None),
                    environment=fallback_name,
                    probe=environment_bindings[fallback_name].get("environment_kind") == "local",
                )
            default_document = environment_bindings.get(binding.environment)
            if default_document is None or not default_document.get("available"):
                raise RuntimeError(default_document.get("error") if default_document else "default environment binding unavailable")
            readiness = binding.readiness.public()
            if backend == "pyscf" and binding.kind == "local":
                # Executable presence is not enough for the CF22D runner. It
                # imports geomeTRIC, pyscf-dispersion, and the installed
                # ts_agent runner at process start. Keep the provider in the
                # catalog while reporting those checks explicitly.
                readiness = _pyscf_runtime_readiness(
                    list(default_document["command"]),
                    {**default_document.get("environment", {}), **dict(binding.to_backend_binding().environment)},
                    readiness,
                )
        except Exception as exc:
            # Missing optional backends and broken activation profiles are
            # represented as unavailable rather than making a configured
            # xTB-only installation fail Gaussian use.
            bindings[provider] = {
                "available": False,
                "backend": backend,
                "error": str(exc),
                "environments": environment_bindings,
            }
            continue
        selected = dict(default_document)
        selected.update({
            "available": True,
            "backend": backend,
            "environment_id": binding.environment,
            "environment_kind": binding.kind,
            "binding_digest": binding.binding_digest,
            "readiness": readiness,
            "environments": environment_bindings,
        })
        bindings[provider] = selected
    local = [item for item in config.environments.values() if item.kind == "local"]
    return {
        "schema_version": "research_agent_compute_bridge/1",
        "ok": True,
        "config_path": str(config.source),
        "default_environment": config.default_environment,
        "local_environment_count": len(local),
        "bindings": bindings,
    }


def _pyscf_environment(activated_environment: dict[str, str]) -> dict[str, str]:
    """Add the checkout kernel to a local PySCF provider environment."""

    kernel_root = str(ROOT / "packages" / "ts-agent-kernel")
    inherited_pythonpath = activated_environment.get("PYTHONPATH") or os.environ.get("PYTHONPATH", "")
    return {
        **activated_environment,
        "PYTHONPATH": os.pathsep.join(value for value in (kernel_root, inherited_pythonpath) if value),
    }


def _binding_document(binding, private, activated_environment: dict[str, str], backend: str) -> dict[str, object]:
    """Serialize one Host-only environment binding for the JS bridge."""

    return {
        "available": True,
        "backend": backend,
        "environment_id": binding.environment,
        "environment_kind": binding.kind,
        "command": list(private.command),
        # Only activation changes and configured backend variables cross the
        # bridge; the inherited process environment stays Host-private.
        "environment": {**activated_environment, **dict(private.environment)},
        "binding_digest": binding.binding_digest,
        "readiness": binding.readiness.public(),
    }


def _pyscf_runtime_readiness(
    command: tuple[str, ...],
    environment: dict[str, str],
    base: dict[str, object],
) -> dict[str, object]:
    """Probe the package imports required by the CF22D runner.

    This is a non-destructive import-only probe. It deliberately does not run
    a calculation and therefore cannot be interpreted as scientific output.
    """

    checks = list(base.get("checks", []))
    if not command:
        return {"state": "unavailable", "checks": checks + [{"name": "runtime_imports", "state": "failed"}], "reason": "pyscf command binding is empty"}
    probe = (
        "import importlib, importlib.metadata; "
        "import pyscf; import pyscf.geomopt.geometric_solver; "
        "importlib.import_module('pyscf.dispersion'); "
        "importlib.metadata.version('pyscf-dispersion'); "
        "import ts_agent.backends.pyscf_runner"
    )
    executable = command[0]
    try:
        completed = subprocess.run(
            [executable, *command[1:], "-c", probe],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, **environment},
            timeout=20,
        )
    except Exception as exc:
        return {
            "state": "unavailable",
            "checks": checks + [{"name": "runtime_imports", "state": "failed"}],
            "reason": f"PySCF runtime probe failed: {exc}",
        }
    if completed.returncode != 0:
        diagnostic = completed.stderr.decode("utf-8", errors="replace").strip()
        return {
            "state": "unavailable",
            "checks": checks + [{"name": "runtime_imports", "state": "failed"}],
            "reason": "PySCF runtime is missing geomeTRIC, pyscf-dispersion, or ts_agent"
            + (f": {diagnostic[-500:]}" if diagnostic else ""),
        }
    return {"state": "ready", "checks": checks + [{"name": "runtime_imports", "state": "ready"}]}


def _activation_environment(script: str | None) -> dict[str, str]:
    """Evaluate one installation-owned activation script and capture its env.

    Provider processes are spawned with ``shell=False``.  Sourcing the script
    once in this trusted Host bridge preserves that invariant while allowing
    vendor profiles (notably Gaussian and xTB) to establish their runtime
    variables.  Only values that differ from the bridge's inherited process
    environment cross the boundary.
    """

    if not script:
        return {}
    script_path = Path(script).expanduser()
    if script_path.is_symlink() or not script_path.is_file() or not os.access(script_path, os.R_OK):
        raise RuntimeError(f"activation script is not a readable regular file: {script_path}")
    command = 'source "$1" >/dev/null && env -0'
    completed = subprocess.run(
        ["bash", "-c", command, "research-agent-capability-bridge", str(script_path)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(os.environ),
        timeout=15,
    )
    if completed.returncode != 0:
        diagnostic = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"activation script failed ({script_path})"
            + (f": {diagnostic[-1000:]}" if diagnostic else "")
        )
    values: dict[str, str] = {}
    for item in completed.stdout.split(b"\0"):
        if not item:
            continue
        key, separator, value = item.partition(b"=")
        if not separator:
            continue
        values[key.decode("utf-8", errors="strict")] = value.decode("utf-8", errors="strict")
    inherited = os.environ
    return {key: value for key, value in values.items() if inherited.get(key) != value}


if __name__ == "__main__":
    raise SystemExit(main())
