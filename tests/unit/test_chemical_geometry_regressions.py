"""Deterministic molecular geometry/graph checks, never transition-state evidence."""
import json
from pathlib import Path
import sys

import numpy as np
import pytest
from rdkit import Chem
from rdkit.Chem import AllChem

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'domains/chemical/skills/_shared'), str(ROOT / 'domains/chemical/skills/gaussian/scripts')]
from chemical_identity import identity, compare
from path_validation import aligned_rmsd, topology
from reaction_checks import reaction


def conformer(smiles):
    mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
    assert AllChem.EmbedMolecule(mol, randomSeed=719) == 0
    assert AllChem.MMFFOptimizeMolecule(mol, maxIters=1000) == 0
    return mol, [(atom.GetSymbol(), *mol.GetConformer().GetAtomPosition(atom.GetIdx())) for atom in mol.GetAtoms()]


def transform(geometry, matrix, translation=(0., 0., 0.)):
    xyz = np.asarray([atom[1:] for atom in geometry]) @ np.asarray(matrix) + translation
    return [(atom[0], *point) for atom, point in zip(geometry, xyz)]


def test_alignment_uses_proper_rotations_and_accepts_integer_coordinates():
    # Labeled noncoplanar tetrahedron: a reflection cannot be superimposed by rotation.
    geometry = [('C', 0, 0, 0), ('F', 1, 1, 1), ('Cl', 1, -1, -1), ('Br', -1, 1, -1), ('I', -1, -1, 1)]
    rotated = transform(geometry, [[0, -1, 0], [1, 0, 0], [0, 0, 1]], (4., -7., 2.))
    reflected = transform(geometry, np.diag([-1., 1., 1.]))
    assert aligned_rmsd(geometry, rotated) == pytest.approx(0., abs=1e-12)
    assert aligned_rmsd(geometry, reflected) > 1.


def test_chirality_survives_rigid_rotation_but_reflection_inverts_the_endpoint():
    mol, geometry = conformer('C[C@H](CC)CCC')
    expected = topology(mol, geometry)
    assert expected['matches'], expected
    rotated = transform(geometry, [[0, -1, 0], [1, 0, 0], [0, 0, 1]], (7., 5., -4.))
    assert topology(mol, rotated)['matches']
    reflected = topology(mol, transform(geometry, np.diag([-1., 1., 1.])))
    assert not reflected['matches']
    assert reflected['bond_mismatches'] == []
    assert reflected['stereo_mismatches'] == [2]


def test_specified_alkene_stereo_is_checked_from_geometry():
    trans, trans_geometry = conformer('C/C=C/C')
    cis, cis_geometry = conformer('C/C=C\\C')
    assert topology(trans, trans_geometry)['matches']
    assert topology(cis, cis_geometry)['matches']
    wrong = topology(trans, cis_geometry)
    assert not wrong['matches'], 'same bond connectivity does not establish the specified E/Z isomer'
    assert wrong['bond_mismatches'] == []
    assert wrong['bond_stereo_mismatches'] == [[2, 3]]
    # The endpoint check must not invent a stereochemical requirement absent from the graph.
    unspecified = Chem.AddHs(Chem.MolFromSmiles('CC=CC'))
    assert topology(unspecified, trans_geometry)['matches']
    assert topology(unspecified, cis_geometry)['matches']


def test_equivalent_atom_permutations_do_not_change_identity_or_endpoint():
    mol, geometry = conformer('CCO')
    order = list(reversed(range(mol.GetNumAtoms())))
    reordered = Chem.RenumberAtoms(mol, order)
    assert identity(mol) == identity(reordered)
    assert topology(reordered, [geometry[index] for index in order])['matches']
    hydrogen_indices = [atom.GetIdx() for atom in mol.GetAtomWithIdx(0).GetNeighbors() if atom.GetAtomicNum() == 1]
    swapped = list(geometry)
    a, b = hydrogen_indices[:2]
    swapped[a], swapped[b] = swapped[b], swapped[a]
    assert topology(mol, swapped)['matches']


