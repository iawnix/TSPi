from __future__ import annotations

from dataclasses import replace

import pytest

from research_compute.artifact_registry import (
    ArtifactOperationDescriptor,
    artifact_operation_catalog,
    artifact_operation_digest,
    register_artifact_provider,
    resolve_artifact_operation,
    validate_artifact_request,
    validate_artifact_result,
)


def _descriptor(operation: str = "fixture.artifact") -> ArtifactOperationDescriptor:
    return ArtifactOperationDescriptor(
        operation=operation,
        version="1",
        input_schema={
            "type": "object",
            "required": ["inputs"],
            "properties": {"inputs": {"type": "array", "items": {"type": "string"}}},
            "additionalProperties": False,
        },
        parameter_schema={"type": "object", "additionalProperties": False},
        result_schema={
            "type": "object",
            "required": ["value"],
            "properties": {"value": {"type": "integer"}},
            "additionalProperties": False,
        },
        output_roles=("artifact",),
        provenance_schema="ts-artifact-provenance/1",
    )


def test_artifact_provider_registration_keeps_provider_out_of_public_catalog() -> None:
    descriptor = _descriptor()

    class Provider:
        provider_id = "fixture-artifact-provider"

        def operations(self):
            return [descriptor]

    provider = Provider()
    registration = register_artifact_provider(provider)

    assert registration[0].provider is provider
    assert resolve_artifact_operation("fixture.artifact").provider_id == "fixture-artifact-provider"
    public = artifact_operation_catalog()
    item = next(item for item in public["operations"] if item["operation"] == "fixture.artifact")
    assert item["result_schema"] == descriptor.result_schema
    assert "provider_id" not in item
    assert "command" not in item


def test_provider_result_requires_descriptor_and_provenance_match() -> None:
    descriptor = _descriptor("fixture.result")
    digest = artifact_operation_digest(descriptor)
    result = {
        "operation": descriptor.operation,
        "version": descriptor.version,
        "result": {"value": 3},
        "provenance": {
            "provider_id": "fixture",
            "descriptor_digest": digest,
            "inputs": [{"artifact_id": "art_input"}],
            "outputs": [{"artifact_id": "art_output", "sha256": digest}],
        },
    }

    checked = validate_artifact_result(
        descriptor,
        result,
        provider_id="fixture",
        descriptor_digest=digest,
    )
    checked["result"]["value"] = 9
    assert result["result"]["value"] == 3

    with pytest.raises(ValueError, match="provenance"):
        validate_artifact_result(
            descriptor,
            result,
            provider_id="other",
            descriptor_digest=digest,
        )
    result["result"]["value"] = "not an integer"
    with pytest.raises(ValueError, match="result_schema"):
        validate_artifact_result(
            descriptor,
            result,
            provider_id="fixture",
            descriptor_digest=digest,
        )


def test_provider_owned_request_schemas_are_validated_before_prepare() -> None:
    descriptor = _descriptor("fixture.request")
    inputs, _parameters = validate_artifact_request(
        descriptor,
        {"inputs": ["art_input"]},
        {},
    )
    inputs["inputs"].append("art_other")
    assert inputs != {"inputs": ["art_input"]}
    with pytest.raises(ValueError, match="inputs"):
        validate_artifact_request(descriptor, {"wrong": []}, {})


def test_provider_can_add_required_provenance_fields() -> None:
    descriptor = replace(
        _descriptor("fixture.provenance"),
        provenance_schema={
            "type": "object",
            "required": ["run_id"],
            "properties": {"run_id": {"type": "string", "minLength": 1}},
            "additionalProperties": True,
        },
    )
    digest = artifact_operation_digest(descriptor)
    result = {
        "operation": descriptor.operation,
        "version": descriptor.version,
        "result": {"value": 1},
        "provenance": {
            "provider_id": "fixture",
            "descriptor_digest": digest,
            "inputs": [],
            "outputs": [],
            "run_id": "run-1",
        },
    }
    validate_artifact_result(descriptor, result, provider_id="fixture", descriptor_digest=digest)
    result["provenance"].pop("run_id")
    with pytest.raises(ValueError, match="provenance_schema"):
        validate_artifact_result(descriptor, result, provider_id="fixture", descriptor_digest=digest)
