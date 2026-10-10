"""Synthetic identity and parser regressions; no workspace research data."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from rdkit import Chem
from rdkit.Chem import AllChem
import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / 'domains/chemical/skills'
sys.path[:0] = [str(SKILLS / '_shared'), str(SKILLS / 'gaussian/scripts')]
from chemical_identity import identity, compare
from path_validation import specification_markers, validate


def structure(path, smiles):
    path.write_text(json.dumps(identity(Chem.MolFromSmiles(smiles))))
    return path


def test_positional_isomers_differ_but_atom_order_does_not(tmp_path):
    target = structure(tmp_path / 'target.json', 'CC1CCC=CC1')
    wrong = structure(tmp_path / 'actual.json', 'CC1=CCCCC1')
    assert compare(target, wrong)['status'] == 'mismatch'
    mol = Chem.MolFromSmiles('CC1CCC=CC1')
    reordered = Chem.RenumberAtoms(mol, list(reversed(range(mol.GetNumAtoms()))))
    assert identity(mol) == identity(reordered)
    wrong.write_text(json.dumps(identity(reordered)))
    # The target has unresolved stereochemistry; graph agreement is not full identity.
    checked = compare(target, wrong)
    assert checked.get('graph_matches') and checked['status'] in {'match', 'indeterminate'}


def test_geometry_identity_is_explicit_inference_and_rejects_wrong_isomer(tmp_path):
    target = structure(tmp_path / 'target.json', 'CC1CCC=CC1')
    mol = Chem.AddHs(Chem.MolFromSmiles('CC1=CCCCC1'))
    assert AllChem.EmbedMolecule(mol, randomSeed=971) == 0
    actual = tmp_path / 'actual.xyz'; actual.write_text(Chem.MolToXYZBlock(mol))
    assert compare(target, actual, actual_format='xyz')['status'] == 'indeterminate'
    result = compare(target, actual, actual_format='xyz', charge=0)
    assert result['status'] == 'mismatch' and result['inference']['charge'] == 0


@pytest.mark.parametrize('marker', ['CoRAgentSpec', 'CoRAgentSpec'])
def test_wrapped_title_digest_is_bounded(marker):
    digest = '1234567890abcdef' * 4
    cut = 70 - len(marker) - 1
    text = f' {marker} {digest[:cut]}\n {digest[cut:]} candidate reactants\n'
    assert specification_markers(text) == ([digest], False)
    assert specification_markers(f'{marker} {digest}\n') == ([digest], False)
    assert specification_markers(f'archive|{marker} {digest}\n') == ([], False)
    assert specification_markers(f'{marker} {digest[:cut]}\n Normal termination\n')[1]
    assert specification_markers(f'{marker} {digest}a\n')[1]
    assert specification_markers(f'{marker} unreadable\n') == ([], True)


def test_unreadable_input_is_not_a_scientific_failure(tmp_path):
    # A missing input is a parser/input failure, never evidence against a hypothesis.
    result = validate('saddle', [tmp_path / 'missing.json'], {'inputs': [{'sha256': 'sha256:missing'}]})
    assert result['verdict'] == 'inconclusive'
    assert result['scientific_verdict'] == 'not_assessed'
    assert result['parsing']['status'] == 'failed'


def test_managed_doctor_imports_staged_shared_modules_without_pythonpath(tmp_path):
    job = tmp_path / 'staged'; job.mkdir()
    shutil.copytree(SKILLS / 'cf22d/scripts', job / 'skills/cf22d/scripts')
    shutil.copytree(SKILLS / '_shared', job / 'skills/_shared')
    launcher = ROOT / 'backend/src/research_agent/jobs/python_entrypoint.py'
    env = {k: v for k, v in os.environ.items() if k not in {'PYTHONPATH', 'PYTHONHOME'}}
    run = subprocess.run([sys.executable, '-I', '-S', str(launcher), '["skills/_shared"]',
                          'skills/cf22d/scripts/doctor.py'], cwd=job, env=env, capture_output=True, text=True, timeout=30)
    result = json.loads(run.stdout)
    assert run.returncode == 1 and result['ready'] is False
    assert result['code'] == 'dependency_missing'
    assert result['module'] != 'xyz'
    assert 'Traceback' not in run.stderr


def test_managed_launcher_classifies_import_failure(tmp_path):
    (tmp_path / 'tool.py').write_text('import deliberately_missing_research_module\n')
    run = subprocess.run([sys.executable, '-I', '-S', str(ROOT / 'backend/src/research_agent/jobs/python_entrypoint.py'),
                          '[]', 'tool.py'], cwd=tmp_path, capture_output=True, text=True, timeout=10)
    error = json.loads(run.stderr)
    assert run.returncode == 1 and error['code'] == 'module_unavailable'


def test_registered_comparison_runs_as_job_and_mismatch_remains_publishable(tmp_path):
    from tests.unit.test_job_recovery import workspace
    from tests.unit.test_chemical_path_execution import run_job, selected
    from research_agent.application.executors import prepare, validate_prepared_entry, registered_executor
    from research_agent.application.api import execute
    workspace(tmp_path)
    target = structure(tmp_path / 'target.json', 'CC1CCC=CC1')
    actual = structure(tmp_path / 'actual.json', 'CC1=CCCCC1')
    refs = [execute('artifact.register', tmp_path, {'path': str(path)}) for path in (target, actual)]
    prepared = prepare(os.environ['CORAGENT_JOB_CONFIG'], 'local', 'chemical.compare', '1',
                       {'target': target, 'actual': actual}, input_artifact_ids=[r['artifact_id'] for r in refs])
    assert '.coragent/python_entrypoint.py' in prepared['command']
    assert set(prepared['metadata']['input_roles']) == {'target', 'actual'}
    collected = run_job(tmp_path, prepared)
    comparison = selected(collected, '/comparison.json')
    assert json.loads(Path(comparison['location']).read_text())['status'] == 'mismatch'
    node = execute('research.create', tmp_path, {'goal': 'Compare', 'subjects': {'target': refs[0]['artifact_ref']}})['node']
    saved = execute('research.result', tmp_path, {'node_id': node['id'], 'conclusion': 'Calculated a different isomer',
        'subjects': {'target': refs[0]['artifact_ref'], 'calculated': refs[1]['artifact_ref']},
        'check_refs': [comparison['artifact_id']]})
    assert saved['result_saved']
    prepared['metadata']['input_roles']['target']['sha256'] = 'sha256:' + '0' * 64
    with pytest.raises(ValueError, match='input_roles_mismatch'):
        validate_prepared_entry(prepared, registered_executor('chemical.compare', '1')[1])
