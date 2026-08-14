from __future__ import annotations

from pathlib import Path

import pytest

from ts_workspace.decision_validator_v3 import ContractError
from ts_workspace.engine_v3 import (
    build_review_snapshot,
    end_node,
    init_workspace,
    report_workspace,
    start_node,
    update_workspace,
    validate_decision_dry_run,
    validate_workspace,
)
from ts_workspace.io import read_json, write_json


def _decision(root: Path, action: str, payload: dict, decision_id: str) -> dict:
    report = report_workspace(root)
    return {
        "schema_version": "ts-decision/3",
        "decision_id": decision_id,
        "action": action,
        "rationale": f"Exercise {action} in the v3 engine.",
        "basis_refs": [],
        "report_ref": {"report_id": report["report_id"], "workspace_root": str(root.resolve())},
        "base_revision": report["workspace_revision"],
        "payload": payload,
    }


def _start(root: Path, node_id: str, *, parent: str | None = None, claims: list[str] | None = None) -> None:
    start_node(
        root,
        _decision(
            root,
            "start_node",
            {
                "node_id": node_id,
                "parent_node": parent,
                "objective": f"Research objective for {node_id}.",
                "tags": ["validation"],
                "claim_refs": claims or [],
            },
            f"dec_start_{node_id}",
        ),
    )


def _end(root: Path, node_id: str, *, claim_updates: list[dict] | None = None, audit: dict | None = None) -> dict:
    return end_node(
        root,
        _decision(
            root,
            "end_node",
            {
                "node_id": node_id,
                "result": {
                    "outcome": "completed",
                    "summary": f"Completed {node_id}.",
                    "claim_updates": claim_updates or [],
                    "audit": audit,
                    "open_questions": [],
                },
            },
            f"dec_end_{node_id}",
        ),
    )


def _evidence(root: Path, node_id: str, evidence_id: str, facts: dict) -> dict:
    artifact = root / "nodes" / node_id / "outputs" / f"{evidence_id}.json"
    artifact.parent.mkdir(exist_ok=True)
    artifact.write_text("{}\n", encoding="utf-8")
    return {
        "schema_version": "ts-evidence/2",
        "evidence_id": evidence_id,
        "node_id": node_id,
        "kind": "gaussian.validation/1",
        "evidence_tier": "local_parse",
        "summary": f"Facts for {evidence_id}.",
        "facts": facts,
        "artifact_refs": [artifact.relative_to(root).as_posix()],
        "provenance": {"producer": "test-parser", "producer_version": "1"},
    }


