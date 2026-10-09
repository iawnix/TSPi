"""Prepare bounded mapped DA QST2 candidates or bidirectional IRC inputs; never submit Jobs."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

import numpy as np
from rdkit import Chem, rdBase
from rdkit.Chem import AllChem, rdMolTransforms
from rdkit.Chem.EnumerateStereoisomers import EnumerateStereoisomers, StereoEnumerationOptions

SHARED = Path(__file__).resolve().parents[2] / '_shared'
sys.path.insert(0, str(SHARED))
from reaction_checks import ordered_molecule, path_spec


def digest(path):
    return 'sha256:' + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def directory(path):
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    if any(path.iterdir()):
        raise ValueError('output directory must be empty')
    return path


def embed(mol, seed):
    result = Chem.Mol(mol)
    parameters = AllChem.ETKDGv3(); parameters.randomSeed = seed
    if AllChem.EmbedMolecule(result, parameters) != 0:
        raise ValueError('RDKit failed to embed this candidate branch')
    if AllChem.UFFHasAllMoleculeParams(result):
        AllChem.UFFOptimizeMolecule(result, maxIters=300)
    return result


def align(source, target):
    left, right = source.mean(axis=0), target.mean(axis=0)
    u, _, vt = np.linalg.svd((source-left).T @ (target-right))
    correction = np.eye(3); correction[-1, -1] = np.linalg.det(u @ vt)
    return u @ correction @ vt, left, right


def coordinates(mol):
    return np.asarray(mol.GetConformer().GetPositions(), dtype=float)


def render(mol, xyz):
    return '\n'.join(f'{atom.GetSymbol():2s} {row[0]: .10f} {row[1]: .10f} {row[2]: .10f}'
                     for atom, row in zip(mol.GetAtoms(), xyz))


def header(spec, checkpoint, route, old=None):
    return ((f'%oldchk={old}\n' if old else '') +
            f'%chk={checkpoint}\n%nprocshared={spec["threads"]}\n%mem={spec["memory_mb"]}MB\n'
            f'#p {spec["method"]}/{spec["basis"]} {route}\n\n')


def prepare_candidates(spec_file, output, conformers=1, enumerate_stereo=False):
    if not 1 <= conformers <= 8:
        raise ValueError('conformers must be between 1 and 8')
    spec_file = Path(spec_file).resolve(); spec = json.loads(spec_file.read_text())
    checks, sides = path_spec(spec)
    if any(str(s.specified) == 'Unspecified' for s in Chem.FindPotentialStereo(sides[0])):
        raise ValueError('specify reactant stereochemistry before candidate generation')
    uncertain = [s for s in Chem.FindPotentialStereo(sides[1]) if str(s.specified) == 'Unspecified']
    if uncertain and not enumerate_stereo:
        raise ValueError('unspecified product stereochemistry: use --enumerate-stereo or a specified product')
    products = list(EnumerateStereoisomers(sides[1], options=StereoEnumerationOptions(onlyUnassigned=True, maxIsomers=16))) if enumerate_stereo else [sides[1]]
    output = directory(output)
    rows = []
    for stereo_index, product in enumerate(products):
        for conformer_index in range(conformers):
            branch = f'candidate-{stereo_index+1}-{conformer_index+1}'
            folder = output/branch; folder.mkdir()
            row = {'id': branch, 'stereo_index': stereo_index, 'conformer_index': conformer_index}
            try:
                local_spec = {**spec, 'mapped_smiles': spec['mapped_smiles'].split('>>')[0]+'>>'+Chem.MolToSmiles(product),
                              'parent_spec_sha256': digest(spec_file)}
                path_spec(local_spec)
                reactant, atom_order = ordered_molecule(sides[0]); product_full, product_order = ordered_molecule(product)
                if atom_order != product_order:
                    raise ValueError('reactant/product atom correspondence differs')
                seed = 17001 + 97*stereo_index + conformer_index
                reactant = embed(reactant, seed); product_geometry = embed(product_full, seed)
                indexes = {a.GetAtomMapNum(): a.GetIdx() for a in reactant.GetAtoms() if a.GetAtomMapNum()}
                d = [indexes[n] for n in spec['transformation']['diene']]
                rdMolTransforms.SetDihedralDeg(reactant.GetConformer(), *d, 0.0)
                rxyz, pxyz = coordinates(reactant), coordinates(product_geometry)
                fragments = Chem.GetMolFrags(reactant)
                for fragment in fragments:
                    heavy = [i for i in fragment if reactant.GetAtomWithIdx(i).GetAtomicNum() > 1]
                    rotation, left, right = align(rxyz[heavy], pxyz[heavy])
                    rxyz[list(fragment)] = (rxyz[list(fragment)]-left) @ rotation+right
                center_a = rxyz[list(fragments[0])].mean(axis=0)
                center_b = rxyz[list(fragments[1])].mean(axis=0)
                axis = center_b-center_a
                if np.linalg.norm(axis) < 1e-8:
                    raise ValueError('cannot determine a fragment separation direction')
                axis /= np.linalg.norm(axis)
                # Bound the initial intermolecular contacts; these are seed geometries, not minima.
                cross = [(i, j) for i in fragments[0] for j in fragments[1]]
                for _ in range(50):
                    if min(np.linalg.norm(rxyz[j]-rxyz[i]) for i, j in cross) >= 2.0:
                        break
                    rxyz[list(fragments[0])] -= 0.05*axis
                    rxyz[list(fragments[1])] += 0.05*axis
                if min(np.linalg.norm(rxyz[j]-rxyz[i]) for i, j in cross) < 2.0:
                    raise ValueError('fragment placement remains overlapping')
                rtext, ptext = render(reactant, rxyz), render(product_geometry, pxyz)
                (folder/'reactants.xyz').write_text(f'{len(rxyz)}\n{branch} reactant complex seed\n{rtext}\n')
                (folder/'product.xyz').write_text(f'{len(pxyz)}\n{branch} product seed\n{ptext}\n')
                write_json(folder/'spec.json', local_spec)
                title_marker = 'TSPiSpec '+digest(folder/'spec.json').removeprefix('sha256:')
                charge = f'{spec["charge"]} {spec["multiplicity"]}'
                route = 'Opt=(QST2,CalcFC,MaxCycles=200) Freq SCF=Tight Int=UltraFine NoSymm'
                (folder/'ts.gjf').write_text(header(spec, 'ts.chk', route)+f'{title_marker}\n{branch} reactants\n\n{charge}\n{rtext}\n\n{title_marker}\n{branch} product\n\n{charge}\n{ptext}\n\n')
                write_json(folder/'atom_order.json', {'schema_version':'chemical-atom-order/1', 'atoms':atom_order})
                row.update(status='prepared', atom_count=len(atom_order), seed=seed,
                           files={name:{'path':str(folder/name), 'sha256':digest(folder/name)} for name in
                                  ('ts.gjf','reactants.xyz','product.xyz','spec.json','atom_order.json')})
            except (ValueError, RuntimeError) as exc:
                row.update(status='failed', error=str(exc))
            rows.append(row)
    result = {'schema_version':'chemical-candidates/1', 'source_spec_sha256':digest(spec_file),
              'strategy':'mapped_da_qst2', 'rdkit_version':rdBase.rdkitVersion, 'script_sha256':digest(__file__), 'candidates':rows, 'mapping_checks':checks,
              'stereo_enumeration_limit':16, 'stereo_limit_reached':len(products)==16,
              'limitations':['Unoptimized endpoint seeds; QST2 convergence is not guaranteed.',
                             'Finite stereoisomer/conformer sample does not establish exhaustive pathway coverage.']}
    write_json(output/'candidates.json',result)
    return result


def prepare_irc(spec_file, checkpoint, output, max_points=80):
    spec_file, checkpoint = Path(spec_file).resolve(), Path(checkpoint).resolve()
    spec = json.loads(spec_file.read_text()); path_spec(spec)
    if not checkpoint.is_file() or checkpoint.stat().st_size == 0:
        raise ValueError('nonempty collected TS checkpoint required')
    if type(max_points) is not int or not 2 <= max_points <= 500:
        raise ValueError('max_points must be between 2 and 500')
    output = directory(output); shutil.copyfile(checkpoint, output/'ts.chk')
    rows=[]
    for direction in ('forward','reverse'):
        name = direction+'.gjf'
        route=f'IRC=({direction.capitalize()},ReadFC,MaxPoints={max_points},StepSize=5) Geom=AllCheck Guess=Read SCF=Tight Int=UltraFine NoSymm'
        (output/name).write_text(header(spec, direction+'.chk',route,old='ts.chk')+'\n')
        rows.append({'direction':direction,'path':str(output/name),'sha256':digest(output/name)})
    result={'schema_version':'chemical-irc-inputs/1','spec_sha256':digest(spec_file),
            'checkpoint':{'path':str(output/'ts.chk'),'sha256':digest(output/'ts.chk')},'inputs':rows,
            'limitations':['The source checkpoint must belong to the validated saddle; preserve its collected Artifact reference.']}
    write_json(output/'irc_inputs.json',result)
    return result


def main():
    from cli import parse_arguments
    a=parse_arguments()
    result=prepare_candidates(a.spec,a.output_dir,a.conformers,a.enumerate_stereo) if a.action=='candidates' else prepare_irc(a.spec,a.checkpoint,a.output_dir,a.max_points)
    print(json.dumps(result,allow_nan=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
