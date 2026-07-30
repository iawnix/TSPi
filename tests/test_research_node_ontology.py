from __future__ import annotations

from pathlib import Path

import pytest

from ts_report import build_final_report
from ts_workspace.engine import end_node, init_workspace, report_workspace, start_node, update_workspace
from ts_workspace.io import read_json, write_json
from ts_workspace.validators.decision import ContractError
from ts_workspace.validators.workspace import _validate_branch_contexts
from ts_web.normalize import explorer_graph_payload_from_view, normalize_workspace
from tests.strict_helpers import gate_artifact_metadata


def _report_ref(workspace: Path) -> dict[str, str]:
    report = report_workspace(workspace)
    return {"report_id": report["report_id"], "workspace_root": str(workspace)}


def _decision(
    action: str,
    report_ref: dict[str, str],
    payload: dict,
    *,
    decision_id: str,
    evidence_refs: list[str] | None = None,
) -> dict:
    workspace = Path(report_ref["workspace_root"])
    revision = report_workspace(workspace)["workspace_revision"]
    return {
        "schema_version": "ts-decision/2",
        "decision_id": decision_id,
        "action": action,
        "rationale": f"Apply {action} for ontology test.",
        "evidence_refs": evidence_refs or [],
        "report_ref": report_ref,
        "base_revision": revision,
        "payload": payload,
    }


def _hypothesis() -> dict:
    return {
        "hypothesis_id": "hyp_0001",
        "parent_hypothesis_id": None,
        "summary": "The target structure follows a closed-shell singlet mechanism.",
        "derived_from": {"reactant_ref": "inputs/reactant.xyz", "product_ref": "inputs/product.xyz"},
        "structured_claim": {
            "reaction_center": {"forming_bonds": [{"atoms": [1, 2]}], "breaking_bonds": []},
            "reaction_class": ["bond_formation"],
            "elementary_step_model": "concerted",
            "electronic_model": {"spin_surface": "singlet"},
        },
        "mechanism_claims": [],
        "testable_predictions": [
            {
                "prediction_id": "pred_state_001",
                "validation_scope": "electronic_structure",
                "expectation": "Natural orbital occupations remain consistent with a closed shell.",
                "required_evidence_roles": ["electronic_structure_gate"],
            }
        ],
        "required_evidence": ["electronic_structure_gate"],
        "uncertainties": ["The wavefunction character has not yet been tested."],
        "alternative_hypotheses": [],
        "evidence_refs": [],
    }


def _close_payload(node_id: str, **sections: dict) -> dict:
    closure = {
        "summary": f"Close {node_id}.",
        "program": {"outcome": "not_run", "summary": "No external program was required.", "evidence_refs": []},
        "open_questions": [],
        **sections,
    }
    return {"node_id": node_id, "closure": closure}


def _bootstrap_v2_hypothesis(workspace: Path, hypothesis: dict | None = None) -> None:
    init_workspace(workspace)
    start_node(
        workspace,
        _decision(
            "start_node",
            _report_ref(workspace),
            {"node_id": "n000", "parent_node": None, "node_type": "intake", "objective": "Normalize inputs."},
            decision_id="dec_bootstrap_intake_start",
        ),
    )
    end_node(
        workspace,
        _decision(
            "end_node",
            _report_ref(workspace),
            _close_payload("n000", intake={"status": "ready"}),
            decision_id="dec_bootstrap_intake_end",
        ),
    )
    proposed = hypothesis or _hypothesis()
    start_node(
        workspace,
        _decision(
            "start_node",
            _report_ref(workspace),
            {
                "node_id": "n001",
                "parent_node": "n000",
                "node_type": "mechanism",
                "objective": "Propose a falsifiable mechanism.",
                "mechanism_action": "propose",
                "proposed_hypothesis": proposed,
                "branch_context": {"relation": "continue_parent", "from_node": "n000", "anchor_node": "n000"},
            },
            decision_id="dec_bootstrap_mechanism_start",
        ),
    )
    end_node(
        workspace,
        _decision(
            "end_node",
            _report_ref(workspace),
            _close_payload(
                "n001",
                hypothesis={
                    "status": "ambiguous",
                    "summary": "The hypothesis is explicit but not fully tested.",
                    "evidence_refs": [],
                    "hypothesis_ref": {"hypothesis_id": proposed["hypothesis_id"], "prediction_ids": []},
                },
            ),
            decision_id="dec_bootstrap_mechanism_end",
        ),
    )


