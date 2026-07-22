from __future__ import annotations

import pytest

from ts_workspace import end_node, init_workspace, report_workspace, start_node, update_workspace, validate_workspace
from ts_workspace.io import read_json, write_json
from strict_helpers import (
    HYPOTHESIS_ID,
    HYPOTHESIS_REF,
    PATHWAY_REF,
    bootstrap_strict_workspace,
    gate_artifact_metadata,
    make_accepted_workspace,
)


def test_accepted_audit_requires_tsfreq_and_connectivity_gates(tmp_path):
    workspace = tmp_path / "ws"
    report_ref = bootstrap_strict_workspace(workspace)

    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Start accepted audit with only one gate registered later.",
            "evidence_refs": ["ev_tsfreq_only"],
            "report_ref": report_ref,
            "payload": {
                "phase": "accepted_audit",
                "parent_node": "n000",
                "hypothesis": "A candidate should not be accepted with only one evidence gate.",
                "hypothesis_ref": HYPOTHESIS_REF,
                "branch_context": {"relation": "continue_parent", "from_node": "n000", "anchor_node": "n000"},
                "expected_evidence": ["tsfreq_gate", "connectivity_gate"],
            },
        },
    )
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register only TS/Freq evidence.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": {
                    "evidence_id": "ev_tsfreq_only",
                    "kind": "gaussian_frequency",
                    "role": "tsfreq_gate",
                    "evidence_tier": "local_parse",
                    "node_id": "n001",
                    "summary": "One imaginary mode supports the candidate.",
                    **gate_artifact_metadata("nodes/n001/outputs/tsfreq_only.json"),
                    "quality": {"hypothesis_id": HYPOTHESIS_ID},
                }
            },
        },
    )

    with pytest.raises(ValueError, match="connectivity_gate"):
        end_node(
            workspace,
            {
                "schema_version": "ts-decision",
                "action": "end_node",
                "rationale": "Attempt to close accepted audit without connectivity evidence.",
                "evidence_refs": ["ev_tsfreq_only"],
                "report_ref": report_ref,
                "payload": {
                    "node_id": "n001",
                    "closure": {
                        "program_status": "completed",
                        "claim_verdict": "supported",
                        "program": {"summary": "Audit ran.", "evidence_refs": ["ev_tsfreq_only"]},
                        "mechanism": {
                            "summary": "Only one gate is available.",
                            "hypothesis_ref": HYPOTHESIS_REF,
                            "evidence_refs": ["ev_tsfreq_only"],
                        },
                        "implication": "This should not create an accepted artifact.",
                        "open_questions": [],
                    },
                },
            },
        )
    node = read_json(workspace / "nodes" / "n001" / "node.json")
    assert node["lifecycle"] == "running"
    assert node["closure"] is None


