"""Physical payload storage for Research State Artifacts.

The store owns bytes and materialization paths only.  Artifact manifests,
lineage, evidence links, and scientific meaning remain owned by
``research_agent.research``.
"""

from .store import ArtifactPayloadError, PayloadReceipt, PayloadStore

__all__ = ["ArtifactPayloadError", "PayloadReceipt", "PayloadStore"]
