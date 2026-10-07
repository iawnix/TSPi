"""Scientific binding readiness shared by preparation and installation.

The caller supplies the public Job configuration contract. This keeps backend
requirements in the chemical extension and the installer standard-library-only.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess


BACKENDS = {"pyscf": "cf22d", "xtb": "xtb", "gaussian": "gaussian"}


def resolve_backend(config, environment, backend, *, contract):
    binding = config["environments"][environment]["backends"][backend]
    python = contract.resolve_python(config, environment, backend)
    command = binding.get("command", [])
    command = [command] if isinstance(command, str) else command
    if backend == "pyscf":
        if command:
            raise ValueError("Remove the legacy pyscf.command interpreter; backends.pyscf.python is the sole Python binding")
    elif len(command) != 1:
        raise ValueError("xTB/Gaussian executable binding must contain one executable")
    return python, command, contract.resolve_submission(config, environment, backend)


def _run(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=90,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    if result.returncode:
        # Do not echo activated environment output or package URLs/credentials.
        raise ValueError("local binding probe failed; verify target Python dependencies and executable activation")
    return result.stdout


def _probe_local(python, binding, backend, *, contract):
    for field in ("conda_executable", "lock_ref"):
        if not Path(python[field]).is_file():
            raise ValueError(f"python.{field} does not exist: {python[field]}")
    lock = Path(python["lock_ref"])
    content = lock.read_bytes()
    if b"@EXPLICIT" not in content:
        raise ValueError("lock_ref must be an explicit Conda package lock (@EXPLICIT)")
    requirements = lock.with_suffix(".requirements.txt")
    pip_lock = requirements.read_bytes() if requirements.is_file() else b""
    prefix = Path(python["prefix"])
    receipt_path = prefix / "tspi-environment.json"
    if not receipt_path.is_file():
        raise ValueError("Python environment has no verified receipt; use install_job_environment.py")
    receipt = json.loads(receipt_path.read_text())
    digest = "sha256:" + hashlib.sha256(content + b"\0" + pip_lock).hexdigest()
    if receipt.get("lock_sha256") != digest or receipt.get("binding_sha256") != contract.binding_digest(python):
        raise ValueError("Python environment receipt does not match its lock/binding")
    exported = _run([python["conda_executable"], "list", "--explicit", "--prefix", str(prefix)])
    def packages(text):
        return {line.strip() for line in text.splitlines() if line.strip() and not line.startswith(("#", "@"))}
    if packages(exported) != packages(content.decode()):
        raise ValueError("Python environment does not match its explicit Conda lock")
    executable = binding.get("command", [])
    executable = executable if isinstance(executable, str) else next(iter(executable), "")
    probe = """import sys,json,shutil,importlib.metadata as m
from pathlib import Path
assert sys.version_info >= (3,11), 'Python >= 3.11 required'
assert Path(sys.prefix).resolve() == Path(sys.argv[1]).resolve(), 'wrong prefix'
for line in sys.argv[2].splitlines():
 if line.strip() and not line.startswith('#'):
  name,version=line.split()[0].split('==');assert m.version(name)==version, name
if sys.argv[3]: assert shutil.which(sys.argv[3]), 'backend executable unavailable'
if sys.argv[4]=='pyscf':
 sys.path.insert(0,sys.argv[5])
 from runner import _load_runtime
 _load_runtime()
print(json.dumps({'python':sys.executable,'ready':True}))
"""
    scripts = Path(__file__).resolve().parents[1] / "cf22d/scripts"
    argv = contract.python_command(python) + ["-c", probe, str(prefix), pip_lock.decode(), executable, backend, str(scripts)]
    activation = binding.get("activation_script")
    if activation:
        if not Path(activation).is_file():
            raise ValueError(f"activation script does not exist: {activation}")
        argv = ["bash", "-c", 'set -e\nsource ' + shlex.quote(activation) + '\nexec "$@"', "probe", *argv]
    _run(argv)
    return {"status": "local_ready", "lock_sha256": digest, "binding_sha256": contract.binding_digest(python)}


def check_environments(config, *, contract, probe_local=False):
    """Fail on unusable declared local/default science; report other remote gaps."""
    contract.validate_job_config(config)
    results = {}
    for name, target in config["environments"].items():
        results[name] = {}
        for backend, binding in target.get("backends", {}).items():
            if backend not in BACKENDS:
                results[name][backend] = {"status": "not_probed"}
                continue
            try:
                python, _, _ = resolve_backend(config, name, backend, contract=contract)
                result = {"status": "static_valid" if target["kind"] == "local" else "remote_not_probed"}
                if probe_local and target["kind"] == "local":
                    result = _probe_local(python, binding, backend, contract=contract)
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                if target["kind"] == "local" or name == config["default_environment"]:
                    raise ValueError(f"science_binding_not_ready: environments.{name}.backends.{backend}: {exc}") from exc
                result = {"status": "invalid", "error": str(exc)}
            results[name][backend] = result
    return results