def test_accepted_audit_rejects_endpoint_recovery_after_failed_irc(tmp_path):
    workspace = tmp_path / "ws"
    report_ref = bootstrap_strict_workspace(workspace)

    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Start accepted audit with failed-IRC connectivity evidence.",
            "evidence_refs": ["ev_tsfreq", "ev_conn_failed_irc"],
            "report_ref": report_ref,
            "payload": {
                "phase": "accepted_audit",
                "parent_node": "n000",
                "hypothesis": "A candidate must not be accepted when mandatory IRC failed.",
                "hypothesis_ref": HYPOTHESIS_REF,
                "branch_context": {"relation": "continue_parent", "from_node": "n000", "anchor_node": "n000"},
                "expected_evidence": ["tsfreq_gate", "connectivity_gate"],
            },
        },
    )
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register TS/Freq and failed-IRC endpoint-recovery evidence.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": [
                    {
                        "evidence_id": "ev_tsfreq",
                        "kind": "gaussian_tsfreq_validation",
                        "role": "tsfreq_gate",
                        "evidence_tier": "local_parse",
                        "node_id": "n001",
                        "summary": "One imaginary mode supports the candidate.",
                        **gate_artifact_metadata("nodes/n001/outputs/tsfreq.json"),
                        "quality": {"hypothesis_id": HYPOTHESIS_ID},
                    },
                    {
                        "evidence_id": "ev_conn_failed_irc",
                        "kind": "irc_connectivity_validation",
                        "role": "connectivity_gate",
                        "evidence_tier": "local_parse",
                        "node_id": "n001",
                        "summary": "IRC endpoints optimize to R/P, but both IRC jobs ended by corrector failure.",
                        **gate_artifact_metadata("nodes/n001/outputs/failed_irc.json"),
                        "quality": {
                            "hypothesis_id": HYPOTHESIS_ID,
                            "strict_irc_complete": False,
                            "irc_program_failures": [
                                {"direction": "forward", "type": "corrector_convergence", "point": 87},
                                {"direction": "reverse", "type": "corrector_convergence", "point": 74},
                            ],
                            "irc_directions": {
                                "forward": {"normal_termination": False, "assignment": "reactant"},
                                "reverse": {"normal_termination": False, "assignment": "product"},
                            },
                            "endpoint_optimization_recovery_used": True,
                            "verdict_against_prediction": "endpoint_basin_supported_but_strict_irc_incomplete",
                        },
                    },
                ]
            },
        },
    )

    with pytest.raises(ValueError, match="strict_irc_complete=true"):
        end_node(
            workspace,
            {
                "schema_version": "ts-decision",
                "action": "end_node",
                "rationale": "Attempt to close accepted audit with failed IRC.",
                "evidence_refs": ["ev_tsfreq", "ev_conn_failed_irc"],
                "report_ref": report_ref,
                "payload": {
                    "node_id": "n001",
                    "closure": {
                        "program_status": "completed",
                        "claim_verdict": "supported",
                        "program": {"summary": "Audit ran.", "evidence_refs": ["ev_tsfreq", "ev_conn_failed_irc"]},
                        "mechanism": {
                            "summary": "Endpoint recovery is not strict IRC completion.",
                            "hypothesis_ref": HYPOTHESIS_REF,
                            "evidence_refs": ["ev_tsfreq", "ev_conn_failed_irc"],
                        },
                        "implication": "This should stay open for follow-up IRC.",
                        "open_questions": [],
                    },
                },
            },
        )
    node = read_json(workspace / "nodes" / "n001" / "node.json")
    manifest = read_json(workspace / "manifest.json")
    assert node["lifecycle"] == "running"
    assert node["closure"] is None
    assert manifest["accepted_ts_refs"] == []


def test_workspace_validator_rejects_existing_non_strict_accepted_connectivity(tmp_path):
    workspace = tmp_path / "ws"
    make_accepted_workspace(workspace)

    registry_path = workspace / "evidence_registry.json"
    registry = read_json(registry_path)
    for record in registry["evidence"]:
        if record.get("evidence_id") == "ev_conn_001":
            record["quality"]["strict_irc_complete"] = False
            record["quality"]["irc_program_failures"] = [
                {"direction": "forward", "type": "corrector_convergence", "point": 87}
            ]
            record["quality"]["irc_directions"]["forward"]["normal_termination"] = False
    write_json(registry_path, registry)

    validation = validate_workspace(workspace)
    assert validation["valid"] is False
    assert any(item["code"] == "non_strict_accepted_ts_connectivity" for item in validation["findings"])


