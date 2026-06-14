"""Mechanism-model checks for ChemGate workspace validation."""

from __future__ import annotations

from typing import Any

from transition_state_workflow.config.state_contract import (
    MECHANISM_ANALYSIS_LAYERS,
    MECHANISM_ANALYSIS_STATUSES,
)
from transition_state_workflow.util.path_utils import clean_string, list_or_empty

from .common import clean_string_list, iter_object_records
from .contracts import Finding


def validate_mechanism_model(_source: Any, mechanism: dict[str, Any], findings: list[Finding]) -> None:
    """Validate structured mechanism-analysis buckets when mechanism_model.json exists."""

    if not mechanism:
        return
    analysis = mechanism.get("mechanism_analysis")
    if analysis is None:
        findings.append(
            Finding(
                "warning",
                "mechanism_analysis_missing",
                "mechanism_model.json should include structured mechanism_analysis buckets",
                path="mechanism_model.json",
            )
        )
        return
    if not isinstance(analysis, dict):
        findings.append(
            Finding(
                "error",
                "mechanism_analysis_not_object",
                "mechanism_analysis must be an object keyed by analysis layer",
                path="mechanism_model.json",
            )
        )
        return
    for layer in MECHANISM_ANALYSIS_LAYERS:
        records = analysis.get(layer)
        if records is None:
            findings.append(
                Finding(
                    "warning",
                    "mechanism_analysis_layer_missing",
                    f"mechanism_analysis is missing layer: {layer}",
                    path="mechanism_model.json",
                )
            )
            continue
        if not isinstance(records, list):
            findings.append(
                Finding(
                    "error",
                    "mechanism_analysis_layer_not_list",
                    f"mechanism_analysis.{layer} must be a list",
                    path="mechanism_model.json",
                )
            )
            continue
        for index, record in iter_object_records(
            records,
            findings,
            code="mechanism_analysis_record_not_object",
            message_template=f"mechanism_analysis.{layer}[{{index}}] is not an object",
            path="mechanism_model.json",
        ):
            status = clean_string(record.get("status"))
            summary = clean_string(record.get("summary"))
            source_text = clean_string(record.get("source"))
            details = record.get("details") if isinstance(record.get("details"), dict) else {}
            details_source = clean_string(details.get("source"))
            evidence_refs = clean_string_list(list_or_empty(record.get("evidence_refs")))
            if status not in MECHANISM_ANALYSIS_STATUSES:
                findings.append(
                    Finding(
                        "error",
                        "mechanism_analysis_status_invalid",
                        f"invalid mechanism_analysis status: {status}",
                        path="mechanism_model.json",
                    )
                )
            if not summary:
                findings.append(
                    Finding(
                        "error",
                        "mechanism_analysis_summary_missing",
                        f"mechanism_analysis.{layer}[{index}] is missing summary",
                        path="mechanism_model.json",
                    )
                )
            if not evidence_refs and not source_text and not details_source:
                findings.append(
                    Finding(
                        "error",
                        "mechanism_analysis_source_missing",
                        f"mechanism_analysis.{layer}[{index}] has no evidence_refs or source",
                        path="mechanism_model.json",
                    )
                )


__all__ = ["validate_mechanism_model"]
