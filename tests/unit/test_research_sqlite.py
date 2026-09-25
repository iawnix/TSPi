from __future__ import annotations

import sqlite3

import pytest

from ts_agent.research import (
    AttemptInterpretation,
    InterpretationOutcome,
    ResearchSqliteError,
    ResearchSqliteRepository,
    StrategyPlan,
    StrategyReview,
    StrategyReviewDecision,
    StrategyStatus,
    TurnCheckpoint,
    TurnDisposition,
)
from tests.support.workspace_helpers import bootstrap_workspace_fixture, start_research_node
from ts_agent.research import ResearchKernel


def _records():
    return {
        "plan": StrategyPlan(
            id="strategy_1",
            claim_id="claim_1",
            node_id="node_1",
            objective="Produce a validated candidate.",
            rationale="The current evidence requires an independent candidate search.",
            steps=[{"kind": "execute", "capability": "xtb.scan", "purpose": "Explore the coordinate."}],
            alternatives=[{"id": "strategy_alt", "reason_rejected": "No validated endpoints yet."}],
            stop_conditions=["A validated stationary point is obtained."],
            switch_conditions=["Two failed scans without a candidate."],
            status=StrategyStatus.ACTIVE,
            actor={"kind": "root_agent", "run_id": "run_1"},
            created_at="2026-09-25T00:00:00Z",
        ),
        "review": StrategyReview(
            id="review_1",
            claim_id="claim_1",
            decision=StrategyReviewDecision.CONTINUE,
            rationale="The first scan is still within the declared budget.",
            trigger_refs=["calc_1"],
            alternatives_considered=[{"strategy_id": "strategy_alt", "reason_rejected": "Not needed yet."}],
            selected_strategy_id="strategy_1",
            attempt_refs=["calc_1"],
            actor={"kind": "root_agent", "run_id": "run_1"},
            created_at="2026-09-25T00:01:00Z",
        ),
        "interpretation": AttemptInterpretation(
            id="interpretation_1",
            claim_id="claim_1",
            node_id="node_1",
            attempt_ref="calc_1",
            summary="The parsed scan does not establish a transition state.",
            outcome=InterpretationOutcome.INCONCLUSIVE,
            artifact_refs=["art_aaaaaaaaaaaaaaaaaaaaaaaa"],
            actor={"kind": "root_agent", "run_id": "run_1"},
            created_at="2026-09-25T00:02:00Z",
        ),
        "checkpoint": TurnCheckpoint(
            id="checkpoint_1",
            turn_id="turn_1",
            disposition=TurnDisposition.CONTINUE_REQUIRED,
            reason="Continue the active strategy in the next turn.",
            claim_ids=["claim_1"],
            node_ids=["node_1"],
            unresolved_refs=["strategy_1"],
            map_revision=0,
            actor={"kind": "root_agent", "run_id": "run_1"},
            created_at="2026-09-25T00:03:00Z",
        ),
    }


def test_sqlite_bootstrap_and_atomic_claim_decision_commit(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(root)
    research_map = ResearchKernel(root).load()
    repository = ResearchSqliteRepository(root)

    assert repository.bootstrap_from_json(research_map)["created"] is True
    records = _records()
    result = repository.commit(
        research_map,
        expected_revision=research_map.revision,
        event_id="event_1",
        rationale="Record the Claim decision thread.",
        basis_refs=["claim_1"],
        strategy_plans=[records["plan"]],
        strategy_reviews=[records["review"]],
        interpretations=[records["interpretation"]],
        checkpoint=records["checkpoint"],
    )

    assert result["revision"] == research_map.revision + 1
    assert repository.load_map().revision == result["revision"]
    assert repository.list_records("strategy_plan", claim_id="claim_1")[0]["id"] == "strategy_1"
    assert repository.list_records("attempt_interpretation")[0]["outcome"] == "inconclusive"
    snapshot = repository.export_snapshot()
    assert snapshot["claim_decisions"]["turn_checkpoints"][0]["disposition"] == "continue_required"


def test_sqlite_event_replay_is_idempotent(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(root)
    research_map = ResearchKernel(root).load()
    repository = ResearchSqliteRepository(root)
    repository.bootstrap_from_json(research_map)
    plan = _records()["plan"]

    first = repository.commit(research_map, expected_revision=research_map.revision, event_id="event_1", strategy_plans=[plan])
    second = repository.commit(research_map, expected_revision=research_map.revision, event_id="event_1", strategy_plans=[plan])
    assert second == first
    assert len(repository.list_records("strategy_plan")) == 1


def test_sqlite_rejects_invalid_claim_decision_without_partial_write(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    start_research_node(root)
    research_map = ResearchKernel(root).load()
    repository = ResearchSqliteRepository(root)
    repository.bootstrap_from_json(research_map)
    invalid = _records()["plan"]
    invalid.claim_id = "claim_404"

    with pytest.raises(Exception, match="unknown claim"):
        repository.commit(research_map, strategy_plans=[invalid])
    assert repository.load_map().revision == research_map.revision
    assert repository.list_records("strategy_plan") == []


def test_sqlite_uses_wal_mode(tmp_path) -> None:
    repository = ResearchSqliteRepository(tmp_path / "workspace")
    repository.initialize()
    with sqlite3.connect(repository.path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
