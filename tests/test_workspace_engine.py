from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.workspace_helpers import (
    accept_research_claim,
    calculation_prepared_fixture,
    calculation_intent_fixture,
    calculation_result_fixture,
)
from ts_agent.workspace.acceptance import project_acceptances
from tests.kernel_helpers import compile_change as _kernel_compile_change
from ts_agent.workspace.decision import validate_decision
from ts_agent.workspace.engine import change_workspace, init_workspace
from tests.kernel_helpers import apply_compiled_change, validate_compiled_change
from ts_agent.workspace.errors import ContractError
from ts_agent.io import read_json, write_json
from ts_agent.workspace.state import RESEARCH_STATE_FILE, STATE_FILES
from ts_agent.workspace.validator import validate_workspace


def compile_change(root: Path, request: dict, **kwargs: object) -> dict:
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
    return _kernel_compile_change(root, {**request, "operations": operations}, **kwargs)


def _apply(root: Path, operations: list[dict], *, rationale: str = "Exercise the research kernel.") -> tuple[dict, dict]:
    drafted = compile_change(
        root,
        {"rationale": rationale, "basis_refs": [], "operations": operations},
    )
    validation = validate_compiled_change(root, drafted["decision"])
    assert validation["valid"] is True
    result = apply_compiled_change(root, drafted["decision"])
    return drafted, result


def _acceptance_projection(root: Path) -> list[dict]:
    documents = {name: read_json(root / name) for name in STATE_FILES}
    return project_acceptances(root, documents[RESEARCH_STATE_FILE]["acceptance_refs"], documents)


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        ({}, "'op' is a required property"),
        ({"op": "not_a_kernel_operation"}, "unsupported change operation"),
        (
            {"op": "set_focus", **{f"extra_{index}": index for index in range(24)}},
            "has too many properties",
        ),
    ],
)
def test_ts_change_rejects_malformed_or_oversized_operation_envelope(
    tmp_path: Path,
    operation: dict,
    message: str,
) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)

    with pytest.raises(ContractError, match=message):
        change_workspace(
            root,
            {
                "schema_version": "ts-change-request/1",
                "rationale": "Reject an invalid typed mutation envelope.",
                "basis_refs": [],
                "operations": [operation],
            },
        )


