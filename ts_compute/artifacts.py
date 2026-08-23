"""Deterministic discovery and binding of workspace calculation artifacts.

Public callers use logical ``art_*`` identifiers. Physical paths remain an
implementation detail of this module and are frozen with a digest whenever a
calculation intent is created.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import posixpath
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from ts_workspace.io import read_json
from ts_workspace.refs import NODE_ID, CALCULATION_ID
from ts_workspace.transactions import workspace_lock
from ts_structures.seed import StructureSeedError, generate_smiles_seed

from .contracts import ComputeContractError


CATALOG_SCHEMA_VERSION = "ts-artifact-catalog/3"
ARTIFACT_ID_SCHEMA_VERSION = "ts-artifact-id/2"
IMPORT_REQUEST_SCHEMA_VERSION = "ts-artifact-import-request/1"
IMPORT_RESULT_SCHEMA_VERSION = "ts-artifact-import-result/1"
STRUCTURE_SEED_REQUEST_SCHEMA_VERSION = "ts-structure-seed-request/1"
STRUCTURE_SEED_RESULT_SCHEMA_VERSION = "ts-structure-seed-result/1"
MAX_IMPORT_BYTES = 128 * 1024
IMPORT_FORMATS = {
    "gaussian_input": ".gjf",
    "xyz_structure": ".xyz",
    "xtb_control": ".inp",
}
ROLE_SUFFIXES = {
    "gjf": frozenset({".gjf", ".com"}),
    "xyz": frozenset({".xyz"}),
    "control": frozenset({".inp"}),
    "config": frozenset({".json"}),
    "reactant": frozenset({".xyz"}),
    "product": frozenset({".xyz"}),
}
ELIGIBLE_SUFFIXES = frozenset({
    ".com", ".gif", ".gjf", ".inp", ".json", ".log", ".out", ".png", ".txt", ".xyz",
})


def list_calculation_artifacts(
    root: str | Path,
    *,
    node_id: str | None = None,
) -> dict[str, Any]:
    """Return a bounded catalog of files eligible as calculation inputs."""

    workspace = _workspace_root(root)
    known_nodes = _node_ids(workspace)
    if node_id is not None and node_id not in known_nodes:
        raise ComputeContractError(f"unknown ResearchNode: {node_id}")
    artifacts = [
        item
        for item in _catalog_items(workspace, known_nodes)
        if node_id is None or item["owner_node"] == node_id
    ]
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "workspace_root": str(workspace),
        "node_id": node_id,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


def resolve_artifact_ids(
    root: str | Path,
    artifact_ids: Iterable[str],
) -> list[dict[str, Any]]:
    """Resolve exact logical IDs to current path/digest records."""

    workspace = _workspace_root(root)
    requested = list(artifact_ids)
    if not requested or len(set(requested)) != len(requested):
        raise ComputeContractError("artifact_ids must be a non-empty unique list")
    catalog = {item["artifact_id"]: item for item in _catalog_items(workspace, _node_ids(workspace))}
    missing = [artifact_id for artifact_id in requested if artifact_id not in catalog]
    if missing:
        raise ComputeContractError("unknown artifact_id: " + ", ".join(missing))
    return [catalog[artifact_id] for artifact_id in requested]


def import_calculation_artifact(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    """Materialize one validated, Node-owned calculation input without a caller path."""

    workspace = _workspace_root(root)
    normalized = _validate_import_request(request)
    with workspace_lock(workspace):
        node = _node_record(workspace, normalized["node_id"])
        if node.get("status") != "open":
            raise ComputeContractError(
                f"artifact import requires an open ResearchNode: {normalized['node_id']}"
            )
        content = _normalize_import_content(normalized["content"])
        payload = content.encode("utf-8")
        if len(payload) > MAX_IMPORT_BYTES:
            raise ComputeContractError(
                f"artifact import exceeds {MAX_IMPORT_BYTES} UTF-8 bytes"
            )
        metadata = _validate_import_content(
            normalized["format"],
            content,
            normalized.get("charge"),
            normalized.get("multiplicity"),
        )
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        suffix = IMPORT_FORMATS[normalized["format"]]
        filename = f"seed_{digest.removeprefix('sha256:')}{suffix}"
        inputs = _node_inputs_directory(workspace, normalized["node_id"])
        path = inputs / filename
        created = _write_import_payload(path, payload)
        artifact = _artifact_for_path(workspace, path, _node_ids(workspace))

    return {
        "schema_version": IMPORT_RESULT_SCHEMA_VERSION,
        "operation": "import",
        "node_id": normalized["node_id"],
        "format": normalized["format"],
        "created": created,
        "chemical_metadata": metadata,
        "artifact": artifact,
    }


def create_structure_seed_artifact(root: str | Path, request: dict[str, Any]) -> dict[str, Any]:
    """Generate and persist one Node-owned RDKit structure seed and provenance."""

    workspace = _workspace_root(root)
    normalized = _validate_structure_seed_request(request)
    try:
        generated = generate_smiles_seed(
            normalized["smiles"],
            charge=normalized["charge"],
            multiplicity=normalized["multiplicity"],
            optimization=normalized["optimization"],
        )
    except StructureSeedError as exc:
        raise ComputeContractError(str(exc)) from exc

    xyz_payload = generated["xyz"].encode("utf-8")
    xyz_digest = "sha256:" + hashlib.sha256(xyz_payload).hexdigest()
    xyz_filename = f"structure_seed_{xyz_digest.removeprefix('sha256:')}.xyz"
    with workspace_lock(workspace):
        node = _node_record(workspace, normalized["node_id"])
        if node.get("status") != "open":
            raise ComputeContractError(
                f"structure seed generation requires an open ResearchNode: {normalized['node_id']}"
            )
        inputs = _node_inputs_directory(workspace, normalized["node_id"])
        xyz_path = inputs / xyz_filename
        xyz_ref = xyz_path.relative_to(workspace).as_posix()
        xyz_artifact_id = _artifact_id(xyz_ref, xyz_digest)
        provenance = {
            "schema_version": "ts-structure-seed-provenance/1",
            "source": generated["source"],
            "generator": generated["generator"],
            "parameters": generated["parameters"],
            "chemical_metadata": generated["chemical_metadata"],
            "limitations": generated["limitations"],
            "output": {
                "artifact_id": xyz_artifact_id,
                "artifact_ref": xyz_ref,
                "sha256": xyz_digest,
                "size_bytes": len(xyz_payload),
            },
        }
        provenance_payload = (
            json.dumps(provenance, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        ).encode("utf-8")
        provenance_digest = "sha256:" + hashlib.sha256(provenance_payload).hexdigest()
        provenance_path = inputs / (
            f"structure_seed_{provenance_digest.removeprefix('sha256:')}.provenance.json"
        )
        created_paths: list[Path] = []
        try:
            if _write_import_payload(xyz_path, xyz_payload):
                created_paths.append(xyz_path)
            if _write_import_payload(provenance_path, provenance_payload):
                created_paths.append(provenance_path)
        except Exception:
            for path in reversed(created_paths):
                path.unlink(missing_ok=True)
            raise
        known_nodes = _node_ids(workspace)
        artifact = _artifact_for_path(workspace, xyz_path, known_nodes)
        provenance_artifact = _artifact_for_path(workspace, provenance_path, known_nodes)

    return {
        "schema_version": STRUCTURE_SEED_RESULT_SCHEMA_VERSION,
        "operation": "generate",
        "node_id": normalized["node_id"],
        "created": bool(created_paths),
        "artifact": artifact,
        "provenance_artifact": provenance_artifact,
        "chemical_metadata": generated["chemical_metadata"],
        "generator": generated["generator"],
        "limitations": generated["limitations"],
    }


def resolve_input_artifacts(
    workspace: Path,
    supplied: list[dict[str, str]],
    required_roles: set[str],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Resolve role/ID pairs into immutable path and digest bindings."""

    by_role: dict[str, str] = {}
    for item in supplied:
        role = str(item["input_role"])
        if role in by_role:
            raise ComputeContractError(f"duplicate calculation input role: {role}")
        by_role[role] = str(item["artifact_id"])
    missing = sorted(required_roles - set(by_role))
    unexpected = sorted(set(by_role) - required_roles)
    if missing or unexpected:
        raise ComputeContractError(
            f"calculation input roles must be exactly {sorted(required_roles)}; "
            f"missing={missing}; unexpected={unexpected}"
        )

    resolved = {
        item["artifact_id"]: item
        for item in resolve_artifact_ids(workspace, by_role.values())
    }
    refs: dict[str, str] = {}
    bindings: list[dict[str, Any]] = []
    for role in sorted(required_roles):
        artifact = resolved[by_role[role]]
        if role not in artifact["input_roles"]:
            raise ComputeContractError(
                f"artifact {artifact['artifact_id']} is not compatible with input role {role}; "
                f"compatible_roles={artifact['input_roles']}"
            )
        path = str(artifact["path"])
        refs[role] = path
        bindings.append(
            {
                "input_role": role,
                "artifact_id": artifact["artifact_id"],
                "path": path,
                "sha256": artifact["sha256"],
                "owner_node": artifact["owner_node"],
                "source_intent_id": artifact["source_intent_id"],
            }
        )
    if len(set(refs.values())) != len(refs):
        raise ComputeContractError("distinct calculation input roles must bind distinct artifacts")
    return refs, bindings


