"""Deterministic validation of an explicit reaction atom mapping.

This module validates a proposed mapping.  It deliberately does not invent an
atom map: symmetry, proton transfer, and multi-fragment correspondence require
an explicit scientific choice or a separately registered mapping generator.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable


def validate_atom_mapping(
    reactant_atoms: list[list[str]],
    product_atoms: list[list[str]],
    mapping: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate one explicit mapping over one or more reaction species.

    Mapping entries use zero-based local atom references::

        {"reactant": {"species": 0, "atom": 1},
         "product": {"species": 0, "atom": 1}}

    The result is factual.  ``valid`` means every atom on both sides is mapped
    exactly once and mapped elements agree.  Incomplete or ambiguous proposals
    remain non-valid with diagnostics rather than being silently completed.
    """

    reactant = _normalise_atoms(reactant_atoms, "reactant")
    product = _normalise_atoms(product_atoms, "product")
    diagnostics: list[str] = []
    pairs: list[dict[str, Any]] = []
    reactant_seen: set[tuple[int, int]] = set()
    product_seen: set[tuple[int, int]] = set()

    if not isinstance(mapping, list) or not mapping:
        diagnostics.append("mapping must contain at least one atom pair")
        mapping_rows: list[Any] = []
    else:
        mapping_rows = mapping

    for index, row in enumerate(mapping_rows):
        if not isinstance(row, dict) or set(row) != {"reactant", "product"}:
            diagnostics.append(f"mapping entry {index} must contain reactant and product only")
            continue
        left = _parse_ref(row.get("reactant"), reactant, "reactant", index, diagnostics)
        right = _parse_ref(row.get("product"), product, "product", index, diagnostics)
        if left is None or right is None:
            continue
        if left in reactant_seen:
            diagnostics.append(f"reactant atom {left} is mapped more than once")
        if right in product_seen:
            diagnostics.append(f"product atom {right} is mapped more than once")
        reactant_seen.add(left)
        product_seen.add(right)
        left_element = reactant[left[0]][left[1]]
        right_element = product[right[0]][right[1]]
        if left_element != right_element:
            diagnostics.append(
                f"mapping entry {index} changes element {left_element} to {right_element}"
            )
        pairs.append(
            {
                "reactant": {"species": left[0], "atom": left[1]},
                "product": {"species": right[0], "atom": right[1]},
                "element": left_element,
                "element_match": left_element == right_element,
            }
        )

    # A definite contradiction takes precedence over incomplete coverage.
    invalid = bool(diagnostics)
    reactant_missing = _missing_atoms(reactant, reactant_seen)
    product_missing = _missing_atoms(product, product_seen)
    if reactant_missing:
        diagnostics.append(f"{len(reactant_missing)} reactant atom(s) are unmapped")
    if product_missing:
        diagnostics.append(f"{len(product_missing)} product atom(s) are unmapped")

    reactant_counts = Counter(element for species in reactant for element in species)
    product_counts = Counter(element for species in product for element in species)
    mapped_reactant_counts = Counter(row["element"] for row in pairs)
    mapped_product_counts = Counter(
        product[row["product"]["species"]][row["product"]["atom"]] for row in pairs
    )
    if reactant_counts != product_counts:
        diagnostics.append(
            "whole-reaction element counts differ: "
            f"reactant={dict(sorted(reactant_counts.items()))}; "
            f"product={dict(sorted(product_counts.items()))}"
        )

    complete = not reactant_missing and not product_missing
    unique = len(reactant_seen) == len(pairs) and len(product_seen) == len(pairs)
    elements_match = all(row["element_match"] for row in pairs)
    counts_match = reactant_counts == product_counts
    valid = bool(pairs) and complete and unique and elements_match and counts_match and not diagnostics
    verdict = "invalid" if invalid or not counts_match else ("valid" if valid else "inconclusive")

    return {
        "verdict": verdict,
        "complete": complete,
        "valid": valid,
        "mapping_count": len(pairs),
        "reactant_atom_count": sum(len(species) for species in reactant),
        "product_atom_count": sum(len(species) for species in product),
        "reactant_species_count": len(reactant),
        "product_species_count": len(product),
        "element_counts": {
            "reactant": dict(sorted(reactant_counts.items())),
            "product": dict(sorted(product_counts.items())),
            "mapped_reactant": dict(sorted(mapped_reactant_counts.items())),
            "mapped_product": dict(sorted(mapped_product_counts.items())),
        },
        "pairs": pairs,
        "unmapped": {"reactant": reactant_missing, "product": product_missing},
        "diagnostics": sorted(set(diagnostics)),
    }


