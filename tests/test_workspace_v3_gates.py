from __future__ import annotations

from ts_workspace.gates_v3 import evaluate_gate, validate_audit_gate_results


def _evidence(evidence_id: str, facts: dict, *, node_id: str = "n004") -> dict:
    return {
        "schema_version": "ts-evidence/2",
        "evidence_id": evidence_id,
        "node_id": node_id,
        "kind": "gaussian.validation/1",
        "evidence_tier": "local_parse",
        "summary": "Parsed deterministic facts.",
        "facts": facts,
        "artifact_refs": [f"nodes/{node_id}/outputs/{evidence_id}.json"],
        "provenance": {"producer": "test-parser", "producer_version": "1"},
    }


def test_tsfreq_gate_is_derived_from_facts_without_an_evidence_role() -> None:
    evidence = _evidence(
        "ev_n004_tsfreq",
        {
            "normal_termination": True,
            "stationary_point": True,
            "final_convergence_satisfied": True,
            "imaginary_frequency_count": 1,
            "route_match": True,
        },
    )

    result = evaluate_gate(
        gate_result_id="gr_n004_tsfreq",
        node_id="n004",
        gate="tsfreq",
        evidence_records=[evidence],
        evidence_refs=[evidence["evidence_id"]],
        target_ref="claim_ts_001",
    )

    assert result["verdict"] == "pass"
    assert result["gate"] == "tsfreq"
    assert "role" not in evidence


def test_gate_distinguishes_missing_facts_from_contradictory_facts() -> None:
    missing = _evidence("ev_missing", {"normal_termination": True})
    failed = _evidence(
        "ev_failed",
        {
            "normal_termination": True,
            "stationary_point": True,
            "final_convergence_satisfied": True,
            "imaginary_frequency_count": 2,
            "route_match": True,
        },
    )

    missing_result = evaluate_gate(
        gate_result_id="gr_missing",
        node_id="n004",
        gate="tsfreq",
        evidence_records=[missing],
        evidence_refs=["ev_missing"],
    )
    failed_result = evaluate_gate(
        gate_result_id="gr_failed",
        node_id="n004",
        gate="tsfreq",
        evidence_records=[failed],
        evidence_refs=["ev_failed"],
    )

    assert missing_result["verdict"] == "inconclusive"
    assert failed_result["verdict"] == "fail"


def test_accepted_ts_policy_requires_passed_tsfreq_and_connectivity_results() -> None:
    tsfreq = {
        "gate_result_id": "gr_tsfreq",
        "gate": "tsfreq",
        "verdict": "pass",
        "target_ref": "claim_ts_001",
    }
    connectivity = {
        "gate_result_id": "gr_connectivity",
        "gate": "connectivity",
        "verdict": "pass",
        "target_ref": "claim_ts_001",
    }

    selected = validate_audit_gate_results(
        "accepted-ts/2",
        [tsfreq, connectivity],
        ["gr_tsfreq", "gr_connectivity"],
        target_ref="claim_ts_001",
    )

    assert set(selected) == {"tsfreq", "connectivity"}
