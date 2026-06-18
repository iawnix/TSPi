"""Reusable diagnostics for ChemKernel decision-context packets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from transition_state_workflow.util.json_io import read_json_object_optional
from transition_state_workflow.util.path_utils import clean_string, list_or_empty

from .ids import node_sort_key


def endpoint_evidence_blocker_summaries(
    root: Path,
    node_payloads: dict[str, dict[str, Any]],
    evidence_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return endpoint-related parsed diagnostics that block endpoint evidence claims.

    Decision context reads already-parsed JSON artifacts only. It intentionally
    does not scan raw engine logs or choose the chemical repair strategy.
    """

    registry_paths_by_node: dict[str, list[str]] = {}
    for record in evidence_records:
        node_id = clean_string(record.get("node_id"))
        path = clean_string(record.get("path"))
        if node_id and path:
            registry_paths_by_node.setdefault(node_id, []).append(path)

    out: list[dict[str, Any]] = []
    for node_id, node in sorted(node_payloads.items(), key=lambda item: node_sort_key(item[0])):
        if not _is_endpoint_related(node):
            continue
        if clean_string(node.get("claim_status")) in {
            "endpoint_minima_ready",
            "endpoint_connected",
            "irc_connected",
            "accepted_ts",
        }:
            continue
        parsed_paths = _candidate_parsed_paths(node, registry_paths_by_node.get(node_id, []))
        parsed_payloads = [_read_json(root / path) for path in parsed_paths]
        parsed_payloads = [payload for payload in parsed_payloads if payload]
        if not parsed_payloads:
            continue
        facts = _endpoint_blocker_facts(node, parsed_payloads)
        labels = _endpoint_blocker_labels(node, facts)
        if "endpoint_not_validated" not in labels:
            continue
        out.append(
            {
                "node_id": node_id,
                "stage": clean_string(node.get("stage")),
                "operation": clean_string(node.get("operation")),
                "claim_status": clean_string(node.get("claim_status")),
                "outcome": clean_string(node.get("outcome")),
                "outcome_code": clean_string(node.get("outcome_code")),
                "labels": labels,
                "facts": facts,
                "source_files": parsed_paths[:6],
                "summary": _endpoint_blocker_summary(node, labels, facts),
            }
        )
    return out


def _is_endpoint_related(node: dict[str, Any]) -> bool:
    stage = clean_string(node.get("stage")).lower()
    operation = clean_string(node.get("operation")).lower()
    outcome_code = clean_string(node.get("outcome_code")).lower()
    decision = clean_string(node.get("decision")).lower()
    if stage in {"candidate_generation", "gaussian_tsfreq_validation", "mechanism_preflight"}:
        return False
    if "endpoint" in stage:
        return True
    if stage == "connectivity_validation":
        text = " ".join((operation, outcome_code, decision))
        return any(marker in text for marker in ("endpoint", "connectivity", "irc"))
    return stage in {"endpoint_validation", "endpoint_minima_validation", "endpoint_optimization"}


def _candidate_parsed_paths(node: dict[str, Any], registry_paths: list[str]) -> list[str]:
    paths: list[str] = []
    display = node.get("display") if isinstance(node.get("display"), dict) else {}
    for path in [clean_string(display.get("primary_file")), *registry_paths]:
        if path:
            paths.append(path)
    evidence = node.get("evidence") if isinstance(node.get("evidence"), dict) else {}
    for value in evidence.values():
        if isinstance(value, str) and value:
            paths.append(value)
    out: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not path.endswith(".json"):
            continue
        if "/outputs/" in path and "/parsed/" not in path:
            continue
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return read_json_object_optional(path)
    except ValueError:
        return {}


