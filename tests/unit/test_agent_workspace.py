from __future__ import annotations

import json
from pathlib import Path

import pytest

from ts_agent.research.agent_workspace import (
    ADMITTED,
    ADMISSION_PENDING,
    CONTEXT_SCHEMA,
    LIVENESS_SCHEMA,
    RESEARCH_CONTEXT_COLLECTIONS,
    AgentWorkspaceError,
    admit_workspace,
    apply_change,
    checkpoint,
    read_context,
    read_liveness,
    turn,
)
from ts_agent.api import execute
from ts_agent.runtime.workspace_mode import initialize_workspace


def _workspace(root: Path) -> None:
    initialize_workspace(root, "workspace_python_unit", "research")


def test_new_workspace_change_checkpoint_and_turn_are_durable(tmp_path: Path) -> None:
    _workspace(tmp_path)
    admitted = admit_workspace(tmp_path, {"workspace_id": "workspace_python_unit", "authority": "host"})
    assert admitted["state"] == ADMITTED
    result = apply_change(
        tmp_path,
        {
            "workspace_id": "workspace_python_unit",
            "principal": "root_agent",
            "authority": "kernel_write",
            "expected_revision": 0,
            "operations": [
                {"type": "create_phase", "id": "phase_1", "title": "Phase", "objective": "Inputs"},
                {"type": "create_claim", "id": "claim_1", "statement": "Hypothesis", "status": "open"},
                {
                    "type": "create_node", "id": "node_1", "title": "Node", "objective": "Study",
                    "phase_id": "phase_1", "claim_ids": ["claim_1"],
                },
                {"type": "set_focus", "claim_ids": ["claim_1"], "node_ids": ["node_1"]},
            ],
        },
    )
    assert result["revision"] == 1
    assert read_context(tmp_path)["focus"] == {"claim_ids": ["claim_1"], "node_ids": ["node_1"]}
    assert checkpoint(tmp_path, {
        "principal": "root_agent",
        "authority": "kernel_write",
        "checkpoint_id": "checkpoint_1",
        "disposition": "deferred",
    })["revision"] == 1
    assert turn(tmp_path, {"operation": "orient"})["accepted"] is True


def test_semantic_refs_and_checkpoint_liveness_are_protocol_stable(tmp_path: Path) -> None:
    _workspace(tmp_path)
    admit_workspace(tmp_path, {"authority": "host"})
    result = apply_change(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "expected_revision": 0, "operations": [
        {"type": "create_claim", "id": "claim_mechanism.revision2", "statement": "A semantic claim"},
        {"type": "create_node", "id": "node_transition.state.revision2", "title": "Transition", "objective": "Inspect", "claim_ids": ["claim_mechanism.revision2"]},
        {"type": "set_focus", "claim_ids": ["claim_mechanism.revision2"], "node_ids": ["node_transition.state.revision2"]},
    ]})
    assert result["created_ids"] == ["claim_mechanism.revision2", "node_transition.state.revision2"]
    pending = read_context(tmp_path)
    assert pending["nodes"][0]["id"] == "node_transition.state.revision2"
    assert read_liveness(tmp_path)["lifecycle"] == "decision_needed"
    checkpoint(tmp_path, {
        "principal": "root_agent",
        "authority": "kernel_write",
        "checkpoint_id": "checkpoint_semantic.1",
        "disposition": "continue_required",
        "unresolved_refs": ["node_transition.state.revision2"],
    })
    liveness = read_liveness(tmp_path)
    assert liveness["lifecycle"] == "continue_required"
    assert liveness["continue_required"][0]["id"] == "node_transition.state.revision2"


def test_new_workspace_requires_admission_and_revision(tmp_path: Path) -> None:
    _workspace(tmp_path)
    with pytest.raises(AgentWorkspaceError, match="research_admission_required"):
        apply_change(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "expected_revision": 0, "operations": [{"type": "create_phase", "id": "p", "title": "P"}]})
    admit_workspace(tmp_path, {"authority": "host"})
    with pytest.raises(AgentWorkspaceError, match="research_revision_mismatch"):
        apply_change(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "expected_revision": 7, "operations": [{"type": "create_phase", "id": "p", "title": "P"}]})


