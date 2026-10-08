"""Resolve identities, validate graphs, generate seeds, or inspect an explicit reaction map."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys

from rdkit import Chem, rdBase
from rdkit.Chem import AllChem, rdMolDescriptors
from rdkit.Chem.EnumerateStereoisomers import EnumerateStereoisomers, StereoEnumerationOptions
from name_resolution import resolve


def inspect(smiles):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError('invalid SMILES')
    stereo = [str(x.type) + ':' + str(x.centeredOn) for x in Chem.FindPotentialStereo(mol)
              if x.specified == Chem.StereoSpecified.Unspecified]
    return mol, {'smiles': Chem.MolToSmiles(mol), 'formula': rdMolDescriptors.CalcMolFormula(mol),
                 'charge': Chem.GetFormalCharge(mol), 'unspecified_stereo': stereo,
                 'rdkit_version': rdBase.rdkitVersion, 'graph_valid': True}


def resolve_name(name, lookup_name=None):
    # This explicit scientific rule is intentionally small and auditable.
    if (lookup_name or name).strip().casefold() in {'water', 'h2o', '水', '水分子'}:
        _, data = inspect('O')
        return {'schema_version': 'chemical-input/1', 'data': {'name': name, 'lookup_name': lookup_name or name,
                'status': 'resolved', 'candidates': [dict(data, canonical_smiles='O', source='builtin')],
                'resolver_provenance': {'implementation': 'tspi-known-species', 'version': '1', 'rule': 'neutral-water'}},
                'diagnostics': [], 'verdict': 'valid'}
    return resolve({}, {'name': name, 'lookup_name': lookup_name or name})


def seeds(smiles, charge, multiplicity, output, enumerate_stereo=False):
    mol, metadata = inspect(smiles)
    if len(Chem.GetMolFrags(mol)) != 1:
        raise ValueError('seed expects one connected species; prepare fragments separately')
    if metadata['charge'] != charge:
        raise ValueError('declared charge differs from SMILES')
    if metadata['unspecified_stereo'] and not enumerate_stereo:
        raise ValueError('unspecified stereochemistry: select an isomer or use --enumerate-stereo to study alternatives')
    options = StereoEnumerationOptions(onlyUnassigned=True, unique=True, maxIsomers=17)
    isomers = list(EnumerateStereoisomers(mol, options=options)) if enumerate_stereo else [mol]
    if len(isomers) > 16:
        raise ValueError('more than 16 stereoisomers; narrow the scientific scope')
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('seed output directory must be empty')
    generated = []
    for index, isomer in enumerate(isomers):
        structure = Chem.AddHs(isomer)
        electrons = sum(atom.GetAtomicNum() for atom in structure.GetAtoms()) - charge
        if multiplicity < 1 or multiplicity - 1 > electrons or (electrons - (multiplicity - 1)) % 2:
            raise ValueError('multiplicity is incompatible with electron count')
        settings = AllChem.ETKDGv3(); settings.randomSeed = 61453
        if AllChem.EmbedMolecule(structure, settings) != 0:
            raise ValueError('3D embedding failed')
        xyz = Chem.MolToXYZBlock(structure)
        path = output / f'seed-{index + 1}.xyz'; path.write_text(xyz)
        generated.append({'smiles': Chem.MolToSmiles(isomer), 'xyz': str(path.resolve()),
                          'sha256': hashlib.sha256(xyz.encode()).hexdigest()})
    return {'schema_version': 'chemical-seeds/1', **metadata, 'multiplicity': multiplicity,
            'seeds': generated, 'geometry_status': 'initial_seed',
            'limitations': ['Embedding is not optimization; conformers and intermolecular approaches require separate exploration.']}


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
from reaction_checks import reaction


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', help='Absolute installation name-resolver TOML')
    parser.add_argument('--output', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    names = sub.add_parser('resolve'); names.add_argument('--name', required=True); names.add_argument('--lookup-name')
    check = sub.add_parser('inspect'); check.add_argument('--smiles', required=True)
    seed = sub.add_parser('seed'); seed.add_argument('--smiles', required=True)
    seed.add_argument('--charge', type=int, required=True); seed.add_argument('--multiplicity', type=int, required=True)
    seed.add_argument('--output-dir', type=Path, required=True); seed.add_argument('--enumerate-stereo', action='store_true')
    mapping = sub.add_parser('reaction'); mapping.add_argument('--smiles', required=True)
    mapping.add_argument('--transformation', type=Path, help='JSON declaring diels_alder or explicit bond/hydrogen changes')
    args = parser.parse_args()
    if args.config: os.environ['TSPI_NAME_RESOLVER_CONFIG'] = args.config
    try:
        if args.command == 'resolve': result = resolve_name(args.name, args.lookup_name)
        elif args.command == 'inspect': result = {'schema_version': 'chemical-structure/1', **inspect(args.smiles)[1], 'identity_status': 'supplied_graph'}
        elif args.command == 'seed': result = seeds(args.smiles, args.charge, args.multiplicity, args.output_dir, args.enumerate_stereo)
        else: result = reaction(args.smiles, json.loads(args.transformation.read_text()) if args.transformation else None)
        path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
        print(json.dumps({'output': str(path.resolve()), 'result': result}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