def _append_v2_evidence(workspace: Path, evidence: dict, *, decision_id: str) -> None:
    update_workspace(
        workspace,
        _decision(
            "update_workspace",
            _report_ref(workspace),
            {"append_evidence": evidence},
            decision_id=decision_id,
        ),
    )


def _acceptance_hypothesis() -> dict:
    hypothesis = _hypothesis()
    hypothesis["testable_predictions"] = [
        {
            "prediction_id": "pred_tsfreq_001",
            "validation_scope": "tsfreq",
            "expectation": "The candidate is a first-order saddle point.",
            "required_evidence_roles": ["tsfreq_gate"],
        },
        {
            "prediction_id": "pred_connectivity_001",
            "validation_scope": "connectivity",
            "expectation": "The candidate connects the declared endpoint basins.",
            "required_evidence_roles": ["connectivity_gate"],
        },
    ]
    hypothesis["required_evidence"] = ["tsfreq_gate", "connectivity_gate"]
    hypothesis["uncertainties"] = ["TS/Freq and connectivity remain to be tested."]
    return hypothesis


def test_v2_tree_supports_mechanism_falsification_without_compute_authority(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)

    start_node(
        workspace,
        _decision(
            "start_node",
            _report_ref(workspace),
            {"node_id": "n000", "parent_node": None, "node_type": "intake", "objective": "Normalize user inputs."},
            decision_id="dec_intake_start",
        ),
    )
    end_node(
        workspace,
        _decision(
            "end_node",
            _report_ref(workspace),
            _close_payload("n000", intake={"status": "ready"}),
            decision_id="dec_intake_end",
        ),
    )

    start_node(
        workspace,
        _decision(
            "start_node",
            _report_ref(workspace),
            {
                "node_id": "n001",
                "parent_node": "n000",
                "node_type": "mechanism",
                "objective": "Propose a falsifiable mechanism.",
                "mechanism_action": "propose",
                "proposed_hypothesis": _hypothesis(),
                "branch_context": {"relation": "continue_parent", "from_node": "n000", "anchor_node": "n000"},
            },
            decision_id="dec_mechanism_start",
        ),
    )
    end_node(
        workspace,
        _decision(
            "end_node",
            _report_ref(workspace),
            _close_payload(
                "n001",
                hypothesis={
                    "status": "ambiguous",
                    "summary": "The hypothesis is explicit but untested.",
                    "evidence_refs": [],
                    "hypothesis_ref": {"hypothesis_id": "hyp_0001", "prediction_ids": []},
                },
            ),
            decision_id="dec_mechanism_end",
        ),
    )

    start_node(
        workspace,
        _decision(
            "start_node",
            _report_ref(workspace),
            {
                "node_id": "n002",
                "parent_node": "n001",
                "node_type": "validation",
                "objective": "Test the declared electronic-structure prediction.",
                "validation_scope": "electronic_structure",
                "hypothesis_ref": {"hypothesis_id": "hyp_0001", "prediction_ids": ["pred_state_001"]},
                "branch_context": {"relation": "continue_parent", "from_node": "n001", "anchor_node": "n001"},
            },
            decision_id="dec_validation_start",
        ),
    )
    with pytest.raises(ContractError, match="program facts only"):
        end_node(
            workspace,
            _decision(
                "end_node",
                _report_ref(workspace),
                {
                    "node_id": "n002",
                    "closure": {
                        "summary": "Backend must not decide the hypothesis.",
                        "program": {"outcome": "success", "summary": "Calculation completed.", "evidence_refs": []},
                        "hypothesis": {
                            "status": "unsupported",
                            "summary": "Forbidden backend verdict.",
                            "evidence_refs": [],
                            "hypothesis_ref": {"hypothesis_id": "hyp_0001", "prediction_ids": ["pred_state_001"]},
                        },
                        "open_questions": [],
                    },
                },
                decision_id="dec_validation_bad_end",
            ),
        )
    end_node(
        workspace,
        _decision(
            "end_node",
            _report_ref(workspace),
            {
                "node_id": "n002",
                "closure": {
                    "summary": "Electronic-structure artifacts were produced.",
                    "program": {"outcome": "success", "summary": "Calculation completed.", "evidence_refs": []},
                    "open_questions": [],
                },
            },
            decision_id="dec_validation_end",
        ),
    )

    start_node(
        workspace,
        _decision(
            "start_node",
            _report_ref(workspace),
            {
                "node_id": "n003",
                "parent_node": "n002",
                "node_type": "mechanism",
                "objective": "Evaluate whether the electronic evidence falsifies the mechanism.",
                "mechanism_action": "evaluate",
                "hypothesis_ref": {"hypothesis_id": "hyp_0001", "prediction_ids": ["pred_state_001"]},
                "branch_context": {"relation": "continue_parent", "from_node": "n002", "anchor_node": "n002"},
            },
            decision_id="dec_evaluate_start",
        ),
    )
    end_node(
        workspace,
        _decision(
            "end_node",
            _report_ref(workspace),
            _close_payload(
                "n003",
                hypothesis={
                    "status": "unsupported",
                    "summary": "The declared closed-shell prediction is contradicted.",
                    "evidence_refs": [],
                    "hypothesis_ref": {"hypothesis_id": "hyp_0001", "prediction_ids": ["pred_state_001"]},
                    "revision": {"action": "refute_hypothesis", "changed_variable": "state_character"},
                },
            ),
            decision_id="dec_evaluate_end",
        ),
    )

    hypotheses = read_json(workspace / "hypotheses.json")
    assert hypotheses["focus_hypothesis_id"] is None
    assert hypotheses["hypotheses"][0]["status"] == "unsupported"
    assert hypotheses["hypotheses"][0]["assessment_history"][-1]["node_id"] == "n003"
    report = report_workspace(workspace)
    assert report["valid"] is True
    n003_report = next(node for node in report["node_index"] if node["node_id"] == "n003")
    assert n003_report["node_type"] == "mechanism"
    assert n003_report["hypothesis_status"] == "unsupported"

    attempt_id = "calc_n002_wavefunction_001"
    attempt_dir = workspace / "nodes" / "n002" / "attempts" / attempt_id
    intent_ref = f"nodes/n002/attempts/{attempt_id}/intent.json"
    write_json(
        attempt_dir / "intent.json",
        {
            "schema_version": "ts-calculation-intent/2",
            "intent_id": attempt_id,
            "node_id": "n002",
            "purpose": "Evaluate the electronic-structure prediction.",
            "validation_scope": "electronic_structure",
            "attempt_kind": "primary",
            "recalculation_ref": None,
            "backend": "gaussian",
            "task_type": "sp",
        },
    )
    write_json(
        attempt_dir / "prepared.json",
        {
            "intent_ref": intent_ref,
            "prepared_at": "2026-07-30T12:00:00+08:00",
            "prepared_task": {"backend": "gaussian"},
            "execution_policy": {"kind": "remote", "authority": "execution_mirror"},
        },
    )
    write_json(
        attempt_dir / "outputs" / "calculation_result.json",
        {
            "state": "parsed",
            "program_status": "completed",
            "error_class": None,
            "artifact_refs": [f"nodes/n002/attempts/{attempt_id}/outputs/result.json"],
            "provenance": {"parsed_at": "2026-07-30T13:00:00+08:00"},
        },
    )

    graph = explorer_graph_payload_from_view(normalize_workspace(workspace))
    n002 = next(node for node in graph["nodes"] if node["id"] == "n002")
    n003 = next(node for node in graph["nodes"] if node["id"] == "n003")
    assert n002["node_type"] == "validation"
    assert n002["scope"] == "electronic_structure"
    assert n002["program_outcome"] == "success"
    assert n002["hypothesis_status"] is None
    assert n002["calculations"][0]["storage"] == "local_attempt"
    assert n002["calculations"][0]["validation_scope"] == "electronic_structure"
    assert n002["calculations"][0]["remote_authority"] == "execution_mirror"
    assert n003["hypothesis_status"] == "unsupported"
    assert n003["node_state"] == "hypothesis_unsupported"

    start_node(
        workspace,
        _decision(
            "start_node",
            _report_ref(workspace),
            {
                "node_id": "n004",
                "parent_node": "n003",
                "node_type": "audit",
                "objective": "Audit whether the current study can close.",
                "audit_scope": "study",
                "hypothesis_ref": {"hypothesis_id": "hyp_0001", "prediction_ids": []},
                "branch_context": {"relation": "continue_parent", "from_node": "n003", "anchor_node": "n003"},
            },
            decision_id="dec_audit_start",
        ),
    )
    bad_audit_close = _close_payload(
        "n004",
        hypothesis={
            "status": "supported",
            "summary": "Audit must not change hypothesis status.",
            "evidence_refs": [],
            "hypothesis_ref": {"hypothesis_id": "hyp_0001", "prediction_ids": []},
        },
        audit={"status": "not_accepted", "study_complete": False, "summary": "More work is required.", "evidence_refs": []},
    )
    with pytest.raises(ContractError, match="audit closure cannot set intake or hypothesis status"):
        end_node(
            workspace,
            _decision("end_node", _report_ref(workspace), bad_audit_close, decision_id="dec_audit_bad_end"),
        )


