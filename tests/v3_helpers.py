from __future__ import annotations

from pathlib import Path
from typing import Any

from ts_workspace import end_node, init_workspace, report_workspace, start_node, update_workspace


HYPOTHESIS_ID = "hyp_0001"
HYPOTHESIS_REF = {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": ["pred_mode_001", "pred_conn_001"]}
PATHWAY_REF = {"pathway_id": "p_single", "step_id": "s1"}


def initial_mechanism_hypothesis(*, pathway_ref: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "hypothesis_id": HYPOTHESIS_ID,
        "summary": "Endpoint-derived single-step C-N formation hypothesis.",
        "derived_from": {
            "reactant_ref": "inputs/reactant.xyz",
            "product_ref": "inputs/product.xyz",
            "charge": 0,
            "multiplicity": 1,
            "atom_mapping_ref": "inputs/atom_mapping.json",
        },
        "structured_claim": {
            "reaction_center": {
                "forming_bonds": [{"atoms": [1, 2], "label": "C1-N2"}],
                "breaking_bonds": [],
                "transferred_atoms": [],
                "spectator_regions": [],
            },
            "reaction_class": ["bond_formation"],
            "elementary_step_model": "concerted",
            "electronic_model": {
                "surface": "ground_state",
                "spin_surface": "singlet",
                "net_electron_transfer": "not_expected",
                "charge_transfer": "possible_but_unconfirmed",
                "spin_density_change": "not_expected",
                "pcet": "not_expected",
            },
            "pathway_ref": pathway_ref or PATHWAY_REF,
        },
        "testable_predictions": [
            {
                "prediction_id": "pred_mode_001",
                "phase": "tsfreq_validation",
                "expectation": "The imaginary mode involves C1-N2 formation.",
                "required_evidence_roles": ["tsfreq_gate", "mode_assignment"],
            },
            {
                "prediction_id": "pred_conn_001",
                "phase": "connectivity_validation",
                "expectation": "Displacement endpoints map to the proposed reactant and product basins.",
                "required_evidence_roles": ["connectivity_gate"],
            },
        ],
        "required_evidence": [
            "endpoint_provenance",
            "charge_multiplicity",
            "atom_mapping",
            "reaction_center_delta",
            "initial_mechanism_hypothesis",
            "tsfreq_gate",
            "connectivity_gate",
        ],
        "uncertainties": ["Endpoint geometry does not prove the electronic timing."],
        "alternative_hypotheses": [{"summary": "Stepwise C-N formation.", "changed_variable": "elementary_step_order"}],
        "evidence_refs": ["ev_hyp_0001"],
    }


def bootstrap_v3_workspace(workspace: Path, *, pathway_ref: dict[str, str] | None = None) -> dict[str, str]:
    init_workspace(workspace)
    report_ref = _report_ref(workspace)
    hypothesis = initial_mechanism_hypothesis(pathway_ref=pathway_ref)
    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Start endpoint hypothesis preflight.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "node_id": "n000",
                "phase": "endpoint",
                "hypothesis": "Initial endpoint-derived mechanism hypothesis.",
                "initial_mechanism_hypothesis": hypothesis,
                "expected_evidence": [
                    "endpoint_provenance",
                    "charge_multiplicity",
                    "atom_mapping",
                    "reaction_center_delta",
                    "initial_mechanism_hypothesis",
                ],
            },
        },
    )
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register endpoint-derived hypothesis evidence.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": [
                    {
                        "evidence_id": "ev_hyp_0001",
                        "kind": "mechanism_hypothesis",
                        "role": "initial_mechanism_hypothesis",
                        "evidence_tier": "hypothesis",
                        "node_id": "n000",
                        "summary": "Endpoint-derived C-N formation hypothesis.",
                        "quality": {"hypothesis_id": HYPOTHESIS_ID, "uncertainty": "medium"},
                    },
                    {
                        "evidence_id": "ev_endpoint_0001",
                        "kind": "endpoint_delta",
                        "role": "reaction_center_delta",
                        "evidence_tier": "manual_observation",
                        "node_id": "n000",
                        "summary": "C1-N2 is the dominant endpoint bond change.",
                        "quality": {"hypothesis_id": HYPOTHESIS_ID},
                    },
                ]
            },
        },
    )
    end_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "end_node",
            "rationale": "Close endpoint preflight with a structured hypothesis.",
            "evidence_refs": ["ev_hyp_0001", "ev_endpoint_0001"],
            "report_ref": report_ref,
            "payload": {
                "node_id": "n000",
                "closure": {
                    "program_status": "completed",
                    "claim_verdict": "supported",
                    "program": {"summary": "Endpoint preflight completed.", "evidence_refs": ["ev_endpoint_0001"]},
                    "mechanism": {"summary": "Initial mechanism hypothesis is ready.", "evidence_refs": ["ev_hyp_0001"]},
                    "implication": "Open a hypothesis-referenced search node.",
                    "open_questions": [],
                },
            },
        },
    )
    return _report_ref(workspace)


