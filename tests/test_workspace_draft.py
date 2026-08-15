from __future__ import annotations

from pathlib import Path

import pytest

from ts_workspace import (
    ContractError,
    draft_decision,
    init_workspace,
    report_workspace,
    start_node,
    update_workspace,
    validate_decision,
    validate_decision_dry_run,
)
from ts_workspace.io import read_json


def _canonical_decision(root: Path, action: str, payload: dict, decision_id: str) -> dict:
    report = report_workspace(root)
    return {
        "schema_version": "ts-decision/3",
        "decision_id": decision_id,
        "action": action,
        "rationale": f"Exercise {action} for draft tests.",
        "basis_refs": [],
        "report_ref": {"report_id": report["report_id"], "workspace_root": report["workspace_root"]},
        "base_revision": report["workspace_revision"],
        "payload": payload,
    }


def _draft_request(payload: dict) -> dict:
    return {
        "action": "update_workspace",
        "rationale": "Record parser facts through the deterministic draft boundary.",
        "basis_refs": [],
        "payload": payload,
    }


def _open_node(root: Path) -> None:
    start_node(
        root,
        _canonical_decision(
            root,
            "start_node",
            {
                "node_id": "n000",
                "parent_node": None,
                "objective": "Exercise deterministic decision drafting.",
                "tags": ["validation"],
                "claim_refs": [],
            },
            "dec_start_draft_test",
        ),
    )


def _evidence(kind: str, artifact_refs: list[str], facts: dict) -> dict:
    return {
        "schema_version": "ts-evidence/2",
        "node_id": "n000",
        "kind": kind,
        "evidence_tier": "local_parse",
        "summary": f"Parsed facts for {kind}.",
        "facts": facts,
        "artifact_refs": artifact_refs,
        "provenance": {
            "producer": "test-parser",
            "producer_version": None,
            "source_sha256": "sha256:" + "a" * 64,
        },
    }


def test_draft_allocates_stable_refs_projects_facts_and_preserves_evidence(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    init_workspace(root)
    _open_node(root)
    artifacts = [
        "nodes/n000/outputs/validation_summary.json",
        "nodes/n000/outputs/frequencies.txt",
        "nodes/n000/outputs/mode_assignment.json",
    ]
    for ref in artifacts:
        path = root / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    request = _draft_request(
        {
            "append_evidence": [
                _evidence(
                    "gaussian_tsfreq/1",
                    artifacts[:2],
                    {
                        "normal_termination": True,
                        "stationary_point_found": True,
                        "final_convergence_satisfied": True,
                        "imaginary_frequency_count": 1,
                        "route_consistent": True,
                        "imaginary_frequencies_cm-1": [-503.0776],
                    },
                ),
                _evidence(
                    "mode_assignment/1",
                    artifacts[2:],
                    {
                        "reaction_coordinate_match": True,
                        "imaginary_mode_matches": True,
                        "mode_description": "Concerted forming-bond motion.",
                    },
                ),
            ]
        }
    )
    first = draft_decision(root, request, decision_id="dec_draft_evidence")
    second = draft_decision(root, request, decision_id="dec_draft_evidence")

    assert first == second
    assert first["allocated_refs"] == {
        "evidence": ["ev_23267751622534aaa4fb48cc", "ev_e29be75932234bbf24f6869d"],
        "gate_results": [],
    }
    records = first["decision"]["payload"]["append_evidence"]
    assert records[0]["facts"]["stationary_point"] is True
    assert records[0]["facts"]["route_match"] is True
    assert records[0]["facts"]["stationary_point_found"] is True
    assert records[0]["facts"]["imaginary_frequencies_cm-1"] == [-503.0776]
    assert records[0]["artifact_refs"] == artifacts[:2]
    assert records[0]["provenance"]["producer_version"] is None
    assert records[0]["provenance"]["source_sha256"] == "sha256:" + "a" * 64
    assert records[1]["facts"]["mode_matches_declared_reaction_coordinate"] is True
    assert records[1]["facts"]["mode_description"] == "Concerted forming-bond motion."

    dry_run = validate_decision_dry_run(root, first["decision"])
    applied = update_workspace(root, first["decision"])
    replay = update_workspace(root, first["decision"])
    assert dry_run["result"]["created_refs"] == first["allocated_refs"] | {
        "claims": [],
        "evidence_events": [],
    }
    assert applied == replay
    assert applied["created_refs"] == dry_run["result"]["created_refs"]

    evidence_refs = first["allocated_refs"]["evidence"]
    gate = draft_decision(
        root,
        _draft_request(
            {
                "evaluate_gate": [
                    {
                        "node_id": "n000",
                        "gate": "tsfreq",
                        "evidence_refs": [evidence_refs[0]],
                        "target_ref": None,
                    },
                    {
                        "node_id": "n000",
                        "gate": "mode_assignment",
                        "evidence_refs": [evidence_refs[1]],
                        "target_ref": None,
                    },
                ]
            }
        ),
        decision_id="dec_draft_gates",
    )
    gate_dry_run = validate_decision_dry_run(root, gate["decision"])
    gate_result = update_workspace(root, gate["decision"])
    assert gate_result["created_refs"] == gate_dry_run["result"]["created_refs"]
    stored = read_json(root / "gate_results.json")["gate_results"]
    assert [item["verdict"] for item in stored] == ["pass", "pass"]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"append_evidence": {"evidence_id": "ev_agent_owned"}},
            "append_evidence.evidence_id is kernel-owned; omit it",
        ),
        (
            {"evaluate_gate": {"gate_result_id": "gr_agent_owned"}},
            "evaluate_gate.gate_result_id is kernel-owned; omit it",
        ),
    ],
)
def test_draft_rejects_explicit_kernel_owned_ids(tmp_path: Path, payload: dict, message: str) -> None:
    root = tmp_path / "ws"
    init_workspace(root)
    with pytest.raises(ContractError, match=message.replace(".", r"\.")):
        draft_decision(root, _draft_request(payload), decision_id="dec_reject_owned_id")


