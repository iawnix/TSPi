"""Bounded chemical-name resolution and candidate structure validation."""

from __future__ import annotations

import json
from typing import Any

from .engine import outcome


def _inchi_fields(molecule) -> dict[str, str]:
    try:
        from rdkit import Chem

        inchi = Chem.MolToInchi(molecule)
        if not inchi:
            return {}
        return {"inchi": inchi, "inchikey": Chem.InchiToInchiKey(inchi)}
    except (AttributeError, RuntimeError, ValueError):
        return {}


def _candidate(candidate: dict[str, Any], index: int) -> tuple[dict[str, Any] | None, str | None]:
    from rdkit import Chem
    from rdkit.Chem import rdMolDescriptors

    smiles = candidate["smiles"].strip()
    source = candidate["source"]
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None or molecule.GetNumAtoms() == 0:
        return None, f"candidate_{index}: RDKit could not parse the supplied SMILES"
    if len(Chem.GetMolFrags(molecule)) != 1:
        return None, f"candidate_{index}: structure must be one connected molecule"

    centers = Chem.FindMolChiralCenters(molecule, includeUnassigned=True, useLegacyImplementation=False)
    unassigned = [int(atom) for atom, assignment in centers if assignment == "?"]
    canonical = Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)
    result = {
        "candidate_id": f"candidate_{index}",
        "source": source,
        "smiles": smiles,
        "canonical_smiles": canonical,
        "isomeric_smiles": canonical,
        "formula": rdMolDescriptors.CalcMolFormula(molecule),
        "charge": int(Chem.GetFormalCharge(molecule)),
        "atom_count": int(molecule.GetNumAtoms()),
        "undefined_stereocenters": unassigned,
    }
    result.update(_inchi_fields(molecule))
    return result, None


def resolve(_inputs, parameters: dict[str, Any]) -> dict[str, Any]:
    name = parameters["name"].strip()
    resolver = parameters.get("resolver", "auto")
    supplied = parameters.get("candidates", [])
    diagnostics: list[str] = []
    candidates: list[dict[str, Any]] = []

    if not supplied:
        return outcome(
            "ts-name-resolution/1",
            {"name": name, "resolver": resolver, "status": "unresolved", "candidates": []},
            verdict="unsupported",
            diagnostics=[
                "No registered deterministic name resolver is configured; install or bind OPSIN/PubChem before resolving a name."
            ],
            limitations=[
                "An LLM cannot be treated as a name-resolution authority without an explicit candidate and confirmation."
            ],
            facts={"chemical.name.status": {"value": "unresolved"}, "chemical.name.candidate_count": {"value": 0}},
        )

    for index, proposed in enumerate(supplied, 1):
        item, diagnostic = _candidate(proposed, index)
        if diagnostic:
            diagnostics.append(diagnostic)
        elif item:
            candidates.append(item)

    if not candidates:
        status = "unresolved"
        verdict = "invalid"
    elif any(item["source"] == "llm" for item in candidates):
        status = "draft"
        verdict = "inconclusive"
    elif len(candidates) != 1 or any(item["undefined_stereocenters"] for item in candidates):
        status = "ambiguous"
        verdict = "inconclusive"
    elif candidates[0]["source"] == "user":
        status = "confirmed"
        verdict = "valid"
    else:
        status = "resolved"
        verdict = "valid"

    data = {
        "name": name,
        "resolver": resolver,
        "status": status,
        "candidates": candidates,
    }
    files = {
        "name_resolution.json": json.dumps(
            {"schema_version": "ts-name-resolution/1", "data": data},
            sort_keys=True,
        ) + "\n"
    }
    return outcome(
        "ts-name-resolution/1",
        data,
        verdict=verdict,
        diagnostics=diagnostics,
        limitations=[
            "Name resolution establishes a molecular graph candidate, not a validated reaction product or optimized 3D structure.",
            "LLM-proposed candidates remain draft until a deterministic resolver or explicit user confirmation establishes identity.",
        ],
        facts={
            "chemical.name.status": {"value": status},
            "chemical.name.candidate_count": {"value": len(candidates)},
        },
        files=files,
    )


HANDLERS = {"chemical.name.resolve": resolve}