def test_v3_engine_applies_the_same_path_that_dry_run_validates(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    init_workspace(root)
    decision = _decision(
        root,
        "start_node",
        {
            "node_id": "n000",
            "parent_node": None,
            "objective": "Collect initial scientific facts.",
            "tags": ["intake", "manual"],
            "claim_refs": [],
        },
        "dec_start_n000",
    )

    dry_run = validate_decision_dry_run(root, decision)
    applied = start_node(root, decision)

    assert dry_run["result"] == applied == {"node_id": "n000", "state": "open"}
    node = read_json(root / "nodes" / "n000" / "node.json")
    assert node["tags"] == ["intake", "manual"]
    assert "node_type" not in node
    assert "lifecycle" not in node
    assert "remote" not in node["artifacts"]
    assert set(path.name for path in (root / "nodes/n000").iterdir()) == {"decision.md", "node.json"}
    assert not (root / ".ts-transactions").exists()
    assert validate_workspace(root)["valid"] is True


def test_gate_can_reuse_active_evidence_from_a_closed_ancestor_node(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    init_workspace(root)
    _start(root, "n000")
    evidence = _evidence(
        root,
        "n000",
        "ev_n000_tsfreq",
        {
            "normal_termination": True,
            "stationary_point": True,
            "final_convergence_satisfied": True,
            "imaginary_frequency_count": 1,
            "route_match": True,
        },
    )
    update_workspace(
        root,
        _decision(
            root,
            "update_workspace",
            {
                "append_claim": {
                    "claim_id": "claim_ts_001",
                    "node_id": "n000",
                    "kind": "transition-state/1",
                    "statement": "The candidate is a transition state.",
                    "required_gates": ["tsfreq"],
                    "details": {},
                },
                "append_evidence": evidence,
                "set_focus_claim_refs": ["claim_ts_001"],
            },
            "dec_record_n000",
        ),
    )
    _end(root, "n000")
    _start(root, "n001", parent="n000", claims=["claim_ts_001"])

    update_workspace(
        root,
        _decision(
            root,
            "update_workspace",
            {
                "evaluate_gate": {
                    "gate_result_id": "gr_n001_tsfreq",
                    "node_id": "n001",
                    "gate": "tsfreq",
                    "evidence_refs": ["ev_n000_tsfreq"],
                    "target_ref": "claim_ts_001",
                }
            },
            "dec_gate_n001",
        ),
    )
    gate = read_json(root / "gate_results.json")["gate_results"][0]
    assert gate["verdict"] == "pass"
    assert gate["node_id"] == "n001"
    assert gate["evidence_refs"] == ["ev_n000_tsfreq"]


def test_accepted_audit_writes_an_immutable_policy_bound_artifact(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    init_workspace(root)
    _start(root, "n000")
    tsfreq = _evidence(
        root,
        "n000",
        "ev_tsfreq",
        {
            "normal_termination": True,
            "stationary_point": True,
            "final_convergence_satisfied": True,
            "imaginary_frequency_count": 1,
            "route_match": True,
        },
    )
    connectivity = _evidence(
        root,
        "n000",
        "ev_connectivity",
        {
            "normal_termination": True,
            "strict_irc_complete": True,
            "irc_program_failures": [],
            "irc_directions": {
                "forward": {"normal_termination": True, "assignment": "product"},
                "reverse": {"normal_termination": True, "assignment": "reactant"},
            },
        },
    )
    update_workspace(
        root,
        _decision(
            root,
            "update_workspace",
            {
                "append_claim": {
                    "claim_id": "claim_ts_accepted",
                    "node_id": "n000",
                    "kind": "transition-state/1",
                    "statement": "This structure connects the declared endpoints through one TS.",
                    "required_gates": ["tsfreq", "connectivity"],
                    "details": {},
                },
                "append_evidence": [tsfreq, connectivity],
                "evaluate_gate": [
                    {
                        "gate_result_id": "gr_tsfreq",
                        "node_id": "n000",
                        "gate": "tsfreq",
                        "evidence_refs": ["ev_tsfreq"],
                        "target_ref": "claim_ts_accepted",
                    },
                    {
                        "gate_result_id": "gr_connectivity",
                        "node_id": "n000",
                        "gate": "connectivity",
                        "evidence_refs": ["ev_connectivity"],
                        "target_ref": "claim_ts_accepted",
                    },
                ],
            },
            "dec_acceptance_facts",
        ),
    )
    result = _end(
        root,
        "n000",
        claim_updates=[
            {
                "claim_ref": "claim_ts_accepted",
                "verdict": "supported",
                "summary": "Both deterministic gates passed.",
                "evidence_refs": ["ev_tsfreq", "ev_connectivity"],
                "gate_result_refs": ["gr_tsfreq", "gr_connectivity"],
            }
        ],
        audit={
            "policy": "accepted-ts/2",
            "verdict": "accepted",
            "target_ref": "claim_ts_accepted",
            "gate_result_refs": ["gr_tsfreq", "gr_connectivity"],
            "study_complete": True,
            "summary": "Strict TS and connectivity requirements passed.",
        },
    )

    assert result["accepted_ref"] == "accepted/acc_dec_end_n000.json"
    accepted = read_json(root / result["accepted_ref"])
    assert accepted["policy"] == "accepted-ts/2"
    assert accepted["target_ref"] == "claim_ts_accepted"
    assert validate_workspace(root)["valid"] is True

    snapshot = build_review_snapshot(root, target_claim_ref="claim_ts_accepted")
    assert snapshot["dependency_refs"]["evidence_refs"] == ["ev_connectivity", "ev_tsfreq"]
    assert {row["gate"] for row in snapshot["gate_results"]} == {"tsfreq", "connectivity"}
    assert [row["node_id"] for row in snapshot["nodes"]] == ["n000"]

    accepted["summary"] = "Tampered summary."
    write_json(root / result["accepted_ref"], accepted)
    validation = validate_workspace(root)
    assert validation["valid"] is False
    assert "accepted_artifact_mismatch" in {item["code"] for item in validation["findings"]}


def test_agent_cannot_claim_support_without_required_passed_gates(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    init_workspace(root)
    _start(root, "n000")
    update_workspace(
        root,
        _decision(
            root,
            "update_workspace",
            {
                "append_claim": {
                    "claim_id": "claim_unverified",
                    "node_id": "n000",
                    "kind": "transition-state/1",
                    "statement": "An unverified TS claim.",
                    "required_gates": ["tsfreq"],
                    "details": {},
                }
            },
            "dec_claim_unverified",
        ),
    )
    decision = _decision(
        root,
        "end_node",
        {
            "node_id": "n000",
            "result": {
                "outcome": "completed",
                "summary": "Attempt to overclaim support.",
                "claim_updates": [
                    {
                        "claim_ref": "claim_unverified",
                        "verdict": "supported",
                        "summary": "Unsupported assertion.",
                        "evidence_refs": [],
                        "gate_result_refs": [],
                    }
                ],
                "audit": None,
                "open_questions": [],
            },
        },
        "dec_invalid_support",
    )

    with pytest.raises(ContractError, match="missing passed required gates"):
        end_node(root, decision)
    assert read_json(root / "nodes" / "n000" / "node.json")["state"] == "open"


def test_append_claim_rejects_a_cycle_and_duplicate_ids(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    init_workspace(root)
    _start(root, "n000")
    cyclic = _decision(
        root,
        "update_workspace",
        {
            "append_claim": [
                {
                    "claim_id": "claim_a",
                    "node_id": "n000",
                    "parent_claim_id": "claim_b",
                    "kind": "mechanism/1",
                    "statement": "Claim A.",
                    "required_gates": [],
                    "details": {},
                },
                {
                    "claim_id": "claim_b",
                    "node_id": "n000",
                    "parent_claim_id": "claim_a",
                    "kind": "mechanism/1",
                    "statement": "Claim B.",
                    "required_gates": [],
                    "details": {},
                },
            ]
        },
        "dec_cycle",
    )
    with pytest.raises(ContractError, match="claim parent cycle"):
        update_workspace(root, cyclic)

    duplicate = _decision(
        root,
        "update_workspace",
        {
            "append_claim": [
                {
                    "claim_id": "claim_dup",
                    "node_id": "n000",
                    "kind": "mechanism/1",
                    "statement": "First copy.",
                    "required_gates": [],
                    "details": {},
                },
                {
                    "claim_id": "claim_dup",
                    "node_id": "n000",
                    "kind": "mechanism/1",
                    "statement": "Second copy.",
                    "required_gates": [],
                    "details": {},
                },
            ]
        },
        "dec_duplicate",
    )
    with pytest.raises(ContractError, match="duplicate claim_id"):
        update_workspace(root, duplicate)


def test_mutation_rejects_stale_revision_and_symlinked_owner_ref(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    init_workspace(root)
    stale = _decision(
        root,
        "start_node",
        {
            "node_id": "n001",
            "parent_node": None,
            "objective": "Stale decision.",
            "tags": [],
            "claim_refs": [],
        },
        "dec_stale",
    )
    _start(root, "n000")
    with pytest.raises(ContractError, match="base_revision"):
        start_node(root, stale)

    external = tmp_path / "outside.json"
    external.write_text("{}\n", encoding="utf-8")
    linked = root / "nodes" / "n000" / "outputs" / "outside.json"
    linked.parent.mkdir()
    linked.symlink_to(external)
    evidence = {
        "schema_version": "ts-evidence/2",
        "evidence_id": "ev_symlink",
        "node_id": "n000",
        "kind": "manual.observation/1",
        "evidence_tier": "manual_observation",
        "summary": "Unsafe linked evidence.",
        "facts": {},
        "artifact_refs": ["nodes/n000/outputs/outside.json"],
        "provenance": {"producer": "test"},
    }
    with pytest.raises(ContractError, match="symbolic link"):
        update_workspace(
            root,
            _decision(root, "update_workspace", {"append_evidence": evidence}, "dec_symlink"),
        )


def test_claim_update_rejects_inactive_evidence(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    init_workspace(root)
    _start(root, "n000")
    evidence = _evidence(root, "n000", "ev_observation", {"observed": True})
    update_workspace(
        root,
        _decision(
            root,
            "update_workspace",
            {
                "append_claim": {
                    "claim_id": "claim_observation",
                    "node_id": "n000",
                    "kind": "observation/1",
                    "statement": "An observed fact.",
                    "required_gates": [],
                    "details": {},
                },
                "append_evidence": evidence,
                "append_evidence_event": {
                    "event_id": "ee_withdraw_observation",
                    "evidence_id": "ev_observation",
                    "state": "withdrawn",
                    "reason": "The source was found to be invalid.",
                },
            },
            "dec_inactive_evidence",
        ),
    )
    with pytest.raises(ContractError, match="evidence is inactive"):
        _end(
            root,
            "n000",
            claim_updates=[
                {
                    "claim_ref": "claim_observation",
                    "verdict": "supported",
                    "summary": "Invalid support attempt.",
                    "evidence_refs": ["ev_observation"],
                    "gate_result_refs": [],
                }
            ],
        )


def test_validator_reports_corrupt_json_focus_and_branch_index_drift(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    init_workspace(root)
    _start(root, "n000")

    claims = read_json(root / "claims.json")
    claims["focus_claim_refs"] = ["claim_missing"]
    write_json(root / "claims.json", claims)
    research = read_json(root / "research_state.json")
    research["branch_events"][0]["decision_id"] = "dec_wrong"
    write_json(root / "research_state.json", research)
    validation = validate_workspace(root)
    codes = {item["code"] for item in validation["findings"]}
    assert {"unknown_focus_claim", "branch_event_mismatch"} <= codes

    (root / "gate_results.json").write_text("{broken", encoding="utf-8")
    validation = validate_workspace(root)
    assert validation["valid"] is False
    assert "invalid_json" in {item["code"] for item in validation["findings"]}
