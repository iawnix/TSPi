from __future__ import annotations

from copy import deepcopy

import pytest

from ts_validation import (
    GateSpecCompileError,
    PredicateRegistry,
    ValidationEngineError,
    builtin_predicate_registry,
    compile_gate_spec,
    evaluate_gate_spec,
)


def _observation(
    observation_id: str,
    concept_id: str,
    value: object,
    *,
    subject_ref: str = "calc_001",
    qualifiers: dict | None = None,
) -> dict:
    return {
        "schema_version": "ts-observation/1",
        "observation_id": observation_id,
        "created_by_act": "act_1",
        "concept_id": concept_id,
        "subject_ref": subject_ref,
        "value": value,
        "datatype": "json",
        "unit": None,
        "qualifiers": qualifiers or {},
        "summary": concept_id,
        "artifact_refs": ["acts/act_1/outputs/result.json"],
        "provenance": {
            "producer": "test-parser",
            "producer_version": "1",
            "source_digests": {"acts/act_1/outputs/result.json": "sha256:" + "a" * 64},
        },
        "created_by_decision": "dec_001",
        "created_at": "2026-08-15T00:00:00+00:00",
    }


def _compile_classical_ts() -> dict:
    registry = builtin_predicate_registry()
    return compile_gate_spec(
        {
            "dimension": "stationary_point",
            "title": "Validate candidate",
            "template": {
                "template_id": "classical-ts",
                "version": "1",
                "parameters": {"subject_ref": "calc_001"},
            },
        },
        spec_id="gsp_001",
        target_claim_ref="clm_001",
        registry=registry,
        created_by_act="act_1",
        created_by_decision="dec_001",
        frozen_at="2026-08-15T00:00:00+00:00",
    )


def test_template_compilation_is_expanded_and_digest_bound() -> None:
    spec = _compile_classical_ts()

    assert spec["schema_version"] == "ts-gate-spec/1"
    assert spec["template_ref"] == {"template_id": "classical-ts", "version": "1"}
    assert spec["template_digest"].startswith("sha256:")
    assert spec["spec_digest"].startswith("sha256:")
    assert all("${" not in repr(check) for check in spec["checks"])
    assert {check["predicate"] for check in spec["checks"]} == {"observation.equals"}


def test_gate_evaluation_passes_from_exact_semantic_observations() -> None:
    registry = builtin_predicate_registry()
    spec = _compile_classical_ts()
    observations = [
        _observation("obs_001", "program.normal_termination", True),
        _observation("obs_002", "stationary_point.confirmed", True),
        _observation("obs_003", "optimization.converged", True),
        _observation("obs_004", "vibration.imaginary_frequency_count", 1),
        _observation("obs_005", "calculation.method_matches_intent", True),
    ]

    result = evaluate_gate_spec(
        spec,
        observations,
        result_id="val_001",
        evaluated_by_act="act_1",
        evaluated_by_decision="dec_002",
        registry=registry,
        evaluated_at="2026-08-15T00:01:00+00:00",
    )

    assert result["verdict"] == "pass"
    assert {item["verdict"] for item in result["check_results"]} == {"pass"}
    assert result["spec_digest"] == spec["spec_digest"]
    assert result["observation_refs"] == [f"obs_{index:03d}" for index in range(1, 6)]
    assert result["result_digest"].startswith("sha256:")


def test_missing_observation_is_inconclusive_and_false_observation_fails() -> None:
    registry = builtin_predicate_registry()
    spec = _compile_classical_ts()
    incomplete = [
        _observation("obs_001", "program.normal_termination", True),
        _observation("obs_002", "stationary_point.confirmed", True),
    ]
    inconclusive = evaluate_gate_spec(
        spec,
        incomplete,
        result_id="val_001",
        evaluated_by_act="act_1",
        evaluated_by_decision="dec_002",
        registry=registry,
    )
    assert inconclusive["verdict"] == "inconclusive"

    complete = incomplete + [
        _observation("obs_003", "optimization.converged", False),
        _observation("obs_004", "vibration.imaginary_frequency_count", 1),
        _observation("obs_005", "calculation.method_matches_intent", True),
    ]
    failed = evaluate_gate_spec(
        spec,
        complete,
        result_id="val_002",
        evaluated_by_act="act_1",
        evaluated_by_decision="dec_003",
        registry=registry,
    )
    assert failed["verdict"] == "fail"