def test_v2_pathway_audit_requires_strict_evidence_and_renders_report(tmp_path: Path) -> None:
    workspace = tmp_path / "pathway-audit"
    _bootstrap_v2_hypothesis(workspace)
    start_node(
        workspace,
        _decision(
            "start_node",
            _report_ref(workspace),
            {
                "node_id": "n002",
                "parent_node": "n001",
                "node_type": "audit",
                "objective": "Audit the declared pathway.",
                "audit_scope": "pathway",
                "hypothesis_ref": {"hypothesis_id": "hyp_0001", "prediction_ids": []},
                "pathway_ref": {"pathway_id": "p_target"},
                "branch_context": {"relation": "continue_parent", "from_node": "n001", "anchor_node": "n001"},
            },
            decision_id="dec_pathway_start",
        ),
    )
    close_payload = _close_payload(
        "n002",
        audit={
            "status": "not_accepted",
            "study_complete": False,
            "summary": "The strict pathway is not accepted.",
            "evidence_refs": [],
        },
    )
    with pytest.raises(ValueError, match="quality.strict_pathway_decision"):
        end_node(
            workspace,
            _decision("end_node", _report_ref(workspace), close_payload, decision_id="dec_pathway_missing_gate"),
        )

    artifact_ref = "nodes/n002/outputs/pathway_audit.json"
    artifact_path = workspace / artifact_ref
    write_json(artifact_path, {"strict_pathway_decision": "pathway_not_accepted"})
    bad_evidence = {
        "evidence_id": "ev_wrong_role",
        "kind": "gaussian_tsfreq_validation",
        "role": "tsfreq_gate",
        "evidence_tier": "local_parse",
        "node_id": "n002",
        "summary": "This role belongs to validation/tsfreq, not audit/pathway.",
        "path": artifact_ref,
        **gate_artifact_metadata(artifact_ref),
        "quality": {"hypothesis_id": "hyp_0001"},
    }
    with pytest.raises(ContractError, match="node type/scope"):
        _append_v2_evidence(workspace, bad_evidence, decision_id="dec_pathway_wrong_role")

    evidence = {
        "evidence_id": "ev_pathway_negative",
        "kind": "pathway_audit_summary",
        "role": "pathway_audit_summary",
        "evidence_tier": "local_parse",
        "node_id": "n002",
        "summary": "The strict pathway is not accepted.",
        "path": artifact_ref,
        **gate_artifact_metadata(artifact_ref),
        "quality": {
            "hypothesis_id": "hyp_0001",
            "strict_pathway_supported": False,
            "strict_pathway_decision": "pathway_not_accepted",
        },
    }
    _append_v2_evidence(workspace, evidence, decision_id="dec_pathway_register_gate")
    close_payload["closure"]["audit"]["evidence_refs"] = ["ev_pathway_negative"]
    end_node(
        workspace,
        _decision(
            "end_node",
            _report_ref(workspace),
            close_payload,
            decision_id="dec_pathway_close",
            evidence_refs=["ev_pathway_negative"],
        ),
    )

    text = build_final_report(workspace)
    assert "| Highest validated layer | `pathway` |" in text
    assert "| Final claim | `not_accepted` |" in text
    assert "n002: audit/pathway / closed / not_accepted (audit_outcome=pathway_not_accepted)" in text
    hypotheses = read_json(workspace / "hypotheses.json")
    assert hypotheses["pathways"][0]["status"] == "refuted"