def start_v3_node(
    workspace: Path,
    report_ref: dict[str, str],
    *,
    node_id: str,
    phase: str,
    parent_node: str = "n000",
    pathway_ref: dict[str, str] | None = None,
    prediction_ids: list[str] | None = None,
    backtrack: dict[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
) -> None:
    ref = {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": prediction_ids or ["pred_mode_001"]}
    payload: dict[str, Any] = {
        "node_id": node_id,
        "parent_node": parent_node,
        "phase": phase,
        "hypothesis": f"Test {phase} under {HYPOTHESIS_ID}.",
        "hypothesis_ref": ref,
        "expected_evidence": [],
    }
    if pathway_ref is not None:
        payload["pathway_ref"] = pathway_ref
    if backtrack is not None:
        payload["backtrack"] = backtrack
    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": f"Start {node_id}.",
            "evidence_refs": evidence_refs or [],
            "report_ref": report_ref,
            "payload": payload,
        },
    )


def end_v3_node(
    workspace: Path,
    report_ref: dict[str, str],
    *,
    node_id: str,
    claim_verdict: str,
    evidence_refs: list[str] | None = None,
    prediction_ids: list[str] | None = None,
    revision: dict[str, Any] | None = None,
) -> None:
    refs = evidence_refs or []
    mechanism: dict[str, Any] = {
        "summary": "Hypothesis prediction was evaluated.",
        "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": prediction_ids or ["pred_mode_001"]},
        "evidence_refs": refs,
    }
    if revision is not None:
        mechanism["revision"] = revision
    end_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "end_node",
            "rationale": f"Close {node_id}.",
            "evidence_refs": refs,
            "report_ref": report_ref,
            "payload": {
                "node_id": node_id,
                "closure": {
                    "program_status": "completed",
                    "claim_verdict": claim_verdict,
                    "program": {"summary": "Program completed.", "evidence_refs": refs},
                    "mechanism": mechanism,
                    "implication": "Choose the next hypothesis test.",
                    "open_questions": [],
                },
            },
        },
    )