def _normalise_atoms(value: Any, label: str) -> list[list[str]]:
    from ase.data import atomic_numbers

    if not isinstance(value, list) or not value:
        raise ValueError(f"{label}_atoms must be a non-empty species array")
    result: list[list[str]] = []
    for species_index, species in enumerate(value):
        if not isinstance(species, list) or not species:
            raise ValueError(f"{label}_atoms species {species_index} must contain atoms")
        normalised: list[str] = []
        for atom_index, element in enumerate(species):
            if not isinstance(element, str) or not element.strip():
                raise ValueError(f"{label}_atoms[{species_index}][{atom_index}] is not an element")
            symbol = element.strip().capitalize()
            if atomic_numbers.get(symbol, 0) <= 0:
                raise ValueError(f"{label}_atoms[{species_index}][{atom_index}] is not a supported element: {element}")
            normalised.append(symbol)
        result.append(normalised)
    return result


def mapping_finding_candidates(
    validation: dict[str, Any], node_id: str, sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """Derive small factual candidates without assigning reaction identity."""

    fields = (
        ("valid", "element_bijection", "boolean"),
        ("complete", "coverage_complete", "boolean"),
        ("mapping_count", "pair_count", "integer"),
    )
    return {
        "schema_version": "ts-analysis-finding-candidates/1",
        "node_id": node_id,
        "capability": "reaction.mapping.validate",
        "capability_version": "1",
        "parser": {"name": "ts_agent.reaction.mapping.validate_atom_mapping", "contract": "ts.reaction.mapping/1"},
        "source_artifacts": [
            {key: item[key] for key in ("artifact_id", "path", "sha256")} for item in sources
        ],
        "candidates": [
            {
                "candidate_id": f"candidate_{index}",
                "concept_id": f"reaction.mapping.{concept}",
                "value": validation[field], "datatype": datatype, "unit": None,
                "qualifiers": {
                    "capability": "reaction.mapping.validate", "capability_version": "1",
                    "parser_field": field, "producer_kind": "analysis",
                    "scope": "element correspondence only",
                },
                "source_artifact_ids": [item["artifact_id"] for item in sources],
            }
            for index, (field, concept, datatype) in enumerate(fields, 1)
        ],
    }


def _parse_ref(
    value: Any,
    atoms: list[list[str]],
    label: str,
    mapping_index: int,
    diagnostics: list[str],
) -> tuple[int, int] | None:
    if not isinstance(value, dict) or set(value) != {"species", "atom"}:
        diagnostics.append(f"mapping entry {mapping_index} has an invalid {label} reference")
        return None
    species = value["species"]
    atom = value["atom"]
    if type(species) is not int or type(atom) is not int or species < 0 or atom < 0:
        diagnostics.append(f"mapping entry {mapping_index} has a negative or non-integer {label} reference")
        return None
    if species >= len(atoms) or atom >= len(atoms[species]):
        diagnostics.append(f"mapping entry {mapping_index} {label} reference is out of range")
        return None
    return species, atom


def _missing_atoms(atoms: list[list[str]], seen: Iterable[tuple[int, int]]) -> list[dict[str, int]]:
    known = set(seen)
    return [
        {"species": species_index, "atom": atom_index}
        for species_index, species in enumerate(atoms)
        for atom_index in range(len(species))
        if (species_index, atom_index) not in known
    ]
