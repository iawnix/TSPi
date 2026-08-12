from __future__ import annotations

import json
from pathlib import Path

from strict_helpers import gate_artifact_metadata, make_accepted_workspace
from ts_report import build_final_report, build_report_package
from ts_report.builder import _mode_lines, _reaction_overview_lines
from ts_report.context import collect_report_context
from ts_report.extractors import collect_structures, collect_tsfreq, reaction_center
from ts_workspace import report_workspace, update_workspace


def _decision(workspace: Path, payload: dict) -> dict:
    report = report_workspace(workspace)
    return {
        "schema_version": "ts-decision/2",
        "action": "update_workspace",
        "rationale": "Register report input evidence.",
        "evidence_refs": [],
        "report_ref": {"report_id": report["report_id"], "workspace_root": str(workspace)},
        "base_revision": report["workspace_revision"],
        "payload": payload,
    }


def test_report_uses_node_type_and_scope_labels(tmp_path: Path) -> None:
    workspace = tmp_path / "report"
    make_accepted_workspace(workspace)

    text = build_final_report(workspace)

    assert "validation/tsfreq" in text
    assert "validation/connectivity" in text
    assert "audit/transition_state" in text
    assert "claim_verdict" not in text
    assert "program_status" not in text


def test_report_package_writes_visual_mechanism_assets(tmp_path: Path) -> None:
    workspace = tmp_path / "package-report"
    make_accepted_workspace(workspace)
    (workspace / "inputs").mkdir(exist_ok=True)
    _write_xyz(workspace / "inputs" / "reactant.xyz", [("C", 0, 0, 0), ("N", 3, 0, 0)])
    _write_xyz(workspace / "inputs" / "product.xyz", [("C", 0, 0, 0), ("N", 1.4, 0, 0)])
    ts_dir = workspace / "nodes" / "n001" / "outputs"
    _write_xyz(ts_dir / "ts_final.xyz", [("C", 0, 0, 0), ("N", 2.0, 0, 0)])
    (ts_dir / "tsfreq_validation.json").write_text(
        json.dumps(
            {
                "ts_structure": "nodes/n001/outputs/ts_final.xyz",
                "electronic_energy_hartree": -100.0,
                "mode_assignment": {
                    "imaginary_frequency_cm-1": -500.0,
                    "mode_verdict": "mode_matches_reaction_center",
                    "product_like_displacement": "C1-N2 shortens.",
                    "reactant_like_displacement": "C1-N2 lengthens.",
                },
                "reaction_center_distances_angstrom": {
                    "reactant_endpoint": {"C1-N2": 3.0},
                    "p39_final": {"C1-N2": 2.0},
                    "product_endpoint": {"C1-N2": 1.4},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = build_report_package(workspace, workspace / "reports" / "pkg")

    report = Path(result["report"]).read_text(encoding="utf-8")
    context = json.loads(Path(result["context"]).read_text(encoding="utf-8"))
    assert "## 3. R-TS-P Structural Panel" in report
    assert "## 4. Imaginary Mode / Vibration Analysis" in report
    assert "## 6. Energy Profile" in report
    assert "## 7. Mechanistic Interpretation" in report
    assert Path(result["assets_dir"], "r_ts_p_structure_panel.svg").exists()
    assert Path(result["assets_dir"], "irc_key_distance_profile.svg").exists()
    assert context["mechanism_interpretation"]["classification"]
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["workspace_revision"] == context["workspace_revision"]


def test_energy_profile_uses_reactant_product_zpe_corrections(tmp_path: Path) -> None:
    workspace = tmp_path / "zpe-report"
    make_accepted_workspace(workspace)
    energy_dir = workspace / "nodes" / "n000" / "outputs"
    ts_dir = workspace / "nodes" / "n001" / "outputs"
    energy_dir.mkdir(parents=True, exist_ok=True)
    _write_energy_json(energy_dir / "reactant_freq.json", species="reactant", electronic=-100.000, zpe=0.010, gibbs=0.020)
    _write_energy_json(energy_dir / "product_freq.json", species="product", electronic=-100.020, zpe=0.011, gibbs=0.021)
    _write_energy_json(
        ts_dir / "tsfreq_validation.json",
        species="transition_state",
        electronic=-99.950,
        zpe=0.015,
        gibbs=0.025,
        extra={"ts_structure": "nodes/n001/outputs/ts_final.xyz"},
    )
    update_workspace(
        workspace,
        _decision(
            workspace,
            {
                "append_evidence": [
                    {
                        "evidence_id": "ev_reactant_energy",
                        "kind": "gaussian_freq_energy",
                        "role": "reactant_energy",
                        "evidence_tier": "local_parse",
                        "node_id": "n000",
                        "summary": "Reactant frequency energy with ZPE correction.",
                        **gate_artifact_metadata("nodes/n000/outputs/reactant_freq.json"),
                    },
                    {
                        "evidence_id": "ev_product_energy",
                        "kind": "gaussian_freq_energy",
                        "role": "product_energy",
                        "evidence_tier": "local_parse",
                        "node_id": "n000",
                        "summary": "Product frequency energy with ZPE correction.",
                        **gate_artifact_metadata("nodes/n000/outputs/product_freq.json"),
                    },
                ]
            },
        ),
    )

    context = collect_report_context(workspace)
    rows = {row["species"]: row for row in context["energy_profile"]["rows"]}
    assert rows["R"]["electronic_plus_zpe_hartree"] == -99.990
    assert rows["TS"]["relative_zpe_corrected_energy_kcal_mol"] == 34.513
    assert rows["P"]["relative_zpe_corrected_energy_kcal_mol"] == -11.923
    assert "34.513" in build_final_report(workspace)


def test_report_extracts_current_v2_hypothesis_and_reaudit_shapes(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    ts_xyz = root / "nodes/n003/outputs/gaussian_final.xyz"
    forward_xyz = root / "nodes/n004/outputs/forward_endpoint.xyz"
    reverse_xyz = root / "nodes/n004/outputs/reverse_endpoint.xyz"
    for path in (ts_xyz, forward_xyz, reverse_xyz):
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_xyz(path, [("C", 0, 0, 0), ("C", 1.4, 0, 0)])

    active = {
        "hypothesis_id": "hyp_0001",
        "summary": "Concerted cycloaddition.",
        "derived_from": {"reactants": "diene plus alkene", "product": "cycloadduct"},
        "structured_claim": {
            "reaction_center": {
                "forming_bonds": [["C1", "C5"], ["C4", "C6"]],
                "breaking_bonds": [],
                "transferred_atoms": [],
                "spectator_regions": [],
            },
            "electronic_model": {"charge": 0, "multiplicity": 1},
        },
    }
    records = [
        {
            "evidence_id": "ev_tsfreq_source",
            "role": "tsfreq_gate",
            "path": "nodes/n003/outputs/validation_summary.json",
            "source_files": ["nodes/n003/outputs/gaussian_final.xyz"],
            "quality": {"imaginary_frequency_cm-1": -504.1854, "imaginary_frequency_count": 1},
        },
        {
            "evidence_id": "ev_mode",
            "role": "mode_assignment",
            "path": "nodes/n003/outputs/imaginary_mode_assignment.json",
            "quality": {"mode_matches_reaction_coordinate": True},
        },
        {
            "evidence_id": "ev_tsfreq_reaudit",
            "role": "tsfreq_gate",
            "path": "nodes/n007/outputs/tsfreq_gate_verification.json",
            "source_files": [
                "nodes/n007/outputs/tsfreq_gate_verification.json",
                "nodes/n003/outputs/validation_summary.json",
            ],
            "quality": {"mode_verdict": "mode_matches_reaction_center", "verdict_against_prediction": "supported"},
        },
        {
            "evidence_id": "ev_endpoints",
            "role": "irc_endpoint_assignment",
            "source_files": [
                "nodes/n004/outputs/forward_endpoint.xyz",
                "nodes/n004/outputs/reverse_endpoint.xyz",
            ],
            "quality": {"forward_assignment": "product", "reverse_assignment": "reactant"},
            "provenance": {"forward_intent_id": "forward", "reverse_intent_id": "reverse"},
        },
    ]
    artifacts = {
        "ev_tsfreq_source": {"imaginary_frequencies_cm-1": [-504.1854]},
        "ev_mode": {
            "selected_frequency_cm-1": -504.1854,
            "assignment": "coupled_C1-C5_and_C4-C6_bond_formation",
        },
        "ev_tsfreq_reaudit": {
            "checks": {"imaginary_frequency_cm-1": -504.1854},
            "verdict_against_prediction": "supported",
        },
    }

    center = reaction_center(active)
    tsfreq = collect_tsfreq(root, records, artifacts)
    structures = collect_structures(root, active, records, artifacts)
    overview = "\n".join(_reaction_overview_lines({"active_hypothesis": active, "reaction_center": center}))
    mode_table = "\n".join(_mode_lines({"tsfreq": tsfreq, "assets": {}}))

    assert [item["label"] for item in center["forming_bonds"]] == ["C1-C5", "C4-C6"]
    assert "diene plus alkene" in overview
    assert "cycloadduct" in overview
    assert "`0 / 1`" in overview
    assert "C1-C5, C4-C6" in overview
    assert "-504.1854" in mode_table
    assert "mode_matches_reaction_center" in mode_table
    assert tsfreq["mode_assignment"]["assignment"] == "coupled_C1-C5_and_C4-C6_bond_formation"
    assert structures["ts"]["path"] == "nodes/n003/outputs/gaussian_final.xyz"
    assert structures["product"]["path"] == "nodes/n004/outputs/forward_endpoint.xyz"
    assert structures["reactant"]["path"] == "nodes/n004/outputs/reverse_endpoint.xyz"


def _write_xyz(path: Path, atoms: list[tuple[str, float, float, float]]) -> None:
    lines = [str(len(atoms)), path.stem]
    lines.extend(f"{symbol} {x:.6f} {y:.6f} {z:.6f}" for symbol, x, y, z in atoms)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_energy_json(
    path: Path,
    *,
    species: str,
    electronic: float,
    zpe: float,
    gibbs: float,
    extra: dict[str, object] | None = None,
) -> None:
    payload = {
        "species": species,
        "electronic_energy_hartree": electronic,
        "zero_point_correction_hartree": zpe,
        "thermal_gibbs_correction_hartree": gibbs,
    }
    if extra:
        payload.update(extra)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
