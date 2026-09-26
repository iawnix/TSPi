from __future__ import annotations

from ts_agent.research import ContextBuilder, ResearchClaim, ResearchMap, ResearchNode


def _map() -> ResearchMap:
    value = ResearchMap(map_id="map_context", title="Context test", created_at="2026-09-25T00:00:00Z")
    value.add_claim(ResearchClaim(
        id="claim_1",
        created_at="2026-09-25T00:00:00Z",
        statement="A bounded context should preserve source identity.",
        predictions=[],
        falsifiers=[],
    ))
    value.add_node(ResearchNode(
        id="node_1",
        created_at="2026-09-25T00:00:00Z",
        title="Build context",
        objective="Verify context provenance.",
        claim_ids=["claim_1"],
    ))
    value.focus_claim_ids = ["claim_1"]
    value.focus_node_ids = ["node_1"]
    return value


def _liveness() -> dict:
    return {
        "lifecycle": "continue_required",
        "continue_required": [{
            "id": "cont_1", "scope": "node", "target_id": "node_1",
            "action": "inspect", "status": "required", "reason": "inspect evidence",
        }],
        "deferred": [],
        "blocked": [],
        "waiting_external": [],
        "decision_needed": [],
        "active_nodes": ["node_1"],
        "counts": {"continue_required": 1, "required": 1, "deferred": 0, "blocked": 0, "waiting_external": 0, "decision_needed": 0},
    }


def test_context_pack_has_memory_revision_scope_and_provenance() -> None:
    research_map = _map()
    research_map.revision = 4
    builder = ContextBuilder()
    first = builder.build(research_map, liveness=_liveness(), runtime={"runtime_revision": "runtime-2"})
    second = builder.build(research_map, liveness=_liveness(), runtime={"runtime_revision": "runtime-2"})

    assert first["context_id"] == second["context_id"]
    assert first["memory_revision"] == 4
    assert first["map_revision"] == 4
    assert first["scope"] == {"claim_ids": ["claim_1"], "node_ids": ["node_1"]}
    assert first["provenance"]["memory_revision"] == 4
    assert first["provenance"]["runtime_revision"] == "runtime-2"
    assert {item["source_ref"] for item in first["items"]} == {
        "claim:claim_1", "node:node_1", "continuation:cont_1",
    }
    assert all(item["source_revision"] == 4 for item in first["items"])


def test_context_pack_is_bounded_and_reports_truncation() -> None:
    research_map = _map()
    research_map.focus_claim_ids = ["claim_1"] * 3
    research_map.revision = 2
    liveness = _liveness()
    liveness["continue_required"] = [
        {"id": f"cont_{index}", "scope": "node", "target_id": "node_1", "action": "inspect", "status": "required", "reason": "x"}
        for index in range(5)
    ]
    liveness["counts"]["continue_required"] = 5
    packed = ContextBuilder(focus_limit=1, continuation_limit=2).build(research_map, liveness=liveness)

    assert len(packed["continuations"]["required"]) == 2
    assert packed["bounds"]["truncated"]["continue_required"] is True
    assert packed["bounds"]["truncated"]["focus_claims"] is True
    assert len(packed["items"]) == 4  # one claim, one node, and two continuations


def test_context_pack_is_rebuildable_without_becoming_memory() -> None:
    packed = ContextBuilder().build(_map(), liveness=_liveness())
    packed["focus"]["claims"][0]["statement"] = "mutated projection"
    rebuilt = ContextBuilder().build(_map(), liveness=_liveness())

    assert rebuilt["focus"]["claims"][0]["statement"] != "mutated projection"
    assert rebuilt["provenance"]["source"] == "ResearchMemory.ContextBuilder"


def test_context_pack_applies_custom_text_and_reference_bounds_to_runtime_rows() -> None:
    research_map = _map()
    liveness = _liveness()
    liveness["continue_required"][0]["reason"] = "r" * 40
    liveness["continue_required"][0]["metadata"] = {f"key_{index}": index for index in range(5)}
    packed = ContextBuilder(text_limit=12, reference_limit=2).build(
        research_map,
        liveness=liveness,
        runtime={"runtime_revision": "runtime-1"},
    )

    continuation = packed["continuations"]["required"][0]
    assert len(continuation["reason"]) <= 12
    assert len(continuation["metadata_keys"]) == 2
    assert continuation["truncated"] == {"reason": True, "metadata_keys": True}
