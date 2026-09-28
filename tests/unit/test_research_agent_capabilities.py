from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


PACKAGE_ROOT = Path(__file__).parents[2] / "packages" / "research-agent-capabilities"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from research_agent_capabilities import (  # noqa: E402
    ArtifactError,
    ArtifactStore,
    CapabilityDescriptor,
    CapabilityModeNotSupportedError,
    DescriptorError,
    EnvironmentBroker,
    EnvironmentError,
    EnvironmentReadiness,
    EnvironmentRequirement,
    EnvironmentSpec,
    ProviderRegistry,
)
from research_agent_capabilities.registry import DuplicateCapabilityError, RegistryError  # noqa: E402


def _descriptor(capability_id: str = "fixture_compute", *, provider_id: str = "fixture_provider"):
    return CapabilityDescriptor(
        capability_id=capability_id,
        version="1",
        provider_id=provider_id,
        input_kinds=("input_xyz",),
        output_kinds=("output_log",),
        parameter_schema={"type": "object", "properties": {"charge": {"type": "integer"}}},
        environment_requirements=("local",),
        metadata={"domain": "fixture"},
    )


def test_descriptor_serialization_is_snake_case_and_detached() -> None:
    descriptor = _descriptor()
    value = descriptor.to_dict()
    assert set(value) == {
        "schema_version",
        "capability_id",
        "version",
        "provider_id",
        "input_kinds",
        "output_kinds",
        "parameter_schema",
        "environment_requirements",
        "supported_workspace_modes",
        "metadata",
    }
    value["metadata"]["domain"] = "changed"
    assert descriptor.metadata["domain"] == "fixture"
    with pytest.raises(DescriptorError):
        CapabilityDescriptor("bad ID", "1", "fixture-provider")


def test_descriptor_round_trip_and_mode_validation() -> None:
    descriptor = _descriptor()
    parsed = CapabilityDescriptor.from_dict(descriptor.to_dict())
    assert parsed == descriptor

    canonical = descriptor.to_canonical_dict()
    assert canonical["protocol"] == "capability_descriptor"
    assert canonical["capability_version"] == descriptor.version
    assert canonical["provider"]["provider_id"] == descriptor.provider_id
    assert CapabilityDescriptor.from_canonical_dict(canonical) == descriptor

    dotted = _descriptor("gaussian.opt_freq").to_canonical_dict()
    assert CapabilityDescriptor.from_canonical_dict(dotted).capability_id == "gaussian.opt_freq"

    serialized = descriptor.to_dict()
    serialized.pop("supported_workspace_modes")
    with pytest.raises(DescriptorError, match="missing capability descriptor fields"):
        CapabilityDescriptor.from_dict(serialized)

    for modes in ([], ["light", "light"], ["sandbox"], "research"):
        invalid = descriptor.to_dict()
        invalid["supported_workspace_modes"] = modes
        with pytest.raises(DescriptorError):
            CapabilityDescriptor.from_dict(invalid)


def test_registry_registers_provider_atomically_and_rejects_duplicates() -> None:
    class Provider:
        provider_id = "fixture_provider"

        def descriptors(self):
            return [_descriptor("fixture_one"), _descriptor("fixture_two")]

    registry = ProviderRegistry()
    entries = registry.register_provider(Provider())
    assert [entry.descriptor.capability_id for entry in entries] == ["fixture_one", "fixture_two"]
    assert registry.require("fixture_one").provider_id == "fixture_provider"

    class BrokenProvider:
        provider_id = "broken_provider"

        def descriptors(self):
            return [_descriptor("fixture_three", provider_id="broken_provider"), _descriptor("fixture_one", provider_id="broken_provider")]

    with pytest.raises(DuplicateCapabilityError):
        registry.register_provider(BrokenProvider())
    assert registry.resolve("fixture_three") is None
    with pytest.raises(DuplicateCapabilityError):
        registry.register_provider(Provider())
    with pytest.raises(RegistryError):
        registry.register_provider(object())


def test_registry_discovers_multiple_providers_and_can_remove_one() -> None:
    class Provider:
        def __init__(self, provider_id: str, capability_id: str) -> None:
            self.provider_id = provider_id
            self.capability_id = capability_id

        def descriptors(self):
            return [_descriptor(self.capability_id, provider_id=self.provider_id)]

    registry = ProviderRegistry()
    first = Provider("first_provider", "first_capability")
    second = Provider("second_provider", "second_capability")
    entries = registry.register_providers([first, second])
    assert len(entries) == 2
    assert registry.provider_ids() == ("first_provider", "second_provider")
    assert registry.registered_providers() == (("first_provider", first), ("second_provider", second))
    assert registry.unregister_provider("first_provider") is True
    assert registry.resolve("first_capability") is None
    assert registry.resolve("second_capability") is not None
    assert registry.unregister_provider("first_provider") is False

    with pytest.raises(DuplicateCapabilityError):
        registry.register_providers([
            Provider("third_provider", "third_capability"),
            Provider("duplicate_provider", "second_capability"),
        ])
    assert registry.resolve("third_capability") is None