def _endpoint_blocker_facts(node: dict[str, Any], parsed_payloads: list[dict[str, Any]]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    opt_diag = _first_dict_for_key(parsed_payloads, "opt_cycle_diagnostics")
    if opt_diag:
        facts["step_limit_reached"] = bool(opt_diag.get("step_limit_reached"))
        facts["requested_opt_max_cycles"] = _first_present(
            opt_diag,
            "requested_opt_max_cycles",
            "requested_max_cycles",
            "requested_maxcycle",
        )
        facts["printed_opt_maximum_steps"] = _first_present(
            opt_diag,
            "printed_opt_maximum_steps",
            "printed_optimum_steps",
            "printed_max_steps",
        )
        facts["max_cycle_request_mismatch"] = bool(opt_diag.get("max_cycle_request_mismatch"))

    for key in ("normal_termination", "error_termination", "stationary_point_found", "final_convergence_satisfied"):
        value = _first_value_for_key(parsed_payloads, key)
        if value is not None:
            facts[key] = value

    force_convergence = _first_dict_for_key(parsed_payloads, "force_convergence")
    if force_convergence:
        facts["force_converged"] = _all_named_criteria_converged(force_convergence, ("Maximum Force", "RMS Force"))
        facts["displacement_converged"] = _all_named_criteria_converged(
            force_convergence,
            ("Maximum Displacement", "RMS Displacement"),
        )
        facts["force_pass_displacement_fail"] = bool(
            facts.get("force_converged") is True and facts.get("displacement_converged") is False
        )

    fragments = _first_fragments(parsed_payloads)
    if fragments:
        facts["fragment_count"] = len(fragments)
        facts["multi_fragment_endpoint"] = len(fragments) > 1

    summary = clean_string((node.get("display") if isinstance(node.get("display"), dict) else {}).get("summary")).lower()
    operation = clean_string(node.get("operation")).lower()
    facts["restart_like"] = "restart" in operation or "restart" in summary
    facts["segmentation_mentioned"] = "segmentation" in summary or "segfault" in summary
    facts["terminal_state_replayed"] = "replay" in summary or "did not continue" in summary
    return facts


def _endpoint_blocker_labels(node: dict[str, Any], facts: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    if facts.get("step_limit_reached"):
        labels.append("gaussian_step_limit_reached")
    if facts.get("max_cycle_request_mismatch"):
        labels.append("opt_maxcycle_request_mismatch")
    if facts.get("force_pass_displacement_fail"):
        labels.append("force_pass_displacement_fail")
    if facts.get("multi_fragment_endpoint"):
        labels.append("multi_fragment_endpoint")
    if facts.get("restart_like") and (
        facts.get("step_limit_reached") or facts.get("terminal_state_replayed") or facts.get("segmentation_mentioned")
    ):
        labels.append("restart_replayed_terminal_state")

    outcome = clean_string(node.get("outcome"))
    run_state = clean_string(node.get("run_state"))
    not_validated = (
        facts.get("step_limit_reached") is True
        or facts.get("normal_termination") is False
        or facts.get("error_termination") is True
        or facts.get("stationary_point_found") is False
        or run_state in {"error", "stopped"}
        or outcome in {"numerical_failure", "parser_refused", "wrong_endpoint"}
    )
    if not_validated:
        labels.append("endpoint_not_validated")
    return labels


def _endpoint_blocker_summary(node: dict[str, Any], labels: list[str], facts: dict[str, Any]) -> str:
    summary = clean_string((node.get("display") if isinstance(node.get("display"), dict) else {}).get("summary"))
    if summary:
        return summary
    bits = [clean_string(node.get("outcome_code")) or "endpoint evidence was not validated"]
    if facts.get("requested_opt_max_cycles") and facts.get("printed_opt_maximum_steps"):
        bits.append(
            f"requested {facts['requested_opt_max_cycles']} cycles but printed {facts['printed_opt_maximum_steps']} steps"
        )
    if labels:
        bits.append("labels: " + ", ".join(labels))
    return "; ".join(bits)


def _all_named_criteria_converged(force_convergence: dict[str, Any], names: tuple[str, ...]) -> bool | None:
    values: list[bool] = []
    for name in names:
        item = force_convergence.get(name)
        if not isinstance(item, dict):
            return None
        status = clean_string(item.get("converged")).upper()
        if status not in {"YES", "NO"}:
            return None
        values.append(status == "YES")
    return all(values)


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload.get(key) is not None:
            return payload.get(key)
    return None


def _first_value_for_key(payloads: list[dict[str, Any]], key: str) -> Any:
    for obj in _iter_objects(payloads):
        if key in obj:
            return obj.get(key)
    return None


def _first_dict_for_key(payloads: list[dict[str, Any]], key: str) -> dict[str, Any]:
    value = _first_value_for_key(payloads, key)
    return value if isinstance(value, dict) else {}


def _first_fragments(payloads: list[dict[str, Any]]) -> list[Any]:
    identity = _first_dict_for_key(payloads, "identity")
    fragments = identity.get("fragments") if identity else None
    if isinstance(fragments, list):
        return fragments
    value = _first_value_for_key(payloads, "fragments")
    return value if isinstance(value, list) else []


def _iter_objects(values: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    stack = list(reversed(values))
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            out.append(value)
            stack.extend(reversed(list(value.values())))
        elif isinstance(value, list):
            stack.extend(reversed(list_or_empty(value)))
    return out


__all__ = ["endpoint_evidence_blocker_summaries"]
