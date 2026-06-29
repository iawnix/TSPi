from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ts_workspace import end_node, init_workspace, report_workspace, start_node, update_workspace, validate_workspace
from ts_workspace.validators.decision import validate_decision
from ts_workspace.validators.decision_context import validate_decision_for_workspace


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "templates" / "decision"
PLACEHOLDER_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")

EXPECTED_TEMPLATE_FILES = {
    "README.md",
    "start_endpoint_n000.json",
    "update_endpoint_evidence.json",
    "end_endpoint_n000_supported.json",
    "start_candidate_generation.json",
    "update_candidate_evidence.json",
    "end_candidate_generation_supported.json",
    "start_tsfreq_validation.json",
    "update_tsfreq_evidence.json",
    "end_tsfreq_validation_supported.json",
    "start_connectivity_validation.json",
    "update_connectivity_evidence.json",
    "update_stereochemical_connectivity_evidence.json",
    "end_connectivity_validation_supported.json",
    "start_accepted_audit.json",
    "end_accepted_audit_supported.json",
    "start_pathway_audit.json",
    "update_pathway_audit_accepted.json",
    "end_pathway_audit_accepted.json",
    "update_pathway_audit_not_accepted.json",
    "end_pathway_audit_not_accepted.json",
    "start_replacement_branch.json",
}


DEFAULT_VALUES = {
    "REPORT_ID": "rep_template",
    "WORKSPACE_ROOT": "template_workspace",
    "HYPOTHESIS_ID": "hyp_0001",
    "INITIAL_HYPOTHESIS_SUMMARY": "Endpoint-derived single-step C-N formation hypothesis.",
    "REACTANT_REF": "inputs/reactant.xyz",
    "PRODUCT_REF": "inputs/product.xyz",
    "CHARGE": "0",
    "MULTIPLICITY": "1",
    "ATOM_MAPPING_REF": "inputs/atom_mapping.json",
    "FORMING_ATOM_A": "1",
    "FORMING_ATOM_B": "2",
    "FORMING_BOND_LABEL": "C1-N2",
    "REACTION_CLASS": "bond_formation",
    "ELEMENTARY_STEP_MODEL": "concerted",
    "ELECTRONIC_SURFACE": "ground_state",
    "SPIN_SURFACE": "singlet",
    "NET_ELECTRON_TRANSFER": "not_expected",
    "CHARGE_TRANSFER": "possible_but_unconfirmed",
    "SPIN_DENSITY_CHANGE": "not_expected",
    "PCET": "not_expected",
    "PATHWAY_ID": "p_single",
    "REVISED_PATHWAY_ID": "p_revised",
    "STEP_ID": "s1",
    "PRED_CANDIDATE_ID": "pred_candidate_001",
    "PRED_MODE_ID": "pred_mode_001",
    "PRED_CONN_ID": "pred_conn_001",
    "PRED_STEREO_ID": "pred_stereo_001",
    "PRED_PATHWAY_ID": "pred_pathway_001",
    "ALTERNATIVE_HYPOTHESIS_SUMMARY": "Stepwise C-N formation.",
    "ALTERNATIVE_CHANGED_VARIABLE": "elementary_step_model",
    "EV_INITIAL_HYPOTHESIS": "ev_hyp_0001",
    "EV_ENDPOINT_PROVENANCE": "ev_endpoint_0001",
    "EV_CHARGE_MULTIPLICITY": "ev_charge_mult_0001",
    "EV_ATOM_MAPPING": "ev_atom_mapping_0001",
    "EV_REACTION_CENTER_DELTA": "ev_reaction_center_0001",
    "ENDPOINT_PROVENANCE_PATH": "inputs/source_manifest.json",
    "EV_CANDIDATE": "ev_candidate_001",
    "CANDIDATE_GEOMETRY_PATH": "nodes/n001/outputs/candidate.xyz",
    "EV_TSFREQ": "ev_tsfreq_001",
    "TSFREQ_LOG_PATH": "nodes/n002/outputs/tsfreq.log",
    "IMAGINARY_FREQUENCY_CM1": "-512.3",
    "EV_CONNECTIVITY": "ev_conn_001",
    "EV_STEREOCHEMISTRY": "ev_stereo_001",
    "IRC_SUMMARY_PATH": "nodes/n003/outputs/irc_summary.json",
    "STEREOCHEMISTRY_SUMMARY_PATH": "nodes/n003/outputs/stereochemistry_summary.json",
    "IRC_REACTANT_ENDPOINT_REF": "nodes/n003/outputs/irc_reverse_opt.xyz",
    "IRC_PRODUCT_ENDPOINT_REF": "nodes/n003/outputs/irc_forward_opt.xyz",
    "STEREO_CENTER_ATOM": "1",
    "EV_PATHWAY_AUDIT": "ev_pathway_audit_001",
    "PATHWAY_AUDIT_PATH": "reports/pathway_audit.json",
    "PATHWAY_AUDIT_DIAGNOSTIC": "forward endpoint does not match product basin",
    "BACKTRACK_EVIDENCE_REF": "ev_pathway_audit_001",
    "NEW_BRANCH_NODE_ID": "n002",
    "BACKTRACK_FROM_NODE": "n001",
    "BACKTRACK_TO_NODE": "n000",
    "BACKTRACK_CHANGED_VARIABLE": "reaction_center",
    "BACKTRACK_REASON_CODE": "connectivity_refuted",
}