def make_accepted_workspace(workspace: Path) -> dict[str, str]:
    report_ref = bootstrap_v3_workspace(workspace, pathway_ref=PATHWAY_REF)

    start_v3_node(
        workspace,
        report_ref,
        node_id="n001",
        phase="tsfreq_validation",
        pathway_ref=PATHWAY_REF,
        prediction_ids=["pred_mode_001"],
    )
    _append_evidence(
        workspace,
        report_ref,
        {
            "evidence_id": "ev_tsfreq_001",
            "kind": "gaussian_tsfreq_validation",
            "role": "tsfreq_gate",
            "evidence_tier": "local_parse",
            "node_id": "n001",
            "summary": "One imaginary mode matches the proposed C-N formation coordinate.",
            "quality": {
                "hypothesis_id": HYPOTHESIS_ID,
                "prediction_ids": ["pred_mode_001"],
                "verdict_against_prediction": "supported",
                "imaginary_frequency_count": 1,
                "mode_verdict": "mode_matches_reaction_center",
            },
        },
    )
    end_v3_node(
        workspace,
        report_ref,
        node_id="n001",
        claim_verdict="supported",
        evidence_refs=["ev_tsfreq_001"],
        prediction_ids=["pred_mode_001"],
    )

    report_ref = _report_ref(workspace)
    start_v3_node(
        workspace,
        report_ref,
        node_id="n002",
        parent_node="n001",
        phase="connectivity_validation",
        pathway_ref=PATHWAY_REF,
        prediction_ids=["pred_conn_001"],
    )
    _append_evidence(
        workspace,
        report_ref,
        {
            "evidence_id": "ev_conn_001",
            "kind": "irc_connectivity_validation",
            "role": "connectivity_gate",
            "evidence_tier": "local_parse",
            "node_id": "n002",
            "summary": "Forward and reverse endpoints match the expected reactant/product basins.",
            "quality": {
                "hypothesis_id": HYPOTHESIS_ID,
                "prediction_ids": ["pred_conn_001"],
                "verdict_against_prediction": "supported",
                "forward_assignment": "product",
                "reverse_assignment": "reactant",
            },
        },
    )
    end_v3_node(
        workspace,
        report_ref,
        node_id="n002",
        claim_verdict="supported",
        evidence_refs=["ev_conn_001"],
        prediction_ids=["pred_conn_001"],
    )

    report_ref = _report_ref(workspace)
    gate_refs = ["ev_tsfreq_001", "ev_conn_001"]
    start_v3_node(
        workspace,
        report_ref,
        node_id="n003",
        parent_node="n002",
        phase="accepted_audit",
        pathway_ref=PATHWAY_REF,
        prediction_ids=["pred_mode_001", "pred_conn_001"],
        evidence_refs=gate_refs,
    )
    end_v3_node(
        workspace,
        report_ref,
        node_id="n003",
        claim_verdict="supported",
        evidence_refs=gate_refs,
        prediction_ids=["pred_mode_001", "pred_conn_001"],
    )
    return _report_ref(workspace)


def make_backtrack_workspace(workspace: Path) -> dict[str, str]:
    report_ref = bootstrap_v3_workspace(workspace)
    start_v3_node(
        workspace,
        report_ref,
        node_id="n001",
        phase="connectivity_validation",
        pathway_ref=PATHWAY_REF,
        prediction_ids=["pred_conn_001"],
    )
    end_v3_node(
        workspace,
        report_ref,
        node_id="n001",
        claim_verdict="refuted",
        prediction_ids=["pred_conn_001"],
        revision={
            "action": "refute_prediction",
            "prediction_ids": ["pred_conn_001"],
            "changed_variable": "reaction_center",
        },
    )

    report_ref = _report_ref(workspace)
    start_v3_node(
        workspace,
        report_ref,
        node_id="n002",
        parent_node="n000",
        phase="candidate_generation",
        pathway_ref={"pathway_id": "p_revised", "step_id": "s1"},
        prediction_ids=["pred_mode_001"],
        backtrack={
            "from_node": "n001",
            "to_node": "n000",
            "changed_variable": "reaction_center",
            "reason_code": "connectivity_refuted",
            "evidence_refs": [],
        },
    )
    return _report_ref(workspace)


def _append_evidence(workspace: Path, report_ref: dict[str, str], evidence: dict[str, Any]) -> None:
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": f"Register {evidence['role']} evidence.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {"append_evidence": evidence},
        },
    )


def _report_ref(workspace: Path) -> dict[str, str]:
    report = report_workspace(workspace)
    return {"report_id": report["report_id"], "workspace_root": str(workspace)}
