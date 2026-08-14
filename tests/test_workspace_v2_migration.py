from __future__ import annotations

import json
from pathlib import Path

import pytest

from ts_workspace.migrate_v2 import MigrationError, migrate_workspace_v2
from ts_workspace.validator_v3 import validate_workspace


def _legacy_workspace(root: Path) -> None:
    node = root / "nodes" / "n000"
    (node / "outputs").mkdir(parents=True)
    (root / "inputs").mkdir()
    (root / "reports").mkdir()
    (node / "outputs" / "parse.json").write_text("{}\n", encoding="utf-8")
    (node / "node.json").write_text(
        json.dumps(
            {
                "schema_version": "ts-node/2",
                "node_id": "n000",
                "parent_node": None,
                "node_type": "validation",
                "validation_scope": "tsfreq",
                "objective": "Validate the TS candidate.",
                "lifecycle": "closed",
                "opened_at": "2026-08-01T00:00:00+00:00",
                "closed_at": "2026-08-01T01:00:00+00:00",
                "closure": {"summary": "The legacy node completed.", "open_questions": []},
            }
        ),
        encoding="utf-8",
    )
    (root / "research_state.json").write_text(
        json.dumps(
            {
                "schema_version": "ts-research-state",
                "created_at": "2026-08-01T00:00:00+00:00",
                "hypothesis_contract_version": "strict",
                "accepted_ts_refs": ["accepted/legacy.json"],
                "provenance": [],
                "nodes": [
                    {
                        "node_id": "n000",
                        "parent_node": None,
                        "node_type": "validation",
                        "validation_scope": "tsfreq",
                        "objective": "Validate the TS candidate.",
                        "lifecycle": "closed",
                    }
                ],
                "edges": [],
                "current_node": None,
                "branch_events": [],
            }
        ),
        encoding="utf-8",
    )
    (root / "hypotheses.json").write_text(
        json.dumps(
            {
                "schema_version": "ts-hypotheses",
                "focus_hypothesis_id": "hyp_legacy",
                "hypotheses": [
                    {
                        "hypothesis_id": "hyp_legacy",
                        "source_node": "n000",
                        "summary": "Legacy concerted pathway hypothesis.",
                        "status": "supported",
                    }
                ],
                "accepted_facts": [],
                "refuted_hypotheses": [],
                "open_questions": [],
                "focus_pathway_id": None,
                "pathways": [],
                "audit_records": [],
            }
        ),
        encoding="utf-8",
    )
    (root / "evidence_registry.json").write_text(
        json.dumps(
            {
                "schema_version": "ts-evidence-registry",
                "evidence": [
                    {
                        "evidence_id": "legacy_freq",
                        "node_id": "n000",
                        "kind": "gaussian_tsfreq_validation",
                        "role": "tsfreq_gate",
                        "evidence_tier": "local_parse",
                        "summary": "One imaginary frequency was parsed.",
                        "path": "nodes/n000/outputs/parse.json",
                        "quality": {"imaginary_frequency_count": 1},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_copy_migration_is_conservative_and_produces_valid_v3(tmp_path: Path) -> None:
    source = tmp_path / "legacy"
    target = tmp_path / "migrated"
    _legacy_workspace(source)
    before = (source / "research_state.json").read_bytes()

    result = migrate_workspace_v2(source, target)

    assert (source / "research_state.json").read_bytes() == before
    assert result["validation"]["valid"] is True
    assert validate_workspace(target)["valid"] is True
    research = json.loads((target / "research_state.json").read_text(encoding="utf-8"))
    claims = json.loads((target / "claims.json").read_text(encoding="utf-8"))
    evidence = json.loads((target / "evidence_registry.json").read_text(encoding="utf-8"))
    node = json.loads((target / "nodes" / "n000" / "node.json").read_text(encoding="utf-8"))
    assert research["accepted_refs"] == []
    assert claims["claims"][0]["status"] == "inconclusive"
    assert claims["focus_claim_refs"] == ["claim_migrated_hyp_legacy"]
    assert "role" not in evidence["evidence"][0]
    assert evidence["evidence"][0]["facts"]["quality"]["imaginary_frequency_count"] == 1
    assert node["tags"] == ["validation", "tsfreq"]
    assert node["state"] == "closed"
    assert (target / "reports" / "migration_v2_to_v3.json").is_file()


def test_migration_refuses_in_place_existing_target_and_symlink_source(tmp_path: Path) -> None:
    source = tmp_path / "legacy"
    _legacy_workspace(source)
    with pytest.raises(MigrationError, match="differ"):
        migrate_workspace_v2(source, source)

    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(MigrationError, match="already exists"):
        migrate_workspace_v2(source, target)

    linked = source / "nodes" / "n000" / "outputs" / "linked.json"
    linked.symlink_to(tmp_path / "outside.json")
    with pytest.raises(MigrationError, match="symbolic link"):
        migrate_workspace_v2(source, tmp_path / "new-target")