def test_admission_updates_manifest_and_kernel_admission_flag(tmp_path: Path) -> None:
    _workspace(tmp_path)
    admit_workspace(tmp_path, {"authority": "host"})
    manifest = json.loads((tmp_path / "workspace_manifest.json").read_text(encoding="utf-8"))
    assert manifest["state"] == "ready"
    assert manifest["research_kernel"]["admission_required"] is False


def test_manifest_state_must_match_canonical_admission_state(tmp_path: Path) -> None:
    _workspace(tmp_path)
    manifest_path = tmp_path / "workspace_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["state"] = "ready"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AgentWorkspaceError, match="workspace_research_kernel_mismatch"):
        read_context(tmp_path)


def test_started_attempt_projects_waiting_external_liveness(tmp_path: Path) -> None:
    _workspace(tmp_path)
    admit_workspace(tmp_path, {"authority": "host"})
    apply_change(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "expected_revision": 0, "operations": [
        {"type": "create_claim", "id": "claim_1", "statement": "Hypothesis"},
        {"type": "create_node", "id": "node_1", "title": "Execution", "objective": "Run", "claim_ids": ["claim_1"]},
        {"type": "create_strategy_plan", "id": "strategy_1", "claim_id": "claim_1", "node_id": "node_1", "objective": "Run", "rationale": "Need evidence"},
        {"type": "set_focus", "claim_ids": ["claim_1"], "node_ids": ["node_1"]},
        {"type": "set_node_state", "node_id": "node_1", "state": "active"},
    ]})
    apply_change(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "expected_revision": 1, "operations": [
        {"type": "create_attempt", "id": "attempt_1", "node_id": "node_1", "capability": "xtb", "capability_version": "1", "state": "running"},
    ]})
    waiting = read_liveness(tmp_path)
    assert waiting["lifecycle"] == "waiting_external"
    assert waiting["waiting_external"][0]["attempt_id"] == "attempt_1"
    memory = json.loads((tmp_path / "memory" / "index.json").read_text(encoding="utf-8"))
    assert memory["lifecycle"] == "waiting_external"
    assert memory["waiting_external"][0]["attempt_id"] == "attempt_1"
    apply_change(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "expected_revision": 2, "operations": [
        {"type": "transition_attempt", "attempt_id": "attempt_1", "state": "succeeded"},
    ]})
    assert read_liveness(tmp_path)["lifecycle"] == "decision_needed"


def test_new_workspace_requires_an_explicit_research_mode(tmp_path: Path) -> None:
    _workspace(tmp_path)
    context_path = tmp_path / "research_map" / "context.json"
    context = json.loads(context_path.read_text(encoding="utf-8"))
    context.pop("workspace_mode")
    context_path.write_text(json.dumps(context), encoding="utf-8")

    with pytest.raises(AgentWorkspaceError, match="research_workspace_mode_required"):
        read_context(tmp_path)


def test_new_workspace_requires_the_complete_research_context_surface(tmp_path: Path) -> None:
    _workspace(tmp_path)
    context_path = tmp_path / "research_map" / "context.json"
    context = json.loads(context_path.read_text(encoding="utf-8"))
    context.pop("attempts")
    context_path.write_text(json.dumps(context), encoding="utf-8")

    with pytest.raises(AgentWorkspaceError, match="research_context_missing_collections: attempts"):
        read_context(tmp_path)

    context["attempts"] = {}
    context_path.write_text(json.dumps(context), encoding="utf-8")
    with pytest.raises(AgentWorkspaceError, match="research_context_collections_must_be_arrays: attempts"):
        read_context(tmp_path)


