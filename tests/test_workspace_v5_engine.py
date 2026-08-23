from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.v5_helpers import accept_research_claim
from ts_workspace.acceptance import project_acceptances
from ts_workspace.decision import draft_decision as _kernel_draft_decision
from ts_workspace.engine import apply_decision, init_workspace, validate_decision_dry_run
from ts_workspace.errors import ContractError
from ts_workspace.io import read_json, write_json
from ts_workspace.state import RESEARCH_STATE_FILE, STATE_FILES
from ts_workspace.validator import validate_workspace


def draft_decision(root: Path, request: dict, **kwargs: object) -> dict:
    operations = [dict(operation) for operation in request.get("operations", [])]
    starts = [operation for operation in operations if operation.get("op") == "start_node"]
    if starts:
        phase_operations = [operation for operation in operations if operation.get("op") == "create_phase"]
        existing_phases = read_json(root / "phases.json")["phases"]
        if phase_operations:
            phase_ref = f"${phase_operations[0]['local_ref']}"
        elif existing_phases:
            phase_ref = existing_phases[0]["phase_id"]
        else:
            operations.insert(0, {
                "op": "create_phase",
                "local_ref": "phase",
                "title": "Test phase",
                "objective": "Contain the ResearchNodes created by this test.",
            })
            phase_ref = "$phase"
        for operation in starts:
            operation.setdefault("phaseRef", phase_ref)
    return _kernel_draft_decision(root, {**request, "operations": operations}, **kwargs)


def _apply(root: Path, operations: list[dict], *, rationale: str = "Exercise the v5 research Kernel.") -> tuple[dict, dict]:
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


def test_research_node_dag_supports_branch_merge_and_kernel_ids(tmp_path: Path) -> None:
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
                "op": "start_node",
                "local_ref": "intake",
                "title": "Bounded research node",
                "deliverable": "One bounded research result.",
                "objective": "Bind the initial molecular system and assumptions.",
                "primaryClaimRef": "$mechanism",
                "claimRefs": ["$mechanism"],
            },
            {
                "op": "start_node",
                "local_ref": "path_a",
                "title": "Bounded research node",
                "deliverable": "One bounded research result.",
                "objective": "Test the concerted pathway.",
                "dependencyRefs": ["$intake"],
                "primaryClaimRef": "$mechanism",
                "claimRefs": ["$mechanism"],
            },
            {
                "op": "start_node",
                "local_ref": "path_b",
                "title": "Bounded research node",
                "deliverable": "One bounded research result.",
                "objective": "Search for a stepwise alternative.",
                "dependencyRefs": ["$intake"],
                "primaryClaimRef": "$mechanism",
                "claimRefs": ["$mechanism"],
            },
            {
                "op": "start_node",
                "local_ref": "synthesis",
                "title": "Bounded research node",
                "deliverable": "One bounded research result.",
                "objective": "Compare both searches without discarding either history.",
                "dependencyRefs": ["$path_a", "$path_b"],
                "primaryClaimRef": "$mechanism",
                "claimRefs": ["$mechanism"],
            },
            {"op": "set_focus", "claimRefs": ["$mechanism"], "nodeRefs": ["$synthesis"]},
        ],
    )

    allocations = drafted["allocated_refs"]
    assert set(allocations) == {"phase", "mechanism", "intake", "path_a", "path_b", "synthesis"}
    assert allocations["phase"] == "phase_1"
    assert allocations["mechanism"] == "claim_1"
    assert [allocations[name] for name in ("intake", "path_a", "path_b", "synthesis")] == [
        "node_1",
        "node_2",
        "node_3",
        "node_4",
    ]
    assert result["created_refs"]["nodes"] == [
        allocations["intake"],
        allocations["path_a"],
        allocations["path_b"],
        allocations["synthesis"],
    ]
    nodes = {item["node_id"]: item for item in read_json(root / "research_nodes.json")["nodes"]}
    assert nodes[allocations["synthesis"]]["dependency_refs"] == [allocations["path_a"], allocations["path_b"]]
    assert {node["phase_ref"] for node in nodes.values()} == {allocations["phase"]}
    assert not (root / "nodes" / allocations["synthesis"]).exists()
    assert validate_workspace(root)["valid"] is True


