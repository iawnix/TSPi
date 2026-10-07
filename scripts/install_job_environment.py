#!/usr/bin/env python3
"""Create a versioned Conda binding from a target-local explicit lock file.

Run on the target host during installation/maintenance, never inside a research
Job. An existing environment is verified and never updated in place.
"""
import argparse
import hashlib
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

contract_path = Path(__file__).resolve().parents[1] / "packages/job-runtime/job_runtime/config_contract.py"
spec = importlib.util.spec_from_file_location("job_config_contract", contract_path)
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)
load_job_config, resolve_python = contract.load_job_config, contract.resolve_python
python_command, binding_digest = contract.python_command, contract.binding_digest


def install(binding, *, adopt=False):
    contract.validate_python(binding)
    prefix = Path(binding["prefix"])
    prefix.parent.mkdir(parents=True, exist_ok=True)
    # Serialize provisioning of a prefix, including verification and publication.
    with (prefix.parent / (prefix.name + ".install.lock")).open("a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        return _install_locked(binding, adopt=adopt)


def _install_locked(binding, *, adopt=False):
    lock = Path(binding["lock_ref"])
    content = lock.read_bytes()
    if b"@EXPLICIT" not in content:
        raise ValueError("lock_ref must be an explicit Conda package lock (@EXPLICIT)")
    requirements = lock.with_suffix(".requirements.txt")
    pip_lock = requirements.read_bytes() if requirements.is_file() else b""
    digest = "sha256:" + hashlib.sha256(content + b"\0" + pip_lock).hexdigest()
    prefix = Path(binding["prefix"])
    receipt = prefix / "tspi-environment.json"
    if prefix.exists():
        if not adopt and (not receipt.is_file() or json.loads(receipt.read_text()).get("lock_sha256") != digest):
            raise ValueError("existing prefix has no matching environment receipt; choose a new versioned prefix")
    else:
        subprocess.run([binding["conda_executable"], "create", "--yes", "--prefix", str(prefix), "--file", str(lock)], check=True)
        if pip_lock:
            subprocess.run(python_command(binding) + ["-m", "pip", "install", "--no-index", "--find-links", str(lock.with_suffix(".wheels")), "--require-hashes", "--no-deps", "-r", str(requirements)], check=True)
    if prefix.exists():
        exported = subprocess.run([binding["conda_executable"], "list", "--explicit", "--prefix", str(prefix)], check=True, capture_output=True, text=True).stdout
        packages = lambda text: {line.strip() for line in text.splitlines() if line.strip() and not line.startswith(("#", "@"))}
        if packages(exported) != packages(content.decode()):
            raise ValueError("existing environment does not match the explicit Conda lock")
    # Verify prefix and pinned pip versions before publishing the receipt.
    script = """import sys,json,re,importlib.metadata as m
from pathlib import Path
assert sys.version_info >= (3,11)
assert Path(sys.prefix).resolve() == Path(sys.argv[1]).resolve()
for line in sys.argv[2].splitlines():
 if line.strip() and not line.startswith('#'):
  name,version=line.split()[0].split('==');assert m.version(name)==version,(name,m.version(name),version)
print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,'version':sys.version}))
"""
    result = subprocess.run(python_command(binding) + ["-c", script, str(prefix), pip_lock.decode()], check=True, capture_output=True, text=True)
    pending = receipt.with_suffix(".tmp")
    pending.write_text(json.dumps({"lock_sha256": digest, "binding_sha256": binding_digest(binding), "python": json.loads(result.stdout)}, indent=2) + "\n")
    pending.replace(receipt)
    return json.loads(receipt.read_text())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--environment", required=True)
    p.add_argument("--backend", required=True)
    p.add_argument("--adopt", action="store_true", help="Verify an explicitly seeded/cloned environment against its exported locks before recording it")
    a = p.parse_args()
    print(json.dumps(install(resolve_python(load_job_config(a.config), a.environment, a.backend), adopt=a.adopt), indent=2))


if __name__ == "__main__":
    main()