def test_new_workspace_requires_a_bound_canonical_manifest(tmp_path: Path) -> None:
    _workspace(tmp_path)
    (tmp_path / "workspace_manifest.json").unlink()
    with pytest.raises(AgentWorkspaceError, match="workspace_manifest_missing"):
        read_context(tmp_path)

    manifest_path = tmp_path / "workspace_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "research_agent_workspace_1",
                "workspace_id": "workspace_python_unit",
                "workspace_mode": "research",
                "state": "admission_pending",
                "workspace_root": str(tmp_path / "other"),
            }
        ),
        encoding="utf-8",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["workspace_root"] = str(tmp_path / "other")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AgentWorkspaceError, match="workspace_root_mismatch"):
        read_context(tmp_path)


def test_command_boundary_does_not_fallback_partial_new_workspace(tmp_path: Path) -> None:
    _workspace(tmp_path)
    (tmp_path / "workspace_manifest.json").unlink()
    with pytest.raises(AgentWorkspaceError, match="workspace_manifest_missing"):
        execute("research.context", tmp_path)


def test_scientific_records_and_traceability_are_indexed_atomically(tmp_path: Path) -> None:
    _workspace(tmp_path)
    admit_workspace(tmp_path, {"authority": "host"})
    apply_change(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "expected_revision": 0, "operations": [
        {"type": "create_claim", "id": "claim_1", "statement": "Hypothesis"},
        {"type": "create_node", "id": "node_1", "title": "Execution", "objective": "Run", "claim_ids": ["claim_1"]},
        {"type": "create_artifact", "id": "artifact_1", "node_id": "node_1", "location": "runs/input.xyz", "sha256": "abc", "size_bytes": 4},
        {"type": "create_attempt", "id": "attempt_1", "node_id": "node_1", "capability": "xtb", "capability_version": "1", "state": "completed", "output_artifact_ids": ["artifact_1"]},
        {"type": "create_finding", "id": "finding_1", "node_id": "node_1", "claim_ids": ["claim_1"], "statement": "Energy was finite", "kind": "fact", "value": True, "source_refs": ["artifact_1"]},
        {"type": "create_gate", "id": "gate_1", "scope": "node", "target_id": "node_1", "criteria": [{"kind": "validated"}]},
        {"type": "create_evidence", "id": "evidence_1", "artifact_id": "artifact_1", "subject_type": "finding", "subject_id": "finding_1", "relation": "supports"},
        {"type": "evaluate_gate", "gate_id": "gate_1", "verdict": "pass", "evidence_refs": ["artifact_1"]},
        {"type": "create_strategy_plan", "id": "strategy_1", "claim_id": "claim_1", "node_id": "node_1", "objective": "Validate", "rationale": "Need evidence"},
        {"type": "create_interpretation", "id": "interpretation_1", "claim_id": "claim_1", "node_id": "node_1", "attempt_ref": "attempt_1", "summary": "Supports claim", "outcome": "supports", "artifact_refs": ["artifact_1"], "finding_ids": ["finding_1"], "gate_ids": ["gate_1"]},
    ]})
    context = read_context(tmp_path)
    assert context["nodes"][0]["finding_ids"] == ["finding_1"]
    assert context["nodes"][0]["attempt_refs"] == ["attempt_1"]
    assert context["gates"][0]["evaluations"][0]["verdict"] == "pass"
    assert context["attempt_interpretations"][0]["attempt_ref"] == "attempt_1"
    assert context["strategy_plans"][0]["id"] == "strategy_1"


def test_scientific_records_reject_unknown_traceability_references(tmp_path: Path) -> None:
    _workspace(tmp_path)
    admit_workspace(tmp_path, {"authority": "host"})
    with pytest.raises(AgentWorkspaceError, match="unknown evidence"):
        apply_change(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "expected_revision": 0, "operations": [
            {"type": "create_claim", "id": "claim_1", "statement": "Hypothesis"},
            {"type": "create_node", "id": "node_1", "title": "Execution", "objective": "Run", "claim_ids": ["claim_1"]},
            {"type": "create_finding", "id": "finding_1", "node_id": "node_1", "statement": "Missing", "kind": "fact", "source_refs": ["artifact_missing"]},
        ]})
    assert read_context(tmp_path)["revision"] == 0


