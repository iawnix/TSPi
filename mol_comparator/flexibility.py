"""Policies for excluding flexible atoms from local metrics."""

from __future__ import annotations


def select_reaction_center(
    atom_count: int,
    reaction_center_atoms: list[int] | None,
    fallback_indices: list[int],
) -> list[int]:
    if reaction_center_atoms:
        invalid = [index for index in reaction_center_atoms if index < 0 or index >= atom_count]
        if invalid:
            raise ValueError(f"reaction center atom index out of range: {invalid}")
        return reaction_center_atoms
    return fallback_indices
