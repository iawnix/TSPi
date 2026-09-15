"""Bounded, read-only summaries for reports and Node detail views."""

from ts_agent.io import read_json


def analysis_projection(root, node_id=None, limit=256):
    from ts_agent.compute.artifacts import list_calculation_artifacts

    catalog = list_calculation_artifacts(root, node_id=node_id)["artifacts"]
    rows, omitted = [], 0
    for artifact in catalog:
        path = artifact["path"]
        if "/outputs/analysis/" not in path or not path.endswith(".json") or artifact["size_bytes"] > 4 * 1024 * 1024:
            continue
        try:
            document = read_json(root / path)
        except (ValueError, OSError):
            omitted += 1
            continue
        if not isinstance(document, dict) or document.get("schema_version") != "ts-scientific-analysis/1":
            continue
        if len(rows) >= limit:
            omitted += 1
            continue
        try:
            rows.append(_analysis_row(document, artifact))
        except (KeyError, TypeError, ValueError, AttributeError):
            omitted += 1
    return {"analyses": rows, "omitted": omitted, "selection": "all indexed analyses; inclusion does not imply Claim acceptance"}


def _analysis_row(document, artifact):
    if document["node_id"] != artifact["owner_node"]:
        raise ValueError("analysis owner mismatch")
    result = document["result"]
    data = result.get("data", {})
    if not isinstance(data, dict) or result["verdict"] not in {"valid", "invalid", "inconclusive", "unsupported"}:
        raise ValueError("invalid analysis result")
    # Large coordinate/mapping arrays stay in the source artifact.
    fields = ("species_key", "step_key", "quantity", "value", "unit", "forward", "reverse", "reaction", "conditions", "methods",
              "rate_constant", "rate_constant_unit", "rate_molar_s", "reaction_order", "fractions", "rate_artifact_ids", "assumptions", "scope", "checks", "audit")
    summary = {key: data[key] for key in fields if key in data}
    if "steps" in data:
        if len(data["steps"]) > 64:
            raise ValueError("oversized network")
        summary["steps"] = [{k: step[k] for k in ("step_key", "reactants", "products", "reversible", "evidence_refs", "source_artifact_id")} for step in data["steps"]]
    if "points" in data and document["capability"] == "mechanism.energy_profile":
        summary["points"] = data["points"][:129]
    return {"artifact_id": artifact["artifact_id"], "path": artifact["path"], "sha256": artifact["sha256"], "node_id": document["node_id"],
            "capability": document["capability"], "version": document["capability_version"], "verdict": result["verdict"],
            "summary": summary, "diagnostics": result["diagnostics"][:32], "limitations": result["limitations"],
            "source_artifacts": document["source_artifacts"], "output_artifacts": document["output_artifacts"]}
