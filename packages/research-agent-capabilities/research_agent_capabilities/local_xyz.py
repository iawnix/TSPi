"""Deterministic local XYZ capability for framework smoke tests.

The provider intentionally has no subprocess or path-writing API.  Artifact
persistence and environment selection are explicit Host-owned boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .artifacts import ArtifactRef, ArtifactStore
from .descriptors import CapabilityDescriptor
from .environment import EnvironmentBinding, EnvironmentBroker, EnvironmentRequirement


class LocalGeometryError(ValueError):
    """Raised when a deterministic geometry request cannot be admitted."""


_GEOMETRIES: dict[str, tuple[str, int, int]] = {
    "water": (
        "3\nwater (deterministic local geometry)\n"
        "O 0.000000 0.000000 0.000000\n"
        "H 0.758602 0.000000 0.504284\n"
        "H -0.758602 0.000000 0.504284\n",
        0,
        1,
    ),
    "methane": (
        "5\nmethane (deterministic local geometry)\n"
        "C 0.000000 0.000000 0.000000\n"
        "H 0.629118 0.629118 0.629118\n"
        "H -0.629118 -0.629118 0.629118\n"
        "H -0.629118 0.629118 -0.629118\n"
        "H 0.629118 -0.629118 -0.629118\n",
        0,
        1,
    ),
    "methanol": (
        "6\nmethanol (deterministic local geometry)\n"
        "C 0.000000 0.000000 0.000000\n"
        "O 1.430000 0.000000 0.000000\n"
        "H -0.363000 0.944000 0.000000\n"
        "H -0.363000 -0.944000 0.000000\n"
        "H -0.363000 0.000000 1.019000\n"
        "H 1.811000 0.763000 0.000000\n",
        0,
        1,
    ),
}


DESCRIPTOR = CapabilityDescriptor(
    capability_id="local_xyz_generate",
    version="1",
    provider_id="local_geometry",
    input_kinds=("molecule",),
    output_kinds=("xyz", "artifact"),
    parameter_schema={
        "type": "object",
        "required": ["molecule"],
        "properties": {
            "molecule": {"enum": sorted(_GEOMETRIES)},
            "logical_ref": {"type": "string", "maxLength": 256},
        },
        "additionalProperties": False,
    },
    supported_workspace_modes=("light", "research"),
    metadata={
        "lifecycle": ["prepare", "execute", "parse", "finalize"],
        "effects": ["artifact_create", "local_prepare", "local_execute", "local_parse", "local_finalize"],
    },
)


@dataclass(frozen=True)
class PreparedGeometry:
    molecule: str
    xyz: str
    charge: int
    multiplicity: int
    logical_ref: str
    environment: dict[str, Any]


class LocalXYZProvider:
    """Provider for bounded, named geometries with an explicit four-stage API."""

    provider_id = "local_geometry"

    def descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        return (DESCRIPTOR,)

    def prepare(
        self,
        request: Mapping[str, Any],
        *,
        environment_broker: EnvironmentBroker | None = None,
        environment_id: str | None = None,
    ) -> PreparedGeometry:
        if not isinstance(request, Mapping):
            raise LocalGeometryError("request must be an object")
        unknown = set(request) - {"molecule", "logical_ref"}
        if unknown:
            raise LocalGeometryError(f"unknown input field: {sorted(unknown)[0]}")
        molecule = request.get("molecule")
        if not isinstance(molecule, str) or molecule not in _GEOMETRIES:
            raise LocalGeometryError("molecule must be one of water, methane, or methanol")
        logical_ref = request.get("logical_ref", f"inputs/{molecule}.xyz")
        if (
            not isinstance(logical_ref, str)
            or not logical_ref
            or len(logical_ref) > 256
            or logical_ref.startswith("/")
            or any(segment in {"", ".", ".."} for segment in logical_ref.split("/"))
        ):
            raise LocalGeometryError("logical_ref must be a relative path without traversal")
        xyz, charge, multiplicity = _GEOMETRIES[molecule]
        if environment_broker is None:
            environment = {"environment_id": "local_builtin", "state": "not_required"}
        else:
            binding = environment_broker.bind(
                EnvironmentRequirement(
                    capability_id=DESCRIPTOR.capability_id,
                    provider_id=self.provider_id,
                    environment_kind="local",
                ),
                environment_id,
            )
            environment = binding.to_dict()
        return PreparedGeometry(molecule, xyz, charge, multiplicity, logical_ref, environment)

    def execute(self, prepared: PreparedGeometry, *, artifact_store: ArtifactStore) -> dict[str, Any]:
        if not isinstance(prepared, PreparedGeometry):
            raise LocalGeometryError("prepared geometry is invalid")
        if not isinstance(artifact_store, ArtifactStore):
            raise LocalGeometryError("an ArtifactStore is required")
        artifact = artifact_store.put_bytes(
            prepared.xyz.encode("utf-8"),
            artifact_type="chemical/xyz",
            metadata={
                "molecule": prepared.molecule,
                "charge": prepared.charge,
                "multiplicity": prepared.multiplicity,
                "provider_id": self.provider_id,
                "capability_id": DESCRIPTOR.capability_id,
                "environment_id": prepared.environment["environment_id"],
            },
        )
        return {"artifact": artifact, "xyz": prepared.xyz}

    def parse(self, executed: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(executed, Mapping) or not isinstance(executed.get("xyz"), str):
            raise LocalGeometryError("execution result is invalid")
        lines = executed["xyz"].rstrip("\n").split("\n")
        try:
            atom_count = int(lines[0])
        except (IndexError, ValueError) as exc:
            raise LocalGeometryError("generated XYZ is invalid") from exc
        if atom_count < 1 or len(lines) != atom_count + 2:
            raise LocalGeometryError("generated XYZ atom count is invalid")
        elements: dict[str, int] = {}
        for row in lines[2:]:
            fields = row.split()
            if len(fields) != 4:
                raise LocalGeometryError("generated XYZ atom row is invalid")
            symbol = fields[0]
            try:
                coordinates = tuple(float(item) for item in fields[1:])
            except ValueError as exc:
                raise LocalGeometryError("generated XYZ coordinate is invalid") from exc
            if any(not (-float("inf") < coordinate < float("inf")) for coordinate in coordinates):
                raise LocalGeometryError("generated XYZ coordinate is invalid")
            elements[symbol] = elements.get(symbol, 0) + 1
        return {"geometry": {"atom_count": atom_count, "elements": elements}, "xyz": executed["xyz"]}

    def finalize(
        self,
        prepared: PreparedGeometry,
        executed: Mapping[str, Any],
        parsed: Mapping[str, Any],
    ) -> dict[str, Any]:
        artifact = executed.get("artifact") if isinstance(executed, Mapping) else None
        geometry = parsed.get("geometry") if isinstance(parsed, Mapping) else None
        if not isinstance(artifact, ArtifactRef) or not isinstance(geometry, Mapping):
            raise LocalGeometryError("lifecycle result is incomplete")
        return {
            "output": {
                "artifact": artifact.to_dict(),
                "geometry": dict(geometry),
                "molecule": prepared.molecule,
                "charge": prepared.charge,
                "multiplicity": prepared.multiplicity,
                "environment": dict(prepared.environment),
            },
            "artifacts": [artifact.artifact_id],
        }

    def invoke(
        self,
        request: Mapping[str, Any],
        *,
        artifact_store: ArtifactStore,
        environment_broker: EnvironmentBroker | None = None,
        environment_id: str | None = None,
    ) -> dict[str, Any]:
        prepared = self.prepare(request, environment_broker=environment_broker, environment_id=environment_id)
        executed = self.execute(prepared, artifact_store=artifact_store)
        parsed = self.parse(executed)
        return self.finalize(prepared, executed, parsed)


def create_local_xyz_provider() -> LocalXYZProvider:
    """Return a fresh provider without global registry mutation."""

    return LocalXYZProvider()


__all__ = [
    "DESCRIPTOR",
    "LocalGeometryError",
    "LocalXYZProvider",
    "PreparedGeometry",
    "create_local_xyz_provider",
]
