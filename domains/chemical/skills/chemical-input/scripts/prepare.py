"""Resolve identities, validate graphs, generate seeds, or inspect an explicit reaction map."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys

from rdkit import Chem, rdBase
from rdkit.Chem import AllChem, rdMolDescriptors
from rdkit.Chem.EnumerateStereoisomers import EnumerateStereoisomers, StereoEnumerationOptions
from name_resolution import resolve, resolve_candidates_file
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
from chemical_identity import identity, compare


def inspect(smiles):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError('invalid SMILES')
    stereo = [str(x.type) + ':' + str(x.centeredOn) for x in Chem.FindPotentialStereo(mol)
              if x.specified == Chem.StereoSpecified.Unspecified]
    return mol, {'smiles': Chem.MolToSmiles(mol), 'formula': rdMolDescriptors.CalcMolFormula(mol),
                 'charge': Chem.GetFormalCharge(mol), 'unspecified_stereo': stereo,
                 'rdkit_version': rdBase.rdkitVersion, 'graph_valid': True, 'identity': identity(mol)}


def resolve_name(name, lookup_name=None):
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
                          'sha256': hashlib.sha256(xyz.encode()).hexdigest(), 'identity': identity(isomer)})
    return {'schema_version': 'chemical-seeds/1', **metadata, 'multiplicity': multiplicity,
            'embedding': {'method': 'ETKDGv3', 'random_seed': 61453},
            'seeds': generated, 'geometry_status': 'initial_seed',
            'limitations': ['Embedding is not optimization; conformers and intermolecular approaches require separate exploration.']}


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
from reaction_checks import reaction


def main():
    from cli import parse_arguments
    args = parse_arguments()
    if args.config: os.environ['RESEARCH_AGENT_NAME_RESOLVER_CONFIG'] = args.config
    try:
        if args.command == 'resolve': result = resolve_name(args.name, args.lookup_name)
        elif args.command == 'candidates': result = resolve_candidates_file(args.input)
        elif args.command == 'inspect': result = {'schema_version': 'chemical-structure/1', **inspect(args.smiles)[1], 'identity_status': 'supplied_graph'}
        elif args.command == 'seed': result = seeds(args.smiles, args.charge, args.multiplicity, args.output_dir, args.enumerate_stereo)
        elif args.command == 'compare': result = compare(args.target, args.actual, actual_format=args.actual_format, charge=args.charge)
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
