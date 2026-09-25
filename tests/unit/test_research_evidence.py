from __future__ import annotations

import pytest

from ts_agent.research import (
    ArtifactManifest,
    AttemptRecord,
    AttemptInterpretation,
    EvidenceLink,
    InterpretationOutcome,
    ResearchKernel,
    ResearchKernelError,
)
from ts_agent.api import execute
from tests.support.workspace_helpers import bootstrap_workspace_fixture, start_research_node


def _records() -> tuple[AttemptRecord, ArtifactManifest, EvidenceLink]:
    attempt = AttemptRecord(
        id="attempt_1",
        node_id="node_1",
        capability="structure.compare",
        capability_version="1",
        state="parsed",
        environment="local",
        input_artifact_ids=["art_input"],
        output_artifact_ids=["art_output"],
        created_at="2026-09-25T00:00:00Z",
        updated_at="2026-09-25T00:01:00Z",
    )
    artifact = ArtifactManifest(
        id="art_output",
        node_id="node_1",
        kind="structure_comparison",
        format="json",
        location="nodes/node_1/outputs/comparison.json",
        sha256="sha256:" + "a" * 64,
        size_bytes=128,
        producer_attempt_id="attempt_1",
        input_artifact_ids=["art_input"],
        created_at="2026-09-25T00:01:00Z",
    )
    link = EvidenceLink(
        id="evidence_1",
        artifact_id="art_output",
        subject_type="claim",
        subject_id="claim_1",
        relation="supports",
        locator="comparison.relative_energy",
        created_at="2026-09-25T00:02:00Z",
        actor={"kind": "root_agent"},
    )
    return attempt, artifact, link


def test_kernel_registers_and_queries_evidence_metadata(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(root)
    kernel = ResearchKernel(root)
    attempt, artifact, link = _records()

    result = kernel.register_evidence(
        attempts=[attempt],
        artifacts=[artifact],
        links=[link],
        event_id="evidence_event_1",
        request_digest="sha256:" + "b" * 64,
    )

    assert result["created_ids"] == ["attempt_1", "art_output", "evidence_1"]
    records = kernel.evidence_records(node_id="node_1")
    assert records["records"]["attempt"][0]["capability"] == "structure.compare"
    assert records["records"]["artifact"][0]["sha256"].startswith("sha256:")
    assert records["records"]["link"][0]["relation"] == "supports"


def test_kernel_evidence_registration_replay_is_idempotent(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(root)
    kernel = ResearchKernel(root)
    attempt, artifact, link = _records()
    first = kernel.register_evidence(
        attempts=[attempt], artifacts=[artifact], links=[link], event_id="evidence_event_1",
        request_digest="sha256:" + "b" * 64,
    )
    second = kernel.register_evidence(
        attempts=[attempt], artifacts=[artifact], links=[link], event_id="evidence_event_1",
        request_digest="sha256:" + "b" * 64,
    )
    assert second == first
    assert len(kernel.evidence_records()["records"]["artifact"]) == 1


def test_kernel_rejects_evidence_for_unknown_map_object(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(root)
    kernel = ResearchKernel(root)
    _attempt, artifact, link = _records()
    link.subject_id = "claim_missing"

    with pytest.raises(ResearchKernelError, match="unknown claim"):
        kernel.register_evidence(artifacts=[artifact], links=[link])


def test_kernel_rejects_links_to_unregistered_artifacts(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(root)
    kernel = ResearchKernel(root)
    _attempt, _artifact, link = _records()
    link.artifact_id = "art_missing"

    with pytest.raises(ResearchKernelError, match="unregistered Artifacts"):
        kernel.register_evidence(links=[link])


def test_research_evidence_command_returns_bounded_registry(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(root)
    kernel = ResearchKernel(root)
    attempt, artifact, link = _records()
    kernel.register_evidence(attempts=[attempt], artifacts=[artifact], links=[link])

    result = execute("research.evidence", root, {"record_type": "artifact", "node_id": "node_1"})
    assert result["schema_version"] == "research-evidence/1"
    assert [item["id"] for item in result["records"]["artifact"]] == ["art_output"]


def test_evidence_register_command_is_replay_safe(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(root)
    attempt, artifact, link = _records()
    request = {
        "schema_version": "research-evidence-request/1",
        "event_id": "evidence-api-event",
        "request_digest": "sha256:" + "c" * 64,
        "attempts": [attempt.to_dict()],
        "artifacts": [artifact.to_dict()],
        "links": [link.to_dict()],
    }
    first = execute("research.evidence.register", root, {"request": request})
    second = execute("research.evidence.register", root, {"request": request})
    assert first["commit"] == second["commit"]
    assert first["commit"]["created_ids"] == ["attempt_1", "art_output", "evidence_1"]


def test_interpretation_rejects_unregistered_artifact_reference(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(root)
    kernel = ResearchKernel(root)
    interpretation = AttemptInterpretation(
        id="interpretation_missing_artifact",
        claim_id="claim_1",
        node_id="node_1",
        attempt_ref="attempt_1",
        summary="The attempt has not been connected to a registered artifact.",
        outcome=InterpretationOutcome.INCONCLUSIVE,
        artifact_refs=["artifact_missing"],
        created_at="2026-09-25T00:03:00Z",
    )

    with pytest.raises(ResearchKernelError, match="unregistered Artifacts"):
        kernel.commit_decisions(interpretations=[interpretation])


def test_finding_source_and_gate_evidence_refs_are_registry_bound(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(root)
    kernel = ResearchKernel(root)
    _attempt, artifact, _link = _records()
    kernel.register_evidence(artifacts=[artifact])

    created = kernel.apply({"operations": [{
        "type": "create_finding",
        "id": "finding_1",
        "node_id": "node_1",
        "claim_ids": ["claim_1"],
        "statement": "The output was observed.",
        "kind": "fact",
        "value": True,
        "datatype": "boolean",
        "source_refs": ["art_output"],
    }]})
    assert created["created_ids"] == ["finding_1"]

    with pytest.raises(ResearchKernelError, match="unregistered evidence"):
        kernel.apply({"operations": [{
            "type": "create_finding",
            "id": "finding_missing_source",
            "node_id": "node_1",
            "claim_ids": ["claim_1"],
            "statement": "This source cannot be resolved.",
            "kind": "fact",
            "value": False,
            "datatype": "boolean",
            "source_refs": ["artifact_missing"],
        }]})

    with pytest.raises(ResearchKernelError, match="unregistered evidence"):
        kernel.apply({"operations": [{
            "type": "create_gate",
            "id": "gate_1",
            "scope": "node",
            "target_id": "node_1",
        }, {
            "type": "evaluate_gate",
            "gate_id": "gate_1",
            "verdict": "pass",
            "evidence_refs": ["link_missing"],
        }]})


def test_evidence_link_subject_must_match_gate_reference(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(root)
    kernel = ResearchKernel(root)
    _attempt, artifact, link = _records()
    link.subject_type = "claim"
    kernel.register_evidence(artifacts=[artifact], links=[link])
    kernel.apply({"operations": [{
        "type": "create_gate",
        "id": "gate_1",
        "scope": "node",
        "target_id": "node_1",
    }]})

    with pytest.raises(ResearchKernelError, match="belongs to claim claim_1"):
        kernel.apply({"operations": [{
            "type": "evaluate_gate",
            "gate_id": "gate_1",
            "verdict": "pass",
            "evidence_refs": ["evidence_1"],
        }]})
