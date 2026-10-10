"""Standalone target-side environment observation and execution guard (stdlib).

This file is staged with Python Jobs. It must not import the control plane or
require CoRAgent to be installed on a compute host. Diagnostics never echo package
URLs, activated environment output, or arbitrary import exceptions.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


class EnvironmentMismatch(ValueError):
    pass


def digest(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_identity(path):
    path = Path(path).resolve(strict=True)
    with path.open("rb") as stream:
        value = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path), "sha256": "sha256:" + value}


def package_lines(text):
    if "@EXPLICIT" not in text.splitlines():
        raise EnvironmentMismatch("environment_lock_invalid")
    packages = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(('#', '@')):
            continue
        url, _, checksum = line.partition('#')
        if checksum and not re.fullmatch(r'[0-9a-f]{64}', checksum):
            raise EnvironmentMismatch('environment_lock_invalid')
        if url in packages and packages[url] != checksum:
            raise EnvironmentMismatch('environment_lock_invalid')
        packages[url] = checksum
    return packages


def pip_packages(content):
    packages = {}
    for line in content.decode().replace('\\\n', ' ').splitlines():
        tokens = shlex.split(line, comments=True)
        if not tokens:
            continue
        match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s*;]+)', tokens[0])
        if (not match or len(tokens) < 2 or
                any(not re.fullmatch(r'--hash=sha256:[0-9a-f]{64}', token) for token in tokens[1:])):
            raise EnvironmentMismatch('environment_pip_lock_invalid')
        name = re.sub(r'[-_.]+', '-', match[1]).lower()
        if name in packages:
            raise EnvironmentMismatch('environment_pip_lock_invalid')
        packages[name] = match[2]
    return packages


def inspect_python(binding, requirements, command=(), *, require_receipt=True):
    if Path(sys.prefix).resolve() != Path(binding["prefix"]).resolve():
        raise EnvironmentMismatch("environment_python_prefix_mismatch")
    lock = Path(binding["lock_ref"])
    content = lock.read_bytes()
    pip_path = lock.with_suffix(".requirements.txt")
    pip_lock = pip_path.read_bytes() if pip_path.is_file() else b""
    lock_digest = "sha256:" + hashlib.sha256(content + b"\0" + pip_lock).hexdigest()
    exported = subprocess.run([binding["conda_executable"], "list", "--explicit", "--sha256", "--prefix", binding["prefix"]],
                              capture_output=True, text=True, timeout=90)
    expected = package_lines(content.decode())
    actual = package_lines(exported.stdout) if not exported.returncode else {}
    if actual.keys() != expected.keys() or any(checksum and checksum != actual[url] for url, checksum in expected.items()):
        raise EnvironmentMismatch("environment_conda_inventory_mismatch")
    for name, version in pip_packages(pip_lock).items():
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed = None
        if installed != version:
            raise EnvironmentMismatch("environment_pip_inventory_mismatch")
    inventory = sorted((re.sub(r"[-_.]+", "-", row.metadata["Name"]).lower(), row.version)
                       for row in importlib.metadata.distributions() if row.metadata["Name"])
    inventory_digest = digest(inventory)
    receipt_path = Path(binding["prefix"]) / "coragent-environment.json"
    receipt_digest = None
    if require_receipt:
        if not receipt_path.is_file():
            raise EnvironmentMismatch("environment_receipt_missing")
        receipt_bytes = receipt_path.read_bytes()
        receipt = json.loads(receipt_bytes)
        if receipt.get("lock_sha256") != lock_digest or receipt.get("binding_sha256") != digest(binding):
            raise EnvironmentMismatch("environment_receipt_mismatch")
        if receipt.get("inventory_sha256") != inventory_digest:
            raise EnvironmentMismatch("environment_receipt_inventory_mismatch")
        receipt_digest = "sha256:" + hashlib.sha256(receipt_bytes).hexdigest()
    versions = {}
    for name in requirements.get("packages", {}):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            raise EnvironmentMismatch("environment_dependency_missing") from None
    for name in requirements.get("imports", []):
        try:
            importlib.import_module(name)
        except Exception:
            raise EnvironmentMismatch("environment_import_failed") from None
    files = {"python": file_identity(sys.executable), "conda": file_identity(binding["conda_executable"])}
    if command:
        path = shutil.which(command[0])
        if path is None:
            raise EnvironmentMismatch("environment_executable_missing")
        files["executable"] = file_identity(path)
    return {"python_version": ".".join(map(str, sys.version_info[:3])), "prefix": str(Path(sys.prefix).resolve()),
            "lock_sha256": lock_digest, "binding_sha256": digest(binding), "inventory_sha256": inventory_digest,
            "receipt_sha256": receipt_digest, "packages": versions, "files": files}


def main():
    request = json.loads(sys.argv[1])
    expected = json.loads(sys.argv[2]) if len(sys.argv) > 2 else None
    try:
        observed = inspect_python(request["python"], request["requirements"], request.get("command", []),
                                  require_receipt=request.get("require_receipt", True))
        if expected is not None and observed != expected:
            raise EnvironmentMismatch("execution_environment_changed")
    except EnvironmentMismatch as exc:
        print("CORAGENT_ENVIRONMENT_ERROR=" + str(exc), file=sys.stderr)
        raise SystemExit(125) from None
    except Exception:
        print("CORAGENT_ENVIRONMENT_ERROR=environment_probe_failed", file=sys.stderr)
        raise SystemExit(125) from None
    if len(sys.argv) > 3:
        if sys.argv[3] != "--" or len(sys.argv) < 5:
            raise SystemExit(125)
        os.execv(sys.executable, [sys.executable, *sys.argv[4:]])
    print("CORAGENT_ENVIRONMENT=" + json.dumps(observed, sort_keys=True))


if __name__ == "__main__":
    main()