def test_v2_accepted_ts_audit_writes_acceptance_artifact(tmp_path: Path) -> None:
    workspace = tmp_path / "accepted-ts"
    _bootstrap_v2_hypothesis(workspace, _acceptance_hypothesis())
    hypothesis_ref = {"hypothesis_id": "hyp_0001", "prediction_ids": ["pred_tsfreq_001"]}
    start_node(
        workspace,
        _decision(
            "start_node",
            _report_ref(workspace),
            {
                "node_id": "n002",
                "parent_node": "n001",
                "node_type": "validation",
                "objective": "Validate TS frequency character.",
                "validation_scope": "tsfreq",
                "hypothesis_ref": hypothesis_ref,
                "branch_context": {"relation": "continue_parent", "from_node": "n001", "anchor_node": "n001"},
            },
            decision_id="dec_tsfreq_start",
        ),
    )
    tsfreq_ref = "nodes/n002/outputs/tsfreq.json"
    write_json(workspace / tsfreq_ref, {"imaginary_frequency_count": 1})
    tsfreq_evidence = {
        "evidence_id": "ev_v2_tsfreq",
        "kind": "gaussian_tsfreq_validation",
        "role": "tsfreq_gate",
        "evidence_tier": "local_parse",
        "node_id": "n002",
        "summary": "The candidate has one assigned imaginary mode.",
        "path": tsfreq_ref,
        **gate_artifact_metadata(tsfreq_ref),
        "quality": {"hypothesis_id": "hyp_0001", "imaginary_frequency_count": 1},
    }
    _append_v2_evidence(workspace, tsfreq_evidence, decision_id="dec_tsfreq_register")
    end_node(
        workspace,
        _decision(
            "end_node",
            _report_ref(workspace),
            {
                "node_id": "n002",
                "closure": {
                    "summary": "TS/Freq evidence was parsed.",
                    "program": {"outcome": "success", "summary": "Frequency job completed.", "evidence_refs": ["ev_v2_tsfreq"]},
                    "open_questions": [],
                },
            },
            decision_id="dec_tsfreq_close",
            evidence_refs=["ev_v2_tsfreq"],
        ),
    )

    connectivity_ref = {"hypothesis_id": "hyp_0001", "prediction_ids": ["pred_connectivity_001"]}
    start_node(
        workspace,
        _decision(
            "start_node",
            _report_ref(workspace),
            {
                "node_id": "n003",
                "parent_node": "n002",
                "node_type": "validation",
                "objective": "Validate strict endpoint connectivity.",
                "validation_scope": "connectivity",
                "hypothesis_ref": connectivity_ref,
                "branch_context": {"relation": "continue_parent", "from_node": "n002", "anchor_node": "n002"},
            },
            decision_id="dec_connectivity_start",
        ),
    )
    connectivity_artifact_ref = "nodes/n003/outputs/connectivity.json"
    write_json(workspace / connectivity_artifact_ref, {"strict_irc_complete": True})
    connectivity_evidence = {
        "evidence_id": "ev_v2_connectivity",
        "kind": "irc_connectivity_validation",
        "role": "connectivity_gate",
        "evidence_tier": "local_parse",
        "node_id": "n003",
        "summary": "Both IRC directions terminate and reach assigned basins.",
        "path": connectivity_artifact_ref,
        **gate_artifact_metadata(connectivity_artifact_ref),
        "quality": {
            "hypothesis_id": "hyp_0001",
            "strict_irc_complete": True,
            "irc_program_failures": [],
            "irc_directions": {
                "forward": {"normal_termination": True, "assignment": "product"},
                "reverse": {"normal_termination": True, "assignment": "reactant"},
            },
        },
    }
    _append_v2_evidence(workspace, connectivity_evidence, decision_id="dec_connectivity_register")
    end_node(
        workspace,
        _decision(
            "end_node",
            _report_ref(workspace),
            {
                "node_id": "n003",
                "closure": {
                    "summary": "Connectivity evidence was parsed.",
                    "program": {"outcome": "success", "summary": "IRC jobs completed.", "evidence_refs": ["ev_v2_connectivity"]},
                    "open_questions": [],
                },
            },
            decision_id="dec_connectivity_close",
            evidence_refs=["ev_v2_connectivity"],
        ),
    )

    start_node(
        workspace,
        _decision(
            "start_node",
            _report_ref(workspace),
            {
                "node_id": "n004",
                "parent_node": "n003",
                "node_type": "audit",
                "objective": "Audit the transition-state evidence chain.",
                "audit_scope": "transition_state",
                "hypothesis_ref": {"hypothesis_id": "hyp_0001", "prediction_ids": []},
                "branch_context": {"relation": "continue_parent", "from_node": "n003", "anchor_node": "n003"},
            },
            decision_id="dec_ts_audit_start",
            evidence_refs=["ev_v2_tsfreq", "ev_v2_connectivity"],
        ),
    )
    end_node(
        workspace,
        _decision(
            "end_node",
            _report_ref(workspace),
            _close_payload(
                "n004",
                audit={
                    "status": "accepted",
                    "study_complete": False,
                    "summary": "The TS/Freq and connectivity gates accept this transition state.",
                    "evidence_refs": ["ev_v2_tsfreq", "ev_v2_connectivity"],
                },
            ),
            decision_id="dec_ts_audit_close",
            evidence_refs=["ev_v2_tsfreq", "ev_v2_connectivity"],
        ),
    )

    accepted_ref = "accepted/accepted_ts_n004.json"
    research_state = read_json(workspace / "research_state.json")
    assert research_state["accepted_ts_refs"] == [accepted_ref]
    accepted = read_json(workspace / accepted_ref)
    assert accepted["schema_version"] == "ts-accepted/2"
    assert accepted["audit_scope"] == "transition_state"
    assert accepted["evidence_refs"] == ["ev_v2_tsfreq", "ev_v2_connectivity"]
    text = build_final_report(workspace)
    assert "| Highest validated layer | `accepted_ts` |" in text
    assert "| Validation scopes reached | `connectivity, tsfreq` |" in text
    assert "n004: audit/transition_state / closed / accepted" in text


