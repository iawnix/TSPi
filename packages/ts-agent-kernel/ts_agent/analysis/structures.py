"""Explicit geometry transformations and graph/electronic-state identity."""

from __future__ import annotations

from .engine import number, outcome, xyz_text
from .reaction import selected_mapping, species_record
from ts_agent.reaction.mapping import validate_atom_mapping


def reindex(inputs, p):
    left = [inputs.xyz("reactants", i) for i in range(len(inputs.bindings["reactants"]))]
    right = [inputs.xyz("products", i) for i in range(len(inputs.bindings["products"]))]
    mapping = selected_mapping(inputs, p)
    check = validate_atom_mapping([f["symbols"] for f in left], [f["symbols"] for f in right], mapping)
    if not check["valid"]:
        raise ValueError("endpoint reindexing requires a complete element-preserving bijection")
    pairs = sorted(mapping, key=lambda r: (r["reactant"]["species"], r["reactant"]["atom"]))
    symbols = [s for f in left for s in f["symbols"]]
    left_xyz = [xyz for f in left for xyz in f["coordinates"]]
    right_xyz = [right[r["product"]["species"]]["coordinates"][r["product"]["atom"]] for r in pairs]
    return outcome("ts-paired-endpoints/1", {"atom_count": len(symbols), "mapping": pairs, "coordinate_unit": "angstrom"},
                   files={"reactant.xyz": xyz_text(symbols, left_xyz), "product.xyz": xyz_text(symbols, right_xyz)},
                   limitations=["Coordinates are preserved; fragment placement, isotopes and chemical identity require separate evidence."],
                   facts={"structure.endpoints_reindexed": {"value": True}})


def assemble(inputs, p):
    import numpy as np

    fragments = [inputs.xyz("fragments", i) for i in range(len(inputs.bindings["fragments"]))]
    choices = p.get("placement_candidates") or [p["placements"]]
    minimum = p.get("minimum_distance_angstrom", 0.5)
    rows, files = [], {}
    for index, placements in enumerate(choices):
        if len(placements) != len(fragments):
            raise ValueError("one transform per fragment is required")
        coordinates, symbols, groups = [], [], []
        for fragment, placement in zip(fragments, placements):
            rotation = np.asarray(placement.get("rotation", np.eye(3)), dtype=float)
            translation = np.asarray(placement["translation"], dtype=float)
            if rotation.shape != (3, 3) or translation.shape != (3,) or not np.isfinite(rotation).all() or not np.isfinite(translation).all():
                raise ValueError("invalid fragment transform")
            if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-8) or not np.isclose(np.linalg.det(rotation), 1, atol=1e-8):
                raise ValueError("rotation must be a proper orthogonal matrix; reflections change chirality")
            moved = np.asarray(fragment["coordinates"]) @ rotation.T + translation
            groups.append(moved)
            coordinates.extend(moved.tolist())
            symbols.extend(fragment["symbols"])
        if len(symbols) > 4096:
            raise ValueError("assembled geometry exceeds 4096 atoms")
        distances = [float(np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2).min()) for i, a in enumerate(groups) for b in groups[i + 1:]]
        separation = min(distances) if distances else None
        clash = separation is not None and separation < minimum
        rows.append({"index": index, "minimum_interfragment_distance_angstrom": separation, "clash": clash})
        files[f"assembly_{index}.xyz"] = xyz_text(symbols, coordinates, "Explicit fragment placement; unoptimized")
    return outcome("ts-fragment-assemblies/1", {"candidates": rows, "minimum_distance_angstrom": minimum, "placements": choices},
                   verdict="invalid" if all(r["clash"] for r in rows) else "valid", files=files,
                   limitations=["No bonding, orientation optimization or relative complex energy is inferred."],
                   facts={"structure.clash_free_assembly_count": {"value": sum(not r["clash"] for r in rows)}})


def identity(inputs, p):
    a, b = [inputs.data(role, schema="ts-species-record/1") for role in ("reference", "target")]
    for record in (a, b):
        if record != species_record(record["key"], record["smiles"], record["multiplicity"], record.get("role", "participant")):
            raise ValueError("SpeciesRecord identity is inconsistent")
    checks = {field: a[field] == b[field] for field in ("canonical_smiles", "charge", "multiplicity")}
    same = all(checks.values())
    return outcome("ts-species-identity/1", {"same_species": same, "checks": checks, "same_conformer": None},
                   limitations=["Identity includes specified stereochemistry/isotopes/electronic state, but does not resolve unspecified stereo or conformers."],
                   facts={"species.same_identity": {"value": same}})


HANDLERS = {"structure.reindex": reindex, "structure.assemble_fragments": assemble, "species.identity": identity}
