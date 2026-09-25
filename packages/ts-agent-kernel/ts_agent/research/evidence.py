"""Kernel-owned metadata for execution attempts and research evidence.

Raw files remain in the workspace or an object store.  These records provide
the stable identity, provenance, and admissible links that let the Research
Kernel reason about evidence without loading large payloads into the map or a
turn context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Collection, Mapping

from .model import ResearchMap, ResearchModelError


class EvidenceModelError(ResearchModelError):
    """Raised when an evidence record violates its Kernel contract."""


def validate_artifact_refs(
    refs: Any,
    artifacts: Mapping[str, "ArtifactManifest"],
    *,
    label: str,
) -> None:
    """Require every reference in an artifact-only field to be registered."""

    _string_list(refs, label)
    missing = sorted(set(refs) - set(artifacts))
    if missing:
        raise EvidenceModelError(f"{label} references unregistered Artifacts: {', '.join(missing)}")


def validate_evidence_refs(
    refs: Any,
    artifacts: Mapping[str, "ArtifactManifest"],
    links: Mapping[str, "EvidenceLink"],
    *,
    label: str,
    subject_type: str,
    subject_id: str,
) -> None:
    """Require refs to resolve to artifacts or links for one map subject.

    Direct Artifact references are useful for findings whose source is a raw
    output.  EvidenceLink references additionally require the link's subject
    to be the object receiving the reference, so a Gate cannot silently cite
    a link that was registered for an unrelated Finding.
    """

    _string_list(refs, label)
    for ref in refs:
        if ref in artifacts:
            continue
        link = links.get(ref)
        if link is None:
            raise EvidenceModelError(f"{label} references unregistered evidence {ref}")
        if link.subject_type != subject_type or link.subject_id != subject_id:
            raise EvidenceModelError(
                f"{label} reference {ref} belongs to {link.subject_type} {link.subject_id}, "
                f"not {subject_type} {subject_id}"
            )


def validate_subject_links(
    refs: Collection[str],
    links: Mapping[str, "EvidenceLink"],
    *,
    label: str,
    subject_type: str,
) -> None:
    """Require each referenced map object to have a matching evidence link."""

    for ref in refs:
        matches = [
            link
            for link in links.values()
            if link.subject_type == subject_type and link.subject_id == ref
        ]
        if not matches:
            raise EvidenceModelError(
                f"{label} {ref} has no registered EvidenceLink for {subject_type}"
            )


def validate_map_evidence(
    research_map: ResearchMap,
    artifacts: Mapping[str, "ArtifactManifest"],
    links: Mapping[str, "EvidenceLink"],
) -> None:
    """Validate all evidence-bearing ResearchMap fields against the registry."""

    for finding in research_map.findings.values():
        validate_evidence_refs(
            finding.source_refs,
            artifacts,
            links,
            label=f"finding {finding.id} source_refs",
            subject_type="finding",
            subject_id=finding.id,
        )
    for gate in research_map.gates.values():
        for index, evaluation in enumerate(gate.evaluations):
            validate_evidence_refs(
                evaluation.evidence_refs,
                artifacts,
                links,
                label=f"gate {gate.id} evaluation {index} evidence_refs",
                subject_type="gate",
                subject_id=gate.id,
            )


def validate_interpretation_evidence(
    interpretation: Any,
    artifacts: Mapping[str, "ArtifactManifest"],
    links: Mapping[str, "EvidenceLink"],
) -> None:
    """Validate an AttemptInterpretation's traceability references."""

    validate_artifact_refs(
        interpretation.artifact_refs,
        artifacts,
        label=f"interpretation {interpretation.id} artifact_refs",
    )
    validate_subject_links(
        interpretation.finding_ids,
        links,
        label=f"interpretation {interpretation.id} finding_ids",
        subject_type="finding",
    )
    validate_subject_links(
        interpretation.gate_ids,
        links,
        label=f"interpretation {interpretation.id} gate_ids",
        subject_type="gate",
    )


