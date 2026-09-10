"""Deterministic derived associations between Claims and ResearchNodes."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .refs import claim_sort_key, node_sort_key


def derive_claim_node_links(
    claims: Iterable[dict[str, Any]],
    nodes: Iterable[dict[str, Any]],
) -> tuple[tuple[str, str], ...]:
    """Return unique ``(claim_id, node_id)`` links from scope and provenance."""

    claim_rows = list(claims)
    node_rows = list(nodes)
    claim_ids = {
        str(row["claim_id"])
        for row in claim_rows
        if isinstance(row.get("claim_id"), str) and row["claim_id"]
    }
    node_ids = {
        str(row["node_id"])
        for row in node_rows
        if isinstance(row.get("node_id"), str) and row["node_id"]
    }
    links: set[tuple[str, str]] = set()

    for node in node_rows:
        node_id = node.get("node_id")
        refs = node.get("claim_refs")
        if not isinstance(node_id, str) or node_id not in node_ids or not isinstance(refs, list):
            continue
        links.update(
            (claim_ref, str(node_id))
            for claim_ref in refs
            if isinstance(claim_ref, str) and claim_ref in claim_ids
        )

    for claim in claim_rows:
        claim_id = claim.get("claim_id")
        creator = claim.get("created_by_node")
        if (
            isinstance(claim_id, str)
            and isinstance(creator, str)
            and claim_id in claim_ids
            and creator in node_ids
        ):
            links.add((claim_id, creator))

    return tuple(
        sorted(
            links,
            key=lambda link: (claim_sort_key(link[0]), node_sort_key(link[1])),
        )
    )