def test_predicate_cannot_cite_observation_outside_selected_snapshot() -> None:
    registry = PredicateRegistry()
    registry.register(
        "test.out_of_scope",
        "1",
        lambda _parameters, _observations: {
            "verdict": "pass",
            "observation_refs": ["obs_not_selected"],
            "message": "Improperly cited an unselected record.",
        },
    )
    spec = compile_gate_spec(
        {
            "dimension": "scope_integrity",
            "title": "Reject predicate refs outside the selected snapshot",
            "definition": {
                "checks": [
                    {
                        "check_id": "bounded_refs",
                        "predicate": "test.out_of_scope",
                        "parameters": {},
                        "blocking": True,
                    }
                ],
                "success_policy": {"mode": "all"},
            },
        },
        spec_id="gsp_001",
        target_claim_ref="clm_001",
        registry=registry,
        created_by_act="act_1",
        created_by_decision="dec_001",
    )

    result = evaluate_gate_spec(
        spec,
        [_observation("obs_001", "test.value", True)],
        result_id="val_001",
        evaluated_by_act="act_1",
        evaluated_by_decision="dec_002",
        registry=registry,
    )

    assert result["verdict"] == "error"
    assert result["check_results"][0]["observation_refs"] == []
    assert "outside the selected snapshot" in result["check_results"][0]["message"]


def test_unknown_predicate_and_executable_fields_are_rejected() -> None:
    registry = builtin_predicate_registry()
    with pytest.raises(GateSpecCompileError, match="not registered"):
        compile_gate_spec(
            {
                "dimension": "invented",
                "title": "Unsupported code",
                "definition": {
                    "checks": [
                        {
                            "check_id": "arbitrary",
                            "predicate": "python.eval",
                            "parameters": {"code": "__import__('os')"},
                            "blocking": True,
                        }
                    ],
                    "success_policy": {"mode": "all"},
                },
            },
            spec_id="gsp_001",
            target_claim_ref="clm_001",
            registry=registry,
            created_by_act="act_1",
            created_by_decision="dec_001",
        )


def test_spec_or_observation_tampering_is_detected() -> None:
    registry = builtin_predicate_registry()
    spec = deepcopy(_compile_classical_ts())
    spec["checks"][0]["parameters"]["expected"] = False
    with pytest.raises(ValidationEngineError, match="digest"):
        evaluate_gate_spec(
            spec,
            [],
            result_id="val_001",
            evaluated_by_act="act_1",
            evaluated_by_decision="dec_002",
            registry=registry,
        )


def test_template_rejects_missing_and_unknown_parameters() -> None:
    registry = builtin_predicate_registry()
    base = {
        "dimension": "stationary_point",
        "title": "Validate candidate",
        "template": {"template_id": "classical-ts", "version": "1", "parameters": {}},
    }
    with pytest.raises(GateSpecCompileError, match="missing template parameters"):
        compile_gate_spec(
            base,
            spec_id="gsp_001",
            target_claim_ref="clm_001",
            registry=registry,
            created_by_act="act_1",
            created_by_decision="dec_001",
        )

    base["template"]["parameters"] = {"subject_ref": "calc_001", "code": "bad"}
    with pytest.raises(GateSpecCompileError, match="unknown template parameters"):
        compile_gate_spec(
            base,
            spec_id="gsp_001",
            target_claim_ref="clm_001",
            registry=registry,
            created_by_act="act_1",
            created_by_decision="dec_001",
        )
