from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ts_workspace import end_node, init_workspace, report_workspace, start_node, update_workspace


CLAIM_ID = "claim_reaction_0001"


def _decision(
    workspace: Path,
    action: str,
    payload: dict[str, Any],
    *,
    decision_id: str,
    rationale: str,
    basis_refs: list[str] | None = None,
) -> dict[str, Any]:
    report = report_workspace(workspace)
    return {
        "schema_version": "ts-decision/3",
        "decision_id": decision_id,
        "action": action,
        "rationale": rationale,
        "basis_refs": list(basis_refs or []),
        "report_ref": {
            "report_id": report["report_id"],
            "workspace_root": str(workspace.resolve()),
        },
        "base_revision": report["workspace_revision"],
        "payload": payload,
    }


def bootstrap_strict_workspace(
    workspace: Path,
    *,
    required_gates: list[str] | None = None,
) -> dict[str, str]:
    """Create a minimal valid v3 workspace with one explicit focus Claim."""

    workspace = workspace.resolve()
    init_workspace(workspace)
    start_node(
        workspace,
        _decision(
            workspace,
            "start_node",
            {
                "node_id": "n000",
                "parent_node": None,
                "objective": "Register the declared endpoints and initial scientific claim.",
                "tags": ["intake"],
                "claim_refs": [],
            },
            decision_id="dec_start_n000",
            rationale="Open the first bounded research act.",
        ),
    )
    (workspace / "inputs" / "reactant.xyz").write_text(
        "2\nreactant\nH 0 0 0\nH 0 0 0.74\n",
        encoding="utf-8",
    )
    (workspace / "inputs" / "product.xyz").write_text(
        "2\nproduct\nH 0 0 0\nH 0 0 0.80\n",
        encoding="utf-8",
    )
    endpoint_ref = "nodes/n000/outputs/endpoint-summary.json"
    endpoint_path = workspace / endpoint_ref
    endpoint_path.write_text(
        json.dumps({"reactant": "inputs/reactant.xyz", "product": "inputs/product.xyz"}) + "\n",
        encoding="utf-8",
    )
    update_workspace(
        workspace,
        _decision(
            workspace,
            "update_workspace",
            {
                "append_claim": {
                    "claim_id": CLAIM_ID,
                    "node_id": "n000",
                    "parent_claim_id": None,
                    "kind": "reaction_path/1",
                    "statement": "A transition structure connects the declared reactant and product endpoints.",
                    "required_gates": list(required_gates or ["tsfreq", "connectivity"]),
                    "details": {
                        "reactant_ref": "inputs/reactant.xyz",
                        "product_ref": "inputs/product.xyz",
                    },
                },
                "append_evidence": {
                    "schema_version": "ts-evidence/2",
                    "evidence_id": "ev_endpoint_0001",
                    "node_id": "n000",
                    "kind": "endpoint.input/1",
                    "evidence_tier": "user_provided",
                    "summary": "The declared endpoint structures are present in the workspace.",
                    "facts": {"endpoints_declared": True},
                    "artifact_refs": [endpoint_ref],
                    "provenance": {
                        "producer": "strict-test-fixture",
                        "producer_version": "3",
                        "source_sha256": None,
                    },
                },
                "set_focus_claim_refs": [CLAIM_ID],
            },
            decision_id="dec_register_claim",
            rationale="Register the initial Claim and its endpoint provenance.",
            basis_refs=[endpoint_ref],
        ),
    )
    end_node(
        workspace,
        _decision(
            workspace,
            "end_node",
            {
                "node_id": "n000",
                "result": {
                    "outcome": "completed",
                    "summary": "Endpoint intake is complete; the Claim remains unresolved.",
                    "claim_updates": [
                        {
                            "claim_ref": CLAIM_ID,
                            "verdict": "inconclusive",
                            "summary": "Endpoint inputs alone do not establish the transition path.",
                            "evidence_refs": ["ev_endpoint_0001"],
                            "gate_result_refs": [],
                        }
                    ],
                    "audit": None,
                    "open_questions": ["Which candidate and validation evidence should be obtained next?"],
                },
            },
            decision_id="dec_end_n000",
            rationale="Close endpoint intake without asserting scientific support.",
            basis_refs=["ev_endpoint_0001"],
        ),
    )
    return _report_ref(workspace)


def start_research_node(
    workspace: Path,
    report_ref: dict[str, str] | None = None,
    *,
    node_id: str,
    parent_node: str = "n000",
    objective: str | None = None,
    tags: list[str] | None = None,
    claim_refs: list[str] | None = None,
) -> dict[str, Any]:
    del report_ref
    return start_node(
        workspace,
        _decision(
            workspace,
            "start_node",
            {
                "node_id": node_id,
                "parent_node": parent_node,
                "objective": objective or f"Perform bounded research work in {node_id}.",
                "tags": list(tags or []),
                "claim_refs": list(claim_refs or [CLAIM_ID]),
            },
            decision_id=f"dec_start_{node_id}",
            rationale=f"Open {node_id} for a Root-selected research act.",
            basis_refs=list(claim_refs or [CLAIM_ID]),
        ),
    )


