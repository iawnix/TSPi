"""Executable scientific-runtime capability probe used by the installer."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
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
        },
        "capabilities": {
            "rdkit_smiles_parse": True,
            "rdkit_etkdg_embed": True,
            "rdkit_uff_optimize": True,
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