def _text(value: Any, label: str, *, max_length: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise EvidenceModelError(f"{label} must be a non-empty bounded string")
    return value.strip()


def _string_list(value: Any, label: str, *, max_items: int = 256) -> list[str]:
    if not isinstance(value, list) or len(value) > max_items:
        raise EvidenceModelError(f"{label} must be a bounded list")
    result: list[str] = []
    for item in value:
        result.append(_text(item, f"{label} item", max_length=1024))
    if len(set(result)) != len(result):
        raise EvidenceModelError(f"{label} must not contain duplicates")
    return result


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceModelError(f"{label} must be an object")
    return dict(value)


@dataclass(kw_only=True)
class AttemptRecord:
    """A generic execution attempt produced by any registered capability."""

    id: str
    node_id: str
    capability: str
    capability_version: str
    state: str
    environment: str | None = None
    input_artifact_ids: list[str] = field(default_factory=list)
    output_artifact_ids: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    type_name = "attempt_record"

    def validate(self, research_map: ResearchMap | None = None) -> None:
        _text(self.id, "attempt id", max_length=256)
        _text(self.node_id, "attempt node_id", max_length=256)
        _text(self.capability, "attempt capability", max_length=256)
        _text(self.capability_version, "attempt capability_version", max_length=64)
        _text(self.state, "attempt state", max_length=64)
        if self.environment is not None:
            _text(self.environment, "attempt environment", max_length=256)
        _string_list(self.input_artifact_ids, "attempt input_artifact_ids")
        _string_list(self.output_artifact_ids, "attempt output_artifact_ids")
        _text(self.created_at, "attempt created_at", max_length=128)
        if self.updated_at:
            _text(self.updated_at, "attempt updated_at", max_length=128)
        _object(self.metadata, "attempt metadata")
        if research_map is not None and self.node_id not in research_map.nodes:
            raise EvidenceModelError(f"attempt {self.id} references unknown node {self.node_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type_name,
            "id": self.id,
            "node_id": self.node_id,
            "capability": self.capability,
            "capability_version": self.capability_version,
            "state": self.state,
            "environment": self.environment,
            "input_artifact_ids": list(self.input_artifact_ids),
            "output_artifact_ids": list(self.output_artifact_ids),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AttemptRecord":
        return cls(
            id=value.get("id", ""),
            node_id=value.get("node_id", ""),
            capability=value.get("capability", ""),
            capability_version=value.get("capability_version", ""),
            state=value.get("state", ""),
            environment=value.get("environment"),
            input_artifact_ids=list(value.get("input_artifact_ids", [])),
            output_artifact_ids=list(value.get("output_artifact_ids", [])),
            created_at=value.get("created_at", ""),
            updated_at=value.get("updated_at", ""),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(kw_only=True)
class ArtifactManifest:
    """Immutable metadata for one workspace or object-store artifact."""

    id: str
    node_id: str | None
    kind: str
    format: str
    location: str
    sha256: str
    size_bytes: int
    status: str = "verified"
    producer_attempt_id: str | None = None
    input_artifact_ids: list[str] = field(default_factory=list)
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    type_name = "artifact_manifest"

    def validate(self, research_map: ResearchMap | None = None) -> None:
        _text(self.id, "artifact id", max_length=256)
        if self.node_id is not None:
            _text(self.node_id, "artifact node_id", max_length=256)
        _text(self.kind, "artifact kind", max_length=128)
        _text(self.format, "artifact format", max_length=128)
        _text(self.location, "artifact location", max_length=4096)
        _text(self.sha256, "artifact sha256", max_length=128)
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise EvidenceModelError("artifact size_bytes must be a non-negative integer")
        if self.status not in {"registered", "verified", "invalid", "superseded"}:
            raise EvidenceModelError("artifact status is invalid")
        if self.producer_attempt_id is not None:
            _text(self.producer_attempt_id, "artifact producer_attempt_id", max_length=256)
        _string_list(self.input_artifact_ids, "artifact input_artifact_ids")
        _text(self.created_at, "artifact created_at", max_length=128)
        _object(self.metadata, "artifact metadata")
        if research_map is not None and self.node_id is not None and self.node_id not in research_map.nodes:
            raise EvidenceModelError(f"artifact {self.id} references unknown node {self.node_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type_name,
            "id": self.id,
            "node_id": self.node_id,
            "kind": self.kind,
            "format": self.format,
            "location": self.location,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "status": self.status,
            "producer_attempt_id": self.producer_attempt_id,
            "input_artifact_ids": list(self.input_artifact_ids),
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactManifest":
        location = value.get("location", value.get("path", ""))
        producer = value.get("producer_attempt_id", value.get("source_intent_id"))
        metadata = dict(value.get("metadata", {}))
        if value.get("role") is not None:
            metadata.setdefault("role", value.get("role"))
        return cls(
            id=value.get("id", value.get("artifact_id", "")),
            node_id=value.get("node_id", value.get("owner_node")),
            kind=value.get("kind", "calculation_artifact"),
            format=value.get("format", str(location).rsplit(".", 1)[-1] if "." in str(location) else "binary"),
            location=location,
            sha256=value.get("sha256", ""),
            size_bytes=value.get("size_bytes", 0),
            status=value.get("status", "verified"),
            producer_attempt_id=producer,
            input_artifact_ids=list(value.get("input_artifact_ids", [])),
            created_at=value.get("created_at", ""),
            metadata=metadata,
        )


@dataclass(kw_only=True)
class EvidenceLink:
    """A typed relation that makes an Artifact admissible evidence."""

    id: str
    artifact_id: str
    subject_type: str
    subject_id: str
    relation: str
    locator: str | None = None
    created_at: str = ""
    actor: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    type_name = "evidence_link"

    def validate(self, research_map: ResearchMap | None = None) -> None:
        _text(self.id, "evidence link id", max_length=256)
        _text(self.artifact_id, "evidence artifact_id", max_length=256)
        if self.subject_type not in {"claim", "finding", "gate", "decision"}:
            raise EvidenceModelError("evidence subject_type is invalid")
        _text(self.subject_id, "evidence subject_id", max_length=256)
        if self.relation not in {"supports", "contradicts", "qualifies", "derived_from", "documents"}:
            raise EvidenceModelError("evidence relation is invalid")
        if self.locator is not None:
            _text(self.locator, "evidence locator", max_length=4096)
        _text(self.created_at, "evidence created_at", max_length=128)
        _object(self.actor, "evidence actor")
        _object(self.metadata, "evidence metadata")
        if research_map is not None:
            collections = {
                "claim": research_map.claims,
                "finding": research_map.findings,
                "gate": research_map.gates,
            }
            if self.subject_type in collections and self.subject_id not in collections[self.subject_type]:
                raise EvidenceModelError(f"evidence link references unknown {self.subject_type} {self.subject_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type_name,
            "id": self.id,
            "artifact_id": self.artifact_id,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "relation": self.relation,
            "locator": self.locator,
            "created_at": self.created_at,
            "actor": dict(self.actor),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceLink":
        return cls(
            id=value.get("id", ""),
            artifact_id=value.get("artifact_id", ""),
            subject_type=value.get("subject_type", ""),
            subject_id=value.get("subject_id", ""),
            relation=value.get("relation", ""),
            locator=value.get("locator"),
            created_at=value.get("created_at", ""),
            actor=dict(value.get("actor", {})),
            metadata=dict(value.get("metadata", {})),
        )


__all__ = [
    "ArtifactManifest",
    "AttemptRecord",
    "EvidenceLink",
    "EvidenceModelError",
    "validate_artifact_refs",
    "validate_evidence_refs",
    "validate_interpretation_evidence",
    "validate_map_evidence",
    "validate_subject_links",
]
