"""Deterministic RDKit structure seeds for bounded calculation bootstrap."""

from __future__ import annotations

import hashlib
from typing import Any


SEED_SCHEMA_VERSION = "ts-structure-seed/1"
RANDOM_SEED = 61_453
MAX_ATOMS = 512
OPTIMIZATIONS = frozenset({"none", "uff"})


class StructureSeedError(ValueError):
    """A requested molecular seed cannot be generated deterministically."""


def generate_smiles_seed(
    smiles: str,
    *,
    charge: int,
    multiplicity: int,
    optimization: str,
) -> dict[str, Any]:
    """Generate one explicit-hydrogen XYZ seed with fixed ETKDG parameters."""

    import rdkit
    from rdkit import Chem
    from rdkit.Chem import AllChem, rdMolDescriptors

    source = _validate_smiles(smiles)
    if optimization not in OPTIMIZATIONS:
        raise StructureSeedError("structure seed optimization must be none or uff")
    molecule = Chem.MolFromSmiles(source)
    if molecule is None:
        raise StructureSeedError("RDKit could not parse the supplied SMILES")
    if len(Chem.GetMolFrags(molecule)) != 1:
        raise StructureSeedError("structure seed SMILES must describe one connected molecule")

    formal_charge = int(Chem.GetFormalCharge(molecule))
    if formal_charge != charge:
        raise StructureSeedError(
            f"SMILES formal charge {formal_charge} does not match declared charge {charge}"
        )
    canonical_smiles = Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)
    unassigned_stereo = [
        int(index)
        for index, assignment in Chem.FindMolChiralCenters(
            molecule,
            includeUnassigned=True,
            useLegacyImplementation=False,
        )
        if assignment == "?"
    ]
    molecule = Chem.AddHs(molecule)
    if not 1 <= molecule.GetNumAtoms() <= MAX_ATOMS:
        raise StructureSeedError(f"explicit-hydrogen atom count must be from 1 to {MAX_ATOMS}")
    electron_count = sum(atom.GetAtomicNum() for atom in molecule.GetAtoms()) - charge
    if electron_count % 2 == multiplicity % 2:
        raise StructureSeedError(
            "declared multiplicity is inconsistent with the molecular electron-count parity"
        )

    parameters = AllChem.ETKDGv3()
    parameters.randomSeed = RANDOM_SEED
    parameters.enforceChirality = True
    parameters.useRandomCoords = False
    if AllChem.EmbedMolecule(molecule, parameters) != 0:
        raise StructureSeedError("RDKit ETKDGv3 could not embed the molecule")

    uff_energy: float | None = None
    if optimization == "uff":
        if not AllChem.UFFHasAllMoleculeParams(molecule):
            raise StructureSeedError("RDKit UFF parameters are unavailable for this molecule")
        if AllChem.UFFOptimizeMolecule(molecule, maxIters=1_000) != 0:
            raise StructureSeedError("RDKit UFF optimization did not converge within 1000 iterations")
        force_field = AllChem.UFFGetMoleculeForceField(molecule)
        uff_energy = float(force_field.CalcEnergy())

    conformer = molecule.GetConformer()
    atom_rows = []
    for atom in molecule.GetAtoms():
        point = conformer.GetAtomPosition(atom.GetIdx())
        atom_rows.append(
            f"{atom.GetSymbol():<3} {point.x: .10f} {point.y: .10f} {point.z: .10f}"
        )
    comment = (
        f"{SEED_SCHEMA_VERSION} rdkit={rdkit.__version__} etkdg=v3 "
        f"random_seed={RANDOM_SEED} optimization={optimization}"
    )
    xyz = f"{molecule.GetNumAtoms()}\n{comment}\n" + "\n".join(atom_rows) + "\n"
    submitted_digest = "sha256:" + hashlib.sha256(smiles.encode("ascii")).hexdigest()
    normalized_digest = "sha256:" + hashlib.sha256(source.encode("ascii")).hexdigest()
    return {
        "schema_version": SEED_SCHEMA_VERSION,
        "xyz": xyz,
        "source": {
            "format": "smiles",
            "submitted_sha256": submitted_digest,
            "normalized_sha256": normalized_digest,
            "canonical_smiles": canonical_smiles,
        },
        "generator": {
            "name": "rdkit_etkdgv3",
            "rdkit_version": str(rdkit.__version__),
        },
        "parameters": {
            "random_seed": RANDOM_SEED,
            "add_hydrogens": True,
            "enforce_chirality": True,
            "optimization": optimization,
            "uff_max_iterations": 1_000 if optimization == "uff" else None,
        },
        "chemical_metadata": {
            "charge": charge,
            "multiplicity": multiplicity,
            "electron_count": electron_count,
            "atom_count": molecule.GetNumAtoms(),
            "formula": rdMolDescriptors.CalcMolFormula(molecule),
            "unassigned_stereocenter_indices": unassigned_stereo,
            "uff_energy_kcal_mol": uff_energy,
        },
        "limitations": [
            "This is an initial three-dimensional guess, not a stationary point or transition-state result.",
            "UFF energy, when present, is a geometry-initialization diagnostic and not scientific evidence.",
        ],
    }


def _validate_smiles(value: str) -> str:
    if not isinstance(value, str):
        raise StructureSeedError("structure seed SMILES must be a string")
    if not 1 <= len(value) <= 4_096:
        raise StructureSeedError("structure seed SMILES must contain 1 to 4096 characters")
    if not value.isascii() or any(character in value for character in ("\x00", "\r", "\n")):
        raise StructureSeedError("structure seed SMILES must be one ASCII line")
    source = value.strip()
    if not source:
        raise StructureSeedError("structure seed SMILES must contain 1 to 4096 characters")
    return source
