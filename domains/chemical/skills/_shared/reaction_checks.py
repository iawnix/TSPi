"""Scoped checks for explicit reaction correspondences; no mechanistic inference."""
from collections import Counter
import re

from rdkit import Chem


def molecules(smiles):
    parts = smiles.split('>>')
    if len(parts) != 2:
        raise ValueError('use reactants>>products with explicit atom-map numbers')
    sides = [Chem.MolFromSmiles(part) for part in parts]
    if any(mol is None for mol in sides):
        raise ValueError('invalid reaction SMILES')
    for mol in sides:
        ids = [a.GetAtomMapNum() for a in mol.GetAtoms()]
        if any(n <= 0 for n in ids) or len(ids) != len(set(ids)):
            raise ValueError('every explicit atom needs a unique positive map number on each side')
    return sides


def bonds(mol):
    return {tuple(sorted((b.GetBeginAtom().GetAtomMapNum(), b.GetEndAtom().GetAtomMapNum()))):
            b.GetBondTypeAsDouble() for b in mol.GetBonds()}


def ordered_molecule(mol):
    """Stable heavy/explicit atom map order, then H by parent map and local ordinal."""
    full = Chem.AddHs(mol)
    keys = []
    counters = Counter()
    for atom in full.GetAtoms():
        if atom.GetAtomMapNum():
            key = (0, atom.GetAtomMapNum(), 0)
        else:
            if atom.GetAtomicNum() != 1 or atom.GetDegree() != 1:
                raise ValueError('only added hydrogen atoms may lack map numbers')
            parent = atom.GetNeighbors()[0].GetAtomMapNum()
            counters[parent] += 1
            key = (1, parent, counters[parent])
        keys.append(key)
    order = sorted(range(len(keys)), key=lambda i: keys[i])
    return Chem.RenumberAtoms(full, order), [list(keys[i]) for i in order]


def expected_da(transformation):
    d = transformation.get('diene', [])
    e = transformation.get('dienophile', [])
    if len(d) != 4 or len(e) != 2 or any(type(x) is not int or x < 1 for x in d + e) or len(set(d + e)) != 6:
        raise ValueError('diels_alder requires six distinct diene/dienophile atom-map IDs')
    formed = transformation.get('forming_bonds', [])
    valid = [{tuple(sorted((d[0], e[0]))), tuple(sorted((d[3], e[1])))},
             {tuple(sorted((d[0], e[1]))), tuple(sorted((d[3], e[0])))}]
    if not isinstance(formed, list) or len(formed) != 2 or any(not isinstance(p, list) or len(p) != 2 for p in formed):
        raise ValueError('diels_alder requires two explicit forming_bonds')
    pairs = {tuple(sorted(p)) for p in formed}
    if pairs not in valid:
        raise ValueError('forming_bonds must pair opposite diene termini with the two dienophile atoms')
    result = {tuple(sorted((d[0], d[1]))): (2., 1.), tuple(sorted((d[1], d[2]))): (1., 2.),
              tuple(sorted((d[2], d[3]))): (2., 1.), tuple(sorted(e)): (2., 1.)}
    result.update({p: (0., 1.) for p in pairs})
    return result


