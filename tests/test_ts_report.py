from __future__ import annotations

from pathlib import Path

import json

from ts_report import build_final_report, build_report_package
from ts_report.context import collect_report_context
from ts_workspace import end_node, init_workspace, report_workspace, start_node, update_workspace
from strict_helpers import (
    HYPOTHESIS_ID,
    HYPOTHESIS_REF,
    PATHWAY_REF,
    bootstrap_strict_workspace,
    gate_artifact_metadata,
    make_accepted_workspace,
)


def test_report_labels_negative_pathway_audit_outcome(tmp_path: Path) -> None:
    workspace = tmp_path / "negative-audit-report"
    report_ref = bootstrap_strict_workspace(workspace)
    node_id = "n001_pathway_audit"

    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Audit the strict pathway.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "node_id": node_id,
                "parent_node": "n000",
                "phase": "pathway_audit",
                "hypothesis": "The strict pathway may be unaccepted.",
                "hypothesis_ref": HYPOTHESIS_REF,
                "branch_context": {"relation": "continue_parent", "from_node": "n000", "anchor_node": "n000"},
                "expected_evidence": ["pathway_audit_summary"],
                "pathway_ref": {"pathway_id": "p_test", "step_id": "s_i_to_p"},
            },
        },
    )
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register a negative audit.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": {
                    "evidence_id": "ev_negative_audit",
                    "kind": "pathway_audit_summary",
                    "role": "pathway_audit_summary",
                    "evidence_tier": "local_parse",
                    "node_id": node_id,
                    "summary": "The strict pathway is not accepted.",
                    **gate_artifact_metadata("nodes/n001_pathway_audit/outputs/pathway_audit.json"),
                    "quality": {
                        "hypothesis_id": HYPOTHESIS_ID,
                        "strict_pathway_supported": False,
                        "strict_pathway_decision": "pathway_not_accepted",
                    },
                }
            },
        },
    )
    end_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "end_node",
            "rationale": "Close the audit.",
            "evidence_refs": ["ev_negative_audit"],
            "report_ref": report_ref,
            "payload": {
                "node_id": node_id,
                "closure": {
                    "program_status": "completed",
                    "claim_verdict": "supported",
                    "program": {"summary": "Audit completed.", "evidence_refs": ["ev_negative_audit"]},
                    "mechanism": {
                        "summary": "Pathway not accepted.",
                        "hypothesis_ref": HYPOTHESIS_REF,
                        "evidence_refs": ["ev_negative_audit"],
                    },
                    "implication": "Agent decides the next branch.",
                    "open_questions": [],
                },
            },
        },
    )

    text = build_final_report(workspace)

    assert "n001_pathway_audit: pathway_audit / closed / supported (audit_outcome=pathway_not_accepted)" in text


def test_report_includes_acceptance_layers_and_pathway_outcome(tmp_path: Path) -> None:
    workspace = tmp_path / "accepted-audit-report"
    report_ref = make_accepted_workspace(workspace)
    node_id = "n004_pathway_audit"

    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Audit the accepted pathway.",
            "evidence_refs": ["ev_tsfreq_001", "ev_conn_001"],
            "report_ref": report_ref,
            "payload": {
                "node_id": node_id,
                "parent_node": "n003",
                "phase": "pathway_audit",
                "hypothesis": "The strict pathway is accepted.",
                "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": ["pred_pathway_001"]},
                "branch_context": {"relation": "continue_parent", "from_node": "n003", "anchor_node": "n000"},
                "expected_evidence": ["pathway_audit_summary"],
                "pathway_ref": PATHWAY_REF,
            },
        },
    )
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register accepted audit evidence.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": {
                    "evidence_id": "ev_pathway_accepted",
                    "kind": "pathway_audit_summary",
                    "role": "pathway_audit_summary",
                    "evidence_tier": "local_parse",
                    "node_id": node_id,
                    "summary": "The strict pathway is accepted.",
                    **gate_artifact_metadata("nodes/n004_pathway_audit/outputs/pathway_audit.json"),
                    "quality": {
                        "hypothesis_id": HYPOTHESIS_ID,
                        "strict_pathway_supported": True,
                        "strict_pathway_decision": "accepted",
                    },
                }
            },
        },
    )
    end_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "end_node",
            "rationale": "Close accepted pathway audit.",
            "evidence_refs": ["ev_pathway_accepted"],
            "report_ref": report_ref,
            "payload": {
                "node_id": node_id,
                "closure": {
                    "program_status": "completed",
                    "claim_verdict": "supported",
                    "program": {"summary": "Audit completed.", "evidence_refs": ["ev_pathway_accepted"]},
                    "mechanism": {
                        "summary": "Pathway accepted.",
                        "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": ["pred_pathway_001"]},
                        "evidence_refs": ["ev_pathway_accepted"],
                    },
                    "implication": "Report the accepted pathway.",
                    "open_questions": [],
                },
            },
        },
    )

    text = build_final_report(workspace)

    assert "| Highest validated layer | `pathway` |" in text
    assert "| Final claim | `accepted` |" in text
    assert "ev_tsfreq_001" in text
    assert "ev_conn_001" in text
    assert "n004_pathway_audit: pathway_audit / closed / supported (audit_outcome=accepted)" in text


