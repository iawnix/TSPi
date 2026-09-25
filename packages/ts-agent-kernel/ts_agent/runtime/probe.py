"""Executable scientific-runtime capability probe used by the installer."""

from __future__ import annotations

import argparse
import importlib.metadata
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from .env import (
    PYTHON_DISTRIBUTION,
    RUNTIME_PROBE_VERSION,
    _is_python_payload_path,
    payload_records_sha256,
)


def probe_runtime_capabilities(*, require_distribution: bool = True) -> dict[str, Any]:
    """Exercise the chemistry and rendering capabilities required by TSPi."""

    import numpy
    import rdkit
    from rdkit import Chem
    from rdkit.Chem import AllChem

    molecule = Chem.MolFromSmiles("CC")
    if molecule is None:
        raise RuntimeError("RDKit could not parse the probe SMILES")
    molecule = Chem.AddHs(molecule)
    parameters = AllChem.ETKDGv3()
    parameters.randomSeed = 61_453
    if AllChem.EmbedMolecule(molecule, parameters) != 0:
        raise RuntimeError("RDKit ETKDG probe embedding failed")
    if not AllChem.UFFHasAllMoleculeParams(molecule):
        raise RuntimeError("RDKit UFF parameters are unavailable for the probe molecule")
    if AllChem.UFFOptimizeMolecule(molecule, maxIters=200) != 0:
        raise RuntimeError("RDKit UFF probe optimization did not converge")
    render = _probe_render_capabilities()
    from ts_agent.analysis.engine import Inputs, evaluate
    analyzed = evaluate("reaction.parse", Inputs({}, {}), {
        "reaction_smiles": "CCl.[OH-]>>CO.[Cl-]", "multiplicities": {"reactants": [1, 1], "products": [1, 1]},
    })
    if analyzed["verdict"] != "valid":
        raise RuntimeError("molecular reaction analysis probe failed")
    from ase.thermochemistry import IdealGasThermo
    thermal = IdealGasThermo([], geometry="monatomic", potentialenergy=0, natoms=1).get_enthalpy(298.15, verbose=False)
    if not 0.06 < thermal < 0.07:
        raise RuntimeError("ASE thermal-model probe failed")

    return {
        "schema_version": RUNTIME_PROBE_VERSION,
        "ok": True,
        "python": {
            "version": sys.version.split()[0],
            "executable": str(Path(sys.executable).resolve()),
        },
        "distribution": _probe_distribution(required=require_distribution),
        "modules": {
            "numpy": {
                "version": str(numpy.__version__),
                "origin": str(Path(numpy.__file__).resolve()),
            },
            "rdkit": {
                "version": str(rdkit.__version__),
                "origin": str(Path(rdkit.__file__).resolve()),
            },
            "matplotlib": render["matplotlib"],
        },
        "commands": {"xyzrender": render["xyzrender"]},
        "capabilities": {
            "rdkit_smiles_parse": True,
            "rdkit_etkdg_embed": True,
            "rdkit_uff_optimize": True,
            "matplotlib_render": True,
            "xyzrender_cli": True,
            "reaction_analysis": True,
            "ase_thermochemistry": True,
        },
    }


def _probe_render_capabilities() -> dict[str, dict[str, Any]]:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(figsize=(1, 1), dpi=32)
    try:
        axes.plot((0, 1), (0, 1))
        axes.set_axis_off()
        output = io.BytesIO()
        figure.savefig(output, format="png")
        if not output.getvalue().startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("Matplotlib did not produce a valid PNG image")
    finally:
        plt.close(figure)

    executable_name = "xyzrender.exe" if os.name == "nt" else "xyzrender"
    candidates = (
        Path(sys.base_prefix) / ("Scripts" if os.name == "nt" else "bin") / executable_name,
        Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin") / executable_name,
    )
    executable = next(
        (
            path.resolve()
            for path in candidates
            if path.is_file() and os.access(path, os.X_OK)
        ),
        None,
    )
    if executable is None:
        raise RuntimeError("managed scientific runtime is missing the xyzrender executable")
    try:
        completed = subprocess.run(
            [str(executable), "--help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"xyzrender capability probe failed: {error}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        raise RuntimeError(f"xyzrender capability probe exited with status {completed.returncode}{suffix}")
    try:
        version = importlib.metadata.version("xyzrender")
    except importlib.metadata.PackageNotFoundError as error:
        raise RuntimeError("managed scientific runtime is missing the xyzrender distribution") from error
    return {
        "matplotlib": {
            "version": str(matplotlib.__version__),
            "origin": str(Path(matplotlib.__file__).resolve()),
        },
        "xyzrender": {
            "version": version,
            "path": str(executable),
        },
    }


def _probe_distribution(*, required: bool) -> dict[str, Any]:
    try:
        distribution = importlib.metadata.distribution(PYTHON_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError:
        if required:
            raise RuntimeError(
                f"managed runtime is missing Python distribution {PYTHON_DISTRIBUTION!r}"
            ) from None
        return {"name": PYTHON_DISTRIBUTION, "installed": False}

    files = distribution.files
    if files is None:
        if not required:
            return {"name": PYTHON_DISTRIBUTION, "installed": False}
        raise RuntimeError(f"Python distribution {PYTHON_DISTRIBUTION!r} has no file manifest")
    records: list[tuple[str, bytes]] = []
    for item in files:
        relative = PurePosixPath(str(item))
        if not _is_python_payload_path(relative):
            continue
        path = Path(distribution.locate_file(item)).resolve()
        if not path.is_file():
            raise RuntimeError(f"installed Python payload file is missing: {relative}")
        records.append((relative.as_posix(), path.read_bytes()))
    if not records:
        if not required:
            return {"name": PYTHON_DISTRIBUTION, "installed": False}
        raise RuntimeError(f"Python distribution {PYTHON_DISTRIBUTION!r} has no package payload")
    root = Path(distribution.locate_file("")).resolve()
    return {
        "name": PYTHON_DISTRIBUTION,
        "installed": True,
        "version": distribution.version,
        "root": str(root),
        "payload_sha256": payload_records_sha256(records),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ts_runtime.probe")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = probe_runtime_capabilities(require_distribution=True)
    except Exception as exc:
        result = {
            "schema_version": RUNTIME_PROBE_VERSION,
            "ok": False,
            "error": {"class": type(exc).__name__, "message": str(exc)},
        }
        stream = sys.stderr
        code = 1
    else:
        stream = sys.stdout
        code = 0
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True), file=stream)
    else:
        print("ok" if result["ok"] else result["error"]["message"], file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
