"""QBICS fragment and diabatic-state request normalization."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class QbicsFragmentSpec:
    """One QBICS diabatic-state fragment definition."""

    state: str
    charge: int
    spin: int
    atoms: tuple[int, ...]

    def as_metadata(self) -> dict[str, Any]:
        """Return a stable JSON-friendly metadata record."""

        return {
            "state": self.state,
            "charge": self.charge,
            "spin": self.spin,
            "atoms": self.atoms,
            "atom_range": format_qbics_atom_range(self.atoms),
        }


def positive_int_or_none(value: int | str | None, *, field: str) -> int | None:
    """Normalize optional positive integer command parameters."""

    if value is None or str(value).strip() == "":
        return None
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"QBICS {field} must be positive")
    return parsed


def normalize_qbics_charge(value: int | str | None, *, field: str = "charge") -> int | None:
    """Normalize optional integer total or fragment charge fields."""

    if value is None or str(value).strip() == "":
        return None
    return int(value)


def normalize_qbics_spin2p1(value: int | str | None, *, field: str = "spin2p1") -> int | None:
    """Normalize optional positive spin multiplicity fields."""

    if value is None or str(value).strip() == "":
        return None
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"QBICS {field} must be positive")
    return parsed


def normalize_qbics_atom_indices(value: Any) -> tuple[int, ...]:
    """Normalize QBICS atom index ranges such as ``1-3,5`` to 1-based indices."""

    if value is None:
        raise ValueError("QBICS fragment atoms are required")
    if isinstance(value, int):
        indices = (value,)
    elif isinstance(value, str):
        tokens = [token for token in re.split(r"[\s,;]+", value.strip()) if token]
        indices_list: list[int] = []
        for token in tokens:
            range_match = re.fullmatch(r"(\d+)\s*[-:]\s*(\d+)", token)
            if range_match:
                start = int(range_match.group(1))
                end = int(range_match.group(2))
                if end < start:
                    raise ValueError(f"QBICS atom range must be ascending: {token!r}")
                indices_list.extend(range(start, end + 1))
            else:
                indices_list.append(int(token))
        indices = tuple(indices_list)
    elif isinstance(value, Sequence):
        indices_list = []
        for item in value:
            indices_list.extend(normalize_qbics_atom_indices(item))
        indices = tuple(indices_list)
    else:
        raise ValueError(f"unsupported QBICS atom index specification: {value!r}")
    if not indices:
        raise ValueError("QBICS fragment atoms are required")
    invalid = tuple(index for index in indices if index <= 0)
    if invalid:
        raise ValueError(f"QBICS atom indices must be positive: {invalid}")
    duplicates = _duplicates(indices)
    if duplicates:
        raise ValueError(f"QBICS fragment atom list contains duplicates: {duplicates}")
    return indices


def format_qbics_atom_range(indices: Sequence[int]) -> str:
    """Return a compact, stable atom-range string for metadata."""

    sorted_indices = sorted(indices)
    if not sorted_indices:
        return ""
    ranges: list[str] = []
    start = previous = sorted_indices[0]
    for index in sorted_indices[1:]:
        if index == previous + 1:
            previous = index
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = index
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def normalize_qbics_fragments(value: Any, *, state: str) -> tuple[QbicsFragmentSpec, ...]:
    """Normalize direct or nested ``frag1``/``frag2`` request values."""

    if value is None:
        return ()
    if isinstance(value, str):
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if not lines:
            return ()
        return tuple(_normalize_qbics_fragment_spec(line, state) for line in lines)
    if isinstance(value, Mapping):
        return (_normalize_qbics_fragment_spec(value, state),)
    if isinstance(value, Sequence):
        if _looks_like_fragment_tuple(value):
            return (_normalize_qbics_fragment_spec(value, state),)
        return tuple(_normalize_qbics_fragment_spec(item, state) for item in value)
    raise ValueError(f"unsupported QBICS {state} fragment collection: {value!r}")


def normalize_qbics_state_metadata(request: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize optional QBICS charge, spin, fragment, and orbital-state metadata."""

    metadata: dict[str, Any] = {}
    charge = normalize_qbics_charge(
        _first_present(request, "charge", "total_charge"),
        field="charge",
    )
    spin2p1 = normalize_qbics_spin2p1(
        _first_present(request, "spin2p1", "multiplicity", "spin_multiplicity"),
        field="spin2p1",
    )
    atom_count = positive_int_or_none(
        _first_present(request, "atom_count", "natoms"),
        field="atom_count",
    )
    frag1 = normalize_qbics_fragments(_fragment_value_from_mapping(request, "frag1"), state="frag1")
    frag2 = normalize_qbics_fragments(_fragment_value_from_mapping(request, "frag2"), state="frag2")
    orbital_states = _orbital_states_from_mapping(request)

    if charge is not None:
        metadata["charge"] = charge
    if spin2p1 is not None:
        metadata["spin2p1"] = spin2p1
    if atom_count is not None:
        metadata["atom_count"] = atom_count

    has_fragments = bool(frag1 or frag2)
    has_orbitals = bool(orbital_states)
    if has_fragments:
        if not frag1 or not frag2:
            raise ValueError("QBICS fragment definitions require both frag1 and frag2")
        if charge is None:
            raise ValueError("QBICS fragment definitions require total charge")
        for state, fragments in (("frag1", frag1), ("frag2", frag2)):
            _validate_qbics_fragment_charge_sum(
                state=state,
                fragments=fragments,
                total_charge=charge,
            )
            _validate_qbics_atom_coverage(
                state=state,
                fragments=fragments,
                atom_count=atom_count,
            )
        metadata["fragment_states"] = {
            "frag1": tuple(fragment.as_metadata() for fragment in frag1),
            "frag2": tuple(fragment.as_metadata() for fragment in frag2),
        }
        metadata["fragment_state_charges"] = {
            "frag1": sum(fragment.charge for fragment in frag1),
            "frag2": sum(fragment.charge for fragment in frag2),
        }

    if has_orbitals:
        metadata["orbital_states"] = orbital_states
    if has_fragments and has_orbitals:
        deliberate_mix = _truthy(
            request.get(
                "allow_mixed_state_definitions",
                request.get("deliberate_mixed_state_definitions", False),
            )
        )
        if not deliberate_mix:
            raise ValueError(
                "mixed QBICS frag/orb state definitions require "
                "allow_mixed_state_definitions=true"
            )
        metadata["state_definition_priority"] = "orbital"
    elif has_fragments:
        metadata["state_definition_priority"] = "fragment"
    elif has_orbitals:
        metadata["state_definition_priority"] = "orbital"
    return metadata


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _duplicates(values: Sequence[int]) -> tuple[int, ...]:
    seen: set[int] = set()
    repeated: list[int] = []
    for value in values:
        if value in seen and value not in repeated:
            repeated.append(value)
        seen.add(value)
    return tuple(repeated)


