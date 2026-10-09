"""One dependency predicate for scheduling, writes and delivery admission."""
from __future__ import annotations


def normalize_dependencies(context, operation):
    rows = operation.get("dependencies", [])
    if not isinstance(rows, list):
        raise ValueError("dependency_contract_invalid: dependencies must be an array")
    known = {node["id"] for node in context.get("nodes", [])}
    seen = set()
    normalized = []
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"node_id", "condition"}
                or row.get("condition") not in {"completed", "finished"}):
            raise ValueError("dependency_contract_invalid: use node_id and completed|finished")
        ref = row["node_id"]
        if not isinstance(ref, str) or ref not in known or ref == operation.get("id"):
            raise ValueError("dependency_node_invalid: " + str(ref))
        if ref in seen:
            raise ValueError("dependency_duplicate: declare each predecessor once: " + ref)
        seen.add(ref)
        normalized.append(dict(row))
    return normalized


def dependency_evaluation(context, node):
    nodes = {item["id"]: item for item in context.get("nodes", [])}
    declared = node.get("dependencies", [])
    rows = []
    for dependency in declared:
        ref, condition = dependency.get("node_id"), dependency.get("condition")
        actual = nodes.get(ref, {})
        satisfied = actual.get("state") == "closed" and (
            condition == "finished" and actual.get("outcome") in {"completed", "inconclusive", "stopped"}
            or condition == "completed" and actual.get("outcome") == "completed")
        rows.append({"node_id": ref, "condition": condition,
                     "state": actual.get("state"), "outcome": actual.get("outcome"),
                     "satisfied": satisfied,
                     "reason": None if satisfied else (
                         f"{ref}: actual {actual.get('state', 'missing')}/{actual.get('outcome')}; "
                         f"required closed/{'completed' if condition == 'completed' else 'any terminal outcome'}")})
    unmet = [row for row in rows if not row["satisfied"]]
    return {"satisfied": not unmet, "dependencies": rows, "unmet": unmet}