def test_report_package_writes_visual_mechanism_assets(tmp_path: Path) -> None:
    workspace = tmp_path / "package-report"
    make_accepted_workspace(workspace)
    (workspace / "inputs").mkdir(exist_ok=True)
    _write_xyz(workspace / "inputs" / "reactant.xyz", [("C", 0, 0, 0), ("N", 3, 0, 0)])
    _write_xyz(workspace / "inputs" / "product.xyz", [("C", 0, 0, 0), ("N", 1.4, 0, 0)])
    ts_dir = workspace / "nodes" / "n001" / "outputs"
    ts_dir.mkdir(parents=True, exist_ok=True)
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
    assert Path(result["manifest"]).is_file()


def test_energy_profile_uses_reactant_product_zpe_corrections(tmp_path: Path) -> None:
    workspace = tmp_path / "zpe-report"
    make_accepted_workspace(workspace)
    energy_dir = workspace / "nodes" / "n000" / "outputs"
    ts_dir = workspace / "nodes" / "n001" / "outputs"
    energy_dir.mkdir(parents=True, exist_ok=True)
    ts_dir.mkdir(parents=True, exist_ok=True)
    _write_energy_json(
        energy_dir / "reactant_freq.json",
        species="reactant",
        electronic=-100.000,
        zpe=0.010,
        gibbs=0.020,
    )
    _write_energy_json(
        energy_dir / "product_freq.json",
        species="product",
        electronic=-100.020,
        zpe=0.011,
        gibbs=0.021,
    )
    _write_energy_json(
        ts_dir / "tsfreq_validation.json",
        species="transition_state",
        electronic=-99.950,
        zpe=0.015,
        gibbs=0.025,
        extra={"ts_structure": "nodes/n001/outputs/ts_final.xyz"},
    )

    report_ref = _report_ref(workspace)
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register endpoint stationary-point energies.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
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
        },
    )

    context = collect_report_context(workspace)
    rows = {row["species"]: row for row in context["energy_profile"]["rows"]}

    assert rows["R"]["electronic_plus_zpe_hartree"] == -99.990
    assert rows["TS"]["electronic_plus_zpe_hartree"] == -99.935
    assert rows["P"]["electronic_plus_zpe_hartree"] == -100.009
    assert rows["R"]["relative_zpe_corrected_energy_kcal_mol"] == 0.0
    assert rows["TS"]["relative_zpe_corrected_energy_kcal_mol"] == 34.513
    assert rows["P"]["relative_zpe_corrected_energy_kcal_mol"] == -11.923
    assert rows["TS"]["relative_electronic_energy_kcal_mol"] == 31.375
    assert not any("E+ZPE is missing" in note for note in context["energy_profile"]["notes"])

    report = build_final_report(workspace)
    assert "Rel E+ZPE / kcal mol-1" in report
    assert "34.513" in report


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


def _report_ref(workspace: Path) -> dict[str, str]:
    report = report_workspace(workspace)
    return {"report_id": report["report_id"], "workspace_root": str(workspace)}