def test_research_node_requires_an_explicit_phase_reference(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    with pytest.raises(ContractError, match="phaseRef"):
        _kernel_draft_decision(
            root,
            {
                "rationale": "Reject an unscoped ResearchNode.",
                "basis_refs": [],
                "operations": [{
                    "op": "start_node",
                    "local_ref": "node",
                    "title": "Unscoped Node",
                    "objective": "Demonstrate the Phase invariant.",
                    "deliverable": "A rejected draft.",
                }],
            },
        )


@pytest.mark.parametrize("missing_field", ["title", "deliverable"])
def test_research_node_schema_requires_human_navigation_fields(
    tmp_path: Path,
    missing_field: str,
) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    _apply(
        root,
        [{
            "op": "start_node",
            "local_ref": "node",
            "title": "Candidate generation",
            "objective": "Generate one bounded transition-state candidate set.",
            "deliverable": "A ranked candidate set with provenance.",
        }],
    )
    registry = read_json(root / "research_nodes.json")
    registry["nodes"][0].pop(missing_field)
    write_json(root / "research_nodes.json", registry)

    validation = validate_workspace(root)

    assert validation["valid"] is False
    assert any(
        finding["code"] == "schema_validation_failed"
        and missing_field in finding["message"]
        for finding in validation["findings"]
    )


def test_research_node_ids_are_monotonic_and_parallel_decision_collision_must_redraft(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    first, _ = _apply(
        root,
        [{"op": "start_node", "local_ref": "first", "title": "Bounded research node", "deliverable": "One bounded research result.", "objective": "Create the first bounded Node."}],
    )
    assert first["allocated_refs"]["first"] == "node_1"

    left = draft_decision(
        root,
        {
            "rationale": "Draft one branch.",
            "basis_refs": [],
            "operations": [{"op": "start_node", "local_ref": "left", "title": "Bounded research node", "deliverable": "One bounded research result.", "objective": "Create the left branch."}],
        },
    )
    right = draft_decision(
        root,
        {
            "rationale": "Draft another branch from the same revision.",
            "basis_refs": [],
            "operations": [{"op": "start_node", "local_ref": "right", "title": "Bounded research node", "deliverable": "One bounded research result.", "objective": "Create the right branch."}],
        },
    )
    assert left["allocated_refs"]["left"] == "node_2"
    assert right["allocated_refs"]["right"] == "node_2"

    apply_decision(root, left["decision"])
    with pytest.raises(ContractError, match="already exists with different content"):
        apply_decision(root, right["decision"])

    redrafted = draft_decision(
        root,
        {
            "rationale": "Redraft the second branch against the current revision.",
            "basis_refs": [],
            "operations": [{"op": "start_node", "local_ref": "right", "title": "Bounded research node", "deliverable": "One bounded research result.", "objective": "Create the right branch."}],
        },
    )
    assert redrafted["allocated_refs"]["right"] == "node_3"


def test_decision_ids_are_monotonic_and_parallel_drafts_conflict_before_redraft(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    left = draft_decision(
        root,
        {
            "rationale": "Draft the left branch.",
            "basis_refs": [],
            "operations": [{"op": "start_node", "local_ref": "left", "title": "Bounded research node", "deliverable": "One bounded research result.", "objective": "Create the left branch."}],
        },
    )
    right = draft_decision(
        root,
        {
            "rationale": "Draft the right branch from the same revision.",
            "basis_refs": [],
            "operations": [{"op": "start_node", "local_ref": "right", "title": "Bounded research node", "deliverable": "One bounded research result.", "objective": "Create the right branch."}],
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
            "operations": [{"op": "start_node", "local_ref": "right", "title": "Bounded research node", "deliverable": "One bounded research result.", "objective": "Create the right branch."}],
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
            "operations": [{"op": "start_node", "local_ref": "next", "title": "Bounded research node", "deliverable": "One bounded research result.", "objective": "Use the next Decision ID."}],
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


def test_validation_record_ids_are_readable_workspace_ordinals(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)

    first = accept_research_claim(root)
    assert first["observation"] == "obs_1"
    assert first["spec"] == "gsp_1"
    assert first["result"] == "val_1"

    drafted = draft_decision(
        root,
        {
            "rationale": "Record and validate a second bounded observation.",
            "basis_refs": [],
            "operations": [
                {
                    "op": "record_observation",
                    "local_ref": "observation",
                    "nodeRef": first["node"],
                    "conceptId": "test.confirmed_again",
                    "subjectRef": "subject",
                    "value": True,
                    "datatype": "boolean",
                    "summary": "The second bounded condition was observed.",
                    "provenance": {"producer": "test"},
                },
                {
                    "op": "freeze_validation_spec",
                    "local_ref": "spec",
                    "nodeRef": first["node"],
                    "targetClaimRef": first["claim"],
                    "dimension": "test_again",
                    "title": "Second bounded check",
                    "definition": {
                        "checks": [
                            {
                                "check_id": "confirmed_again",
                                "predicate": "observation.equals",
                                "parameters": {
                                    "selector": {
                                        "concept_id": "test.confirmed_again",
                                        "subject_ref": "subject",
                                    },
                                    "expected": True,
                                },
                                "blocking": True,
                            }
                        ],
                        "success_policy": {"mode": "all_blocking"},
                    },
                },
                {
                    "op": "evaluate_validation",
                    "local_ref": "result",
                    "nodeRef": first["node"],
                    "specRef": "$spec",
                    "observationRefs": ["$observation"],
                },
            ],
        },
    )

    assert drafted["allocated_refs"] == {
        "observation": "obs_2",
        "spec": "gsp_2",
        "result": "val_2",
    }
    apply_decision(root, drafted["decision"])
    assert validate_workspace(root)["valid"] is True


def test_decision_snapshots_preserve_human_readable_utf8(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    rationale = "未能定位连接反应物与产物的一阶鞍点。"
    drafted, _ = _apply(
        root,
        [{"op": "start_node", "local_ref": "search", "title": "Bounded research node", "deliverable": "One bounded research result.", "objective": "搜索协同反应路径。"}],
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
    assert drafted["allocated_refs"]["ab"] == "rel_1"
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
        {"op": "start_node", "local_ref": "validate", "title": "Bounded research node", "deliverable": "One bounded research result.", "objective": "Validate stationary point, mode, and connectivity.", "claimRefs": ["$ts"]},
    ]
    for alias, concept, value, qualifiers in observations:
        datatype = "boolean" if isinstance(value, bool) else "integer" if isinstance(value, int) else "string" if isinstance(value, str) else "json"
        operations.append(
            {
                "op": "record_observation",
                "local_ref": alias,
                "nodeRef": "$validate",
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
                "nodeRef": "$validate",
                "targetClaimRef": "$ts",
                "dimension": "stationary_point",
                "title": "Classical TS stationary point",
                "template": {"templateId": "classical-ts", "version": "1", "parameters": {"subject_ref": "calc_ts_001"}},
            },
            {
                "op": "freeze_validation_spec",
                "local_ref": "mode_spec",
                "nodeRef": "$validate",
                "targetClaimRef": "$ts",
                "dimension": "reaction_coordinate",
                "title": "Mode assignment",
                "template": {"templateId": "reaction-coordinate", "version": "1", "parameters": {"subject_ref": "calc_ts_001"}},
            },
            {
                "op": "freeze_validation_spec",
                "local_ref": "connectivity_spec",
                "nodeRef": "$validate",
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
                "nodeRef": "$validate",
                "specRef": "$stationary_spec",
                "observationRefs": ["$normal", "$stationary", "$converged", "$imaginary", "$method"],
            },
            {
                "op": "evaluate_validation",
                "local_ref": "mode_result",
                "nodeRef": "$validate",
                "specRef": "$mode_spec",
                "observationRefs": ["$mode"],
            },
            {
                "op": "evaluate_validation",
                "local_ref": "connectivity_result",
                "nodeRef": "$validate",
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
                "op": "complete_node",
                "nodeRef": "$validate",
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
    assert drafted["allocated_refs"]["normal"] == "obs_1"
    assert drafted["allocated_refs"]["forward_endpoint"] == "obs_10"
    assert drafted["allocated_refs"]["stationary_spec"] == "gsp_1"
    assert drafted["allocated_refs"]["connectivity_spec"] == "gsp_3"
    assert drafted["allocated_refs"]["stationary_result"] == "val_1"
    assert drafted["allocated_refs"]["connectivity_result"] == "val_3"
    assert drafted["allocated_refs"]["accepted_ts"] == "acc_1"
    acceptance_id = drafted["allocated_refs"]["accepted_ts"]
    accepted = read_json(root / "acceptances" / f"{acceptance_id}.json")
    assert accepted["schema_version"] == "ts-acceptance-record/2"
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
            {"op": "start_node", "local_ref": "node", "title": "Bounded research node", "deliverable": "One bounded research result.", "objective": "Test the claim.", "claimRefs": ["$claim"]},
            {
                "op": "record_observation", "local_ref": "obs", "nodeRef": "$node", "conceptId": "test.confirmed", "subjectRef": "subject", "value": True,
                "datatype": "boolean", "summary": "Confirmed.", "provenance": {"producer": "test"}
            },
            {
                "op": "freeze_validation_spec", "local_ref": "spec", "nodeRef": "$node", "targetClaimRef": "$claim", "dimension": "test", "title": "Test",
                "definition": {"checks": [{"check_id": "confirmed", "predicate": "observation.equals", "parameters": {"selector": {"concept_id": "test.confirmed", "subject_ref": "subject"}, "expected": True}, "blocking": True}], "success_policy": {"mode": "all_blocking"}}
            },
            {"op": "evaluate_validation", "local_ref": "result", "nodeRef": "$node", "specRef": "$spec", "observationRefs": ["$obs"]},
            {"op": "record_finding", "local_ref": "risk", "findingType": "unexpected_state", "severity": "blocking", "statement": "An unresolved anomaly remains.", "claimRefs": ["$claim"], "nodeRefs": ["$node"]},
        ],
    )
    assert drafted["allocated_refs"]["risk"] == "fnd_1"
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
                    {"op": "start_node", "local_ref": "node", "title": "Bounded research node", "deliverable": "One bounded research result.", "objective": "Observe one fact without a GateSpec.", "claimRefs": ["$claim"]},
                    {
                        "op": "record_observation",
                        "local_ref": "observation",
                        "nodeRef": "$node",
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
    assert refs["acceptance"] == "acc_1"

    initial = _acceptance_projection(root)
    assert [(item["acceptance_id"], item["current"]) for item in initial] == [(refs["acceptance"], True)]

    finding, _ = _apply(
        root,
        [
            {
                "op": "record_finding",
                "local_ref": "limitation",
                "findingType": "bounded_limitation",
                "severity": "warning",
                "statement": "A nonblocking limitation was identified after acceptance.",
                "claimRefs": [refs["claim"]],
                "nodeRefs": [refs["node"]],
            }
        ],
    )
    assert finding["allocated_refs"]["limitation"] == "fnd_1"
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
    assert reassessed["allocated_refs"]["reassessment"] == "acc_2"
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


def test_v5_validator_rejects_legacy_canonical_markers(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    (root / "gate_results.json").write_text("{}\n", encoding="utf-8")
    validation = validate_workspace(root)
    assert validation["valid"] is False
    assert "legacy_state_present" in {item["code"] for item in validation["findings"]}
