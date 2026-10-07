"""Public, standard-library-only contract for installation execution bindings."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tomllib


def validate_python(binding, label="python"):
    if not isinstance(binding, dict) or set(binding) != {"manager", "conda_executable", "prefix", "lock_ref"}:
        raise ValueError(f"{label} requires manager, conda_executable, prefix and lock_ref; migrate legacy Python strings")
    if binding["manager"] != "conda":
        raise ValueError(f"{label}.manager must be conda")
    for field in ("conda_executable", "prefix", "lock_ref"):
        if not isinstance(binding[field], str) or not binding[field].startswith("/") or "\n" in binding[field]:
            raise ValueError(f"{label}.{field} must be an absolute target path")
    if not isinstance(binding["lock_ref"], str) or not binding["lock_ref"].strip():
        raise ValueError(f"{label}.lock_ref must identify the installed dependency lock")
    return binding


def validate_job_config(value):
    environments = value.get("environments")
    if not isinstance(environments, dict) or not environments or value.get("default_environment") not in environments:
        raise ValueError("job config must define default_environment and at least one environment")
    for name, target in environments.items():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name):
            raise ValueError(f"invalid job environment name: {name!r}")
        if not isinstance(target, dict) or target.get("kind") not in {"local", "remote"}:
            raise ValueError(f"job environment {name!r} must declare kind=local or kind=remote")
        if "python" in target:
            validate_python(target["python"], f"environments.{name}.python")
        backends = target.get("backends", {})
        if not isinstance(backends, dict):
            raise ValueError(f"environments.{name}.backends must be a table")
        for backend, binding in backends.items():
            if not isinstance(binding, dict):
                raise ValueError(f"invalid backend binding: {backend}")
            if "python" in binding:
                validate_python(binding["python"], f"environments.{name}.backends.{backend}.python")
            command = binding.get("command")
            if command is not None:
                argv = [command] if isinstance(command, str) else command
                if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or not x.strip() for x in argv):
                    raise ValueError(f"backend {backend}.command must be a nonempty string or argv")
            elif "python" not in binding:
                raise ValueError(f"backend {backend} requires command or an explicit python binding")
            activation = binding.get("activation_script")
            if activation is not None and (not isinstance(activation, str) or not activation.startswith("/")):
                raise ValueError(f"backend {backend}.activation_script must be absolute")
    return value


def load_job_config(path):
    with Path(path).expanduser().open("rb") as handle:
        return validate_job_config(tomllib.load(handle))


def resolve_python(config, environment, backend):
    target = config["environments"][environment]
    binding = target.get("backends", {}).get(backend, {}).get("python", target.get("python"))
    if binding is None:
        raise ValueError(f"python_binding_missing: configure environments.{environment}.python or backends.{backend}.python as a Conda environment")
    return validate_python(binding)


def python_command(binding):
    validate_python(binding)
    # env -u applies before Conda itself; inherited host PYTHONPATH must not
    # contaminate either Conda or the selected target interpreter.
    return ["env", "-u", "PYTHONHOME", "-u", "PYTHONPATH", "PYTHONNOUSERSITE=1",
            binding["conda_executable"], "run", "--no-capture-output", "-p", binding["prefix"], "python"]


def binding_digest(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