def end_research_node(
    workspace: Path,
    report_ref: dict[str, str] | None = None,
    *,
    node_id: str,
    outcome: str = "completed",
    summary: str | None = None,
    program_outcome: str | None = None,
) -> dict[str, Any]:
    del report_ref, program_outcome
    return end_node(
        workspace,
        _decision(
            workspace,
            "end_node",
            {
                "node_id": node_id,
                "result": {
                    "outcome": outcome,
                    "summary": summary or f"Bounded research work in {node_id} ended.",
                    "claim_updates": [],
                    "audit": None,
                    "open_questions": [],
                },
            },
            decision_id=f"dec_end_{node_id}",
            rationale=f"Close {node_id} without changing a Claim verdict.",
        ),
    )


def make_accepted_workspace(
    workspace: Path,
    *,
    stereochemical: bool = False,
    identity_claim: bool = False,
) -> dict[str, str]:
    required_gates = ["tsfreq", "connectivity"]
    if stereochemical:
        required_gates.append("stereochemistry")
    if identity_claim:
        required_gates.append("intermediate_identity")
    report_ref = bootstrap_strict_workspace(workspace, required_gates=required_gates)
    start_research_node(
        workspace,
        report_ref,
        node_id="n001",
        objective="Evaluate the focus Claim using deterministic scientific Gates.",
        tags=["validation", "audit"],
    )

    evidence_specs: list[tuple[str, str, dict[str, Any]]] = [
        (
            "ev_tsfreq_001",
            "gaussian.tsfreq/1",
            {
                "normal_termination": True,
                "stationary_point": True,
                "final_convergence_satisfied": True,
                "imaginary_frequency_count": 1,
                "route_match": True,
                "imaginary_frequency_cm1": -500.0,
            },
        ),
        (
            "ev_conn_001",
            "gaussian.irc/1",
            {
                "normal_termination": True,
                "strict_irc_complete": True,
                "irc_program_failures": [],
                "irc_directions": {
                    "forward": {"normal_termination": True, "assignment": "product"},
                    "reverse": {"normal_termination": True, "assignment": "reactant"},
                },
            },
        ),
    ]
    gate_specs = [
        ("gr_tsfreq_001", "tsfreq", "ev_tsfreq_001"),
        ("gr_conn_001", "connectivity", "ev_conn_001"),
    ]
    if stereochemical:
        evidence_specs.append(
            (
                "ev_stereo_001",
                "structure.stereochemistry/1",
                {"stereochemistry_matched": True, "stereochemical_mismatches": []},
            )
        )
        gate_specs.append(("gr_stereo_001", "stereochemistry", "ev_stereo_001"))
    if identity_claim:
        evidence_specs.append(
            ("ev_identity_001", "structure.intermediate_identity/1", {"identity_supported": True})
        )
        gate_specs.append(("gr_identity_001", "intermediate_identity", "ev_identity_001"))

    evidence_records = []
    for evidence_id, kind, facts in evidence_specs:
        artifact_ref = f"nodes/n001/outputs/{evidence_id}.json"
        (workspace / artifact_ref).write_text(json.dumps(facts, sort_keys=True) + "\n", encoding="utf-8")
        evidence_records.append(
            {
                "schema_version": "ts-evidence/2",
                "evidence_id": evidence_id,
                "node_id": "n001",
                "kind": kind,
                "evidence_tier": "local_parse",
                "summary": f"Deterministic facts for {kind}.",
                "facts": facts,
                "artifact_refs": [artifact_ref],
                "provenance": {
                    "producer": "strict-test-parser",
                    "producer_version": "3",
                    "source_sha256": None,
                },
            }
        )

    update_workspace(
        workspace,
        _decision(
            workspace,
            "update_workspace",
            {
                "append_evidence": evidence_records,
                "evaluate_gate": [
                    {
                        "gate_result_id": gate_result_id,
                        "node_id": "n001",
                        "gate": gate,
                        "evidence_refs": [evidence_id],
                        "target_ref": CLAIM_ID,
                    }
                    for gate_result_id, gate, evidence_id in gate_specs
                ],
            },
            decision_id="dec_register_acceptance_evidence",
            rationale="Register parsed facts and evaluate their deterministic Gates.",
            basis_refs=[item[0] for item in evidence_specs],
        ),
    )
    evidence_refs = [item[0] for item in evidence_specs]
    gate_refs = [item[0] for item in gate_specs]
    end_node(
        workspace,
        _decision(
            workspace,
            "end_node",
            {
                "node_id": "n001",
                "result": {
                    "outcome": "completed",
                    "summary": "All required deterministic Gates passed.",
                    "claim_updates": [
                        {
                            "claim_ref": CLAIM_ID,
                            "verdict": "supported",
                            "summary": "The selected evidence supports the focus Claim.",
                            "evidence_refs": evidence_refs,
                            "gate_result_refs": gate_refs,
                        }
                    ],
                    "audit": {
                        "policy": "accepted-ts/2",
                        "verdict": "accepted",
                        "target_ref": CLAIM_ID,
                        "gate_result_refs": gate_refs,
                        "study_complete": True,
                        "summary": "The focus Claim satisfies the accepted TS policy.",
                    },
                    "open_questions": [],
                },
            },
            decision_id="dec_accept_claim",
            rationale="Accept the supported Claim after deterministic Gate evaluation.",
            basis_refs=[CLAIM_ID, *gate_refs],
        ),
    )
    return _report_ref(workspace)


def _report_ref(workspace: Path) -> dict[str, str]:
    report = report_workspace(workspace)
    return {
        "report_id": report["report_id"],
        "workspace_root": report["workspace_root"],
    }
