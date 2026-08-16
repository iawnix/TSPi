"""Executable scientific-runtime capability probe used by the installer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .env import RUNTIME_PROBE_VERSION


def probe_runtime_capabilities() -> dict[str, Any]:
    """Exercise the RDKit operations required by deterministic structure seeding."""

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

    return {
        "schema_version": RUNTIME_PROBE_VERSION,
        "ok": True,
        "python": {
            "version": sys.version.split()[0],
            "executable": str(Path(sys.executable).resolve()),
        },
        "modules": {
            "numpy": {
                "version": str(numpy.__version__),
                "origin": str(Path(numpy.__file__).resolve()),
            },
            "rdkit": {
                "version": str(rdkit.__version__),
                "origin": str(Path(rdkit.__file__).resolve()),
            },
        },
        "capabilities": {
            "rdkit_smiles_parse": True,
            "rdkit_etkdg_embed": True,
            "rdkit_uff_optimize": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ts_runtime.probe")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = probe_runtime_capabilities()
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
