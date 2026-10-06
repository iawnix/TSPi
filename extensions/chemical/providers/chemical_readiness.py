"""Chemistry-owned runtime probes used by the generic compute readiness API."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any


def ase_neb_check_script() -> str:
    return r'''set -eo pipefail
activation=$1
python_executable=$2
xtb_executable=$3
gaussian_executable=${4:-}
if [[ -n "$activation" ]]; then source "$activation"; fi
if [[ -z "$xtb_executable" && -z "$gaussian_executable" ]]; then
  exit 1
fi
"$python_executable" -c 'import ase, numpy'
if [[ -n "$xtb_executable" ]]; then
  if [[ "$xtb_executable" == /* ]]; then
    test -x "$xtb_executable"
  else
    command -v -- "$xtb_executable" >/dev/null
  fi
  "$xtb_executable" --version >/dev/null 2>&1
fi
if [[ -n "$gaussian_executable" ]]; then
  if [[ "$gaussian_executable" == /* ]]; then
    test -x "$gaussian_executable"
  else
    command -v -- "$gaussian_executable" >/dev/null
  fi
fi
'''


def pyscf_check_script() -> str:
    return r'''set -eo pipefail
activation=$1
python_executable=$2
if [[ -n "$activation" ]]; then source "$activation"; fi
"$python_executable" -c '
import importlib.metadata
import json
import sys
import pyscf
import chemical_runtime
import geometric
import pyscf.dispersion as pyscf_dispersion
import numpy
import psutil
import yaml
from pyscf import dft, gto
from pyscf.scf import dispersion as scf_dispersion
mol = gto.M(atom="H 0 0 0; H 0 0 1.4", basis="sto-3g", verbose=0)
mol.build()
mf = dft.KS(mol, xc="CF22D")
if not scf_dispersion.check_disp(mf):
    raise RuntimeError("CF22D did not select its D3 dispersion correction")
if scf_dispersion.dftd3 is None:
    raise RuntimeError("PySCF cannot access the installed D3 dispersion implementation")
def module_info(module):
    return {
        "version": str(getattr(module, "__version__", "unknown")),
        "origin": str(getattr(module, "__file__", "unknown")),
    }
report = {
    "python": {"version": sys.version.split()[0], "executable": sys.executable},
    "modules": {
        "chemical_runtime": module_info(chemical_runtime),
        "pyscf": module_info(pyscf),
        "pyscf.dispersion": module_info(pyscf_dispersion),
        "geometric": module_info(geometric),
        "numpy": module_info(numpy),
        "psutil": module_info(psutil),
        "yaml": module_info(yaml),
    },
    "distributions": {
        "pyscf-dispersion": importlib.metadata.version("pyscf-dispersion"),
    },
}
print("TS_PYSCF_DOCTOR " + json.dumps(report, sort_keys=True))
'
'''


def parse_pyscf_doctor_report(output: str) -> dict[str, Any] | None:
    marker = "TS_PYSCF_DOCTOR "
    for line in output.splitlines():
        if line.startswith(marker):
            try:
                report = json.loads(line[len(marker):])
            except json.JSONDecodeError:
                return None
            return report if isinstance(report, dict) else None
    return None


def readiness_probe(backend: str, binding: Any) -> dict[str, Any] | None:
    """Return the extension-owned probe for a configured backend binding."""
    activation = getattr(binding, "activation_script", None) or ""
    environment = getattr(binding, "environment", {}) or {}
    command = getattr(binding, "command", ())
    executable = command[0] if command else ""
    if backend == "pyscf":
        return {
            "script": pyscf_check_script(),
            "args": [activation, executable],
            "parse": parse_pyscf_doctor_report,
        }
    if backend in {"ase_neb", "ase_neb_xtb"}:
        python_executable = environment.get("TSPI_RUNTIME_PYTHON", executable)
        xtb = environment.get("TS_ASE_NEB_XTB", "")
        if backend == "ase_neb_xtb" and not xtb:
            xtb = executable
        gaussian = environment.get("TS_ASE_NEB_GAUSSIAN", "")
        return {
            "script": ase_neb_check_script(),
            "args": [activation, python_executable, xtb, gaussian] if gaussian.strip() else [activation, python_executable, xtb],
            "parse": None,
        }
    return None


def bridge_environment(backend: str, kind: str, activated_environment: dict[str, str]) -> dict[str, str]:
    """Add extension runtime imports to the Host bridge environment."""
    if backend != "pyscf" or kind != "local":
        return activated_environment
    kernel_root = str(__import__("pathlib").Path(__file__).resolve().parents[3] / "packages" / "tspi-runtime")
    inherited = activated_environment.get("PYTHONPATH") or os.environ.get("PYTHONPATH", "")
    return {**activated_environment, "PYTHONPATH": os.pathsep.join(v for v in (kernel_root, inherited) if v)}


def bridge_readiness(backend: str, command: list[str], environment: dict[str, str], base: dict[str, Any]) -> dict[str, Any]:
    """Probe imports required by extension runners after binding resolution."""
    if backend != "pyscf" or not command:
        return base
    checks = list(base.get("checks", []))
    probe = (
        "import importlib, importlib.metadata; import pyscf; "
        "import pyscf.geomopt.geometric_solver; importlib.import_module('pyscf.dispersion'); "
        "importlib.metadata.version('pyscf-dispersion'); import chemical_runtime.backends.pyscf_runner"
    )
    try:
        completed = subprocess.run(
            [command[0], *command[1:], "-c", probe], check=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, **environment}, timeout=20,
        )
    except Exception as exc:
        return {"state": "unavailable", "checks": checks + [{"name": "runtime_imports", "state": "failed"}], "reason": f"PySCF runtime probe failed: {exc}"}
    if completed.returncode != 0:
        diagnostic = completed.stderr.decode("utf-8", errors="replace").strip()
        return {"state": "unavailable", "checks": checks + [{"name": "runtime_imports", "state": "failed"}], "reason": "PySCF runtime imports unavailable" + (f": {diagnostic[-500:]}" if diagnostic else "")}
    return {"state": "ready", "checks": checks + [{"name": "runtime_imports", "state": "ready"}]}
