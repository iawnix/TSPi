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
import shutil

contract_path = Path(__file__).resolve().parents[1] / "backend/src/research_agent/jobs/config_contract.py"
spec = importlib.util.spec_from_file_location("job_config_contract", contract_path)
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)
load_job_config, resolve_python = contract.load_job_config, contract.resolve_python
python_command, binding_digest = contract.python_command, contract.binding_digest
spec = importlib.util.spec_from_file_location('job_environment_probe', contract_path.with_name('environment_probe.py'))
probe_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe_module)


def install(binding, *, adopt=False, package_cache=None, offline=False):
    contract.validate_python(binding)
    prefix = Path(binding["prefix"])
    prefix.parent.mkdir(parents=True, exist_ok=True)
    # Serialize provisioning of a prefix, including verification and publication.
    with (prefix.parent / (prefix.name + ".install.lock")).open("a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        existed = prefix.exists()
        try:
            return _install_locked(binding, adopt=adopt, package_cache=package_cache, offline=offline)
        except BaseException:
            # Only remove a prefix created by this attempt. Existing installations
            # and explicit adoption are never rewritten or deleted on failure.
            if not existed and prefix.exists():
                shutil.rmtree(prefix)
            raise


def _install_locked(binding, *, adopt=False, package_cache=None, offline=False):
    lock = Path(binding["lock_ref"])
    content = lock.read_bytes()
    probe_module.package_lines(content.decode())
    requirements = lock.with_suffix(".requirements.txt")
    pip_lock = requirements.read_bytes() if requirements.is_file() else b""
    probe_module.pip_packages(pip_lock)
    digest = "sha256:" + hashlib.sha256(content + b"\0" + pip_lock).hexdigest()
    prefix = Path(binding["prefix"])
    receipt = prefix / "coragent-environment.json"
    previous = json.loads(receipt.read_text()) if receipt.is_file() else None
    if prefix.exists():
        if not adopt and (not previous or previous.get("lock_sha256") != digest
                          or previous.get("binding_sha256") != binding_digest(binding) or not previous.get("inventory_sha256")):
            raise ValueError("existing prefix has no matching environment receipt; choose a new versioned prefix")
    else:
        subprocess.run([binding["conda_executable"], "create", "--yes", "--prefix", str(prefix), "--file", str(lock),
                        *(['--offline'] if offline else [])], check=True)
        if pip_lock:
            cache = Path(package_cache) if package_cache else prefix.parent / '.pip-packages' / digest.removeprefix('sha256:')
            cache.mkdir(parents=True, exist_ok=True)
            pip = python_command(binding) + ['-m', 'pip']
            pip_env = {**os.environ, 'PIP_CACHE_DIR': str(cache / '.cache')}
            locked = ['--require-hashes', '--no-deps', '--no-build-isolation', '-r', str(requirements)]
            if not offline:
                subprocess.run(pip + ['download', '--dest', str(cache), *locked], check=True, env=pip_env)
            subprocess.run(pip + ['install', '--no-index', '--find-links', str(cache), *locked], check=True, env=pip_env)
    if pip_lock:
        subprocess.run(python_command(binding) + ['-m', 'pip', 'check'], check=True)
    # Installation and execution share the same target-side observation code.
    probe = contract_path.with_name("environment_probe.py").read_text()
    request = {"python": binding, "requirements": {}, "require_receipt": False}
    result = subprocess.run(python_command(binding) + ["-c", probe, json.dumps(request)],
                            capture_output=True, text=True, timeout=120)
    rows = [line.removeprefix("CORAGENT_ENVIRONMENT=") for line in result.stdout.splitlines() if line.startswith("CORAGENT_ENVIRONMENT=")]
    if result.returncode or len(rows) != 1:
        raise ValueError("environment verification failed: target prefix or package inventory does not match its lock")
    observed = json.loads(rows[0])
    if observed.get("lock_sha256") != digest or observed.get("binding_sha256") != binding_digest(binding):
        raise ValueError("environment lock or binding changed during installation verification")
    if previous and not adopt and previous["inventory_sha256"] != observed["inventory_sha256"]:
        raise ValueError("environment inventory changed; choose a new versioned prefix or explicitly reverify with --adopt")
    pending = receipt.with_suffix(".tmp")
    pending.write_text(json.dumps({"lock_sha256": digest, "binding_sha256": binding_digest(binding),
        "inventory_sha256": observed["inventory_sha256"], "python": {
            "executable": observed["files"]["python"]["path"], "prefix": observed["prefix"], "version": observed["python_version"]}}, indent=2) + "\n")
    pending.replace(receipt)
    return json.loads(receipt.read_text())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--environment", required=True)
    p.add_argument("--backend", required=True)
    p.add_argument("--adopt", action="store_true", help="Verify an explicitly seeded/cloned environment against its exported locks before recording it")
    p.add_argument('--package-cache', type=Path, help='Directory for pinned pip wheels/source archives; defaults below the environment parent')
    p.add_argument('--offline', action='store_true', help='Install only from the Conda and pip package caches')
    a = p.parse_args()
    print(json.dumps(install(resolve_python(load_job_config(a.config), a.environment, a.backend), adopt=a.adopt,
                             package_cache=a.package_cache, offline=a.offline), indent=2))


if __name__ == "__main__":
    main()