def test_stereochemical_hypothesis_requires_stereo_gate_for_acceptance(tmp_path):
    workspace = tmp_path / "ws"
    report_ref = bootstrap_strict_workspace(workspace, stereochemical=True)

    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Start accepted audit without declared stereochemical gate.",
            "evidence_refs": ["ev_tsfreq", "ev_conn"],
            "report_ref": report_ref,
            "payload": {
                "phase": "accepted_audit",
                "parent_node": "n000",
                "hypothesis": "Stereo-sensitive hypothesis cannot be accepted without stereo gate.",
                "hypothesis_ref": HYPOTHESIS_REF,
                "branch_context": {"relation": "continue_parent", "from_node": "n000", "anchor_node": "n000"},
                "expected_evidence": ["tsfreq_gate", "connectivity_gate", "stereochemical_connectivity_gate"],
            },
        },
    )
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register only TS/Freq and connectivity evidence.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": [
                    {
                        "evidence_id": "ev_tsfreq",
                        "kind": "gaussian_tsfreq_validation",
                        "role": "tsfreq_gate",
                        "evidence_tier": "local_parse",
                        "node_id": "n001",
                        "summary": "One imaginary mode supports the candidate.",
                        **gate_artifact_metadata("nodes/n001/outputs/stereo_tsfreq.json"),
                        "quality": {"hypothesis_id": HYPOTHESIS_ID},
                    },
                    {
                        "evidence_id": "ev_conn",
                        "kind": "irc_connectivity_validation",
                        "role": "connectivity_gate",
                        "evidence_tier": "local_parse",
                        "node_id": "n001",
                        "summary": "Strict bidirectional IRC reached assigned basins.",
                        **gate_artifact_metadata("nodes/n001/outputs/stereo_connectivity.json"),
                        "quality": {
                            "hypothesis_id": HYPOTHESIS_ID,
                            "strict_irc_complete": True,
                            "irc_program_failures": [],
                            "irc_directions": {
                                "forward": {"normal_termination": True, "assignment": "product"},
                                "reverse": {"normal_termination": True, "assignment": "reactant"},
                            },
                        },
                    },
                ]
            },
        },
    )

    with pytest.raises(ValueError, match="stereochemical_connectivity_gate"):
        end_node(
            workspace,
            {
                "schema_version": "ts-decision",
                "action": "end_node",
                "rationale": "Attempt accepted closure without stereo gate.",
                "evidence_refs": ["ev_tsfreq", "ev_conn"],
                "report_ref": report_ref,
                "payload": {
                    "node_id": "n001",
                    "closure": {
                        "program_status": "completed",
                        "claim_verdict": "supported",
                        "program": {"summary": "Audit ran.", "evidence_refs": ["ev_tsfreq", "ev_conn"]},
                        "mechanism": {
                            "summary": "Stereo evidence is missing.",
                            "hypothesis_ref": HYPOTHESIS_REF,
                            "evidence_refs": ["ev_tsfreq", "ev_conn"],
                        },
                        "implication": "This should not create an accepted artifact.",
                        "open_questions": [],
                    },
                },
            },
        )


def test_stereochemical_gate_is_recorded_in_accepted_artifact(tmp_path):
    workspace = tmp_path / "ws"
    make_accepted_workspace(workspace, stereochemical=True)

    manifest = read_json(workspace / "manifest.json")
    artifact = read_json(workspace / manifest["accepted_ts_refs"][0])

    assert "stereochemical_connectivity_gate" in artifact["required_gates"]
    assert "ev_stereo_001" in artifact["evidence_refs"]
    assert validate_workspace(workspace)["valid"] is True


def test_workspace_validator_rejects_stereo_required_accepted_artifact_missing_stereo_gate(tmp_path):
    workspace = tmp_path / "ws"
    make_accepted_workspace(workspace, stereochemical=True)

    manifest = read_json(workspace / "manifest.json")
    artifact_path = workspace / manifest["accepted_ts_refs"][0]
    artifact = read_json(artifact_path)
    artifact["evidence_refs"] = [item for item in artifact["evidence_refs"] if item != "ev_stereo_001"]
    write_json(artifact_path, artifact)

    validation = validate_workspace(workspace)
    assert validation["valid"] is False
    assert any(item["code"] == "invalid_accepted_ts_gates" for item in validation["findings"])


def test_workspace_validator_rejects_failed_stereo_gate(tmp_path):
    workspace = tmp_path / "ws"
    make_accepted_workspace(workspace, stereochemical=True)

    registry_path = workspace / "evidence_registry.json"
    registry = read_json(registry_path)
    for record in registry["evidence"]:
        if record.get("evidence_id") == "ev_stereo_001":
            record["quality"]["stereochemistry_matched"] = False
            record["quality"]["stereochemical_verdict"] = "mismatched"
    write_json(registry_path, registry)

    validation = validate_workspace(workspace)
    assert validation["valid"] is False
    assert any(item["code"] == "invalid_accepted_ts_stereochemistry" for item in validation["findings"])