def reaction(smiles, transformation=None):
    sides = molecules(smiles)
    inventories = [Counter((a.GetSymbol(), a.GetIsotope()) for a in Chem.AddHs(m).GetAtoms()) for m in sides]
    charges = [Chem.GetFormalCharge(m) for m in sides]
    identities = [{a.GetAtomMapNum(): (a.GetSymbol(), a.GetIsotope()) for a in m.GetAtoms()} for m in sides]
    hydrogens = [{a.GetAtomMapNum(): a.GetTotalNumHs(includeNeighbors=True) for a in m.GetAtoms()} for m in sides]
    edges = [bonds(m) for m in sides]
    changes = [{'atoms': list(p), 'before': edges[0].get(p, 0.), 'after': edges[1].get(p, 0.)}
               for p in sorted(set(edges[0]) | set(edges[1])) if edges[0].get(p) != edges[1].get(p)]
    hchanges = [{'atom': n, 'before': hydrogens[0].get(n), 'after': hydrogens[1].get(n)}
                for n in sorted(set(hydrogens[0]) | set(hydrogens[1])) if hydrogens[0].get(n) != hydrogens[1].get(n)]
    mapped = identities[0] == identities[1]
    balanced = inventories[0] == inventories[1] and charges[0] == charges[1]
    checks = {'molecular_graphs': {'verdict': 'pass'},
              'element_charge_balance': {'verdict': 'pass' if balanced else 'fail'},
              'map_identity': {'verdict': 'pass' if mapped else 'fail'},
              'atom_hydrogen_changes': {'verdict': 'not_assessed', 'changes': hchanges},
              'declared_transformation': {'verdict': 'not_assessed'},
              'stereochemical_correspondence': {'verdict': 'not_assessed'}}
    if transformation is not None:
        kind = transformation.get('kind')
        if kind == 'diels_alder':
            expected = expected_da(transformation)
            atoms = {a.GetAtomMapNum(): a for a in sides[0].GetAtoms()}
            active = transformation['diene'] + transformation['dienophile']
            neutral_carbon = all(n in atoms and atoms[n].GetAtomicNum() == 6 and atoms[n].GetFormalCharge() == 0 and not atoms[n].GetIsAromatic() for n in active)
            # Comparing all changed bonds preserves substituent attachment and untouched skeleton.
            actual = {tuple(c['atoms']): (c['before'], c['after']) for c in changes}
            topology = mapped and balanced and neutral_carbon and actual == expected
            checks['declared_transformation'] = {'verdict': 'pass' if topology else 'fail',
                'kind': kind, 'expected_bond_changes': [{'atoms': list(p), 'before': v[0], 'after': v[1]} for p, v in sorted(expected.items())]}
            checks['atom_hydrogen_changes']['verdict'] = 'pass' if mapped and not hchanges else 'fail'
        elif kind == 'explicit':
            expected = transformation.get('bond_changes')
            if not isinstance(expected, list):
                raise ValueError('explicit transformation requires bond_changes')
            canonical = lambda rows: sorted((tuple(sorted(r['atoms'])), r['before'], r['after']) for r in rows)
            checks['declared_transformation'] = {'verdict': 'pass' if mapped and balanced and canonical(changes) == canonical(expected) else 'fail', 'kind': kind}
            expected_h = transformation.get('hydrogen_changes')
            if expected_h is not None:
                checks['atom_hydrogen_changes']['verdict'] = 'pass' if sorted(hchanges, key=lambda r:r['atom']) == sorted(expected_h, key=lambda r:r['atom']) else 'fail'
        else:
            raise ValueError('unsupported declared transformation; use diels_alder or explicit')
    return {'schema_version': 'chemical-reaction/2', 'balanced': balanced, 'mapping_valid': mapped,
            'charges': charges, 'bond_changes': changes, 'hydrogen_changes': hchanges, 'checks': checks,
            'limitations': ['Graph checks do not establish a transition state, IRC connection, or stereochemical mechanism.',
                            'Implicit hydrogen correspondence is counted per mapped atom; individual H transfer needs explicit H maps.']}


def path_spec(value):
    if not isinstance(value, dict) or value.get('schema_version') != 'chemical-path-spec/1':
        raise ValueError('chemical-path-spec/1 required')
    for key in ('method', 'basis'):
        if not isinstance(value.get(key), str) or not re.fullmatch(r'[A-Za-z0-9+*(),._-]+', value[key]):
            raise ValueError('method/basis must be explicit Gaussian route tokens')
    for key in ('charge', 'multiplicity', 'threads', 'memory_mb'):
        if type(value.get(key)) is not int or key != 'charge' and value[key] < 1:
            raise ValueError('explicit charge, multiplicity, threads and memory_mb required')
    if value.get('transformation', {}).get('kind') != 'diels_alder':
        raise ValueError('this candidate path supports a declared diels_alder transformation only')
    checked = reaction(value.get('mapped_smiles', ''), value['transformation'])
    if any(checked['checks'][key]['verdict'] != 'pass' for key in
           ('element_charge_balance', 'map_identity', 'declared_transformation', 'atom_hydrogen_changes')):
        raise ValueError('reaction does not match the declared diels_alder topology and hydrogen correspondence')
    sides = molecules(value['mapped_smiles'])
    if any(Chem.GetFormalCharge(m) != value['charge'] for m in sides):
        raise ValueError('requested charge differs from the molecular graphs')
    if any(a.GetIsotope() or a.GetNumRadicalElectrons() for mol in sides for a in mol.GetAtoms()):
        raise ValueError('first DA candidate path excludes isotope-specific and open-shell structures')
    if value['multiplicity'] != 1:
        raise ValueError('first DA candidate path supports closed-shell singlets only')
    if len(Chem.GetMolFrags(sides[0])) != 2 or len(Chem.GetMolFrags(sides[1])) != 1:
        raise ValueError('first DA candidate path requires two reactant fragments and one product')
    return checked, sides