def test_runtime_decision_templates_are_complete_and_separate_from_tests() -> None:
    names = {path.name for path in TEMPLATE_DIR.iterdir() if path.is_file()}
    assert EXPECTED_TEMPLATE_FILES.issubset(names)

    readme = (TEMPLATE_DIR / "README.md").read_text(encoding="utf-8")
    normalized_readme = " ".join(readme.lower().split())
    assert "Do not use files under `tests/` as runtime decision examples." in readme
    assert "do not encode a fixed retry policy" in normalized_readme


def test_all_runtime_decision_templates_render_to_valid_decisions() -> None:
    for path in sorted(TEMPLATE_DIR.glob("*.json")):
        decision = _render_template(path.name)
        assert decision["schema_version"] == "ts-decision", path.name
        validate_decision(decision)


def test_runtime_templates_drive_complete_accepted_pathway_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "accepted_pathway"
    init_workspace(workspace)

    for template_name in [
        "start_endpoint_n000.json",
        "update_endpoint_evidence.json",
        "end_endpoint_n000_supported.json",
        "start_candidate_generation.json",
        "update_candidate_evidence.json",
        "end_candidate_generation_supported.json",
        "start_tsfreq_validation.json",
        "update_tsfreq_evidence.json",
        "end_tsfreq_validation_supported.json",
        "start_connectivity_validation.json",
        "update_connectivity_evidence.json",
        "end_connectivity_validation_supported.json",
        "start_accepted_audit.json",
        "end_accepted_audit_supported.json",
        "start_pathway_audit.json",
        "update_pathway_audit_accepted.json",
        "end_pathway_audit_accepted.json",
    ]:
        _apply_template(workspace, template_name)

    report = report_workspace(workspace)
    assert report["hypothesis_context"]["required_next_evidence"] == []
    assert report["hypothesis_context"]["open_predictions"] == []
    assert report["hypothesis_context"]["pathway_audits"][-1]["audit_outcome"] == "accepted"
    assert validate_workspace(workspace)["valid"] is True


def test_replacement_branch_template_requires_explicit_backtrack_context(tmp_path: Path) -> None:
    workspace = tmp_path / "replacement_branch"
    init_workspace(workspace)
    for template_name in [
        "start_endpoint_n000.json",
        "update_endpoint_evidence.json",
        "end_endpoint_n000_supported.json",
        "start_candidate_generation.json",
    ]:
        _apply_template(workspace, template_name)

    refuted_close = _with_report_ref(workspace, _render_template("end_candidate_generation_supported.json"))
    refuted_close["payload"]["closure"]["claim_verdict"] = "refuted"
    refuted_close["payload"]["closure"]["mechanism"]["summary"] = "Candidate-generation prediction was refuted."
    refuted_close["payload"]["closure"]["mechanism"]["revision"] = {
        "action": "refute_prediction",
        "prediction_ids": ["pred_candidate_001"],
        "changed_variable": "reaction_center",
    }
    _apply_decision(workspace, refuted_close)

    replacement = _with_report_ref(workspace, _render_template("start_replacement_branch.json"))
    validate_decision_for_workspace(workspace, replacement)
    started = start_node(workspace, replacement)

    assert started["node_id"] == "n002"
    tree = json.loads((workspace / "tree.json").read_text(encoding="utf-8"))
    assert tree["backtrack_events"][-1]["from_node"] == "n001"
    assert tree["backtrack_events"][-1]["to_node"] == "n000"
    assert tree["backtrack_events"][-1]["changed_variable"] == "reaction_center"


def _apply_template(workspace: Path, template_name: str) -> dict[str, Any]:
    return _apply_decision(workspace, _with_report_ref(workspace, _render_template(template_name)))


def _apply_decision(workspace: Path, decision: dict[str, Any]) -> dict[str, Any]:
    action = decision["action"]
    if action == "start_node":
        validate_decision_for_workspace(workspace, decision)
        return start_node(workspace, decision)
    if action == "update_workspace":
        validate_decision(decision)
        return update_workspace(workspace, decision)
    if action == "end_node":
        validate_decision_for_workspace(workspace, decision)
        return end_node(workspace, decision)
    raise AssertionError(f"unsupported template action in test: {action}")


def _with_report_ref(workspace: Path, decision: dict[str, Any]) -> dict[str, Any]:
    report = report_workspace(workspace)
    decision = json.loads(json.dumps(decision))
    decision["report_ref"] = {"report_id": report["report_id"], "workspace_root": str(workspace)}
    return decision


def _render_template(template_name: str, **overrides: str) -> dict[str, Any]:
    path = TEMPLATE_DIR / template_name
    text = path.read_text(encoding="utf-8")
    values = {**DEFAULT_VALUES, **overrides}
    missing = sorted(set(PLACEHOLDER_RE.findall(text)) - set(values))
    assert not missing, f"{template_name} has unmapped placeholders: {missing}"
    for key, value in values.items():
        text = text.replace("${" + key + "}", str(value))
    remaining = PLACEHOLDER_RE.findall(text)
    assert not remaining, f"{template_name} still has placeholders: {remaining}"
    return json.loads(text)