def _fragment_value_from_mapping(request: Mapping[str, Any], state: str) -> Any:
    if state in request:
        return request[state]
    for container_key in ("fragments", "fragment_states"):
        container = request.get(container_key)
        if isinstance(container, Mapping) and state in container:
            return container[state]
    return None


def _looks_like_fragment_tuple(value: Sequence[Any]) -> bool:
    if len(value) < 3:
        return False
    if isinstance(value[0], Mapping) or isinstance(value[1], Mapping):
        return False
    try:
        int(value[0])
        int(value[1])
    except (TypeError, ValueError):
        return False
    return True


def _normalize_qbics_fragment_spec(raw: Any, state: str) -> QbicsFragmentSpec:
    if isinstance(raw, QbicsFragmentSpec):
        if raw.state != state:
            raise ValueError(f"QBICS fragment state mismatch: expected {state}, got {raw.state}")
        return raw
    if isinstance(raw, Mapping):
        charge_value = raw.get("charge")
        spin_value = _first_present(raw, "spin", "spin2p1", "multiplicity")
        atom_value = _first_present(raw, "atoms", "atom_indices", "atom_range", "range")
    elif isinstance(raw, str):
        parts = raw.strip().split(maxsplit=2)
        if len(parts) != 3:
            raise ValueError(f"QBICS {state} fragment line requires charge, spin, and atoms")
        charge_value, spin_value, atom_value = parts
    elif isinstance(raw, Sequence) and _looks_like_fragment_tuple(raw):
        charge_value = raw[0]
        spin_value = raw[1]
        atom_value = raw[2] if len(raw) == 3 else raw[2:]
    else:
        raise ValueError(f"unsupported QBICS {state} fragment specification: {raw!r}")

    charge = normalize_qbics_charge(charge_value, field=f"{state} fragment charge")
    spin = normalize_qbics_spin2p1(spin_value, field=f"{state} fragment spin")
    if charge is None:
        raise ValueError(f"QBICS {state} fragment charge is required")
    if spin is None:
        raise ValueError(f"QBICS {state} fragment spin is required")
    return QbicsFragmentSpec(
        state=state,
        charge=charge,
        spin=spin,
        atoms=normalize_qbics_atom_indices(atom_value),
    )


def _validate_qbics_fragment_charge_sum(
    *,
    state: str,
    fragments: Sequence[QbicsFragmentSpec],
    total_charge: int,
) -> None:
    state_charge = sum(fragment.charge for fragment in fragments)
    if state_charge != total_charge:
        raise ValueError(
            f"QBICS {state} fragment charges sum to {state_charge}, "
            f"but total charge is {total_charge}"
        )


def _validate_qbics_atom_coverage(
    *,
    state: str,
    fragments: Sequence[QbicsFragmentSpec],
    atom_count: int | None,
) -> None:
    atoms = tuple(atom for fragment in fragments for atom in fragment.atoms)
    duplicates = _duplicates(atoms)
    if duplicates:
        raise ValueError(f"QBICS {state} atom coverage contains duplicates: {duplicates}")
    if atom_count is None:
        return
    expected = set(range(1, atom_count + 1))
    actual = set(atoms)
    missing = tuple(sorted(expected - actual))
    extra = tuple(sorted(actual - expected))
    if missing or extra:
        raise ValueError(
            f"QBICS {state} atoms must cover 1..{atom_count} exactly once; "
            f"missing={missing}, extra={extra}"
        )


def _orbital_states_from_mapping(request: Mapping[str, Any]) -> dict[str, str]:
    states: dict[str, str] = {}
    for key in ("orb1", "orb2"):
        value = request.get(key)
        if value is not None and str(value).strip() != "":
            states[key] = str(value)
    container = request.get("orbital_states")
    if isinstance(container, Mapping):
        for key in ("orb1", "orb2"):
            value = container.get(key)
            if value is not None and str(value).strip() != "":
                states[key] = str(value)
    if states and set(states) != {"orb1", "orb2"}:
        raise ValueError("QBICS orbital state definitions require both orb1 and orb2")
    return states


__all__ = [
    "QbicsFragmentSpec",
    "format_qbics_atom_range",
    "normalize_qbics_atom_indices",
    "normalize_qbics_charge",
    "normalize_qbics_fragments",
    "normalize_qbics_spin2p1",
    "normalize_qbics_state_metadata",
    "positive_int_or_none",
]