def test_registry_provider_replace_is_complete_and_cannot_clobber_another_provider() -> None:
    class Provider:
        def __init__(self, provider_id: str, capabilities: tuple[str, ...]) -> None:
            self.provider_id = provider_id
            self.capabilities = capabilities

        def descriptors(self):
            return tuple(_descriptor(capability, provider_id=self.provider_id) for capability in self.capabilities)

    registry = ProviderRegistry()
    registry.register_provider(Provider("first_provider", ("first_capability", "stale_capability")))
    registry.register_provider(Provider("second_provider", ("second_capability",)))
    registry.register_provider(Provider("first_provider", ("first_capability",)), replace=True)
    assert registry.resolve("first_capability") is not None
    assert registry.resolve("stale_capability") is None
    with pytest.raises(DuplicateCapabilityError, match="belongs to provider second_provider"):
        registry.register_provider(Provider("third_provider", ("second_capability",)), replace=True)


def test_registry_enforces_workspace_mode_admission() -> None:
    class Provider:
        provider_id = "fixture_provider"

        def descriptors(self):
            return [
                CapabilityDescriptor(
                    capability_id="research_only",
                    version="1",
                    provider_id=self.provider_id,
                    supported_workspace_modes=("research",),
                )
            ]

    registry = ProviderRegistry()
    registry.register_provider(Provider())
    assert registry.require_for_workspace_mode("research_only", "research").descriptor.capability_id == "research_only"
    with pytest.raises(CapabilityModeNotSupportedError):
        registry.require_for_workspace_mode("research_only", "light")

    registry.register_descriptor(_descriptor(), Provider())
    assert registry.require_for_workspace_mode("fixture_compute", "light").descriptor.capability_id == "fixture_compute"
    assert registry.require_for_workspace_mode("fixture_compute", "research").descriptor.capability_id == "fixture_compute"
    with pytest.raises(CapabilityModeNotSupportedError):
        registry.require_for_workspace_mode("fixture_compute", "unknown")


def test_environment_broker_selects_matching_environment_and_probes() -> None:
    environment = EnvironmentSpec(
        environment_id="local-cpu",
        environment_kind="local",
        provider_ids=("fixture-provider",),
        tool_ids=("fixture-tool",),
        environment_keys=("cpu",),
    )

    def probe(selected, requirement):
        assert selected.environment_id == "local-cpu"
        assert requirement.capability_id == "fixture_compute"
        return EnvironmentReadiness("ready", ({"name": "fixture-tool", "state": "ready"},))

    broker = EnvironmentBroker((environment,), readiness_probe=probe)
    binding = broker.bind(
        EnvironmentRequirement(
            "fixture_compute",
            "fixture-provider",
            environment_kind="local",
            required_tool_ids=("fixture-tool",),
            required_environment_keys=("cpu",),
        ),
        probe=True,
    )
    assert binding.readiness.state == "ready"
    assert binding.to_dict()["schema_version"] == "research-agent-environment-binding/1"
    assert "command" not in json.dumps(binding.to_dict())
    with pytest.raises(EnvironmentError):
        broker.bind(EnvironmentRequirement("fixture_compute", "missing-provider"))


def test_artifact_store_is_content_addressed_and_fails_closed(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    first = store.put_bytes(b"hello", artifact_type="text/plain", metadata={"source": "test"})
    second = store.put_bytes(b"hello", artifact_type="text/plain", metadata={"source": "test"})
    assert first == second
    assert store.get(first.artifact_id) == first
    assert store.read_bytes(first) == b"hello"

    content_path = tmp_path / "artifacts" / first.artifact_path
    content_path.write_bytes(b"tampered")
    with pytest.raises(ArtifactError, match="digest mismatch"):
        store.read_bytes(first)
    with pytest.raises(ArtifactError):
        store.get("artifact_" + "0" * 63)
    with pytest.raises(ArtifactError, match="does not match"):
        type(first)(
            artifact_id=first.artifact_id,
            content_digest=first.content_digest,
            artifact_type=first.artifact_type,
            byte_count=first.byte_count,
            artifact_path="content/../outside.bin",
            metadata=first.metadata,
        )


def test_protocol_schemas_validate_serialized_values() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema_root = PACKAGE_ROOT / "schemas"
    descriptor_schema = json.loads((schema_root / "capability_descriptor.schema.json").read_text())
    jsonschema.Draft202012Validator(descriptor_schema).validate(_descriptor().to_dict())
    for modes in ([], ["light", "light"], ["sandbox"]):
        invalid = _descriptor().to_dict()
        invalid["supported_workspace_modes"] = modes
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(descriptor_schema).validate(invalid)
