from __future__ import annotations

from pathlib import Path

from mol_comparator import compare_structures


def test_compare_structures_matches_declared_tetrahedral_stereochemistry(tmp_path: Path) -> None:
    ref = tmp_path / "ref.xyz"
    target = tmp_path / "target.xyz"
    coords = [
        ("C", (0.0, 0.0, 0.0)),
        ("H", (1.0, 0.0, 0.0)),
        ("H", (0.0, 1.0, 0.0)),
        ("H", (0.0, 0.0, 1.0)),
        ("H", (-1.0, -1.0, -1.0)),
    ]
    _write_xyz(ref, coords)
    _write_xyz(target, coords)

    result = compare_structures(
        ref,
        target,
        stereochemical_checks=[
            {"type": "tetrahedral", "center": 0, "neighbors": [1, 2, 3, 4], "policy": "retain"}
        ],
    )

    assert result["verdict"] == "matched"
    assert result["metrics"]["stereochemistry"][0]["verdict"] == "matched"


def test_compare_structures_rejects_declared_tetrahedral_stereo_mismatch(tmp_path: Path) -> None:
    ref = tmp_path / "ref.xyz"
    target = tmp_path / "target.xyz"
    _write_xyz(
        ref,
        [
            ("C", (0.0, 0.0, 0.0)),
            ("H", (1.0, 0.0, 0.0)),
            ("H", (0.0, 1.0, 0.0)),
            ("H", (0.0, 0.0, 1.0)),
            ("H", (-1.0, -1.0, -1.0)),
        ],
    )
    _write_xyz(
        target,
        [
            ("C", (0.0, 0.0, 0.0)),
            ("H", (1.0, 0.0, 0.0)),
            ("H", (0.0, 1.0, 0.0)),
            ("H", (0.0, 0.0, -1.0)),
            ("H", (-1.0, -1.0, 1.0)),
        ],
    )

    result = compare_structures(
        ref,
        target,
        stereochemical_checks=[
            {"type": "tetrahedral", "center": 0, "neighbors": [1, 2, 3, 4], "policy": "retain"}
        ],
        rmsd_threshold=10.0,
        reaction_center_threshold=10.0,
    )

    assert result["verdict"] == "mismatched"
    assert result["metrics"]["stereochemistry"][0]["verdict"] == "mismatched"
    assert any("tetrahedral parity" in item for item in result["diagnostics"])


def test_compare_structures_rejects_declared_dihedral_stereo_mismatch(tmp_path: Path) -> None:
    ref = tmp_path / "ref.xyz"
    target = tmp_path / "target.xyz"
    _write_xyz(
        ref,
        [
            ("C", (1.0, 0.0, 0.0)),
            ("C", (0.0, 0.0, 0.0)),
            ("C", (0.0, 1.0, 0.0)),
            ("C", (0.0, 1.0, 1.0)),
        ],
    )
    _write_xyz(
        target,
        [
            ("C", (1.0, 0.0, 0.0)),
            ("C", (0.0, 0.0, 0.0)),
            ("C", (0.0, 1.0, 0.0)),
            ("C", (0.0, 1.0, -1.0)),
        ],
    )

    result = compare_structures(
        ref,
        target,
        stereochemical_checks=[{"type": "dihedral", "atoms": [0, 1, 2, 3], "policy": "retain", "max_delta_degrees": 20}],
        rmsd_threshold=10.0,
        reaction_center_threshold=10.0,
    )

    assert result["verdict"] == "mismatched"
    assert result["metrics"]["stereochemistry"][0]["verdict"] == "mismatched"
    assert any("dihedral stereochemical policy" in item for item in result["diagnostics"])


def _write_xyz(path: Path, atoms: list[tuple[str, tuple[float, float, float]]]) -> None:
    lines = [str(len(atoms)), path.stem]
    lines.extend(f"{symbol} {x:.6f} {y:.6f} {z:.6f}" for symbol, (x, y, z) in atoms)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
