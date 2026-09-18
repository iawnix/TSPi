"""Stable ResearchNode scope binding shared by context and operational tools."""

from __future__ import annotations

from typing import Any

from ts_agent.io import sha256_json


NODE_CONTRACT_FIELDS = (
    "id",
    "phase_id",
    "title",
    "objective",
    "dependency_ids",
    "claim_ids",
    "created_at",
)


def node_contract_snapshot(node: dict[str, Any]) -> dict[str, Any]:
    """Return the immutable scope fields that define why a Node exists."""

    return {
        "schema_version": "research-node-contract/1",
        **{field: node.get(field) for field in NODE_CONTRACT_FIELDS},
    }


def node_contract_digest(node: dict[str, Any]) -> str:
    return sha256_json(node_contract_snapshot(node))
