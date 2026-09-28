"""Framework-neutral capability, environment, and artifact contracts."""

from .artifacts import ArtifactError, ArtifactRef, ArtifactStore
from .descriptors import CapabilityDescriptor, DescriptorError, WORKSPACE_MODES, WorkspaceMode
from .environment import (
    EnvironmentBinding,
    EnvironmentBroker,
    EnvironmentError,
    EnvironmentReadiness,
    EnvironmentRequirement,
    EnvironmentSpec,
)
from .registry import (
    CapabilityProvider,
    CapabilityNotFoundError,
    CapabilityModeNotSupportedError,
    DuplicateCapabilityError,
    ProviderRegistration,
    ProviderRegistry,
    RegistryError,
)
from .local_xyz import (
    DESCRIPTOR as LOCAL_XYZ_DESCRIPTOR,
    LocalGeometryError,
    LocalXYZProvider,
    PreparedGeometry,
    create_local_xyz_provider,
)

__all__ = [
    "ArtifactError",
    "ArtifactRef",
    "ArtifactStore",
    "CapabilityDescriptor",
    "CapabilityProvider",
    "DescriptorError",
    "WORKSPACE_MODES",
    "WorkspaceMode",
    "CapabilityNotFoundError",
    "CapabilityModeNotSupportedError",
    "DuplicateCapabilityError",
    "EnvironmentBinding",
    "EnvironmentBroker",
    "EnvironmentError",
    "EnvironmentReadiness",
    "EnvironmentRequirement",
    "EnvironmentSpec",
    "ProviderRegistration",
    "ProviderRegistry",
    "RegistryError",
    "LOCAL_XYZ_DESCRIPTOR",
    "LocalGeometryError",
    "LocalXYZProvider",
    "PreparedGeometry",
    "create_local_xyz_provider",
]