def test_ts_change_is_atomic_when_post_state_validation_fails(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    before = {name: (root / name).read_bytes() for name in STATE_FILES}
    request = {
        "schema_version": "ts-change-request/1",
        "rationale": "Reject a cyclic Claim graph without committing its partial proposal.",
        "basis_refs": [],
        "operations": [
            {
                "op": "create_claim",
                "local_ref": "a",
                "question": "Which Claim is first?",
                "claimType": "test",
                "statement": "Claim A.",
                "scope": "The bounded fixture.",
                "uncertainty": "The relation is unresolved.",
                "predictions": ["A testable observation supports Claim A."],
                "falsifiers": ["A testable observation contradicts Claim A."],
            },
            {
                "op": "create_claim",
                "local_ref": "b",
                "question": "Which Claim is second?",
                "claimType": "test",
                "statement": "Claim B.",
                "scope": "The bounded fixture.",
                "uncertainty": "The relation is unresolved.",
                "predictions": ["A testable observation supports Claim B."],
                "falsifiers": ["A testable observation contradicts Claim B."],
            },
            {
                "op": "relate_claims",
                "local_ref": "ab",
                "sourceClaimRef": "$a",
                "targetClaimRef": "$b",
                "relationType": "depends_on",
                "rationale": "A depends on B.",
            },
            {
                "op": "relate_claims",
                "local_ref": "ba",
                "sourceClaimRef": "$b",
                "targetClaimRef": "$a",
                "relationType": "depends_on",
                "rationale": "B depends on A.",
            },
        ],
    }

    with pytest.raises(ContractError, match="cycle"):
        change_workspace(root, request)

    assert before == {name: (root / name).read_bytes() for name in STATE_FILES}
def test_research_node_dag_supports_branch_merge_and_kernel_ids(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    intake_draft, intake_result = _apply(
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
            {"op": "set_focus", "claimRefs": ["$mechanism"], "nodeRefs": ["$intake"]},
        ],
    )
    phase_id = intake_draft["allocated_refs"]["phase"]
    claim_id = intake_draft["allocated_refs"]["mechanism"]
    intake_id = intake_draft["allocated_refs"]["intake"]
    path_a_draft, _ = _apply(root, [{
        "op": "start_node", "local_ref": "path_a", "title": "Concerted-path decision",
        "deliverable": "One bounded research result.", "objective": "Test the concerted pathway.",
        "dependencyRefs": [intake_id], "primaryClaimRef": claim_id, "claimRefs": [claim_id],
    }], rationale="Open the concerted-path research branch.")
    path_b_draft, _ = _apply(root, [{
        "op": "start_node", "local_ref": "path_b", "title": "Stepwise-path decision",
        "deliverable": "One bounded research result.", "objective": "Search for a stepwise alternative.",
        "dependencyRefs": [intake_id], "primaryClaimRef": claim_id, "claimRefs": [claim_id],
    }], rationale="Open the competing stepwise-path research branch.")
    path_a_id = path_a_draft["allocated_refs"]["path_a"]
    path_b_id = path_b_draft["allocated_refs"]["path_b"]
    synthesis_draft, synthesis_result = _apply(root, [{
        "op": "start_node", "local_ref": "synthesis", "title": "Branch synthesis decision",
        "deliverable": "One bounded comparison of both branches.",
        "objective": "Compare both searches without discarding either history.",
        "dependencyRefs": [path_a_id, path_b_id], "primaryClaimRef": claim_id, "claimRefs": [claim_id],
    }, {"op": "set_focus", "claimRefs": [claim_id], "nodeRefs": ["$synthesis"]}], rationale="Merge both completed research questions for synthesis.")
    synthesis_id = synthesis_draft["allocated_refs"]["synthesis"]

    assert phase_id == "phase_1"
    assert claim_id == "claim_1"
    assert [intake_id, path_a_id, path_b_id, synthesis_id] == ["node_1", "node_2", "node_3", "node_4"]
    assert intake_result["created_refs"]["nodes"] == [intake_id]
    assert synthesis_result["created_refs"]["nodes"] == [synthesis_id]
    nodes = {item["node_id"]: item for item in read_json(root / "research_nodes.json")["nodes"]}
    assert nodes[synthesis_id]["dependency_refs"] == [path_a_id, path_b_id]
    assert {node["phase_ref"] for node in nodes.values()} == {phase_id}
    assert not (root / "nodes" / synthesis_id).exists()
    assert validate_workspace(root)["valid"] is True


@pytest.mark.parametrize("operation", ["create_phase", "start_node", "complete_node"])
def test_one_research_decision_cannot_open_or_close_multiple_roadmap_records(
    tmp_path: Path,
    operation: str,
) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    operations = [{"op": operation}, {"op": operation}]

    with pytest.raises(ContractError, match="each material research transition remains visible"):
        _kernel_compile_change(
            root,
            {"rationale": "Reject an opaque multi-Node transition.", "basis_refs": [], "operations": operations},
        )


def test_frozen_decision_cannot_bypass_the_single_node_transition_contract(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    drafted = _kernel_compile_change(
        root,
        {
            "rationale": "Open one visible research decision.",
            "basis_refs": [],
            "operations": [
                {"op": "create_phase", "local_ref": "phase", "title": "Exploration", "objective": "Test one question."},
                {
                    "op": "start_node", "local_ref": "first", "phaseRef": "$phase",
                    "title": "First decision", "objective": "Test the first question.",
                    "deliverable": "One first-question result.",
                },
            ],
        },
    )
    forged = deepcopy(drafted["decision"])
    second = deepcopy(next(operation for operation in forged["operations"] if operation["op"] == "append_research_node"))
    second["record"]["node_id"] = "node_2"
    second["record"]["artifact_root"] = "nodes/node_2"
    forged["operations"].append(second)
    forged["allocations"]["second"] = "node_2"

    with pytest.raises(ContractError, match="each material research transition remains visible"):
        validate_decision(forged)


def test_one_decision_may_close_a_node_and_open_its_successor(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    first, _ = _apply(root, [{
        "op": "start_node", "local_ref": "first", "title": "Candidate decision",
        "objective": "Determine whether one candidate is viable.",
        "deliverable": "One candidate viability result.",
    }])
    first_id = first["allocated_refs"]["first"]

    successor, _ = _apply(root, [
        {"op": "complete_node", "nodeRef": first_id, "outcome": "completed", "summary": "The candidate is viable."},
        {
            "op": "start_node", "local_ref": "successor", "title": "Connectivity decision",
            "objective": "Determine which endpoints this candidate connects.",
            "deliverable": "One endpoint-connectivity conclusion.", "dependencyRefs": [first_id],
        },
    ], rationale="The viable candidate justifies a separate connectivity question.")
    successor_id = successor["allocated_refs"]["successor"]
    nodes = {row["node_id"]: row for row in read_json(root / "research_nodes.json")["nodes"]}

    assert nodes[first_id]["status"] == "completed"
    assert nodes[successor_id]["status"] == "open"
    assert nodes[successor_id]["dependency_refs"] == [first_id]


def test_node_completion_rejects_a_queued_calculation_attempt(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    started, _ = _apply(root, [{
        "op": "start_node",
        "local_ref": "node",
        "title": "Wait for calculation",
        "objective": "Keep the research episode open until its calculation settles.",
        "deliverable": "A terminal calculation outcome.",
    }])
    node_id = started["allocated_refs"]["node"]
    attempt = root / "nodes" / node_id / "attempts" / "calc_1"
    intent = calculation_intent_fixture(node_id, "calc_1")
    write_json(attempt / "intent.json", intent)
    write_json(attempt / "prepared.json", calculation_prepared_fixture(intent))
    write_json(
        attempt / "status.json",
        calculation_result_fixture(
            intent,
            state="queued",
            program_status="not_run",
            job_id="208319.cluster.hpc",
        ),
    )

    with pytest.raises(ContractError, match="calculation Attempt is still queued"):
        _apply(root, [{
            "op": "complete_node",
            "nodeRef": node_id,
            "outcome": "inconclusive",
            "summary": "The calculation has not reached a terminal state.",
        }])

    write_json(
        attempt / "outputs" / "calculation_result.json",
        calculation_result_fixture(
            intent,
            state="parsed",
            program_status="completed",
            job_id="208319.cluster.hpc",
        ),
    )
    _apply(root, [{
        "op": "complete_node",
        "nodeRef": node_id,
        "outcome": "completed",
        "summary": "The parsed calculation is now terminal.",
    }])


def test_one_decision_may_start_and_complete_the_same_node(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)

    drafted, _ = _apply(
        root,
        [
            {
                "op": "start_node",
                "local_ref": "synthesis",
                "title": "Existing-evidence synthesis",
                "objective": "Summarize one bounded conclusion from existing evidence.",
                "deliverable": "One synthesis conclusion.",
            },
            {
                "op": "complete_node",
                "nodeRef": "$synthesis",
                "outcome": "completed",
                "summary": "The existing evidence supports the bounded conclusion.",
            },
        ],
        rationale="Record one fully resolved research decision as a visible Node.",
    )
    node_id = drafted["allocated_refs"]["synthesis"]
    node = read_json(root / "research_nodes.json")["nodes"][0]

    assert node["node_id"] == node_id
    assert node["status"] == "completed"
    assert node["result"]["decision_id"] == drafted["decision"]["decision_id"]


def test_combined_close_and_open_requires_an_explicit_successor_edge(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    first, _ = _apply(root, [{
        "op": "start_node", "local_ref": "first", "title": "Candidate decision",
        "objective": "Determine whether one candidate is viable.",
        "deliverable": "One candidate viability result.",
    }])

    with pytest.raises(ContractError, match="explicit dependency of its successor"):
        _kernel_compile_change(
            root,
            {
                "rationale": "Do not hide two unrelated research transitions.",
                "basis_refs": [],
                "operations": [
                    {
                        "op": "complete_node",
                        "nodeRef": first["allocated_refs"]["first"],
                        "outcome": "completed",
                        "summary": "The candidate is viable.",
                    },
                    {
                        "op": "start_node",
                        "local_ref": "unrelated",
                        "title": "Unrelated decision",
                        "objective": "Answer a separate question.",
                        "deliverable": "One unrelated result.",
                    },
                ],
            },
        )


def test_research_node_requires_an_explicit_phase_reference(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    with pytest.raises(ContractError, match="phaseRef"):
        _kernel_compile_change(
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

    left = compile_change(
        root,
        {
            "rationale": "Draft one branch.",
            "basis_refs": [],
            "operations": [{"op": "start_node", "local_ref": "left", "title": "Bounded research node", "deliverable": "One bounded research result.", "objective": "Create the left branch."}],
        },
    )
    right = compile_change(
        root,
        {
            "rationale": "Draft another branch from the same revision.",
            "basis_refs": [],
            "operations": [{"op": "start_node", "local_ref": "right", "title": "Bounded research node", "deliverable": "One bounded research result.", "objective": "Create the right branch."}],
        },
    )
    assert left["allocated_refs"]["left"] == "node_2"
    assert right["allocated_refs"]["right"] == "node_2"

    apply_compiled_change(root, left["decision"])
    with pytest.raises(ContractError, match="already exists with different content"):
        apply_compiled_change(root, right["decision"])

    redrafted = compile_change(
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
    left = compile_change(
        root,
        {
            "rationale": "Draft the left branch.",
            "basis_refs": [],
            "operations": [{"op": "start_node", "local_ref": "left", "title": "Bounded research node", "deliverable": "One bounded research result.", "objective": "Create the left branch."}],
        },
    )
    right = compile_change(
        root,
        {
            "rationale": "Draft the right branch from the same revision.",
            "basis_refs": [],
            "operations": [{"op": "start_node", "local_ref": "right", "title": "Bounded research node", "deliverable": "One bounded research result.", "objective": "Create the right branch."}],
        },
    )
    assert left["decision"]["decision_id"] == "dec_1"
    assert right["decision"]["decision_id"] == "dec_1"

    applied = apply_compiled_change(root, left["decision"])
    assert apply_compiled_change(root, left["decision"]) == applied
    with pytest.raises(ContractError, match="already exists with different content"):
        apply_compiled_change(root, right["decision"])

    redrafted = compile_change(
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

    drafted = compile_change(
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

    left = compile_change(
        root,
        {
            "rationale": "Draft one Claim.",
            "basis_refs": [],
            "operations": [
                {"op": "create_claim", "local_ref": "left", "claimType": "hypothesis", "statement": "Left Claim."}
            ],
        },
    )
    right = compile_change(
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

    apply_compiled_change(root, left["decision"])
    with pytest.raises(ContractError, match="already exists with different content"):
        apply_compiled_change(root, right["decision"])

    redrafted = compile_change(
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
    assert first["spec"] == "proof_1"
    assert first["result"] == "result_1"

    drafted = compile_change(
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
                    "op": "freeze_proof_spec",
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
                    "op": "evaluate_proof",
                    "local_ref": "result",
                    "nodeRef": first["node"],
                    "proofRef": "$spec",
                    "observationRefs": ["$observation"],
                },
            ],
        },
    )

    assert drafted["allocated_refs"] == {
        "observation": "obs_2",
        "spec": "proof_2",
        "result": "result_2",
    }
    apply_compiled_change(root, drafted["decision"])
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
    reverse = compile_change(
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
        validate_compiled_change(root, reverse["decision"])
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
                "op": "freeze_proof_spec",
                "local_ref": "stationary_spec",
                "nodeRef": "$validate",
                "targetClaimRef": "$ts",
                "dimension": "stationary_point",
                "title": "Classical TS stationary point",
                "template": {"templateId": "classical-ts", "version": "1", "parameters": {"subject_ref": "calc_ts_001"}},
            },
            {
                "op": "freeze_proof_spec",
                "local_ref": "mode_spec",
                "nodeRef": "$validate",
                "targetClaimRef": "$ts",
                "dimension": "reaction_coordinate",
                "title": "Mode assignment",
                "template": {"templateId": "reaction-coordinate", "version": "1", "parameters": {"subject_ref": "calc_ts_001"}},
            },
            {
                "op": "freeze_proof_spec",
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
                "op": "evaluate_proof",
                "local_ref": "stationary_result",
                "nodeRef": "$validate",
                "proofRef": "$stationary_spec",
                "observationRefs": ["$normal", "$stationary", "$converged", "$imaginary", "$method"],
            },
            {
                "op": "evaluate_proof",
                "local_ref": "mode_result",
                "nodeRef": "$validate",
                "proofRef": "$mode_spec",
                "observationRefs": ["$mode"],
            },
            {
                "op": "evaluate_proof",
                "local_ref": "connectivity_result",
                "nodeRef": "$validate",
                "proofRef": "$connectivity_spec",
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
    assert len(result["created_refs"]["proof_specs"]) == 3
    assert len(result["created_refs"]["validation_results"]) == 3
    assert len(result["created_refs"]["acceptances"]) == 1
    assert drafted["allocated_refs"]["normal"] == "obs_1"
    assert drafted["allocated_refs"]["forward_endpoint"] == "obs_10"
    assert drafted["allocated_refs"]["stationary_spec"] == "proof_1"
    assert drafted["allocated_refs"]["connectivity_spec"] == "proof_3"
    assert drafted["allocated_refs"]["stationary_result"] == "result_1"
    assert drafted["allocated_refs"]["connectivity_result"] == "result_3"
    assert drafted["allocated_refs"]["accepted_ts"] == "acc_1"
    acceptance_id = drafted["allocated_refs"]["accepted_ts"]
    accepted = read_json(root / "acceptances" / f"{acceptance_id}.json")
    assert accepted["schema_version"] == "ts-acceptance-record/3"
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
                "op": "freeze_proof_spec", "local_ref": "spec", "nodeRef": "$node", "targetClaimRef": "$claim", "dimension": "test", "title": "Test",
                "definition": {"checks": [{"check_id": "confirmed", "predicate": "observation.equals", "parameters": {"selector": {"concept_id": "test.confirmed", "subject_ref": "subject"}, "expected": True}, "blocking": True}], "success_policy": {"mode": "all_blocking"}}
            },
            {"op": "evaluate_proof", "local_ref": "result", "nodeRef": "$node", "proofRef": "$spec", "observationRefs": ["$obs"]},
            {"op": "record_finding", "local_ref": "risk", "findingType": "unexpected_state", "severity": "blocking", "statement": "An unresolved anomaly remains.", "claimRefs": ["$claim"], "nodeRefs": ["$node"]},
        ],
    )
    assert drafted["allocated_refs"]["risk"] == "fnd_1"
    claim = drafted["allocated_refs"]["claim"]
    with pytest.raises(ContractError, match="blocking Findings"):
        compile_change(
            root,
            {
                "rationale": "Attempt acceptance while a blocker is open.",
                "basis_refs": [],
                "operations": [{"op": "accept_claim", "local_ref": "accept", "claimRef": claim, "profile": {"profileId": "research-claim", "version": "1"}, "summary": "Should be blocked."}],
            },
        )


def test_acceptance_requires_at_least_one_attached_proof_spec(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)

    with pytest.raises(ContractError, match="at least one attached ProofSpec"):
        compile_change(
            root,
            {
                "rationale": "Do not accept an unvalidated Claim.",
                "basis_refs": [],
                "operations": [
                    {"op": "create_claim", "local_ref": "claim", "claimType": "research", "statement": "An unvalidated Claim."},
                    {"op": "start_node", "local_ref": "node", "title": "Bounded research node", "deliverable": "One bounded research result.", "objective": "Observe one fact without a ProofSpec.", "claimRefs": ["$claim"]},
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
    first = compile_change(
        root,
        {"rationale": "Create one Claim.", "basis_refs": [], "operations": [{"op": "create_claim", "local_ref": "claim", "claimType": "test", "statement": "One Claim."}]},
    )
    stale = compile_change(
        root,
        {"rationale": "Create another Claim.", "basis_refs": [], "operations": [{"op": "create_claim", "local_ref": "claim", "claimType": "test", "statement": "Another Claim."}]},
    )
    applied = apply_compiled_change(root, first["decision"])
    assert apply_compiled_change(root, first["decision"]) == applied
    with pytest.raises(ContractError, match="already exists with different content"):
        apply_compiled_change(root, stale["decision"])


def test_validator_rejects_unsupported_canonical_markers(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    init_workspace(root)
    (root / "gate_results.json").write_text("{}\n", encoding="utf-8")
    validation = validate_workspace(root)
    assert validation["valid"] is False
    assert "unsupported_state_present" in {item["code"] for item in validation["findings"]}
