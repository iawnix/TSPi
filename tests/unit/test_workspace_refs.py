from __future__ import annotations

import pytest

from tspi_runtime.workspace.activities import _node_sort_key, build_activity_index
from tspi_runtime.workspace.refs import (
    WorkspaceRefError,
    claim_ordinal,
    claim_sort_key,
    node_ordinal,
    node_sort_key,
)


def test_semantic_node_ids_use_opaque_sorting_in_activity_read_model() -> None:
    values = ["node_pathway_search", "node_10", "node_ac_ala_nhme_2d_scan", "node_2"]

    expected = ["node_2", "node_10", "node_ac_ala_nhme_2d_scan", "node_pathway_search"]
    assert sorted(values, key=node_sort_key) == expected
    assert sorted(values, key=_node_sort_key) == expected


def test_semantic_claim_ids_sort_without_ordinal_parsing() -> None:
    values = ["claim_reaction_path", "claim_2", "claim_mechanism"]

    assert sorted(values, key=claim_sort_key) == [
        "claim_2",
        "claim_mechanism",
        "claim_reaction_path",
    ]


@pytest.mark.parametrize(
    "parser, value",
    [
        (node_ordinal, "node_ac_ala_nhme_2d_scan"),
        (node_ordinal, "node_pathway_search"),
        (claim_ordinal, "claim_reaction_path"),
    ],
)
def test_ordinal_helpers_reject_opaque_ids_without_integer_conversion(parser, value: str) -> None:
    with pytest.raises(WorkspaceRefError, match="does not contain a numeric ordinal"):
        parser(value)


def test_activity_index_accepts_semantic_known_nodes(tmp_path) -> None:
    result = build_activity_index(
        tmp_path,
        known_node_ids=["node_pathway_search", "node_ac_ala_nhme_2d_scan"],
    )

    assert [row["node_id"] for row in result["activity_summaries"]] == [
        "node_ac_ala_nhme_2d_scan",
        "node_pathway_search",
    ]
    assert result["integrity_findings"] == []
