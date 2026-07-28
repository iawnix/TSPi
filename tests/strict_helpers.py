from __future__ import annotations

from pathlib import Path
from typing import Any

from ts_workspace import end_node, init_workspace, report_workspace, start_node, update_workspace


HYPOTHESIS_ID = "hyp_0001"
HYPOTHESIS_REF = {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": ["pred_mode_001", "pred_conn_001"]}
PATHWAY_REF = {"pathway_id": "p_single", "step_id": "s1"}


def initial_mechanism_hypothesis(
    *,
    pathway_ref: dict[str, str] | None = None,
    stereochemical: bool = False,
    identity_claim: bool = False,
) -> dict[str, Any]:
    hypothesis = {
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
        "mechanism_claims": [
            {
                "claim_id": "claim_reaction_center_001",
                "claim_type": "reaction_center_motif",
                "subject": "C1-N2 reaction center",
                "subject_type": "reaction_center",
                "summary": "The candidate should preserve the declared local reaction-center motif.",
                "geometry_reflection_plan": {
                    "reaction_center_metrics": ["C1-N2 distance"],
                    "unwanted_short_contacts": [],
                    "decision_boundary": "Reject if the candidate falls into a different local motif.",
                },
                "electronic_structure_reflection_plan": {
                    "diagnostics": ["method-available population sanity checks"],
                    "decision_boundary": "Do not infer electronic timing from geometry alone.",
                },
                "required_evidence_roles": [],
            }
        ],
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
    if stereochemical:
        hypothesis["structured_claim"]["stereochemical_policy"] = {
            "endpoint_policy": "retain_explicit_stereocenters",
            "checks": [
                {
                    "type": "tetrahedral",
                    "center": 1,
                    "neighbors": [0, 2, 3, 4],
                    "policy": "retain",
                }
            ],
        }
        hypothesis["testable_predictions"].append(
            {
                "prediction_id": "pred_stereo_001",
                "phase": "connectivity_validation",
                "expectation": "IRC endpoints preserve the declared stereochemical assignment.",
                "required_evidence_roles": ["stereochemical_connectivity_gate"],
            }
        )
        hypothesis["required_evidence"].append("stereochemical_connectivity_gate")
    if identity_claim:
        hypothesis["mechanism_claims"].append(
            {
                "claim_id": "claim_intermediate_identity_001",
                "claim_type": "intermediate_identity",
                "subject": "shared intermediate",
                "subject_type": "intermediate",
                "summary": "The mechanism uses a declared intermediate identity.",
                "geometry_reflection_plan": {
                    "reaction_center_metrics": ["C1-N2 and unintended short contacts"],
                    "motif_or_coordination_checks": ["local valence"],
                    "decision_boundary": "Reject the identity label if the basin has a different local motif.",
                },
                "electronic_structure_reflection_plan": {
                    "diagnostics": ["NPA/NBO or method-available population diagnostics"],
                    "decision_boundary": "Do not claim this identity from IRC endpoint assignment alone.",
                },
                "state_character_reflection_plan": {
                    "diagnostics": ["spin/state comparison when needed"],
                    "decision_boundary": "Do not claim state character without state evidence.",
                },
                "required_evidence_roles": ["intermediate_identity_gate"],
            }
        )
        hypothesis["required_evidence"].append("intermediate_identity_gate")
    return hypothesis


def bootstrap_strict_workspace(
    workspace: Path,
    *,
    pathway_ref: dict[str, str] | None = None,
    stereochemical: bool = False,
    identity_claim: bool = False,
) -> dict[str, str]:
    init_workspace(workspace)
    report_ref = _report_ref(workspace)
    hypothesis = initial_mechanism_hypothesis(
        pathway_ref=pathway_ref,
        stereochemical=stereochemical,
        identity_claim=identity_claim,
    )
    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Start endpoint validation and hypothesis generation.",
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
            "rationale": "Close endpoint validation with a structured hypothesis.",
            "evidence_refs": ["ev_hyp_0001", "ev_endpoint_0001"],
            "report_ref": report_ref,
            "payload": {
                "node_id": "n000",
                "closure": {
                    "program_status": "completed",
                    "claim_verdict": "supported",
                    "program": {"summary": "Endpoint validation completed.", "evidence_refs": ["ev_endpoint_0001"]},
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
    branch_context: dict[str, Any] | None = None,
    solution_ref: dict[str, Any] | None = None,
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
        "branch_context": branch_context or {
            "relation": "continue_parent",
            "from_node": parent_node,
            "anchor_node": "n000",
        },
    }
    if pathway_ref is not None:
        payload["pathway_ref"] = pathway_ref
    if solution_ref is not None:
        payload["solution_ref"] = solution_ref
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


def make_accepted_workspace(
    workspace: Path,
    *,
    stereochemical: bool = False,
    identity_claim: bool = False,
) -> dict[str, str]:
    report_ref = bootstrap_strict_workspace(
        workspace,
        pathway_ref=PATHWAY_REF,
        stereochemical=stereochemical,
        identity_claim=identity_claim,
    )

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
            **gate_artifact_metadata("nodes/n001/outputs/tsfreq_validation.json"),
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
    connectivity_evidence: list[dict[str, Any]] = [
        {
            "evidence_id": "ev_conn_001",
            "kind": "irc_connectivity_validation",
            "role": "connectivity_gate",
            "evidence_tier": "local_parse",
            "node_id": "n002",
            "summary": "Forward and reverse endpoints match the expected reactant/product basins.",
            **gate_artifact_metadata("nodes/n002/outputs/connectivity_validation.json"),
            "quality": {
                "hypothesis_id": HYPOTHESIS_ID,
                "prediction_ids": ["pred_conn_001"],
                "verdict_against_prediction": "supported",
                "strict_irc_complete": True,
                "irc_program_failures": [],
                "irc_directions": {
                    "forward": {"normal_termination": True, "assignment": "product"},
                    "reverse": {"normal_termination": True, "assignment": "reactant"},
                },
                "forward_assignment": "product",
                "reverse_assignment": "reactant",
            },
        }
    ]
    if stereochemical:
        connectivity_evidence.append(
            {
                "evidence_id": "ev_stereo_001",
                "kind": "stereochemical_connectivity_validation",
                "role": "stereochemical_connectivity_gate",
                "evidence_tier": "local_parse",
                "node_id": "n002",
                "summary": "Declared stereochemical checks are matched at the assigned IRC endpoints.",
                **gate_artifact_metadata("nodes/n002/outputs/stereochemical_connectivity_validation.json"),
                "quality": {
                    "hypothesis_id": HYPOTHESIS_ID,
                    "prediction_ids": ["pred_stereo_001"],
                    "verdict_against_prediction": "supported",
                    "stereochemical_verdict": "matched",
                    "stereochemistry_matched": True,
                    "stereochemical_mismatches": [],
                    "stereochemical_checks": [
                        {
                            "type": "tetrahedral",
                            "center": 1,
                            "policy": "retain",
                            "verdict": "matched",
                        }
                    ],
                },
            }
        )
    if identity_claim:
        connectivity_evidence.append(
            {
                "evidence_id": "ev_identity_001",
                "kind": "intermediate_identity_audit",
                "role": "intermediate_identity_gate",
                "evidence_tier": "local_parse",
                "node_id": "n002",
                "summary": "Declared intermediate identity is supported with the stated boundary.",
                **gate_artifact_metadata("nodes/n002/outputs/intermediate_identity.json"),
                "quality": {
                    "hypothesis_id": HYPOTHESIS_ID,
                    "prediction_ids": ["pred_conn_001"],
                    "intermediate_identity_gate_completed": True,
                    "verdict_against_declared_claim": "supported_with_boundary",
                },
            }
        )
    _append_evidence(workspace, report_ref, connectivity_evidence)
    end_v3_node(
        workspace,
        report_ref,
        node_id="n002",
        claim_verdict="supported",
        evidence_refs=[item["evidence_id"] for item in connectivity_evidence],
        prediction_ids=["pred_conn_001"] + (["pred_stereo_001"] if stereochemical else []),
    )

    report_ref = _report_ref(workspace)
    gate_refs = ["ev_tsfreq_001", "ev_conn_001"] + (["ev_stereo_001"] if stereochemical else [])
    if identity_claim:
        gate_refs.append("ev_identity_001")
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


def make_branch_workspace(workspace: Path) -> dict[str, str]:
    report_ref = bootstrap_strict_workspace(workspace)
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
        branch_context={
            "relation": "new_pathway_branch",
            "from_node": "n001",
            "anchor_node": "n000",
            "changed_variable": "reaction_center",
            "reason_code": "connectivity_refuted",
            "evidence_refs": [],
        },
    )
    return _report_ref(workspace)


def gate_artifact_metadata(source_file: str) -> dict[str, Any]:
    return {
        "source_files": [source_file],
        "source_sha256": "0" * 64,
        "parser_name": "test_parser",
        "parser_version": "1.0",
        "normal_termination": True,
        "diagnostics": [],
    }


def _append_evidence(workspace: Path, report_ref: dict[str, str], evidence: dict[str, Any] | list[dict[str, Any]]) -> None:
    entries = evidence if isinstance(evidence, list) else [evidence]
    roles = ",".join(str(item.get("role", "")) for item in entries)
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": f"Register {roles} evidence.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {"append_evidence": evidence},
        },
    )


def _report_ref(workspace: Path) -> dict[str, str]:
    report = report_workspace(workspace)
    return {"report_id": report["report_id"], "workspace_root": str(workspace)}
