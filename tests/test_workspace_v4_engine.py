from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.v4_helpers import accept_research_claim
from ts_workspace.acceptance import project_acceptances
from ts_workspace.decision import draft_decision
from ts_workspace.engine import apply_decision, init_workspace, validate_decision_dry_run
from ts_workspace.errors import ContractError
from ts_workspace.io import read_json
from ts_workspace.state import RESEARCH_STATE_FILE, STATE_FILES
from ts_workspace.validator import validate_workspace


def _apply(root: Path, operations: list[dict], *, rationale: str = "Exercise the v4 research Kernel.") -> tuple[dict, dict]:
    drafted = draft_decision(
        root,
        {"rationale": rationale, "basis_refs": [], "operations": operations},
    )
    validation = validate_decision_dry_run(root, drafted["decision"])
    assert validation["valid"] is True
    result = apply_decision(root, drafted["decision"])
    return drafted, result


def _acceptance_projection(root: Path) -> list[dict]:
    documents = {name: read_json(root / name) for name in STATE_FILES}
    return project_acceptances(root, documents[RESEARCH_STATE_FILE]["acceptance_refs"], documents)


def test_research_act_dag_supports_branch_merge_and_kernel_ids(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    drafted, result = _apply(
        root,
        [
            {
                "op": "create_claim",
                "local_ref": "mechanism",
                "claimType": "mechanism.hypothesis",
                "statement": "The transformation follows one concerted elementary step.",
                "falsifiers": ["A stable intermediate is observed."],
            },
            {
                "op": "start_act",
                "local_ref": "intake",
                "objective": "Bind the initial molecular system and assumptions.",
                "claimRefs": ["$mechanism"],
            },
            {
                "op": "start_act",
                "local_ref": "path_a",
                "objective": "Test the concerted pathway.",
                "dependencyRefs": ["$intake"],
                "claimRefs": ["$mechanism"],
                "hypothesis": {
                    "statement": "A concerted saddle can be located.",
                    "predictions": ["One reaction-coordinate imaginary mode."],
                    "falsifiers": ["All candidates relax to an intermediate."],
                },
            },
            {
                "op": "start_act",
                "local_ref": "path_b",
                "objective": "Search for a stepwise alternative.",
                "dependencyRefs": ["$intake"],
                "claimRefs": ["$mechanism"],
            },
            {
                "op": "start_act",
                "local_ref": "synthesis",
                "objective": "Compare both searches without discarding either history.",
                "dependencyRefs": ["$path_a", "$path_b"],
                "claimRefs": ["$mechanism"],
            },
            {"op": "set_focus", "claimRefs": ["$mechanism"], "actRefs": ["$synthesis"]},
        ],
    )

    allocations = drafted["allocated_refs"]
    assert set(allocations) == {"mechanism", "intake", "path_a", "path_b", "synthesis"}
    assert allocations["mechanism"] == "claim_1"
    assert [allocations[name] for name in ("intake", "path_a", "path_b", "synthesis")] == [
        "act_1",
        "act_2",
        "act_3",
        "act_4",
    ]
    assert result["created_refs"]["acts"] == [
        allocations["intake"],
        allocations["path_a"],
        allocations["path_b"],
        allocations["synthesis"],
    ]
    acts = {item["act_id"]: item for item in read_json(root / "research_acts.json")["acts"]}
    assert acts[allocations["synthesis"]]["dependency_refs"] == [allocations["path_a"], allocations["path_b"]]
    assert not (root / "acts" / allocations["synthesis"]).exists()
    assert validate_workspace(root)["valid"] is True


def test_research_act_ids_are_monotonic_and_parallel_decision_collision_must_redraft(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    first, _ = _apply(
        root,
        [{"op": "start_act", "local_ref": "first", "objective": "Create the first bounded Act."}],
    )
    assert first["allocated_refs"]["first"] == "act_1"

    left = draft_decision(
        root,
        {
            "rationale": "Draft one branch.",
            "basis_refs": [],
            "operations": [{"op": "start_act", "local_ref": "left", "objective": "Create the left branch."}],
        },
    )
    right = draft_decision(
        root,
        {
            "rationale": "Draft another branch from the same revision.",
            "basis_refs": [],
            "operations": [{"op": "start_act", "local_ref": "right", "objective": "Create the right branch."}],
        },
    )
    assert left["allocated_refs"]["left"] == "act_2"
    assert right["allocated_refs"]["right"] == "act_2"

    apply_decision(root, left["decision"])
    with pytest.raises(ContractError, match="already exists with different content"):
        apply_decision(root, right["decision"])

    redrafted = draft_decision(
        root,
        {
            "rationale": "Redraft the second branch against the current revision.",
            "basis_refs": [],
            "operations": [{"op": "start_act", "local_ref": "right", "objective": "Create the right branch."}],
        },
    )
    assert redrafted["allocated_refs"]["right"] == "act_3"


def test_decision_ids_are_monotonic_and_parallel_drafts_conflict_before_redraft(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    left = draft_decision(
        root,
        {
            "rationale": "Draft the left branch.",
            "basis_refs": [],
            "operations": [{"op": "start_act", "local_ref": "left", "objective": "Create the left branch."}],
        },
    )
    right = draft_decision(
        root,
        {
            "rationale": "Draft the right branch from the same revision.",
            "basis_refs": [],
            "operations": [{"op": "start_act", "local_ref": "right", "objective": "Create the right branch."}],
        },
    )
    assert left["decision"]["decision_id"] == "dec_1"
    assert right["decision"]["decision_id"] == "dec_1"

    applied = apply_decision(root, left["decision"])
    assert apply_decision(root, left["decision"]) == applied
    with pytest.raises(ContractError, match="already exists with different content"):
        apply_decision(root, right["decision"])

    redrafted = draft_decision(
        root,
        {
            "rationale": "Redraft the right branch against the current revision.",
            "basis_refs": [],
            "operations": [{"op": "start_act", "local_ref": "right", "objective": "Create the right branch."}],
        },
    )
    assert redrafted["decision"]["decision_id"] == "dec_2"


def test_recorded_aborted_decision_id_is_not_reused(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    (root / "transaction_log.jsonl").write_text(
        json.dumps({"decision_id": "dec_1", "stage": "aborted"}) + "\n",
        encoding="utf-8",
    )

    drafted = draft_decision(
        root,
        {
            "rationale": "Allocate after an aborted transaction.",
            "basis_refs": [],
            "operations": [{"op": "start_act", "local_ref": "next", "objective": "Use the next Decision ID."}],
        },
    )
    assert drafted["decision"]["decision_id"] == "dec_2"


def test_claim_ids_are_monotonic_and_parallel_decision_collision_must_redraft(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    first, _ = _apply(
        root,
        [{"op": "create_claim", "local_ref": "first", "claimType": "hypothesis", "statement": "First Claim."}],
    )
    assert first["allocated_refs"]["first"] == "claim_1"

    left = draft_decision(
        root,
        {
            "rationale": "Draft one Claim.",
            "basis_refs": [],
            "operations": [
                {"op": "create_claim", "local_ref": "left", "claimType": "hypothesis", "statement": "Left Claim."}
            ],
        },
    )
    right = draft_decision(
        root,
        {
            "rationale": "Draft another Claim from the same revision.",
            "basis_refs": [],
            "operations": [
                {"op": "create_claim", "local_ref": "right", "claimType": "hypothesis", "statement": "Right Claim."}
            ],
        },
    )
    assert left["allocated_refs"]["left"] == "claim_2"
    assert right["allocated_refs"]["right"] == "claim_2"

    apply_decision(root, left["decision"])
    with pytest.raises(ContractError, match="already exists with different content"):
        apply_decision(root, right["decision"])

    redrafted = draft_decision(
        root,
        {
            "rationale": "Redraft the second Claim against the current revision.",
            "basis_refs": [],
            "operations": [
                {"op": "create_claim", "local_ref": "right", "claimType": "hypothesis", "statement": "Right Claim."}
            ],
        },
    )
    assert redrafted["allocated_refs"]["right"] == "claim_3"


def test_decision_snapshots_preserve_human_readable_utf8(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    rationale = "未能定位连接反应物与产物的一阶鞍点。"
    drafted, _ = _apply(
        root,
        [{"op": "start_act", "local_ref": "search", "objective": "搜索协同反应路径。"}],
        rationale=rationale,
    )

    snapshot = root / "decisions" / f"{drafted['decision']['decision_id']}.json"
    raw = snapshot.read_text(encoding="utf-8")
    assert rationale in raw
    assert "搜索协同反应路径" in raw
    assert "\\u672a" not in raw


def test_claim_relation_cycle_is_rejected_without_partial_state(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    drafted, _ = _apply(
        root,
        [
            {"op": "create_claim", "local_ref": "a", "claimType": "hypothesis", "statement": "Claim A."},
            {"op": "create_claim", "local_ref": "b", "claimType": "hypothesis", "statement": "Claim B."},
            {"op": "relate_claims", "local_ref": "ab", "sourceClaimRef": "$a", "targetClaimRef": "$b", "relationType": "depends_on", "rationale": "A depends on B."},
        ],
    )
    a = drafted["allocated_refs"]["a"]
    b = drafted["allocated_refs"]["b"]
    before = read_json(root / "claim_relations.json")
    reverse = draft_decision(
        root,
        {
            "rationale": "Attempt an invalid cycle.",
            "basis_refs": [],
            "operations": [
                {"op": "relate_claims", "local_ref": "ba", "sourceClaimRef": b, "targetClaimRef": a, "relationType": "depends_on", "rationale": "B depends on A."}
            ],
        },
    )
    with pytest.raises(ContractError, match="cycle"):
        validate_decision_dry_run(root, reverse["decision"])
    assert read_json(root / "claim_relations.json") == before


def test_declarative_specs_observations_and_acceptance_share_one_transaction(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    observations = [
        ("normal", "program.normal_termination", True, {}),
        ("stationary", "stationary_point.confirmed", True, {}),
        ("converged", "optimization.converged", True, {}),
        ("imaginary", "vibration.imaginary_frequency_count", 1, {}),
        ("method", "calculation.method_matches_intent", True, {}),
        ("mode", "vibration.mode_matches_reaction_coordinate", True, {}),
        ("path_complete", "reaction_path.bidirectional_complete", True, {}),
        ("path_failures", "reaction_path.program_failures", [], {}),
        ("reverse_endpoint", "reaction_path.endpoint_assignment", "reactant", {"direction": "reverse"}),
        ("forward_endpoint", "reaction_path.endpoint_assignment", "product", {"direction": "forward"}),
    ]
    operations: list[dict] = [
        {"op": "create_claim", "local_ref": "ts", "claimType": "transition_state", "statement": "The candidate is a connecting transition state."},
        {"op": "start_act", "local_ref": "validate", "objective": "Validate stationary point, mode, and connectivity.", "claimRefs": ["$ts"]},
    ]
    for alias, concept, value, qualifiers in observations:
        datatype = "boolean" if isinstance(value, bool) else "integer" if isinstance(value, int) else "string" if isinstance(value, str) else "json"
        operations.append(
            {
                "op": "record_observation",
                "local_ref": alias,
                "actRef": "$validate",
                "conceptId": concept,
                "subjectRef": "calc_ts_001",
                "value": value,
                "datatype": datatype,
                "qualifiers": qualifiers,
                "summary": concept,
                "provenance": {"producer": "test-parser", "producerVersion": "1"},
            }
        )
    operations.extend(
        [
            {
                "op": "freeze_validation_spec",
                "local_ref": "stationary_spec",
                "actRef": "$validate",
                "targetClaimRef": "$ts",
                "dimension": "stationary_point",
                "title": "Classical TS stationary point",
                "template": {"templateId": "classical-ts", "version": "1", "parameters": {"subject_ref": "calc_ts_001"}},
            },
            {
                "op": "freeze_validation_spec",
                "local_ref": "mode_spec",
                "actRef": "$validate",
                "targetClaimRef": "$ts",
                "dimension": "reaction_coordinate",
                "title": "Mode assignment",
                "template": {"templateId": "reaction-coordinate", "version": "1", "parameters": {"subject_ref": "calc_ts_001"}},
            },
            {
                "op": "freeze_validation_spec",
                "local_ref": "connectivity_spec",
                "actRef": "$validate",
                "targetClaimRef": "$ts",
                "dimension": "connectivity",
                "title": "Path connectivity",
                "template": {
                    "templateId": "connectivity",
                    "version": "1",
                    "parameters": {"subject_ref": "calc_ts_001", "reactant_ref": "reactant", "product_ref": "product"},
                },
            },
            {
                "op": "evaluate_validation",
                "local_ref": "stationary_result",
                "actRef": "$validate",
                "specRef": "$stationary_spec",
                "observationRefs": ["$normal", "$stationary", "$converged", "$imaginary", "$method"],
            },
            {
                "op": "evaluate_validation",
                "local_ref": "mode_result",
                "actRef": "$validate",
                "specRef": "$mode_spec",
                "observationRefs": ["$mode"],
            },
            {
                "op": "evaluate_validation",
                "local_ref": "connectivity_result",
                "actRef": "$validate",
                "specRef": "$connectivity_spec",
                "observationRefs": ["$normal", "$path_complete", "$path_failures", "$reverse_endpoint", "$forward_endpoint"],
            },
            {
                "op": "update_claim",
                "claimRef": "$ts",
                "status": "supported",
                "summary": "All frozen validation dimensions passed.",
                "validationResultRefs": ["$stationary_result", "$mode_result", "$connectivity_result"],
            },
            {
                "op": "accept_claim",
                "local_ref": "accepted_ts",
                "claimRef": "$ts",
                "profile": {"profileId": "accepted-ts", "version": "3"},
                "summary": "Stationary point, mode assignment, and bidirectional connectivity passed.",
            },
            {
                "op": "complete_act",
                "actRef": "$validate",
                "outcome": "completed",
                "summary": "Validation completed.",
            },
        ]
    )

    drafted, result = _apply(root, operations)
    assert len(result["created_refs"]["observations"]) == 10
    assert len(result["created_refs"]["validation_specs"]) == 3
    assert len(result["created_refs"]["validation_results"]) == 3
    assert len(result["created_refs"]["acceptances"]) == 1
    acceptance_id = drafted["allocated_refs"]["accepted_ts"]
    accepted = read_json(root / "acceptances" / f"{acceptance_id}.json")
    assert accepted["schema_version"] == "ts-acceptance-record/1"
    assert accepted["acceptance_digest"].startswith("sha256:")
    assert {read_json(root / "validation_results.json")["results"][index]["verdict"] for index in range(3)} == {"pass"}
    assert validate_workspace(root)["valid"] is True


def test_open_blocking_finding_prevents_acceptance(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    drafted, _ = _apply(
        root,
        [
            {"op": "create_claim", "local_ref": "claim", "claimType": "research", "statement": "A bounded claim."},
            {"op": "start_act", "local_ref": "act", "objective": "Test the claim.", "claimRefs": ["$claim"]},
            {
                "op": "record_observation", "local_ref": "obs", "actRef": "$act", "conceptId": "test.confirmed", "subjectRef": "subject", "value": True,
                "datatype": "boolean", "summary": "Confirmed.", "provenance": {"producer": "test"}
            },
            {
                "op": "freeze_validation_spec", "local_ref": "spec", "actRef": "$act", "targetClaimRef": "$claim", "dimension": "test", "title": "Test",
                "definition": {"checks": [{"check_id": "confirmed", "predicate": "observation.equals", "parameters": {"selector": {"concept_id": "test.confirmed", "subject_ref": "subject"}, "expected": True}, "blocking": True}], "success_policy": {"mode": "all_blocking"}}
            },
            {"op": "evaluate_validation", "local_ref": "result", "actRef": "$act", "specRef": "$spec", "observationRefs": ["$obs"]},
            {"op": "record_finding", "local_ref": "risk", "findingType": "unexpected_state", "severity": "blocking", "statement": "An unresolved anomaly remains.", "claimRefs": ["$claim"], "actRefs": ["$act"]},
        ],
    )
    claim = drafted["allocated_refs"]["claim"]
    with pytest.raises(ContractError, match="blocking Findings"):
        draft_decision(
            root,
            {
                "rationale": "Attempt acceptance while a blocker is open.",
                "basis_refs": [],
                "operations": [{"op": "accept_claim", "local_ref": "accept", "claimRef": claim, "profile": {"profileId": "research-claim", "version": "1"}, "summary": "Should be blocked."}],
            },
        )


def test_acceptance_requires_at_least_one_attached_gate_spec(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)

    with pytest.raises(ContractError, match="at least one attached GateSpec"):
        draft_decision(
            root,
            {
                "rationale": "Do not accept an unvalidated Claim.",
                "basis_refs": [],
                "operations": [
                    {"op": "create_claim", "local_ref": "claim", "claimType": "research", "statement": "An unvalidated Claim."},
                    {"op": "start_act", "local_ref": "act", "objective": "Observe one fact without a GateSpec.", "claimRefs": ["$claim"]},
                    {
                        "op": "record_observation",
                        "local_ref": "observation",
                        "actRef": "$act",
                        "conceptId": "test.observed",
                        "subjectRef": "subject",
                        "value": True,
                        "datatype": "boolean",
                        "summary": "One fact was observed.",
                        "provenance": {"producer": "test"},
                    },
                    {
                        "op": "update_claim",
                        "claimRef": "$claim",
                        "status": "supported",
                        "summary": "Root interpretation without validation.",
                        "observationRefs": ["$observation"],
                    },
                    {
                        "op": "accept_claim",
                        "local_ref": "acceptance",
                        "claimRef": "$claim",
                        "profile": {"profileId": "research-claim", "version": "1"},
                        "summary": "Must be rejected.",
                    },
                ],
            },
        )


def test_acceptance_history_becomes_stale_and_can_be_reassessed(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = accept_research_claim(root)

    initial = _acceptance_projection(root)
    assert [(item["acceptance_id"], item["current"]) for item in initial] == [(refs["acceptance"], True)]

    _apply(
        root,
        [
            {
                "op": "record_finding",
                "local_ref": "limitation",
                "findingType": "bounded_limitation",
                "severity": "warning",
                "statement": "A nonblocking limitation was identified after acceptance.",
                "claimRefs": [refs["claim"]],
                "actRefs": [refs["act"]],
            }
        ],
    )
    stale = _acceptance_projection(root)
    assert stale[0]["current"] is False
    assert stale[0]["stale_reasons"] == ["finding_snapshot_changed"]
    validation = validate_workspace(root)
    assert validation["valid"] is True
    assert "acceptance_not_current" in {item["code"] for item in validation["findings"]}

    reassessed, _ = _apply(
        root,
        [
            {
                "op": "accept_claim",
                "local_ref": "reassessment",
                "claimRef": refs["claim"],
                "profile": {"profileId": "research-claim", "version": "1"},
                "summary": "The warning was included in a new acceptance assessment.",
            }
        ],
    )
    projected = _acceptance_projection(root)
    assert [item["current"] for item in projected] == [False, True]
    assert projected[-1]["acceptance_id"] == reassessed["allocated_refs"]["reassessment"]


def test_acceptance_record_tampering_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    refs = accept_research_claim(root)
    path = root / "acceptances" / f"{refs['acceptance']}.json"
    record = read_json(path)
    record["summary"] = "A directly edited summary must not retain acceptance integrity."
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    validation = validate_workspace(root)
    assert validation["valid"] is False
    assert "acceptance_digest_mismatch" in {item["code"] for item in validation["findings"]}


def test_decision_replay_is_idempotent_but_conflicting_parallel_decision_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    first = draft_decision(
        root,
        {"rationale": "Create one Claim.", "basis_refs": [], "operations": [{"op": "create_claim", "local_ref": "claim", "claimType": "test", "statement": "One Claim."}]},
    )
    stale = draft_decision(
        root,
        {"rationale": "Create another Claim.", "basis_refs": [], "operations": [{"op": "create_claim", "local_ref": "claim", "claimType": "test", "statement": "Another Claim."}]},
    )
    applied = apply_decision(root, first["decision"])
    assert apply_decision(root, first["decision"]) == applied
    with pytest.raises(ContractError, match="already exists with different content"):
        apply_decision(root, stale["decision"])


def test_v4_validator_rejects_legacy_canonical_markers(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    (root / "gate_results.json").write_text("{}\n", encoding="utf-8")
    validation = validate_workspace(root)
    assert validation["valid"] is False
    assert "legacy_state_present" in {item["code"] for item in validation["findings"]}