def test_accepted_audit_requires_declared_intermediate_identity_gate(tmp_path):
    workspace = tmp_path / "ws"
    report_ref = bootstrap_strict_workspace(workspace, identity_claim=True)

    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Start accepted audit without the declared intermediate identity gate.",
            "evidence_refs": ["ev_tsfreq", "ev_conn"],
            "report_ref": report_ref,
            "payload": {
                "phase": "accepted_audit",
                "parent_node": "n000",
                "hypothesis": "Identity-sensitive hypothesis cannot be accepted without identity evidence.",
                "hypothesis_ref": HYPOTHESIS_REF,
                "branch_context": {"relation": "continue_parent", "from_node": "n000", "anchor_node": "n000"},
                "expected_evidence": ["tsfreq_gate", "connectivity_gate", "intermediate_identity_gate"],
            },
        },
    )
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register TS/Freq and strict connectivity only.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": [
                    {
                        "evidence_id": "ev_tsfreq",
                        "kind": "gaussian_tsfreq_validation",
                        "role": "tsfreq_gate",
                        "evidence_tier": "local_parse",
                        "node_id": "n001",
                        "summary": "One imaginary mode supports the candidate.",
                        **gate_artifact_metadata("nodes/n001/outputs/identity_tsfreq.json"),
                        "quality": {"hypothesis_id": HYPOTHESIS_ID},
                    },
                    {
                        "evidence_id": "ev_conn",
                        "kind": "irc_connectivity_validation",
                        "role": "connectivity_gate",
                        "evidence_tier": "local_parse",
                        "node_id": "n001",
                        "summary": "Strict bidirectional IRC reached assigned basins.",
                        **gate_artifact_metadata("nodes/n001/outputs/identity_connectivity.json"),
                        "quality": {
                            "hypothesis_id": HYPOTHESIS_ID,
                            "strict_irc_complete": True,
                            "irc_program_failures": [],
                            "irc_directions": {
                                "forward": {"normal_termination": True, "assignment": "product"},
                                "reverse": {"normal_termination": True, "assignment": "reactant"},
                            },
                        },
                    },
                ]
            },
        },
    )

    with pytest.raises(ValueError, match="intermediate_identity_gate"):
        end_node(
            workspace,
            {
                "schema_version": "ts-decision",
                "action": "end_node",
                "rationale": "Attempt accepted closure without identity gate.",
                "evidence_refs": ["ev_tsfreq", "ev_conn"],
                "report_ref": report_ref,
                "payload": {
                    "node_id": "n001",
                    "closure": {
                        "program_status": "completed",
                        "claim_verdict": "supported",
                        "program": {"summary": "Audit ran.", "evidence_refs": ["ev_tsfreq", "ev_conn"]},
                        "mechanism": {
                            "summary": "Identity evidence is missing.",
                            "hypothesis_ref": HYPOTHESIS_REF,
                            "evidence_refs": ["ev_tsfreq", "ev_conn"],
                        },
                        "implication": "This should not create an accepted artifact.",
                        "open_questions": [],
                    },
                },
            },
        )


def test_declared_identity_gate_is_recorded_in_accepted_artifact(tmp_path):
    workspace = tmp_path / "ws"
    make_accepted_workspace(workspace, identity_claim=True)

    manifest = read_json(workspace / "manifest.json")
    artifact = read_json(workspace / manifest["accepted_ts_refs"][0])

    assert "intermediate_identity_gate" in artifact["required_gates"]
    assert "ev_identity_001" in artifact["evidence_refs"]
    assert validate_workspace(workspace)["valid"] is True


def test_workspace_validator_rejects_identity_required_accepted_artifact_missing_identity_gate(tmp_path):
    workspace = tmp_path / "ws"
    make_accepted_workspace(workspace, identity_claim=True)

    manifest = read_json(workspace / "manifest.json")
    artifact_path = workspace / manifest["accepted_ts_refs"][0]
    artifact = read_json(artifact_path)
    artifact["evidence_refs"] = [item for item in artifact["evidence_refs"] if item != "ev_identity_001"]
    write_json(artifact_path, artifact)

    validation = validate_workspace(workspace)
    assert validation["valid"] is False
    assert any(item["code"] == "invalid_accepted_ts_mechanism_reflection_gates" for item in validation["findings"])