def verify_input_bindings(workspace: Path, intent: dict[str, Any]) -> None:
    """Verify that a frozen input binding still identifies identical bytes."""

    refs = intent.get("input_refs")
    bindings = intent.get("input_bindings")
    if not isinstance(refs, dict) or not isinstance(bindings, list):
        raise ComputeContractError("calculation intent requires input_refs and input_bindings")
    by_role: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        if not isinstance(binding, dict):
            raise ComputeContractError("calculation input binding must be an object")
        role = binding.get("input_role")
        if not isinstance(role, str) or role in by_role:
            raise ComputeContractError(f"duplicate or invalid calculation input binding role: {role}")
        by_role[role] = binding
    if set(by_role) != set(refs):
        raise ComputeContractError("calculation input_bindings roles must match input_refs")
    known_nodes = _node_ids(workspace)
    for role, ref in sorted(refs.items()):
        binding = by_role[role]
        if binding.get("path") != ref:
            raise ComputeContractError(f"calculation input binding path mismatch for role {role}")
        current = _artifact_for_ref(workspace, str(ref), known_nodes)
        for key in ("artifact_id", "sha256", "owner_node", "source_intent_id"):
            if binding.get(key) != current.get(key):
                raise ComputeContractError(
                    f"calculation input binding changed for role {role}: {key} mismatch"
                )