def test_recalculation_is_attempt_relation_not_node_type(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_workspace(workspace)
    decision = _decision(
        "start_node",
        _report_ref(workspace),
        {
            "node_id": "n000",
            "node_type": "validation",
            "objective": "Invalid recalculation root.",
            "attempt_kind": "recalculation",
            "recalculation_ref": {
                "source_node": "n999",
                "changed_settings": ["functional"],
                "purpose": "method_robustness",
            },
            "validation_scope": "method_robustness",
            "hypothesis_ref": {"hypothesis_id": "hyp_0001", "prediction_ids": ["pred_001"]},
            "branch_context": {"relation": "recalculation_of", "from_node": "n999", "anchor_node": "n999"},
        },
        decision_id="dec_invalid_recalc",
    )
    with pytest.raises(ContractError, match="first node"):
        start_node(workspace, decision)


def test_workspace_validation_rechecks_recalculation_lineage() -> None:
    findings: list[dict[str, str]] = []
    _validate_branch_contexts(
        {
            "n000": {"schema_version": "ts-node/2", "node_id": "n000", "parent_node": None, "node_type": "intake"},
            "n001": {
                "schema_version": "ts-node/2",
                "node_id": "n001",
                "parent_node": "n000",
                "node_type": "validation",
                "attempt_kind": "recalculation",
                "recalculation_ref": {"source_node": "n999"},
                "branch_context": {"relation": "continue_parent", "from_node": "n000", "anchor_node": "n000"},
            },
        },
        findings,
    )
    assert any(item["code"] == "invalid_recalculation" for item in findings)
