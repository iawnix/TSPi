from __future__ import annotations

from pathlib import Path

import pytest

from ts_structures import compare_structures
from ts_structures.internals import mapped_indices
from ts_structures.rmsd import kabsch_transform, rmsd


def test_compare_structures_kabsch_aligns_mapped_rotation_and_translation(tmp_path: Path) -> None:
    reference_atoms = [
        ("C", (0.0, 0.0, 0.0)),
        ("C", (1.2, 0.1, 0.0)),
        ("O", (-0.2, 1.1, 0.2)),
        ("N", (0.1, -0.3, 1.4)),
    ]
    transformed = [(symbol, _rotate_translate(point)) for symbol, point in reference_atoms]
    target_order = [2, 0, 3, 1]
    target_atoms = [transformed[index] for index in target_order]
    reference = tmp_path / "reference.xyz"
    target = tmp_path / "target.xyz"
    _write_xyz(reference, reference_atoms)
    _write_xyz(target, target_atoms)

    result = compare_structures(
        reference,
        target,
        atom_mapping=[1, 3, 0, 2],
        reaction_center_atoms=[0, 1, 2],
    )

    assert result["verdict"] == "matched"
    assert result["metrics"]["alignment"] == {
        "method": "kabsch",
        "fit_selection": "heavy_atoms",
        "fit_atom_count": 4,
        "reflection_allowed": False,
    }
    assert result["metrics"]["heavy_atom_rmsd"] == pytest.approx(0.0, abs=1e-6)
    assert result["metrics"]["reaction_center_rmsd"] == pytest.approx(0.0, abs=1e-6)


def test_compare_structures_reaction_center_reuses_global_alignment(tmp_path: Path) -> None:
    reference_atoms = [
        ("C", (0.0, 0.0, 0.0)),
        ("C", (1.0, 0.0, 0.0)),
        ("C", (0.0, 1.0, 0.0)),
        ("C", (0.0, 0.0, 1.0)),
    ]
    target_atoms = [
        ("C", (0.6, 0.0, 0.0)),
        ("C", (1.6, 0.0, 0.0)),
        ("C", (0.0, 1.0, 0.0)),
        ("C", (0.0, 0.0, 1.0)),
    ]
    reference = tmp_path / "reference.xyz"
    target = tmp_path / "target.xyz"
    _write_xyz(reference, reference_atoms)
    _write_xyz(target, target_atoms)

    result = compare_structures(
        reference,
        target,
        reaction_center_atoms=[0, 1],
        rmsd_threshold=10.0,
        reaction_center_threshold=0.1,
    )

    assert result["verdict"] == "mismatched"
    assert result["metrics"]["reaction_center_rmsd"] > 0.1
    assert "reaction center RMSD exceeds threshold" in result["diagnostics"]


def test_kabsch_transform_never_uses_mirror_reflection() -> None:
    reference = [
        (0.0, 0.0, 0.0),
        (1.2, 0.1, 0.0),
        (-0.2, 1.1, 0.2),
        (0.1, -0.3, 1.4),
    ]
    mirrored = [(-x, y, z) for x, y, z in reference]

    transform = kabsch_transform(reference, mirrored)
    aligned = transform.apply(mirrored)

    assert _determinant(transform.rotation) == pytest.approx(1.0, abs=1e-12)
    assert rmsd(reference, aligned) > 0.1


def test_atom_mapping_must_be_a_target_permutation() -> None:
    with pytest.raises(ValueError, match="one-to-one"):
        mapped_indices(3, [0, 0, 2])
    with pytest.raises(ValueError, match="out of range"):
        mapped_indices(3, [0, 1, 3])


def test_compare_structures_rejects_element_inconsistent_mapping(tmp_path: Path) -> None:
    reference = tmp_path / "reference.xyz"
    target = tmp_path / "target.xyz"
    _write_xyz(reference, [("C", (0.0, 0.0, 0.0)), ("O", (1.0, 0.0, 0.0))])
    _write_xyz(target, [("N", (0.0, 0.0, 0.0)), ("O", (1.0, 0.0, 0.0))])

    result = compare_structures(reference, target)

    assert result["verdict"] == "mismatched"
    assert result["metrics"] == {}
    assert result["diagnostics"][0].startswith("mapped atom elements differ")


def _rotate_translate(point: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = point
    return (-y + 4.0, x - 3.0, z + 2.0)


def _determinant(matrix: tuple[tuple[float, float, float], ...]) -> float:
    (a, b, c), (d, e, f), (g, h, i) = matrix
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def _write_xyz(path: Path, atoms: list[tuple[str, tuple[float, float, float]]]) -> None:
    lines = [str(len(atoms)), path.stem]
    lines.extend(f"{symbol} {x:.12f} {y:.12f} {z:.12f}" for symbol, (x, y, z) in atoms)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
