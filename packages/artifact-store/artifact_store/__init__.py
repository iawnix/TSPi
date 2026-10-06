"""Physical payload storage for Research State Artifacts.

The store owns bytes and materialization paths only.  Artifact manifests,
lineage, evidence links, and scientific meaning remain owned by
``research_state``.
"""

from .store import ArtifactPayloadError, PayloadReceipt, PayloadStore
from .transfer import (
    DEFAULT_CHUNK_SIZE,
    SCHEMA_VERSION as TRANSFER_SCHEMA_VERSION,
    TransferManifestError,
    apply_manifest,
    build_manifest,
    validate_manifest,
)

__all__ = [
    "ArtifactPayloadError",
    "PayloadReceipt",
    "PayloadStore",
    "DEFAULT_CHUNK_SIZE",
    "TRANSFER_SCHEMA_VERSION",
    "TransferManifestError",
    "apply_manifest",
    "build_manifest",
    "validate_manifest",
]