def test_xyz_identity_detects_enantiomer_and_ignores_atom_order(tmp_path):
    mol, geometry = conformer('C[C@H](CC)CCC')
    target = tmp_path / 'target.json'
    target.write_text(json.dumps(identity(mol)))
    actual = tmp_path / 'actual.xyz'
    def write_xyz(atoms):
        actual.write_text(str(len(atoms)) + '\nDeterministic molecular fixture\n' + '\n'.join(
            symbol + ' ' + ' '.join(f'{coordinate:.10f}' for coordinate in xyz) for symbol, *xyz in atoms) + '\n')
    write_xyz(list(reversed(geometry)))
    assert compare(target, actual, actual_format='xyz', charge=0)['status'] == 'match'
    write_xyz(transform(geometry, np.diag([-1., 1., 1.])))
    result = compare(target, actual, actual_format='xyz', charge=0)
    assert result['status'] == 'mismatch'
    assert result['reason'] == 'stereochemistry_differs'


REACTANTS = '[CH2:1]=[CH:2][CH:3]=[CH2:4].[CH2:5]=[CH:6][CH3:7]'
PRODUCT = '[CH2:1]1[CH:2]=[CH:3][CH2:4][CH2:5][CH:6]1[CH3:7]'
TRANSFORMATION = {'kind': 'diels_alder', 'diene': [1, 2, 3, 4], 'dienophile': [5, 6], 'forming_bonds': [[1, 6], [4, 5]]}


def test_symmetry_equivalent_product_does_not_prove_the_declared_atom_trajectory():
    # Reversing unsubstituted butadiene exchanges equivalent termini; the product is the same molecule.
    equivalent = '[CH2:4]1[CH:3]=[CH:2][CH2:1][CH2:5][CH:6]1[CH3:7]'
    assert identity(Chem.MolFromSmiles(PRODUCT)) == identity(Chem.MolFromSmiles(equivalent))
    checked = reaction(REACTANTS + '>>' + equivalent, TRANSFORMATION)
    declared = checked['checks']['declared_transformation']
    assert declared['verdict'] == 'fail', 'explicit atom correspondence must remain strict'
    assert declared['product_graph_matches'] is True
    assert declared['reason'] == 'product_graph_equivalent_but_atom_mapping_differs'
    assert checked['checks']['atom_hydrogen_changes']['verdict'] == 'pass'
    matching_declaration = {**TRANSFORMATION, 'forming_bonds': [[1, 5], [4, 6]]}
    corrected = reaction(REACTANTS + '>>' + equivalent, matching_declaration)
    assert corrected['checks']['declared_transformation']['verdict'] == 'pass'
    assert corrected['checks']['declared_transformation']['product_graph_matches'] is True


def test_graph_equivalence_does_not_hide_wrong_hydrogen_or_bond_correspondence():
    wrong_mapping = '[CH:1]1=[CH:2][CH2:3][CH2:4][CH:5]([CH3:7])[CH2:6]1'
    checked = reaction(REACTANTS + '>>' + wrong_mapping, TRANSFORMATION)
    assert checked['checks']['declared_transformation']['verdict'] == 'fail'
    assert checked['checks']['declared_transformation']['product_graph_matches'] is True
    assert checked['checks']['atom_hydrogen_changes']['verdict'] == 'fail'
    # Move the methyl substituent onto the surviving double bond: a genuinely different constitutional isomer.
    isomer = '[CH2:1]1[C:2]([CH3:7])=[CH:3][CH2:4][CH2:5][CH2:6]1'
    checked = reaction(REACTANTS + '>>' + isomer, TRANSFORMATION)
    assert checked['balanced'] and checked['mapping_valid']
    assert checked['checks']['declared_transformation']['verdict'] == 'fail'
    assert checked['checks']['declared_transformation']['product_graph_matches'] is False
    assert checked['checks']['declared_transformation']['reason'] == 'product_graph_differs'


def test_nonfinite_coordinates_are_input_errors_not_scientific_mismatches():
    mol, geometry = conformer('CCO')
    invalid = list(geometry)
    invalid[0] = ('C', float('nan'), 0., 0.)
    with pytest.raises(ValueError, match='finite'):
        aligned_rmsd(geometry, invalid)
    with pytest.raises(ValueError, match='finite'):
        topology(mol, invalid)