def test_draft_rejects_conflicting_parser_and_gate_fact_names(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    init_workspace(root)
    evidence = _evidence(
        "gaussian_tsfreq/1",
        [],
        {"stationary_point": False, "stationary_point_found": True},
    )
    with pytest.raises(ContractError, match="conflicting facts for stationary_point"):
        draft_decision(
            root,
            _draft_request({"append_evidence": evidence}),
            decision_id="dec_conflicting_facts",
        )


def test_canonical_schema_error_reports_the_invalid_evidence_id_path() -> None:
    decision = {
        "schema_version": "ts-decision/3",
        "decision_id": "dec_bad_evidence_id",
        "action": "update_workspace",
        "rationale": "Expose the exact invalid field.",
        "basis_refs": [],
        "report_ref": {"report_id": "rep_test", "workspace_root": "ws"},
        "base_revision": "sha256:test",
        "payload": {
            "append_evidence": {
                "schema_version": "ts-evidence/2",
                "evidence_id": "evidence_tsfreq_001",
                "node_id": "n001",
                "kind": "gaussian_tsfreq/1",
                "evidence_tier": "local_parse",
                "summary": "Otherwise complete evidence.",
                "facts": {},
                "artifact_refs": ["nodes/n001/outputs/result.json"],
                "provenance": {"producer": "test-parser"},
            }
        },
    }
    with pytest.raises(ContractError) as captured:
        validate_decision(decision)
    message = str(captured.value)
    assert "$.payload.append_evidence.evidence_id" in message
    assert "does not match '^ev_" in message
    assert "not valid under any of the given schemas" not in message


def test_schema_expansion_keeps_nested_field_type_errors() -> None:
    decision = {
        "schema_version": "ts-decision/3",
        "decision_id": "dec_bad_evidence_facts",
        "action": "update_workspace",
        "rationale": "Expose a nested type error.",
        "basis_refs": [],
        "report_ref": {"report_id": "rep_test", "workspace_root": "ws"},
        "base_revision": "sha256:test",
        "payload": {
            "append_evidence": {
                "schema_version": "ts-evidence/2",
                "evidence_id": "ev_tsfreq_001",
                "node_id": "n001",
                "kind": "gaussian_tsfreq/1",
                "evidence_tier": "local_parse",
                "summary": "Evidence with an invalid facts value.",
                "facts": [],
                "artifact_refs": [],
                "provenance": {"producer": "test-parser"},
            }
        },
    }
    with pytest.raises(ContractError) as captured:
        validate_decision(decision)
    message = str(captured.value)
    assert "$.payload.append_evidence.facts" in message
    assert "is not of type 'object'" in message
