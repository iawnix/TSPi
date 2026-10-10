"""Conservative deterministic checks for one explicitly mapped DA path."""
import hashlib
import json
import re
from pathlib import Path

import numpy as np
from rdkit import Chem

from reaction_checks import ordered_molecule, path_spec
from gaussian_io import parse_log, parse_irc_log, select_job_section, final_geometry


def bindings(spec, manifest):
    source = manifest['inputs'][0]
    return {'spec_artifact_id':source['artifact_id'], 'spec_sha256':source['sha256'],
            **{k:spec[k] for k in ('method','basis','charge','multiplicity','threads','memory_mb')}}


def output(checks, binding, scope):
    verdicts=[v['verdict'] for v in checks.values()]
    verdict='fail' if 'fail' in verdicts else 'inconclusive' if any(v!='pass' for v in verdicts) else 'pass'
    scientific = [v['verdict'] for k, v in checks.items() if not k.endswith('specification_binding')]
    return {'schema_version':'validator-output/1','verdict':verdict,'checks':checks,'bindings':binding,'scope':scope,
            'parsing': {'status': 'completed'},
            'scientific_verdict': 'fail' if 'fail' in scientific else 'inconclusive' if any(v != 'pass' for v in scientific) else 'pass'}


def record(value, details=None, missing=False):
    return {'verdict':'pass' if value else 'inconclusive' if missing else 'fail', **({'details':details} if details is not None else {})}


def specification(path, manifest):
    raw=Path(path).read_bytes(); source=manifest['inputs'][0]
    if source['sha256'] != 'sha256:'+hashlib.sha256(raw).hexdigest():
        raise ValueError('bound specification digest differs')
    spec=json.loads(raw); checked,sides=path_spec(spec)
    spec['_bound_spec_sha256']=hashlib.sha256(raw).hexdigest()
    return spec,checked,sides


def specification_markers(text):
    """Read only title lines starting with a known marker, including Gaussian wrapping.

    Never compact the whole log: a truncated digest must not consume unrelated text.
    Older marker names remain readable in historical scientific evidence.
    """
    lines = text.splitlines()
    markers, malformed = [], False
    for index, line in enumerate(lines):
        match = re.match(r'^\s*(?:CoRAgentSpec|CoRAgentSpec)\s+([0-9a-f]+)(.*)$', line)
        if not match:
            if re.match(r'^\s*(?:CoRAgentSpec|CoRAgentSpec)\b', line):
                malformed = True
            continue
        value, tail = match.groups()
        if len(value) < 64 and not tail.strip() and index + 1 < len(lines):
            continuation = re.match(r'^\s+([0-9a-f]+)(?=\s|$)', lines[index + 1])
            if continuation and len(value) + len(continuation[1]) == 64:
                value += continuation[1]
        if len(value) == 64 and (not tail or tail[0].isspace()):
            markers.append(value)
        else:
            malformed = True
    return markers, malformed


def log_checks(path, spec, atoms):
    parsed=parse_log(Path(path)); summary=parsed['summary']
    lines=select_job_section(Path(path).read_text(errors='replace').splitlines())['lines']
    text='\n'.join(lines)
    route=re.sub(r'\s+','',str(summary.get('gaussian_route') or '')).lower()
    token=f'{spec["method"]}/{spec["basis"]}'.lower()
    method=bool(re.search(r'(?<![a-z0-9_.-])'+re.escape(token)+r'(?=$|[^a-z0-9+*(),._-])',route))
    # Whitespace-free routes concatenate adjacent keywords; check route tokens before compaction too.
    method=method or token in [part.lower() for part in str(summary.get('gaussian_route') or '').split()]
    state=re.findall(r'Charge\s*=\s*(-?\d+)\s+Multiplicity\s*=\s*(\d+)',text,re.I)
    processors=re.findall(r'%nproc(?:shared)?\s*=\s*(\d+)',text,re.I) or re.findall(r'Will use up to\s+(\d+)\s+processors',text,re.I)
    memory=re.findall(r'%mem\s*=\s*(\d+)\s*(MB|GB)',text,re.I)
    expected_elements=[a.GetSymbol() for a in atoms.GetAtoms()]
    found=[a[0] for a in parsed['atoms']]
    markers, malformed = specification_markers(text)
    mismatch = any(m != spec.get('_bound_spec_sha256') for m in markers)
    marker_check = record(bool(markers) and not malformed and not mismatch,
                          {'status': 'mismatch' if mismatch else 'unreadable' if malformed else 'matched' if markers else 'missing',
                           'scope': 'Output title cross-check; execution provenance is recorded separately'},
                          missing=not mismatch and (not markers or malformed))
    checks={'specification_binding':marker_check,
            'normal_termination':record(summary['normal_termination'] and not summary['error_termination']),
            'method_basis':record(method),
            'processor_binding':record(bool(processors) and all(int(n)==spec['threads'] for n in processors),missing=not processors),
            'memory_binding':record(bool(memory) and all(int(n)*(1024 if unit.lower()=='gb' else 1)==spec['memory_mb'] for n,unit in memory),missing=not memory),
            'electronic_state':record(bool(state) and all((int(c),int(m))==(spec['charge'],spec['multiplicity']) for c,m in state),missing=not state),
            'atom_order':record(found==expected_elements,{'expected':expected_elements,'actual':found},missing=not found)}
    return parsed,checks,lines


