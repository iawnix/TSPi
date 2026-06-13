from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
CONNECTIVITY_CLI = SKILL_ROOT / "scripts" / "rmsd_connectivity_check.py"


def write_xyz(path: Path, atoms: list[tuple[str, float, float, float]]) -> None:
    lines = [str(len(atoms)), path.stem]
    for element, x, y, z in atoms:
        lines.append(f"{element} {x:.6f} {y:.6f} {z:.6f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_conformer_aware_identity_is_ambiguous_not_connected(tmp_path: Path) -> None:
    reactant = tmp_path / "reactant.xyz"
    product = tmp_path / "product.xyz"
    forward = tmp_path / "forward.xyz"
    reverse = tmp_path / "reverse.xyz"
    outdir = tmp_path / "connectivity"

    reactant_atoms = [
        ("C", 0.0, 0.0, 0.0),
        ("C", 1.54, 0.0, 0.0),
        ("O", 3.20, 0.0, 0.0),
        ("H", 0.0, 1.09, 0.0),
    ]
    product_atoms = [
        ("C", 0.0, 0.0, 0.0),
        ("C", 1.54, 0.0, 0.0),
        ("O", 2.78, 0.0, 0.0),
        ("H", 0.0, 1.09, 0.0),
    ]
    product_conformer_atoms = [
        ("C", 0.0, 0.0, 0.0),
        ("C", 1.54, 0.0, 0.0),
        ("O", 1.54, 1.24, 0.0),
        ("H", 0.0, -1.09, 0.0),
    ]
    write_xyz(reactant, reactant_atoms)
    write_xyz(product, product_atoms)
    write_xyz(forward, product_conformer_atoms)
    write_xyz(reverse, reactant_atoms)

    result = subprocess.run(
        [
            sys.executable,
            str(CONNECTIVITY_CLI),
            "--forward",
            str(forward),
            "--reverse",
            str(reverse),
            "--reactant",
            str(reactant),
            "--product",
            str(product),
            "--bonds",
            "2-3",
            "--rmsd-threshold",
            "0.10",
            "--bond-threshold",
            "0.15",
            "--conformer-aware",
            "-o",
            str(outdir),
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 3
    summary = json.loads((outdir / "connectivity_summary.json").read_text(encoding="utf-8"))
    assert summary["decision"] == "conformer_identity_supported"
    assert summary["connectivity_supported"] is False
    assert summary["conformer_identity_supported"] is True
    assert summary["claim_suggestion"] == {
        "claim_status": "ambiguous",
        "outcome": "wrong_endpoint",
        "outcome_code": "conformer_identity_only",
    }
    assert summary["selected_covalent_identity_assignment"]["covalent_identity_passed"] is True
