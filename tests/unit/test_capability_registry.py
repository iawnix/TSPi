from __future__ import annotations

import pytest
from pathlib import Path

from tspi_runtime.backends.base import PreparedTask
from research_compute.capabilities import CapabilityDescriptor
from research_compute.registry import (
    CapabilityRegistry,
    CapabilityRegistryError,
    DuplicateCapabilityError,
)


def _descriptor(
    name: str,
    version: str = "1",
    *,
    backend: str = "test",
    task_type: str = "sp",
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability=name,
        version=version,
        backend=backend,
        task_type=task_type,
        input_roles=frozenset({"xyz"}),
        output_roles=("program_output",),
        effects=("local_prepare",),
        parameter_schema={"type": "object"},
        limits={},
        parsers=(),
    )


def test_registry_resolves_versioned_descriptors_and_rejects_implicit_replace() -> None:
    registry: CapabilityRegistry[CapabilityDescriptor] = CapabilityRegistry()
    descriptor = _descriptor("test.sp")

    registration = registry.register(descriptor, provider_id="fixture")

    assert registration.provider_id == "fixture"
    assert registry.resolve("test.sp", "1").descriptor is descriptor
    with pytest.raises(DuplicateCapabilityError):
        registry.register(descriptor, provider_id="other")
    replacement = _descriptor("test.sp", "2")
    registry.register(replacement, provider_id="other")
    assert registry.resolve("test.sp", "2").provider_id == "other"


def test_provider_registration_is_atomic_and_keeps_provider_association() -> None:
    registry: CapabilityRegistry[dict[str, str]] = CapabilityRegistry()

    class Provider:
        provider_id = "fixture-provider"

        def descriptors(self):
            return [
                {"capability": "fixture.one", "version": "1"},
                {"capability": "fixture.two", "version": "1"},
            ]

    provider = Provider()
    registrations = registry.register_provider(provider)
    assert [item.provider_id for item in registrations] == ["fixture-provider"] * 2
    assert all(item.provider is provider for item in registrations)
    assert [item.descriptor["capability"] for item in registry.registrations()] == [
        "fixture.one", "fixture.two"
    ]

    class BrokenProvider:
        provider_id = "broken"

        def descriptors(self):
            return [
                {"capability": "fixture.three", "version": "1"},
                {"capability": "fixture.one", "version": "1"},
            ]

    with pytest.raises(DuplicateCapabilityError):
        registry.register_provider(BrokenProvider())
    assert registry.resolve("fixture.three", "1") is None


def test_registry_accepts_analysis_mapping_descriptors() -> None:
    registry: CapabilityRegistry[dict[str, str]] = CapabilityRegistry()
    descriptor = {"capability": "analysis.fixture", "version": "1"}
    registry.register(descriptor)
    assert registry.resolve("analysis.fixture", "1").descriptor == descriptor


def test_provider_without_descriptor_method_is_rejected() -> None:
    with pytest.raises(CapabilityRegistryError, match=r"descriptors\(\) or capabilities\(\)"):
        CapabilityRegistry().register_provider(object())


def test_registered_execution_provider_is_an_explicit_prepare_boundary(tmp_path: Path) -> None:
    from research_compute.capabilities import register_capability_provider
    from research_compute.control import _raw_prepared_task

    class Provider:
        provider_id = "fixture-execution-provider"

        def descriptors(self):
            return [_descriptor("fixture.execution", version="7", backend="xtb", task_type="fixture")]

        def validate_inputs(self, *, workspace, intent, inputs):
            assert workspace == tmp_path
            assert intent["capability"] == "fixture.execution"
            assert set(inputs) == {"xyz"}

        def prepare(self, task):
            return PreparedTask(
                backend=task.backend if hasattr(task, "backend") else "test",
                node_id=task.node_id,
                command=["fixture-program", task.inputs["xyz"]],
                input_paths=[task.inputs["xyz"]],
                expected_artifacts=["fixture.out"],
            )

    provider = Provider()
    register_capability_provider(provider)
    prepared = _raw_prepared_task(tmp_path, {
        "capability": "fixture.execution",
        "capability_version": "7",
        "backend": "xtb",
        "task_type": "fixture",
        "node_id": "node_1",
        "intent_id": "calc_1",
        "input_refs": {"xyz": "nodes/node_1/inputs/input.xyz"},
        "parameters": {},
    }, verify_inputs=False)

    assert prepared.command == ["fixture-program", "nodes/node_1/inputs/input.xyz"]
    assert prepared.expected_artifacts == ["fixture.out"]


def test_calculation_intent_contract_allows_provider_owned_backend_ids() -> None:
    from tspi_runtime.calculation_contracts import validate_calculation_contract
    from tests.support.workspace_helpers import calculation_intent_fixture

    intent = calculation_intent_fixture("node_1", "calc_1")
    intent["backend"] = "openmm"
    validate_calculation_contract("calculation_intent.schema.json", intent)
