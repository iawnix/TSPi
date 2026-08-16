"""Deterministic derived associations between Claims and ResearchActs."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .refs import act_sort_key, claim_sort_key


def derive_claim_act_links(
    claims: Iterable[dict[str, Any]],
    acts: Iterable[dict[str, Any]],
) -> tuple[tuple[str, str], ...]:
    """Return unique ``(claim_id, act_id)`` links from scope and provenance."""

    claim_rows = list(claims)
    act_rows = list(acts)
    claim_ids = {
        str(row["claim_id"])
        for row in claim_rows
        if isinstance(row.get("claim_id"), str) and row["claim_id"]
    }
    act_ids = {
        str(row["act_id"])
        for row in act_rows
        if isinstance(row.get("act_id"), str) and row["act_id"]
    }
    links: set[tuple[str, str]] = set()

    for act in act_rows:
        act_id = act.get("act_id")
        refs = act.get("claim_refs")
        if not isinstance(act_id, str) or act_id not in act_ids or not isinstance(refs, list):
            continue
        links.update(
            (claim_ref, str(act_id))
            for claim_ref in refs
            if isinstance(claim_ref, str) and claim_ref in claim_ids
        )

    for claim in claim_rows:
        claim_id = claim.get("claim_id")
        creator = claim.get("created_by_act")
        if (
            isinstance(claim_id, str)
            and isinstance(creator, str)
            and claim_id in claim_ids
            and creator in act_ids
        ):
            links.add((claim_id, creator))

    return tuple(
        sorted(
            links,
            key=lambda link: (claim_sort_key(link[0]), act_sort_key(link[1])),
        )
    )
