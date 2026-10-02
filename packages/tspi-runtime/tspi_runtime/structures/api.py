"""Public structure analysis API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .flexibility import select_reaction_center
from .internals import angle, dihedral, distance, heavy_atom_indices, mapped_indices, read_xyz
from .rmsd import kabsch_transform, rmsd
from .stereo import compare_stereochemistry


def compare_structures(
    reference_structure: str | Path,
    target_structure: str | Path,
    *,
    atom_mapping: list[int] | None = None,
    reaction_center_atoms: list[int] | None = None,
    key_bonds: list[tuple[int, int]] | None = None,
    key_angles: list[tuple[int, int, int]] | None = None,
    key_dihedrals: list[tuple[int, int, int, int]] | None = None,
    stereochemical_checks: list[dict[str, Any]] | None = None,
    rmsd_threshold: float = 0.5,
    reaction_center_threshold: float = 0.25,
) -> dict[str, Any]:
    ref_symbols, ref_coords = read_xyz(reference_structure)
    tgt_symbols, tgt_coords = read_xyz(target_structure)
    if len(ref_symbols) != len(tgt_symbols):
        return _result("mismatched", "low", {}, ["atom count differs"])
    if not ref_symbols:
        return _result("mismatched", "low", {}, ["structures contain no atoms"])

    mapping = mapped_indices(len(ref_symbols), atom_mapping)
    element_mismatches = [
        (ref_index, target_index, ref_symbols[ref_index], tgt_symbols[target_index])
        for ref_index, target_index in mapping
        if ref_symbols[ref_index].upper() != tgt_symbols[target_index].upper()
    ]
    if element_mismatches:
        return _result("mismatched", "low", {}, [f"mapped atom elements differ: {element_mismatches}"])

    heavy_pairs = [pair for pair in mapping if ref_symbols[pair[0]].upper() != "H"]
    fit_pairs = heavy_pairs or mapping
    fit_selection = "heavy_atoms" if heavy_pairs else "all_atoms"
    fit_reference = [ref_coords[index] for index, _ in fit_pairs]
    fit_target = [tgt_coords[index] for _, index in fit_pairs]
    alignment = kabsch_transform(fit_reference, fit_target)
    aligned_tgt_coords = alignment.apply(tgt_coords)
    aligned_fit_target = [aligned_tgt_coords[index] for _, index in fit_pairs]
    heavy_rmsd = rmsd(fit_reference, aligned_fit_target)

    fallback_center = heavy_atom_indices(ref_symbols) or list(range(len(ref_symbols)))
    center_ref_indices = select_reaction_center(len(ref_symbols), reaction_center_atoms, fallback_center)
    center_pairs = [(index, mapping[index][1]) for index in center_ref_indices]
    center_rmsd = rmsd(
        [ref_coords[index] for index, _ in center_pairs],
        [aligned_tgt_coords[index] for _, index in center_pairs],
    )
    stereo_rows, stereo_diagnostics = compare_stereochemistry(ref_coords, tgt_coords, mapping, stereochemical_checks)

    metrics: dict[str, Any] = {
        "alignment": {
            "method": "kabsch",
            "fit_selection": fit_selection,
            "fit_atom_count": len(fit_pairs),
            "reflection_allowed": False,
        },
        "heavy_atom_rmsd": round(heavy_rmsd, 6),
        "reaction_center_rmsd": round(center_rmsd, 6),
        "key_bonds": _bond_metrics(ref_coords, tgt_coords, key_bonds or [], mapping),
        "key_angles": _angle_metrics(ref_coords, tgt_coords, key_angles or [], mapping),
        "key_dihedrals": _dihedral_metrics(ref_coords, tgt_coords, key_dihedrals or [], mapping),
        "stereochemistry": stereo_rows,
    }
    diagnostics = list(stereo_diagnostics)
    if heavy_rmsd > rmsd_threshold:
        diagnostics.append("heavy atom RMSD exceeds threshold")
    if center_rmsd > reaction_center_threshold:
        diagnostics.append("reaction center RMSD exceeds threshold")

    if diagnostics:
        verdict = "mismatched"
        uncertainty = "medium"
    else:
        verdict = "matched"
        uncertainty = "low"
    return _result(verdict, uncertainty, metrics, diagnostics)


def _bond_metrics(ref_coords, tgt_coords, bonds, mapping):
    rows = []
    for i, j in bonds:
        ti, tj = mapping[i][1], mapping[j][1]
        ref_value = distance(ref_coords[i], ref_coords[j])
        tgt_value = distance(tgt_coords[ti], tgt_coords[tj])
        rows.append({"atoms": [i, j], "reference": ref_value, "target": tgt_value, "delta": tgt_value - ref_value})
    return rows


def _angle_metrics(ref_coords, tgt_coords, angles, mapping):
    rows = []
    for i, j, k in angles:
        ti, tj, tk = mapping[i][1], mapping[j][1], mapping[k][1]
        ref_value = angle(ref_coords[i], ref_coords[j], ref_coords[k])
        tgt_value = angle(tgt_coords[ti], tgt_coords[tj], tgt_coords[tk])
        rows.append({"atoms": [i, j, k], "reference": ref_value, "target": tgt_value, "delta": tgt_value - ref_value})
    return rows


def _dihedral_metrics(ref_coords, tgt_coords, torsions, mapping):
    rows = []
    for i, j, k, l in torsions:
        ti, tj, tk, tl = mapping[i][1], mapping[j][1], mapping[k][1], mapping[l][1]
        ref_value = dihedral(ref_coords[i], ref_coords[j], ref_coords[k], ref_coords[l])
        tgt_value = dihedral(tgt_coords[ti], tgt_coords[tj], tgt_coords[tk], tgt_coords[tl])
        rows.append({"atoms": [i, j, k, l], "reference": ref_value, "target": tgt_value, "delta": tgt_value - ref_value})
    return rows


def _result(verdict: str, uncertainty: str, metrics: dict[str, Any], diagnostics: list[str]) -> dict[str, Any]:
    return {"verdict": verdict, "uncertainty": uncertainty, "metrics": metrics, "diagnostics": diagnostics}
