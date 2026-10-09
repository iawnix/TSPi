"""Actual Job/parser/validator execution with synthetic Gaussian output, never a chemistry calculation."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import time

import numpy as np
import pytest
from rdkit import Chem

ROOT=Path(__file__).resolve().parents[2]
SKILLS=ROOT/'domains/chemical/skills'
sys.path[:0]=[str(SKILLS/'_shared'),str(SKILLS/'gaussian/scripts')]
from reaction_checks import reaction, path_spec, ordered_molecule
from path_validation import validate, topology
from gaussian_io import read_xyz, parse_log
spec=importlib.util.spec_from_file_location('chemical_candidate_path',SKILLS/'candidate-generation/scripts/prepare_path.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)

REACTANTS='[CH2:1]=[CH:2][CH:3]=[CH2:4].[CH2:5]=[CH:6][CH3:7]'
PRODUCT='[CH2:1]1[CH:2]=[CH:3][CH2:4][CH2:5][CH:6]1[CH3:7]'
WRONG='[CH:1]1=[CH:2][CH2:3][CH2:4][CH:5]([CH3:7])[CH2:6]1'
SPEC={'schema_version':'chemical-path-spec/1','mapped_smiles':REACTANTS+'>>'+PRODUCT,
      'transformation':{'kind':'diels_alder','diene':[1,2,3,4],'dienophile':[5,6],'forming_bonds':[[1,6],[4,5]]},
      'method':'M062X','basis':'6-31G**','charge':0,'multiplicity':1,'threads':12,'memory_mb':4000}


def test_t009_same_product_graph_wrong_correspondence_fails_declared_da():
    wrong=reaction(REACTANTS+'>>'+WRONG,SPEC['transformation'])
    assert wrong['balanced'] and wrong['mapping_valid']
    assert 'validated' not in wrong
    assert wrong['checks']['declared_transformation']['verdict']=='fail'
    assert wrong['checks']['atom_hydrogen_changes']['verdict']=='fail'
    assert {r['atom'] for r in wrong['hydrogen_changes']}=={1,3,5,6}
    good=reaction(SPEC['mapped_smiles'],SPEC['transformation'])
    assert good['checks']['declared_transformation']['verdict']=='pass'
    assert good['checks']['atom_hydrogen_changes']['verdict']=='pass'
    assert reaction(SPEC['mapped_smiles'])['checks']['declared_transformation']['verdict']=='not_assessed'
    # Generic transformations must not universally forbid hydrogen changes.
    proton='[OH2:1].[NH3:2]>>[OH-:1].[NH4+:2]'
    expected={'kind':'explicit','bond_changes':[], 'hydrogen_changes':[{'atom':1,'before':2,'after':1},{'atom':2,'before':3,'after':4}]}
    assert reaction(proton,expected)['checks']['atom_hydrogen_changes']['verdict']=='pass'


def candidate(tmp_path, conformers=1):
    source=tmp_path/'spec.json';source.write_text(json.dumps(SPEC))
    result=helper.prepare_candidates(source,tmp_path/'candidates',conformers,True)
    assert all(row['status']=='prepared' for row in result['candidates']),result
    return result,result['candidates'][0]


def test_candidates_are_reproducible_bound_ordered_inputs_and_keep_branches(tmp_path):
    for name in ('first','second'):(tmp_path/name).mkdir()
    first,a=candidate(tmp_path/'first',2);second,b=candidate(tmp_path/'second',2)
    assert len(first['candidates'])==4
    assert a['files']['ts.gjf']['sha256']==b['files']['ts.gjf']['sha256']
    assert len({r['files']['product.xyz']['sha256'] for r in first['candidates']})==4
    from input_job import inspect_input
    for row in first['candidates']:
        path=Path(row['files']['ts.gjf']['path'])
        assert 'QST2' in inspect_input(path,'M062X','6-31G**',0,1,12,4000)['routes'][0]
        molecule=path_spec(json.loads(Path(row['files']['spec.json']['path']).read_text()))[1][0]
        assert len(json.loads(Path(row['files']['atom_order.json']['path']).read_text())['atoms'])==Chem.AddHs(molecule).GetNumAtoms()
    bad=copy.deepcopy(SPEC);bad['mapped_smiles']=REACTANTS+'>>'+WRONG
    (tmp_path/'bad.json').write_text(json.dumps(bad))
    with pytest.raises(ValueError,match='topology'):
        helper.prepare_candidates(tmp_path/'bad.json',tmp_path/'bad')
    assert not (tmp_path/'bad').exists()


def orientation(atoms):
    lines=[' Standard orientation:', ' ---------------------------------------------------------------------',
           ' Center Atomic Atomic Coordinates (Angstroms)', ' Number Number Type X Y Z',
           ' ---------------------------------------------------------------------']
    for i,(symbol,*coords) in enumerate(atoms,1):
        lines.append(f' {i} {Chem.GetPeriodicTable().GetAtomicNumber(symbol)} 0 '+ ' '.join(f'{x:.9f}' for x in coords))
    return '\n'.join(lines+[' ---------------------------------------------------------------------'])


def synthetic_logs(row):
    """Parser fixtures only: midpoint geometry and interpolated mode are not a computed TS."""
    _,_,reactants=read_xyz(Path(row['files']['reactants.xyz']['path']))
    _,_,product=read_xyz(Path(row['files']['product.xyz']['path']))
    # Separate the asymptotic fixture reactants enough for conservative basin classification.
    spec=json.loads(Path(row['files']['spec.json']['path']).read_text())
    _,sides=path_spec(spec);mol,_=ordered_molecule(sides[0]);xyz=np.array([a[1:] for a in reactants])
    fragments=Chem.GetMolFrags(mol);xyz[list(fragments[1])]+=np.array([0.,0.,8.])
    endpoint_reactants=[(a[0],*p) for a,p in zip(reactants,xyz)]
    r=np.array([a[1:] for a in reactants]);p=np.array([a[1:] for a in product]);middle=(r+p)/2
    saddle=[(a[0],*v) for a,v in zip(reactants,middle)]
    vector=p-r;vector/=np.linalg.norm(vector)
    title=' SYNTHETIC FIXTURE: exercises parser and runtime, not physical chemistry\n %nprocshared=12\n %mem=4000MB\n ResearchAgentSpec '+hashlib.sha256(Path(row['files']['spec.json']['path']).read_bytes()).hexdigest()+'\n'
    route=Path(row['files']['ts.gjf']['path']).read_text().splitlines()[3]
    log=title+route+'\n ----------------\n Charge = 0 Multiplicity = 1\n'+orientation(saddle)+'\n SCF Done: E(RM062X) = -270.0 A.U.\n'
    log+=' Maximum Force 0.00001 0.00045 YES\n RMS     Force 0.00001 0.00030 YES\n Maximum Displacement 0.00001 0.0018 YES\n RMS     Displacement 0.00001 0.0012 YES\n Stationary point found.\n Harmonic frequencies\n'
    for start in range(0,3*len(saddle)-6,3):
        fs=[-200.0 if start+i==0 else 100.+start+i for i in range(3)]
        log+=' Frequencies -- '+ ' '.join(map(str,fs))+'\n Red. masses -- 1.0 1.0 1.0\n Atom  AN      X Y Z        X Y Z        X Y Z\n'
        for index,(symbol,*_) in enumerate(saddle):
            values=list(vector[index]) if start==0 else [0.,0.,0.]
            log+=f' {index+1} {Chem.GetPeriodicTable().GetAtomicNumber(symbol)} '+' '.join(f'{x:.9f}' for x in values+[0.]*6)+'\n'
    log+=' Thermochemistry\n Normal termination of Gaussian\n'
    result={'ts':log}
    for direction,endpoint in [('forward',product),('reverse',endpoint_reactants)]:
        route=f'#p M062X/6-31G** IRC=({direction.capitalize()},ReadFC,MaxPoints=80,StepSize=5) Geom=AllCheck Guess=Read SCF=Tight Int=UltraFine NoSymm'
        text=title+route+'\n ----------------\n Charge = 0 Multiplicity = 1\n'+orientation(saddle)+'\n'
        text+=f' Point Number 1 in {direction.upper()} path direction\n SCF Done: E(RM062X) = -270.1 A.U.\n Point Number: 1 Path Number: 1\n CURRENT STRUCTURE\n'
        for i,(symbol,*coords) in enumerate(endpoint,1):text+=f' {i} {Chem.GetPeriodicTable().GetAtomicNumber(symbol)} '+' '.join(f'{x:.9f}' for x in coords)+'\n'
        text+=f' NET REACTION COORDINATE UP TO THIS POINT = 1.0\n Calculation of {direction.upper()} path complete.\n Normal termination of Gaussian\n'
        result[direction]=text
    return spec,result


def direct_validate(tmp_path, row, kind, texts):
    spec_path=Path(row['files']['spec.json']['path'])
    paths=[spec_path]
    for i,text in enumerate(texts):
        path=tmp_path/f'log-{i}.out';path.write_text(text);paths.append(path)
    manifest={'inputs':[{'artifact_id':'art_spec','sha256':'sha256:'+hashlib.sha256(spec_path.read_bytes()).hexdigest()}]}
    return validate(kind,paths,manifest)


def test_scientific_checks_reject_method_mode_missing_origin_and_wrong_endpoint(tmp_path):
    _,row=candidate(tmp_path);spec,logs=synthetic_logs(row)
    passed=direct_validate(tmp_path,row,'saddle',[logs['ts']])
    assert passed['verdict']=='pass',passed
    assert direct_validate(tmp_path,row,'saddle',[logs['ts'].replace('M062X/6-31G**','HF/6-31G**')])['verdict']=='fail'
    assert direct_validate(tmp_path,row,'saddle',[logs['ts'].replace('%nprocshared=12','%nprocshared=1')])['verdict']=='fail'
    assert direct_validate(tmp_path,row,'saddle',[logs['ts'].replace('%mem=4000MB','%mem=1000MB')])['verdict']=='fail'
    assert direct_validate(tmp_path,row,'saddle',[logs['ts'].replace('ResearchAgentSpec ', 'UnknownSpec ')])['verdict']!='pass'
    wrong_mode=logs['ts'].replace('Frequencies -- -200.0','Frequencies -- 200.0')
    assert direct_validate(tmp_path,row,'saddle',[wrong_mode])['verdict']=='fail'
    spectator=logs['ts']
    rows=spectator.splitlines();header=next(i for i,line in enumerate(rows) if 'Atom  AN' in line)
    atom_count=len(parse_log(Path(tmp_path/'log-0.out'))['atoms'])
    for index in range(header+1,header+1+atom_count):
        fields=rows[index].split()
        # Move only the last hydrogen; preserve exactly one imaginary frequency.
        fields[2:5]=['0.0','0.0','1.0' if index==header+atom_count else '0.0']
        rows[index]=' '.join(fields)
    spectator='\n'.join(rows)+'\n'
    rejected=direct_validate(tmp_path,row,'saddle',[spectator])
    assert rejected['checks']['one_imaginary_frequency']['verdict']=='pass'
    assert rejected['checks']['forming_bond_mode']['verdict']=='fail'
    partial=re.sub(r'^.*RMS     Displacement.*\n','',logs['ts'],flags=re.M)
    assert direct_validate(tmp_path,row,'saddle',[partial])['verdict']!='pass'
    assert direct_validate(tmp_path,row,'saddle',[logs['ts'].replace('Frequencies -- -200.0 101.0','Frequencies -- -200.0 nan')])['verdict']!='pass'
    # Select only the final harmonic table, even after a passing earlier table.
    final_positive=logs['ts'].split(' Thermochemistry')[0]+'\n Harmonic frequencies\n'+wrong_mode.split(' Harmonic frequencies\n')[1]
    assert direct_validate(tmp_path,row,'saddle',[final_positive])['verdict']=='fail'
    connected=direct_validate(tmp_path,row,'irc',[logs['ts'],logs['forward'],logs['reverse']])
    assert connected['verdict']=='pass',connected
    incomplete=logs['forward'].replace('Calculation of FORWARD path complete.','Maximum points reached.')
    assert direct_validate(tmp_path,row,'irc',[logs['ts'],incomplete,logs['reverse']])['verdict']!='pass'
    wrong_basin=logs['forward'].replace('FORWARD','REVERSE').replace('Forward','Reverse')
    assert direct_validate(tmp_path,row,'irc',[logs['ts'],logs['forward'],wrong_basin])['verdict']!='pass'
    source=tmp_path/'origin.out';source.write_text(logs['forward']);atoms=parse_log(source)['atoms']
    changed=list(atoms);symbol,x,y,z=changed[0];changed[0]=(symbol,x+1.,y,z)
    wrong_origin=logs['forward'].replace(orientation(atoms),orientation(changed))
    rejected=direct_validate(tmp_path,row,'irc',[logs['ts'],wrong_origin,logs['reverse']])
    assert rejected['checks']['forward_saddle_origin']['verdict']=='fail'
    missing_origin=logs['forward'].replace(orientation(atoms),'')
    assert direct_validate(tmp_path,row,'irc',[logs['ts'],missing_origin,logs['reverse']])['verdict']!='pass'


def run_job(root, params):
    from research_agent.application.execution import dispatch
    job=dispatch('start',{'root':str(root),'timeout_seconds':20,**params})
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        status=dispatch('status',{'root':str(root),'job_id':job['job_id']})
        if status['state'] in {'succeeded','failed','cancelled','timed_out'}:break
        time.sleep(.02)
    else:
        dispatch('cancel',{'root':str(root),'job_id':job['job_id']});raise AssertionError('fixture Job timed out')
    result=dispatch('collect',{'root':str(root),'job_id':job['job_id']})
    assert status['state']=='succeeded',(result,Path(result['stderr']).read_text() if result.get('stderr') else '')
    return result


def selected(result, suffix):
    return next(a for a in result['artifacts'] if a['provenance']['source_path'].endswith(suffix))


@pytest.mark.parametrize('destinations', [
    ['./validator_inputs.json'], ['validator_result.json'], ['./spec.json'],
    ['logs/stdout.log'], ['module.py', './module.py'], ['library', 'library/module.py'],
])
def test_registered_validator_rejects_resource_target_collisions(tmp_path, monkeypatch, destinations):
    from tests.unit.test_job_recovery import workspace
    from research_agent.application.validators import prepare
    workspace(tmp_path)
    package=tmp_path/'package';domain=package/'domains'/'fixture';domain.mkdir(parents=True)
    script=domain/'validator.py';script.write_text('print("fixture")\n')
    digest='sha256:'+hashlib.sha256(script.read_bytes()).hexdigest()
    descriptor={'id':'fixture.validator','version':'1','entry':'validator.py','sha256':digest,'backend':'validation',
                'resources':{name:{'path':'validator.py','sha256':digest} for name in destinations}}
    (domain/'execution.json').write_text(json.dumps({'schema_version':'research-agent-execution/1','name':'fixture','version':'1.0.0','executors':[],'validators':[descriptor],'acceptance_profiles':[]}))
    (package/'package.json').write_text(json.dumps({'researchAgent':{'execution':['domains/fixture/execution.json']}}))
    monkeypatch.setenv('RESEARCH_AGENT_PACKAGE_ROOT',str(package))
    with pytest.raises(ValueError,match='execution_(resource_path_invalid|destinations_overlap_or_reserved)'):
        prepare(tmp_path,{'validator_id':'fixture.validator', "validator_version": "1",'input_artifact_ids':['art_unused']})


def test_generic_jobs_execute_candidate_gaussian_and_registered_validators(tmp_path):
    from tests.unit.test_job_recovery import workspace
    from research_agent.application.evidence import dispatch as artifact
    from research_agent.application.validators import prepare
    workspace(tmp_path)
    _,row=candidate(tmp_path);spec,logs=synthetic_logs(row)
    spec_record=artifact('register',{'root':str(tmp_path),'path':row['files']['spec.json']['path']})
    ref=spec_record['artifact_id']
    mapping=run_job(tmp_path,{'job_id':'job_mapping','validator_id':'chemical.reaction_mapping', "validator_version": "1",'input_artifact_ids':[ref]})
    assert mapping['result_receipt']['validator_result']['verdict']=='pass'
    assert mapping['result_receipt']['validator_result']['bindings']['spec_artifact_id']==ref
    with pytest.raises(ValueError,match='collected_output'):
        prepare(tmp_path,{'validator_id':'chemical.gaussian_frequency', "validator_version": "1",'input_artifact_ids':[ref]})
    fixture=tmp_path/'fixture_solver.py'
    fixture.write_text(f'#!{sys.executable}\nimport sys,json\nfrom pathlib import Path\nlogs=json.loads({json.dumps(json.dumps(logs))})\ntext=sys.stdin.read()\nkey="forward" if "IRC=(Forward" in text else "reverse" if "IRC=(Reverse" in text else "ts"\nPath(key+".chk").write_bytes(b"synthetic fixture checkpoint")\nprint(logs[key])\n')
    fixture.chmod(0o755)
    def gaussian(gjf,job_id,validation,checkpoint=None):
        inputs=[{'source':str(SKILLS/'gaussian/scripts'),'destination':'skills/gaussian/scripts'},
                {'source':str(SKILLS/'_shared'),'destination':'skills/_shared'},
                {'source':str(gjf),'destination':'input.gjf'}, {'source':str(fixture),'destination':'fixture_solver.py'}]
        if checkpoint:inputs.append({'source':str(checkpoint),'destination':'ts.chk'})
        command=[sys.executable,'skills/gaussian/scripts/run.py','--input-gjf','input.gjf','--executable',str(fixture),
                 '--output-dir','results','--method','M062X','--basis','6-31G**','--threads','12','--memory-mb','4000','--validation',validation]
        outputs=[{'path':'results/'+name,'required':True} for name in ['gaussian.out','parsed.json','result.json']+(['ts.chk'] if validation=='saddle' else ['irc_path_summary.json','gaussian_endpoint.xyz'])]
        return run_job(tmp_path,{'job_id':job_id,'command':command,'inputs':inputs,'outputs':outputs})
    ts=gaussian(row['files']['ts.gjf']['path'],'job_ts','saddle')
    raw=selected(ts,'gaussian.out')['artifact_id']
    validated=run_job(tmp_path,{'job_id':'job_saddle','validator_id':'chemical.gaussian_saddle', "validator_version": "1",'input_artifact_ids':[ref,raw]})
    assert validated['result_receipt']['validator_result']['verdict']=='pass'
    checkpoint=selected(ts,'ts.chk')
    irc=helper.prepare_irc(Path(row['files']['spec.json']['path']),Path(checkpoint['location']),tmp_path/'irc')
    forwards=gaussian(irc['inputs'][0]['path'],'job_forward','irc',irc['checkpoint']['path'])
    reverse=gaussian(irc['inputs'][1]['path'],'job_reverse','irc',irc['checkpoint']['path'])
    joined=run_job(tmp_path,{'job_id':'job_connectivity','validator_id':'chemical.gaussian_irc_connectivity', "validator_version": "1",
        'input_artifact_ids':[ref,raw,selected(forwards,'gaussian.out')['artifact_id'],selected(reverse,'gaussian.out')['artifact_id']]})
    proof=joined['result_receipt']['validator_result']
    assert proof['verdict']=='pass',proof
    assert proof['bindings']['method']=='M062X'
    assert set(proof['input_result_versions'])=={ts['result_receipt']['job_id'],forwards['result_receipt']['job_id'],reverse['result_receipt']['job_id']}
    # Registered source bytes cannot be modified behind the bound Artifact manifest.
    Path(spec_record['location']).write_text('{}')
    with pytest.raises(ValueError,match='digest_mismatch'):
        prepare(tmp_path,{'validator_id':'chemical.reaction_mapping', "validator_version": "1",'input_artifact_ids':[ref]})
