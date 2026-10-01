"""Live, read-only readiness for the same bindings used by Native compute.

No intents, jobs or Artifacts are created. Probes are cached only within one
request and share a time budget so a catalog query cannot multiply SSH waits.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from ts_agent.platforms import EnvironmentBroker, EnvironmentRequirement, load_config
from ts_agent.remote.client import SSHClient
from ts_agent.remote.diagnostics import ase_neb_check_script, backend_check_script, pyscf_check_script
from ts_agent.remote.errors import RemoteError
from ts_agent.remote.torque import parse_records
from ts_agent.runtime.env import configured_python

from .capabilities import CAPABILITY_REGISTRY


def calculation_readiness(
    *, capability_id: str | None = None, environment_id: str | None = None,
    execution_kind: str | None = None, config_path: str | Path | None = None,
) -> dict[str, Any]:
    for name, value in (("capability_id", capability_id), ("environment_id", environment_id)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"{name} must be a non-empty string")
    if execution_kind not in (None, "local", "remote"):
        raise ValueError("execution_kind must be local or remote")
    descriptors = [d for d in CAPABILITY_REGISTRY.descriptors() if capability_id is None or d.capability == capability_id]
    rows = []
    result = {"protocol_version": "compute_readiness_1", "readiness": rows}
    selectors = {k: v for k, v in {"environment_id": environment_id, "execution_kind": execution_kind}.items() if v is not None}
    if not descriptors:
        rows.append({"capability_id": capability_id, **selectors, "readiness": _failure("capability", "capability_not_found", "Capability is not registered")})
        return result
    try:
        config = load_config(config_path)
        selected = config.environment(environment_id, kind=execution_kind)
        broker = EnvironmentBroker(config)
    except (ValueError, OSError, RemoteError) as exc:
        for descriptor in descriptors:
            rows.append({"capability_id": descriptor.capability, "capability_version": descriptor.version, **selectors,
                         "readiness": _failure("environment", "environment_configuration_invalid", "Compute environment configuration is invalid")})
        return result
    probe = _Probe(selected)
    cache: dict[str, dict[str, Any]] = {}
    for descriptor in descriptors:
        row = {"capability_id": descriptor.capability, "capability_version": descriptor.version,
               "environment_id": selected.name, "execution_kind": selected.kind}
        # Match Native control's local ASE alias; remote ASE requires Python.
        providers = ("ase_neb_xtb", "ase_neb") if descriptor.backend == "ase_neb" and selected.kind == "local" else (descriptor.backend,)
        try:
            binding = broker.bind(EnvironmentRequirement(providers, kind=selected.kind), selected.name)
            row["binding_digest"] = binding.binding_digest
            if binding.provider not in cache:
                cache[binding.provider] = probe.backend(binding.provider, binding.to_backend_binding())
            row["readiness"] = deepcopy(cache[binding.provider])
        except (ValueError, OSError, RemoteError) as exc:
            row["readiness"] = _failure("backend_binding", "backend_not_configured", "Capability is not configured for the selected environment")
        rows.append(row)
    return result


def _failure(name: str, code: str, message: str, *, unknown: bool = False) -> dict[str, Any]:
    state = "unknown" if unknown else "unavailable"
    return {"state": state, "checks": [{"name": name, "state": "unknown" if unknown else "failed", "code": code, "message": message[:500]}], "reason": message[:500]}


class _Probe:
    def __init__(self, environment):
        self.environment = environment
        self.platform = environment.platform
        self.client = SSHClient(self.platform) if self.platform else None
        self.deadline = time.monotonic() + 45
        self.transport: dict[str, Any] | None = None
        self.queues: dict[str, dict[str, str]] = {}

    def _timeout(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("readiness probe budget exhausted")
        return min(remaining, 10, self.platform.command_timeout_seconds if self.platform else 10)

    def _script(self, script, args=()):
        if self.client:
            return self.client.run_script(script, args, check=False, timeout=self._timeout())
        return subprocess.run(["bash", "-c", script, "native-readiness", *args],
                              capture_output=True, text=True, check=False, timeout=self._timeout(), env=dict(os.environ))

    def _check(self, checks, name, code, message, action):
        try:
            completed = action()
            if completed.returncode != 0:
                checks.append({"name": name, "state": "failed", "code": code, "message": message})
                return None
        except (TimeoutError, subprocess.TimeoutExpired):
            checks.append({"name": name, "state": "unknown", "code": "probe_timeout", "message": f"{name} timed out; retry readiness"})
            return None
        except (OSError, RemoteError):
            # Raw subprocess errors can contain configured environment values.
            checks.append({"name": name, "state": "failed", "code": code, "message": message})
            return None
        checks.append({"name": name, "state": "ready"})
        return completed

    def _result(self, checks):
        failed = next((c for c in checks if c["state"] == "failed"), None)
        unknown = next((c for c in checks if c["state"] == "unknown"), None)
        result = {"state": "unavailable" if failed else "unknown" if unknown else "ready", "checks": checks,
                  "scope": "remote_login_host" if self.client else "local_host"}
        if failed or unknown:
            result["reason"] = (failed or unknown)["message"]
        result["limitations"] = ["Job-specific resources and scientific inputs are checked by Native preflight."]
        if self.client:
            result["limitations"].append("Login-host checks do not establish runtime availability on every compute node.")
        return result

    def _remote(self):
        checks = []
        if self._check(checks, "ssh", "remote_connection_failed", "SSH connection failed; check host, credentials and SSH configuration",
                       lambda: self.client.run(["true"], check=False, timeout=self._timeout())) is None:
            return self._result(checks)
        commands = self.platform.commands
        if self._check(checks, "scheduler_commands", "scheduler_commands_missing", "Configured qsub, qstat or qdel is unavailable",
                       lambda: self._script('set -e\nfor cmd in "$@"; do command -v -- "$cmd" >/dev/null; done\n', [commands.qsub, commands.qstat, commands.qdel])) is None:
            return self._result(checks)
        queues = self._check(checks, "scheduler", "scheduler_query_failed", "Torque queue query failed",
                             lambda: self.client.run([commands.qstat, "-Qf"], check=False, timeout=self._timeout()))
        if queues is None:
            return self._result(checks)
        try:
            self.queues = parse_records(queues.stdout, "Queue")
        except RemoteError:
            self.queues = {}
        if not self.queues:
            checks.append({"name": "queues", "state": "failed", "code": "scheduler_response_invalid", "message": "Torque returned no valid queue records"})
        self._check(checks, "remote_root", "remote_root_unavailable", "Remote workspace root is absent or not writable",
                    lambda: self.client.run(["test", "-d", self.platform.remote_root, "-a", "-w", self.platform.remote_root], check=False, timeout=self._timeout()))
        return self._result(checks)

    def backend(self, provider, binding):
        checks = [{"name": "backend_binding", "state": "ready"}]
        if self.client:
            if self.transport is None:
                self.transport = self._remote()
            checks.extend(deepcopy(self.transport["checks"]))
            if self.transport["state"] != "ready":
                return self._result(checks)
            remote_binding = self.platform.backends[provider]
            allowed = remote_binding.allowed_queues or self.platform.allowed_queues
            usable = [name for name in allowed if name in self.queues and all(str(self.queues[name].get(flag, "")).lower() == "true" for flag in ("enabled", "started"))]
            if not usable:
                checks.append({"name": "queues", "state": "failed", "code": "queue_unavailable", "message": "No allowed queue is both enabled and started"})
                return self._result(checks)
            checks.append({"name": "queues", "state": "ready", "available": usable})
            if remote_binding.requires_gpu:
                checks.append({"name": "resources", "state": "failed", "code": "gpu_resources_unsupported", "message": "The Torque adapter does not support GPU resource syntax"})
                return self._result(checks)
        # Match execution: configured variables precede the activation script.
        prefix = "".join(f"export {key}={shlex.quote(value)}\n" for key, value in sorted(binding.environment.items()))
        activation = binding.activation_script or ""
        if activation and self._check(checks, "activation", "activation_failed", "Backend activation script is unreadable or failed",
                                      lambda: self._script(prefix + 'set -e\ntest -r "$1"\nsource "$1" >/dev/null\n', [activation])) is None:
            return self._result(checks)
        if self._check(checks, "executable", "backend_executable_unavailable", "Backend executable is unavailable after activation",
                       lambda: self._script(prefix + backend_check_script(), [activation, binding.command[0]])) is None:
            return self._result(checks)
        if binding.scratch_root:
            self._check(checks, "scratch", "scratch_unavailable", "Configured scratch root is absent or not writable",
                        lambda: self._script('test -d "$1" -a -w "$1"', [binding.scratch_root]))
        if provider == "pyscf":
            self._check(checks, "runtime_dependencies", "backend_dependencies_unavailable", "PySCF/CF22D runtime dependencies are unavailable",
                        lambda: self._script(prefix + pyscf_check_script(), [activation, binding.command[0]]))
        elif provider in {"ase_neb", "ase_neb_xtb"}:
            python_executable = binding.command[0] if provider == "ase_neb" else self._local_runtime_python()
            calculator_binding = self.environment.backends.get("ase_neb_xtb")
            xtb_executable = binding.environment.get("TS_ASE_NEB_XTB")
            if not xtb_executable and calculator_binding is not None:
                xtb_executable = calculator_binding.command[0]
            if not xtb_executable and provider == "ase_neb_xtb":
                xtb_executable = binding.command[0]
            self._check(checks, "runtime_dependencies", "backend_dependencies_unavailable", "ASE NEB runner or calculator dependencies are unavailable",
                        lambda: self._script(prefix + ase_neb_check_script(), [activation, python_executable, xtb_executable, binding.environment.get("TS_ASE_NEB_GAUSSIAN", "")]))
        return self._result(checks)

    @staticmethod
    def _local_runtime_python() -> str:
        try:
            configured = configured_python()
        except (OSError, RuntimeError, ValueError):
            configured = None
        return str(configured) if configured is not None else sys.executable