def _catalog_items(workspace: Path, known_nodes: set[str]) -> list[dict[str, Any]]:
    artifacts = [
        _artifact_for_path(workspace, path, known_nodes)
        for path in _eligible_paths(workspace, known_nodes)
    ]
    artifacts.sort(key=lambda item: str(item["path"]))
    return artifacts


def _eligible_paths(workspace: Path, known_nodes: set[str]) -> Iterable[Path]:
    roots: list[Path] = []
    inputs = workspace / "inputs"
    if inputs.is_dir() and not inputs.is_symlink():
        roots.append(inputs)
    nodes_root = workspace / "nodes"
    if nodes_root.is_dir() and not nodes_root.is_symlink():
        for node_dir in sorted(nodes_root.iterdir()):
            if not node_dir.is_dir() or node_dir.is_symlink() or node_dir.name not in known_nodes:
                continue
            for name in ("inputs", "outputs"):
                candidate = node_dir / name
                if candidate.is_dir() and not candidate.is_symlink():
                    roots.append(candidate)
            attempts = node_dir / "attempts"
            if attempts.is_dir() and not attempts.is_symlink():
                for attempt in sorted(attempts.iterdir()):
                    output = attempt / "outputs"
                    if (
                        attempt.is_dir()
                        and not attempt.is_symlink()
                        and CALCULATION_ID.fullmatch(attempt.name)
                        and output.is_dir()
                        and not output.is_symlink()
                    ):
                        roots.append(output)
    seen: set[str] = set()
    for root in roots:
        for current, dirnames, filenames in os.walk(root, followlinks=False):
            current_path = Path(current)
            dirnames[:] = sorted(
                name for name in dirnames if not (current_path / name).is_symlink()
            )
            for name in sorted(filenames):
                path = current_path / name
                if path.suffix.lower() not in ELIGIBLE_SUFFIXES or path.is_symlink():
                    continue
                ref = path.relative_to(workspace).as_posix()
                if ref in seen:
                    continue
                try:
                    _safe_existing_path(workspace, ref, known_nodes)
                except ComputeContractError:
                    continue
                seen.add(ref)
                yield path


