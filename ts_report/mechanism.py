"""Mechanistic interpretation helpers for reports."""

from __future__ import annotations

from typing import Any


def build_mechanism_interpretation(context: dict[str, Any]) -> dict[str, Any]:
    active = context.get("active_hypothesis") if isinstance(context.get("active_hypothesis"), dict) else {}
    center = context.get("reaction_center") if isinstance(context.get("reaction_center"), dict) else {}
    profile = context.get("distance_profile") if isinstance(context.get("distance_profile"), dict) else {}
    tsfreq = context.get("tsfreq") if isinstance(context.get("tsfreq"), dict) else {}
    connectivity = context.get("connectivity") if isinstance(context.get("connectivity"), dict) else {}

    progress = _reaction_progress(center, profile)
    classification = _classify_progress(progress)
    mode = tsfreq.get("mode_assignment") if isinstance(tsfreq.get("mode_assignment"), dict) else {}
    electronic = tsfreq.get("electronic_structure_gate") if isinstance(tsfreq.get("electronic_structure_gate"), dict) else {}
    verdict = connectivity.get("verdict") if isinstance(connectivity.get("verdict"), dict) else {}
    alternatives = active.get("alternative_hypotheses", []) if isinstance(active.get("alternative_hypotheses"), list) else []

    support = []
    if mode:
        support.append(str(mode.get("mode_verdict") or mode.get("local_geometry_consistency") or "Mode assignment is recorded."))
    if verdict:
        support.append(str(verdict.get("r_to_p_connected_via_ts") or verdict.get("verdict") or "Connectivity verdict is recorded."))
    boundaries = []
    if electronic:
        if electronic.get("population_analysis_available") is False:
            boundaries.append("Population or bonding diagnostics were not available; electronic timing is a boundary, not a proven claim.")
        if electronic.get("spin_contamination_available") is False:
            boundaries.append("Spin contamination diagnostics were not available in the parsed evidence.")
        if electronic.get("verdict"):
            boundaries.append(str(electronic["verdict"]))
    if verdict.get("stationary_endpoint_irc_complete") is False:
        boundaries.append("IRC endpoint assignment is not stationary-endpoint complete.")

    summary = active.get("summary") or "Mechanism hypothesis is recorded in mechanism_model.json."
    if classification:
        summary = f"{summary} The distance profile is best described as {classification}."
    return {
        "summary": summary,
        "classification": classification,
        "reaction_progress": progress,
        "supporting_observations": support,
        "boundaries": _dedupe(boundaries),
        "alternative_hypotheses": alternatives,
    }


def _reaction_progress(center: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    rows = profile.get("rows", []) if isinstance(profile.get("rows"), list) else []
    reactant = _distances_for(rows, "Reactant")
    product = _distances_for(rows, "Product")
    ts = _distances_for(rows, "TS")
    if not ts:
        return []
    out: list[dict[str, Any]] = []
    for group, direction in [("forming_bonds", "forming"), ("breaking_bonds", "breaking")]:
        for item in center.get(group, []):
            if not isinstance(item, dict) or not item.get("label"):
                continue
            label = str(item["label"])
            r_value = _float_or_none(reactant.get(label))
            p_value = _float_or_none(product.get(label))
            ts_value = _float_or_none(ts.get(label))
            progress = None
            if r_value is not None and p_value is not None and ts_value is not None and abs(p_value - r_value) > 1e-9:
                progress = (ts_value - r_value) / (p_value - r_value)
                progress = max(0.0, min(1.0, progress))
            out.append({"label": label, "type": direction, "reactant": r_value, "ts": ts_value, "product": p_value, "progress": progress})
    return out


def _classify_progress(progress: list[dict[str, Any]]) -> str:
    values = [float(item["progress"]) for item in progress if isinstance(item.get("progress"), int | float)]
    if not values:
        return ""
    spread = max(values) - min(values)
    if spread >= 0.35:
        return "an asynchronous coupled rearrangement"
    if spread >= 0.15:
        return "a moderately asynchronous coupled rearrangement"
    return "a tightly coupled reaction-coordinate motion"


def _distances_for(rows: list[Any], label: str) -> dict[str, Any]:
    for row in rows:
        if isinstance(row, dict) and row.get("label") == label and isinstance(row.get("distances"), dict):
            return row["distances"]
    return {}


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out