def test_bulk_evidence_registration_allows_cross_references(tmp_path: Path) -> None:
    _workspace(tmp_path)
    admit_workspace(tmp_path, {"authority": "host"})
    apply_change(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "expected_revision": 0, "operations": [
        {"type": "create_claim", "id": "claim_1", "statement": "Hypothesis"},
        {"type": "create_node", "id": "node_1", "title": "Execution", "objective": "Run", "claim_ids": ["claim_1"]},
        {"type": "register_evidence", "attempts": [{"id": "attempt_1", "node_id": "node_1", "capability": "xtb", "capability_version": "1", "state": "completed", "output_artifact_ids": ["artifact_1"]}], "artifacts": [{"id": "artifact_1", "node_id": "node_1", "location": "runs/out.xyz", "producer_attempt_id": "attempt_1"}]},
    ]})
    context = read_context(tmp_path)
    assert context["attempts"][0]["output_artifact_ids"] == ["artifact_1"]
    assert context["artifacts"][0]["producer_attempt_id"] == "attempt_1"


def test_attempt_lifecycle_transitions_and_evidence_links_are_bounded(tmp_path: Path) -> None:
    _workspace(tmp_path)
    admit_workspace(tmp_path, {"authority": "host"})
    apply_change(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "expected_revision": 0, "operations": [
        {"type": "create_claim", "id": "claim_1", "statement": "Hypothesis"},
        {"type": "create_node", "id": "node_1", "title": "Execution", "objective": "Run", "claim_ids": ["claim_1"]},
        {"type": "create_attempt", "id": "attempt_1", "node_id": "node_1", "capability": "xtb", "capability_version": "1", "state": "started"},
        {"type": "create_finding", "id": "finding_1", "node_id": "node_1", "claim_ids": ["claim_1"], "statement": "Observed", "kind": "fact"},
    ]})
    apply_change(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "expected_revision": 1, "operations": [
        {"type": "transition_attempt", "attempt_id": "attempt_1", "state": "running", "started_at": "2026-09-26T01:00:00Z"},
        {"type": "create_artifact", "id": "artifact_1", "node_id": "node_1", "location": "runs/out.xyz", "producer_attempt_id": "attempt_1"},
        {"type": "create_evidence", "id": "evidence_1", "artifact_id": "artifact_1", "attempt_ref": "attempt_1", "subject_type": "finding", "subject_id": "finding_1", "relation": "supports"},
    ]})
    apply_change(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "expected_revision": 2, "operations": [
        {"type": "update_attempt", "attempt_id": "attempt_1", "state": "failed", "error_class": "process_exit", "error": {"message": "nonzero"}, "finished_at": "2026-09-26T01:01:00Z"},
    ]})
    context = read_context(tmp_path)
    attempt = context["attempts"][0]
    assert attempt["state"] == "failed"
    assert attempt["started_at"] == "2026-09-26T01:00:00Z"
    assert attempt["finished_at"] == "2026-09-26T01:01:00Z"
    assert attempt["output_artifact_ids"] == ["artifact_1"]
    assert attempt["evidence_link_ids"] == ["evidence_1"]
    assert context["artifacts"][0]["evidence_link_ids"] == ["evidence_1"]
    assert context["findings"][0]["evidence_link_ids"] == ["evidence_1"]
    with pytest.raises(AgentWorkspaceError, match="invalid_attempt_transition"):
        apply_change(tmp_path, {"principal": "root_agent", "authority": "kernel_write", "expected_revision": 3, "operations": [
            {"type": "transition_attempt", "attempt_id": "attempt_1", "state": "running"},
        ]})