def test_pathway_audit_close_requires_strict_pathway_decision(tmp_path):
    workspace = tmp_path / "ws"
    report_ref = make_accepted_workspace(workspace)

    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Start pathway audit with an explicit pathway reference.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "phase": "pathway_audit",
                "parent_node": "n003",
                "hypothesis": "Pathway audit must record a strict decision.",
                "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": ["pred_pathway_001"]},
                "branch_context": {"relation": "continue_parent", "from_node": "n003", "anchor_node": "n000"},
                "pathway_ref": PATHWAY_REF,
                "expected_evidence": ["pathway_audit_summary"],
            },
        },
    )
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register pathway audit evidence without the strict decision.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": {
                    "evidence_id": "ev_pathway_missing_decision",
                    "kind": "pathway_audit",
                    "role": "pathway_audit_summary",
                    "evidence_tier": "local_parse",
                    "node_id": "n004",
                    "summary": "The pathway audit evidence omits the strict pathway decision.",
                    **gate_artifact_metadata("nodes/n004/outputs/pathway_audit.json"),
                    "quality": {
                        "hypothesis_id": HYPOTHESIS_ID,
                        "strict_pathway_supported": True,
                    },
                }
            },
        },
    )

    with pytest.raises(ValueError, match="quality.strict_pathway_decision"):
        end_node(
            workspace,
            {
                "schema_version": "ts-decision",
                "action": "end_node",
                "rationale": "Attempt pathway audit close without strict decision evidence.",
                "evidence_refs": ["ev_pathway_missing_decision"],
                "report_ref": report_ref,
                "payload": {
                    "node_id": "n004",
                    "closure": {
                        "program_status": "completed",
                        "claim_verdict": "supported",
                        "program": {"summary": "Audit ran.", "evidence_refs": ["ev_pathway_missing_decision"]},
                        "mechanism": {
                            "summary": "Pathway is claimed accepted without strict decision evidence.",
                            "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": ["pred_pathway_001"]},
                            "evidence_refs": ["ev_pathway_missing_decision"],
                        },
                        "implication": "This should not close.",
                        "open_questions": [],
                    },
                },
            },
        )

    node = read_json(workspace / "nodes" / "n004" / "node.json")
    assert node["lifecycle"] == "running"
    validation = validate_workspace(workspace)
    assert validation["valid"] is True


def test_pathway_audit_acceptance_requires_declared_identity_gate(tmp_path):
    workspace = tmp_path / "ws"
    report_ref = make_accepted_workspace(workspace, identity_claim=True)

    start_node(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "start_node",
            "rationale": "Start pathway audit without carrying the declared identity gate.",
            "evidence_refs": ["ev_pathway"],
            "report_ref": report_ref,
            "payload": {
                "phase": "pathway_audit",
                "parent_node": "n003",
                "hypothesis": "Accepted pathway audit still needs declared identity evidence.",
                "hypothesis_ref": {"hypothesis_id": HYPOTHESIS_ID, "prediction_ids": ["pred_pathway_001"]},
                "branch_context": {"relation": "continue_parent", "from_node": "n003", "anchor_node": "n000"},
                "pathway_ref": PATHWAY_REF,
                "expected_evidence": ["pathway_audit_summary", "intermediate_identity_gate"],
            },
        },
    )
    update_workspace(
        workspace,
        {
            "schema_version": "ts-decision",
            "action": "update_workspace",
            "rationale": "Register accepted pathway audit without identity evidence.",
            "evidence_refs": [],
            "report_ref": report_ref,
            "payload": {
                "append_evidence": {
                    "evidence_id": "ev_pathway",
                    "kind": "pathway_audit",
                    "role": "pathway_audit_summary",
                    "evidence_tier": "local_parse",
                    "node_id": "n004",
                    "summary": "The pathway audit claims acceptance.",
                    **gate_artifact_metadata("nodes/n004/outputs/pathway_audit.json"),
                    "quality": {
                        "hypothesis_id": HYPOTHESIS_ID,
                        "strict_pathway_supported": True,
                        "strict_pathway_decision": "accepted",
                    },
                    "facts": {"audit_outcome": "accepted", "whole_R_to_P_pathway_accepted": True},
                }
            },
        },
    )

    with pytest.raises(ValueError, match="intermediate_identity_gate"):
        end_node(
            workspace,
            {
                "schema_version": "ts-decision",
                "action": "end_node",
                "rationale": "Attempt pathway acceptance without identity gate.",
                "evidence_refs": ["ev_pathway"],
                "report_ref": report_ref,
                "payload": {
                    "node_id": "n004",
                    "closure": {
                        "program_status": "completed",
                        "claim_verdict": "supported",
                        "program": {"summary": "Audit ran.", "evidence_refs": ["ev_pathway"]},
                        "mechanism": {
                            "summary": "Pathway is claimed accepted.",
                            "hypothesis_ref": {
                                "hypothesis_id": HYPOTHESIS_ID,
                                "prediction_ids": ["pred_pathway_001"],
                            },
                            "evidence_refs": ["ev_pathway"],
                        },
                        "implication": "This should not accept the pathway.",
                        "open_questions": [],
                    },
                },
            },
        )
