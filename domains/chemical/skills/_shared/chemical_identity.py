"""Versioned molecular identities and scoped comparisons, independent of Memory."""
import hashlib
import json
from pathlib import Path
from rdkit import Chem, rdBase
from rdkit.Chem import rdDetermineBonds


def identity(molecule):
    mol = Chem.RemoveHs(Chem.Mol(molecule))
    for atom in mol.GetAtoms():
        atom.SetAtomMapNum(0)
    smiles = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
    value = {'canonical_smiles': smiles, 'charge': Chem.GetFormalCharge(mol),
             'rdkit_version': rdBase.rdkitVersion}
    return {'schema_version': 'chemical-identity/1', **value,
            'identity_id': 'chemical_' + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest(),
            'unspecified_stereo': any(s.specified == Chem.StereoSpecified.Unspecified for s in Chem.FindPotentialStereo(mol))}


def _structure(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError('structure_requires_object')
    value = value.get('identity', value)
    if not isinstance(value, dict):
        raise ValueError('structure_identity_requires_object')
    mol = Chem.MolFromSmiles(value.get('canonical_smiles', value.get('smiles', '')))
    if mol is None or mol.GetNumAtoms() == 0:
        raise ValueError('structure_requires_explicit_smiles')
    actual = identity(mol)
    if value.get('identity_id') and value['identity_id'] != actual['identity_id']:
        raise ValueError('structure_identity_changed_or_incompatible_version')
    return mol


def compare(target, actual, *, actual_format='structure', charge=None):
    result = {'schema_version': 'chemical-identity-check/1', 'status': 'indeterminate',
              'scope': 'Molecular graph, charge, isotope and specified stereochemistry; not mechanism or energy validation',
              'sources': {role: {'sha256': 'sha256:' + hashlib.sha256(Path(path).read_bytes()).hexdigest()}
                          for role, path in [('target', target), ('actual', actual)]}}
    try:
        expected = _structure(target)
        result['target'] = identity(expected)
        if actual_format == 'xyz':
            if charge is None:
                raise ValueError('actual_charge_required_for_xyz')
            observed = Chem.MolFromXYZBlock(Path(actual).read_text())
            if observed is None:
                raise ValueError('xyz_unreadable')
            # Inference is explicit: XYZ does not itself contain bond orders.
            rdDetermineBonds.DetermineBonds(observed, charge=charge)
            result['inference'] = {'method': 'rdkit.DetermineBonds', 'rdkit_version': rdBase.rdkitVersion,
                                   'charge': charge, 'limitation': 'Bond orders inferred from geometry; review ambiguous chemistry'}
        elif actual_format == 'structure':
            observed = _structure(actual)
        else:
            raise ValueError('actual_format_invalid')
        result['actual'] = identity(observed)
        expected = Chem.RemoveHs(expected); observed = Chem.RemoveHs(observed)
        for mol in (expected, observed):
            for atom in mol.GetAtoms(): atom.SetAtomMapNum(0)
        a, b = Chem.Mol(expected), Chem.Mol(observed)
        Chem.RemoveStereochemistry(a); Chem.RemoveStereochemistry(b)
        if Chem.MolToSmiles(a) != Chem.MolToSmiles(b):
            result.update(status='mismatch', reason='molecular_graph_differs')
        elif result['target']['unspecified_stereo'] or result['actual']['unspecified_stereo']:
            result.update(reason='stereochemistry_not_fully_specified', graph_matches=True)
        elif result['target']['canonical_smiles'] != result['actual']['canonical_smiles']:
            result.update(status='mismatch', reason='stereochemistry_differs')
        else:
            result.update(status='match', graph_matches=True)
    except (ValueError, RuntimeError, KeyError, TypeError) as exc:
        result.update(reason=str(exc), exception_type=type(exc).__name__)
    return result