def saddle(spec, sides, path):
    atoms,_=ordered_molecule(sides[0]);parsed,checks,_=log_checks(path,spec,atoms)
    summary=parsed['summary']
    convergence=summary['force_convergence']
    complete_convergence=set(convergence)=={'Maximum Force','RMS Force','Maximum Displacement','RMS Displacement'}
    checks['stationary_point']=record(summary['stationary_point_found'] and summary['final_convergence_satisfied'] and complete_convergence,missing=not complete_convergence)
    negative=[f for f in parsed['frequencies'] if f<0]
    checks['frequency_table_complete']=record(len(parsed['frequencies'])==3*atoms.GetNumAtoms()-6 and np.isfinite(parsed['frequencies']).all(),{'expected':3*atoms.GetNumAtoms()-6,'actual':len(parsed['frequencies'])})
    checks['one_imaginary_frequency']=record(len(negative)==1,{'frequencies_cm-1':parsed['frequencies']},missing=not parsed['frequencies'])
    modes=[m for m in parsed['normal_modes'] if m['frequency_cm-1']<0]
    derivatives=[]
    valid=False
    if len(modes)==1 and len(parsed['atoms'])==atoms.GetNumAtoms():
        vector=np.asarray(modes[0]['displacements'],dtype=float)
        geometry=np.asarray([a[1:] for a in parsed['atoms']],dtype=float)
        norm=np.linalg.norm(vector)
        indexes={a.GetAtomMapNum():a.GetIdx() for a in atoms.GetAtoms() if a.GetAtomMapNum()}
        if norm>0 and modes[0]['atomic_numbers']==[a.GetAtomicNum() for a in atoms.GetAtoms()]:
            for pair in spec['transformation']['forming_bonds']:
                i,j=[indexes[n] for n in pair]; delta=geometry[j]-geometry[i]; distance=np.linalg.norm(delta)
                derivatives.append(float(np.dot(delta/distance,vector[j]-vector[i])/norm) if distance>0 else 0.)
            valid=len(derivatives)==2 and derivatives[0]*derivatives[1]>0 and min(abs(x) for x in derivatives)>=0.02
    checks['forming_bond_mode']=record(valid,{'normalized_distance_derivatives':derivatives,'minimum_absolute_derivative':0.02},missing=not modes)
    return checks,parsed


def topology(mol, geometry):
    """Conservative all-atom connectivity by covalent radii; ambiguous distances never pass."""
    if len(geometry)!=mol.GetNumAtoms() or [a[0] for a in geometry]!=[a.GetSymbol() for a in mol.GetAtoms()]:
        return {'matches':False,'ambiguous':True,'reason':'atom count/order differs'}
    xyz=np.asarray([a[1:] for a in geometry],dtype=float)
    if not np.isfinite(xyz).all():
        raise ValueError('geometry_coordinates_must_be_finite')
    radii=[Chem.GetPeriodicTable().GetRcovalent(a.GetAtomicNum()) for a in mol.GetAtoms()]
    expected={tuple(sorted((b.GetBeginAtomIdx(),b.GetEndAtomIdx()))) for b in mol.GetBonds()}
    deviations=[];ambiguous=False
    for i in range(len(xyz)):
        for j in range(i+1,len(xyz)):
            ratio=float(np.linalg.norm(xyz[j]-xyz[i])/(radii[i]+radii[j]))
            bonded=(i,j) in expected
            if not np.isfinite(ratio) or ratio<0.55 or (bonded and ratio>1.25) or (not bonded and ratio<1.45):
                deviations.append({'atoms':[i+1,j+1],'expected_bond':bonded,'distance_ratio':ratio})
                ambiguous=ambiguous or 1.25<ratio<1.45
    # Assess only stereochemistry explicitly specified in the input graph.
    probe=Chem.Mol(mol);conformer=Chem.Conformer(mol.GetNumAtoms())
    for i,point in enumerate(xyz):conformer.SetAtomPosition(i,point)
    probe.RemoveAllConformers();probe.AddConformer(conformer)
    Chem.AssignStereochemistryFrom3D(probe,replaceExistingTags=True)
    Chem.AssignStereochemistry(probe,cleanIt=True,force=True)
    Chem.AssignStereochemistry(mol,cleanIt=True,force=True)
    stereo=[]
    for original,actual in zip(mol.GetAtoms(),probe.GetAtoms()):
        if original.HasProp('_CIPCode') and (not actual.HasProp('_CIPCode') or original.GetProp('_CIPCode')!=actual.GetProp('_CIPCode')):
            stereo.append(original.GetIdx()+1)
    bond_stereo=[]
    for original,actual in zip(mol.GetBonds(),probe.GetBonds()):
        if original.GetStereo() in (Chem.BondStereo.STEREOE,Chem.BondStereo.STEREOZ) and original.GetStereo()!=actual.GetStereo():
            bond_stereo.append([original.GetBeginAtomIdx()+1,original.GetEndAtomIdx()+1])
    return {'matches':not deviations and not stereo and not bond_stereo,'ambiguous':ambiguous,
            'bond_mismatches':deviations,'stereo_mismatches':stereo,'bond_stereo_mismatches':bond_stereo}