def _artifact_for_path(workspace: Path, path: Path, known_nodes: set[str]) -> dict[str, Any]:
    return _artifact_for_ref(workspace, path.relative_to(workspace).as_posix(), known_nodes)


def _artifact_for_ref(workspace: Path, ref: str, known_nodes: set[str]) -> dict[str, Any]:
    normalized, path = _safe_existing_path(workspace, ref, known_nodes)
    owner_node, source_intent_id = _ownership(normalized)
    roles = sorted(
        role for role, suffixes in ROLE_SUFFIXES.items() if path.suffix.lower() in suffixes
    )
    digest = _sha256_file(path)
    return {
        "artifact_id": _artifact_id(normalized, digest),
        "path": normalized,
        "owner_node": owner_node,
        "source_intent_id": source_intent_id,
        "size_bytes": path.stat().st_size,
        "sha256": digest,
        "input_roles": roles,
    }


def _artifact_id(path: str, digest: str) -> str:
    material = json.dumps(
        {"schema_version": ARTIFACT_ID_SCHEMA_VERSION, "path": path, "sha256": digest},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "art_" + hashlib.sha256(material).hexdigest()[:24]


def _validate_import_request(request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ComputeContractError("artifact import request must be an object")
    required = {"schema_version", "node_id", "format", "content"}
    optional = {"charge", "multiplicity"}
    missing = sorted(required - set(request))
    unexpected = sorted(set(request) - required - optional)
    if missing or unexpected:
        raise ComputeContractError(
            f"artifact import fields are invalid: missing={missing}; unexpected={unexpected}"
        )
    if request.get("schema_version") != IMPORT_REQUEST_SCHEMA_VERSION:
        raise ComputeContractError(
            f"artifact import schema_version must be {IMPORT_REQUEST_SCHEMA_VERSION}"
        )
    node_id = request.get("node_id")
    if not isinstance(node_id, str) or NODE_ID.fullmatch(node_id) is None:
        raise ComputeContractError("artifact import node_id is invalid")
    artifact_format = request.get("format")
    if artifact_format not in IMPORT_FORMATS:
        raise ComputeContractError(
            "artifact import format must be one of: " + ", ".join(sorted(IMPORT_FORMATS))
        )
    content = request.get("content")
    if not isinstance(content, str) or not content:
        raise ComputeContractError("artifact import content must be a non-empty string")
    charge = request.get("charge")
    multiplicity = request.get("multiplicity")
    if artifact_format in {"gaussian_input", "xyz_structure"}:
        if type(charge) is not int or not -20 <= charge <= 20:
            raise ComputeContractError("structure artifact charge must be an integer from -20 to 20")
        if type(multiplicity) is not int or not 1 <= multiplicity <= 21:
            raise ComputeContractError("structure artifact multiplicity must be an integer from 1 to 21")
    elif charge is not None or multiplicity is not None:
        raise ComputeContractError("xTB control artifact does not accept charge or multiplicity")
    return dict(request)


def _validate_structure_seed_request(request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ComputeContractError("structure seed request must be an object")
    required = {
        "schema_version",
        "node_id",
        "smiles",
        "charge",
        "multiplicity",
        "optimization",
    }
    missing = sorted(required - set(request))
    unexpected = sorted(set(request) - required)
    if missing or unexpected:
        raise ComputeContractError(
            f"structure seed fields are invalid: missing={missing}; unexpected={unexpected}"
        )
    if request.get("schema_version") != STRUCTURE_SEED_REQUEST_SCHEMA_VERSION:
        raise ComputeContractError(
            f"structure seed schema_version must be {STRUCTURE_SEED_REQUEST_SCHEMA_VERSION}"
        )
    node_id = request.get("node_id")
    if not isinstance(node_id, str) or NODE_ID.fullmatch(node_id) is None:
        raise ComputeContractError("structure seed node_id is invalid")
    smiles = request.get("smiles")
    if not isinstance(smiles, str) or not 1 <= len(smiles) <= 4_096:
        raise ComputeContractError("structure seed SMILES must contain 1 to 4096 characters")
    charge = request.get("charge")
    multiplicity = request.get("multiplicity")
    if type(charge) is not int or not -20 <= charge <= 20:
        raise ComputeContractError("structure seed charge must be an integer from -20 to 20")
    if type(multiplicity) is not int or not 1 <= multiplicity <= 21:
        raise ComputeContractError("structure seed multiplicity must be an integer from 1 to 21")
    if request.get("optimization") not in {"none", "uff"}:
        raise ComputeContractError("structure seed optimization must be none or uff")
    return dict(request)


def _normalize_import_content(content: str) -> str:
    if "\x00" in content:
        raise ComputeContractError("artifact import content cannot contain NUL bytes")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        raise ComputeContractError("artifact import content cannot be blank")
    return normalized if normalized.endswith("\n") else normalized + "\n"


def _validate_import_content(
    artifact_format: str,
    content: str,
    charge: int | None,
    multiplicity: int | None,
) -> dict[str, Any]:
    if artifact_format == "xyz_structure":
        return _xyz_import_metadata(content, int(charge), int(multiplicity))
    if artifact_format == "gaussian_input":
        return _gaussian_import_metadata(content, int(charge), int(multiplicity))
    if not re.search(r"(?m)^\s*\$[A-Za-z]", content) or not re.search(
        r"(?mi)^\s*\$end\s*$", content
    ):
        raise ComputeContractError("xTB control input requires at least one $ block and a $end line")
    return {"format": "xtb_control"}


def _xyz_import_metadata(content: str, charge: int, multiplicity: int) -> dict[str, Any]:
    lines = content.splitlines()
    if len(lines) < 3:
        raise ComputeContractError("XYZ seed is too short")
    try:
        atom_count = int(lines[0].strip())
    except ValueError as exc:
        raise ComputeContractError("XYZ seed first line must be an atom count") from exc
    if not 1 <= atom_count <= 512:
        raise ComputeContractError("XYZ seed atom count must be from 1 to 512")
    if len(lines) < atom_count + 2 or any(line.strip() for line in lines[atom_count + 2 :]):
        raise ComputeContractError("XYZ seed must contain exactly one complete frame")
    atom_order: list[str] = []
    for index, line in enumerate(lines[2 : atom_count + 2], start=3):
        parts = line.split()
        if len(parts) < 4 or re.fullmatch(r"(?:[A-Za-z]{1,3}|[1-9][0-9]{0,2})", parts[0]) is None:
            raise ComputeContractError(f"XYZ seed has an invalid atom line {index}")
        try:
            coordinates = [float(value) for value in parts[1:4]]
        except ValueError as exc:
            raise ComputeContractError(f"XYZ seed has a non-numeric coordinate on line {index}") from exc
        if not all(math.isfinite(value) for value in coordinates):
            raise ComputeContractError(f"XYZ seed has a non-finite coordinate on line {index}")
        atom_order.append(parts[0])
    return {
        "format": "xyz",
        "charge": charge,
        "multiplicity": multiplicity,
        "atom_count": atom_count,
        "atom_order": atom_order,
    }


def _gaussian_import_metadata(content: str, charge: int, multiplicity: int) -> dict[str, Any]:
    lines = content.splitlines()
    route_index = next((index for index, line in enumerate(lines) if line.lstrip().startswith("#")), None)
    if route_index is None:
        raise ComputeContractError("Gaussian seed requires a route section")
    route_end = next(
        (index for index in range(route_index + 1, len(lines)) if not lines[index].strip()),
        len(lines),
    )
    route = " ".join(line.strip() for line in lines[route_index:route_end]).strip()
    if route in {"#", "#p", "#P"}:
        raise ComputeContractError("Gaussian seed route section cannot be empty")
    if any(re.fullmatch(r"\s*--Link1--\s*", line, flags=re.IGNORECASE) for line in lines):
        raise ComputeContractError("Gaussian seed must contain exactly one job; --Link1-- is not allowed")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("%") and any(marker in stripped for marker in ("/", "\\", "..")):
            raise ComputeContractError("Gaussian Link 0 directives cannot select filesystem paths")

    qst_matches = {int(match.group(1)) for match in re.finditer(r"(?i)\bqst([23])\b", route)}
    if len(qst_matches) > 1:
        raise ComputeContractError("Gaussian seed route cannot request both QST2 and QST3")
    structure_count = next(iter(qst_matches), 1)
    structures: list[list[str]] = []
    cursor = route_end
    for structure_index in range(1, structure_count + 1):
        cursor = _skip_blank_lines(lines, cursor)
        title_start = cursor
        while cursor < len(lines) and lines[cursor].strip():
            cursor += 1
        if cursor == title_start:
            raise ComputeContractError(
                f"Gaussian seed requires title section {structure_index} of {structure_count}"
            )
        cursor = _skip_blank_lines(lines, cursor)
        atom_order, cursor = _gaussian_cartesian_structure(
            lines,
            cursor,
            charge,
            multiplicity,
            structure_index,
            structure_count,
        )
        structures.append(atom_order)

    atom_order = structures[0]
    for structure_index, candidate in enumerate(structures[1:], start=2):
        if len(candidate) != len(atom_order):
            raise ComputeContractError(
                f"Gaussian QST structure {structure_index} atom count does not match structure 1"
            )
        if candidate != atom_order:
            raise ComputeContractError(
                f"Gaussian QST structure {structure_index} atom order does not match structure 1"
            )
    return {
        "format": "gaussian_input",
        "charge": charge,
        "multiplicity": multiplicity,
        "structure_count": structure_count,
        "atom_count": len(atom_order),
        "atom_order": atom_order,
        "route": route,
    }


def _skip_blank_lines(lines: list[str], cursor: int) -> int:
    while cursor < len(lines) and not lines[cursor].strip():
        cursor += 1
    return cursor


def _gaussian_cartesian_structure(
    lines: list[str],
    cursor: int,
    charge: int,
    multiplicity: int,
    structure_index: int,
    structure_count: int,
) -> tuple[list[str], int]:
    if cursor >= len(lines):
        raise ComputeContractError(
            f"Gaussian seed requires charge and multiplicity for structure "
            f"{structure_index} of {structure_count}"
        )
    charge_line = re.fullmatch(
        r"\s*([+-]?\d+)\s+(\d+)(?:\s+[+-]?\d+\s+\d+)*\s*",
        lines[cursor],
    )
    if charge_line is None:
        raise ComputeContractError(
            f"Gaussian seed has an invalid charge/multiplicity line for structure "
            f"{structure_index} of {structure_count}"
        )
    embedded = (int(charge_line.group(1)), int(charge_line.group(2)))
    if embedded != (charge, multiplicity):
        raise ComputeContractError(
            f"Gaussian seed structure {structure_index} charge/multiplicity does not match "
            "declared chemical metadata"
        )

    cursor += 1
    atom_order: list[str] = []
    while cursor < len(lines) and lines[cursor].strip():
        parts = lines[cursor].split()
        symbol = re.match(r"^(?:[A-Za-z]{1,3}|[1-9][0-9]{0,2})", parts[0]) if parts else None
        if len(parts) < 4 or symbol is None:
            raise ComputeContractError(f"Gaussian seed has an invalid Cartesian atom line {cursor + 1}")
        try:
            coordinates = [float(value) for value in parts[-3:]]
        except ValueError as exc:
            raise ComputeContractError(
                f"Gaussian seed requires Cartesian coordinates on line {cursor + 1}"
            ) from exc
        if not all(math.isfinite(value) for value in coordinates):
            raise ComputeContractError(f"Gaussian seed has a non-finite coordinate on line {cursor + 1}")
        atom_order.append(symbol.group(0))
        cursor += 1
    if not atom_order:
        raise ComputeContractError(
            f"Gaussian seed requires at least one Cartesian atom in structure "
            f"{structure_index} of {structure_count}"
        )
    if len(atom_order) > 512:
        raise ComputeContractError("Gaussian seed atom count cannot exceed 512")
    return atom_order, cursor


def _node_inputs_directory(workspace: Path, node_id: str) -> Path:
    nodes_root = workspace / "nodes"
    if not nodes_root.is_dir() or nodes_root.is_symlink():
        raise ComputeContractError("workspace nodes root must be a physical directory")
    node_root = nodes_root / node_id
    if node_root.exists():
        if not node_root.is_dir() or node_root.is_symlink():
            raise ComputeContractError(f"ResearchNode artifact root is unsafe: {node_id}")
    else:
        node_root.mkdir(mode=0o700)
    inputs = node_root / "inputs"
    if inputs.exists():
        if not inputs.is_dir() or inputs.is_symlink():
            raise ComputeContractError(f"ResearchNode input root is unsafe: {node_id}")
    else:
        inputs.mkdir(mode=0o700)
    expected = workspace / "nodes" / node_id / "inputs"
    if inputs.resolve(strict=True) != expected.resolve(strict=True):
        raise ComputeContractError(f"ResearchNode input root escapes the workspace: {node_id}")
    return inputs


def _write_import_payload(path: Path, payload: bytes) -> bool:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise ComputeContractError("artifact import target is not a regular file")
        if path.read_bytes() != payload:
            raise ComputeContractError("artifact import content-address collision")
        if path.stat().st_mode & 0o077:
            raise ComputeContractError("existing imported artifact is not private")
        return False
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return True


def _node_record(workspace: Path, node_id: str) -> dict[str, Any]:
    registry = read_json(workspace / "research_nodes.json")
    matches = [
        item
        for item in registry.get("nodes", [])
        if isinstance(item, dict) and item.get("node_id") == node_id
    ]
    if len(matches) != 1:
        raise ComputeContractError(f"unknown ResearchNode: {node_id}")
    return matches[0]


def _ownership(ref: str) -> tuple[str | None, str | None]:
    parts = PurePosixPath(ref).parts
    if len(parts) >= 2 and parts[0] == "inputs":
        return None, None
    if len(parts) >= 4 and parts[0] == "nodes" and parts[2] in {"inputs", "outputs"}:
        return parts[1], None
    if len(parts) >= 6 and parts[0] == "nodes" and parts[2] == "attempts" and parts[4] == "outputs":
        return parts[1], parts[3]
    raise ComputeContractError(
        "calculation artifacts must come from workspace inputs or ResearchNode inputs/outputs"
    )


def _safe_existing_path(
    workspace: Path,
    value: str,
    known_nodes: set[str],
) -> tuple[str, Path]:
    text = str(value).replace("\\", "/").lstrip("@")
    if PurePosixPath(text).is_absolute():
        raise ComputeContractError(f"workspace path must be relative: {value}")
    normalized = posixpath.normpath(text)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise ComputeContractError(f"invalid workspace path: {value}")
    owner_node, _ = _ownership(normalized)
    if owner_node is not None and owner_node not in known_nodes:
        raise ComputeContractError(f"calculation artifact owner ResearchNode does not exist: {owner_node}")
    path = workspace.joinpath(*PurePosixPath(normalized).parts)
    if not path.is_file() or path.is_symlink():
        raise ComputeContractError(f"workspace calculation artifact does not exist: {normalized}")
    workspace_real = workspace.resolve(strict=True)
    expected = workspace_real.joinpath(*PurePosixPath(normalized).parts)
    if path.resolve(strict=True) != expected:
        raise ComputeContractError(f"workspace calculation artifact uses a symlink: {normalized}")
    return normalized, path


def _workspace_root(root: str | Path) -> Path:
    workspace = Path(root).expanduser().resolve()
    workspace_doc = workspace / "workspace.json"
    acts_doc = workspace / "research_nodes.json"
    if not workspace_doc.is_file() or not acts_doc.is_file() or not (workspace / "nodes").is_dir():
        raise ComputeContractError(f"not an initialized v5 TS workspace: {workspace}")
    if read_json(workspace_doc).get("schema_version") != "ts-workspace/5":
        raise ComputeContractError(f"unsupported workspace protocol: {workspace}")
    return workspace


def _node_ids(workspace: Path) -> set[str]:
    registry = read_json(workspace / "research_nodes.json")
    if registry.get("schema_version") != "ts-research-node-registry/1":
        raise ComputeContractError("invalid ResearchNode registry")
    ids = {
        item.get("node_id")
        for item in registry.get("nodes", [])
        if isinstance(item, dict) and isinstance(item.get("node_id"), str)
    }
    if any(NODE_ID.fullmatch(value) is None for value in ids):
        raise ComputeContractError("ResearchNode registry contains an invalid node_id")
    return ids


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()