def aligned_rmsd(a,b):
    """Least-squares proper rotation of the supplied atom correspondence; never relabel atoms."""
    if [x[0] for x in a]!=[x[0] for x in b] or not a:return None
    x=np.asarray([v[1:] for v in a],dtype=float);y=np.asarray([v[1:] for v in b],dtype=float)
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('geometry_coordinates_must_be_finite')
    x-=x.mean(axis=0);y-=y.mean(axis=0)
    u,_,vt=np.linalg.svd(x.T@y);fix=np.eye(3);fix[-1,-1]=np.linalg.det(u@vt)
    return float(np.sqrt(np.mean(np.sum((x@u@fix@vt-y)**2,axis=1))))


def _validate(kind, paths, manifest):
    try:
        spec,checked,sides=specification(paths[0],manifest)
    except (ValueError, KeyError) as exc:
        return {'schema_version':'validator-output/1','verdict':'fail','checks':{'specification':record(False,str(exc))},
                'parsing': {'status': 'failed' if isinstance(exc, json.JSONDecodeError) else 'completed'},
                'scientific_verdict': 'not_assessed', 'scope':'declared input specification'}
    binding=bindings(spec,manifest)
    if kind=='mapping':
        names=('molecular_graphs','element_charge_balance','map_identity','atom_hydrogen_changes','declared_transformation')
        return output({n:checked['checks'][n] for n in names},binding,'declared DA topology, preserved skeleton and per-atom H counts; not TS or stereochemical mechanism proof')
    if kind=='saddle':
        checks,_=saddle(spec,sides,paths[1])
        return output(checks,binding,'converged first-order saddle with simultaneous forming-bond displacement; not IRC or mechanism uniqueness')
    if kind!='irc':raise ValueError('unknown validator')
    saddle_checks,reference=saddle(spec,sides,paths[1])
    checks={'saddle_'+k:v for k,v in saddle_checks.items()}
    molecules=[ordered_molecule(m)[0] for m in sides]
    assignments=[]
    for direction,path in zip(('forward','reverse'),paths[2:]):
        parsed,current,lines=log_checks(path,spec,molecules[0]);checks.update({direction+'_'+k:v for k,v in current.items()})
        try:
            irc=parse_irc_log(Path(path));summary=irc['summary']
            checks[direction+'_path_complete']=record(summary['direction']==direction and summary['path_complete_marker'] and not summary['max_points_reached'],summary)
            first_point=next((i for i,line in enumerate(lines) if re.search(r'Point Number:\s*\d+',line)),len(lines))
            starting=final_geometry(lines[:first_point]);rmsd=aligned_rmsd(starting,reference['atoms'])
            checks[direction+'_saddle_origin']=record(rmsd is not None and rmsd<=0.05,{'aligned_rmsd_angstrom':rmsd,'maximum':0.05},missing=rmsd is None)
            matches=[topology(m,irc['atoms']) for m in molecules]
            assigned=[i for i,m in enumerate(matches) if m['matches']]
            assignments.append(assigned[0] if len(assigned)==1 else None)
            checks[direction+'_endpoint_identity']=record(len(assigned)==1,{'reactant':matches[0],'product':matches[1]},missing=any(m.get('ambiguous') for m in matches))
        except (ValueError,KeyError) as exc:
            checks[direction+'_path_complete']=record(False,str(exc),missing=True);assignments.append(None)
    checks['opposite_endpoint_basins']=record(sorted(x for x in assignments if x is not None)==[0,1],{'assignments':assignments})
    return output(checks,binding,'bidirectional completed IRC from the supplied saddle to declared mapped connectivity; excludes bond-order determination and exhaustive pathways')


def validate(kind, paths, manifest):
    try:
        return _validate(kind, paths, manifest)
    except (ValueError, KeyError, IndexError, TypeError, OSError) as exc:
        return {'schema_version': 'validator-output/1', 'verdict': 'inconclusive',
                'scientific_verdict': 'not_assessed', 'checks': {},
                'parsing': {'status': 'failed', 'exception_type': type(exc).__name__, 'reason': str(exc)},
                'scope': 'Input could not be interpreted; no scientific conclusion is established'}


def main(kind, paths):
    manifest=json.loads(Path('validator_inputs.json').read_text())
    expected={'mapping':1,'saddle':2,'irc':4}[kind]
    if len(paths)!=expected or len(manifest.get('inputs',[]))!=expected:
        raise ValueError('validator input roles/count differ')
    result=validate(kind,paths,manifest)
    Path('validator_result.json').write_text(json.dumps(result,sort_keys=True,allow_nan=False)+'\n')
