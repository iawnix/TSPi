import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT/'domains/chemical/skills/chemical-input/scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('chemical_input_helper', SCRIPTS/'prepare.py')
helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)


@pytest.mark.parametrize('smiles,formula,atoms', [('O', 'H2O', 3), ('CCO', 'C2H6O', 9), ('CC(=O)C', 'C3H6O', 10)])
def test_reproducible_seed_from_supplied_structure(tmp_path, smiles, formula, atoms):
    first = helper.seeds(smiles, 0, 1, tmp_path/'first')
    second = helper.seeds(smiles, 0, 1, tmp_path/'second')
    assert first['formula'] == formula
    assert first['seeds'][0]['sha256'] == second['seeds'][0]['sha256']
    assert (tmp_path/'first/seed-1.xyz').read_text().splitlines()[0] == str(atoms)
    with pytest.raises(ValueError, match='multiplicity'):
        helper.seeds(smiles, 0, 2, tmp_path/'bad')


def test_stereo_is_explicitly_enumerated_without_selecting_one_identity(tmp_path):
    with pytest.raises(ValueError, match='unspecified stereochemistry'):
        helper.seeds('CC(O)F', 0, 1, tmp_path/'blocked')
    result = helper.seeds('CC(O)F', 0, 1, tmp_path/'ensemble', True)
    assert len(result['seeds']) == 2
    assert len({seed['smiles'] for seed in result['seeds']}) == 2
    assert result['geometry_status'] == 'initial_seed'


def test_reaction_checks_conservation_and_chosen_mapping():
    result = helper.reaction('[CH2:1]=[CH:2][CH:3]=[CH2:4].[CH2:5]=[CH:6][CH3:7]>>[CH2:1]1[CH:2]=[CH:3][CH2:4][CH2:5][CH:6]1[CH3:7]')
    assert result['checks']['element_charge_balance']['verdict']=='pass'
    assert result['checks']['declared_transformation']['verdict']=='not_assessed'
    assert [change['atoms'] for change in result['bond_changes'] if change['before'] == 0] == [[1, 6], [4, 5]]
    with pytest.raises(ValueError, match='unique'):
        helper.reaction('[CH4:1]>>[CH3:1][CH3:1]')
    assert helper.reaction('[CH4:1]>>[OH2:1]')['checks']['map_identity']['verdict']=='fail'
    assert helper.reaction('[13CH4:1]>>[CH4:1]')['checks']['map_identity']['verdict']=='fail'


def test_opsin_configuration_calls_real_resolver_implementation(tmp_path, monkeypatch):
    import name_resolution
    config = tmp_path/'name-resolver.toml'
    config.write_text('default_resolver="opsin"\n[backends.opsin]\nenabled=true\ncache=false\n')
    monkeypatch.setenv('CORAGENT_NAME_RESOLVER_CONFIG', str(config))
    calls = []
    def reply(url, **kwargs):
        calls.append(url)
        return {'status': 'SUCCESS', 'smiles': 'C=CC=C'}, 'sha256:fixture'
    monkeypatch.setattr(name_resolution, '_http_json', reply)
    result = helper.resolve_name('丁二烯', 'buta-1,3-diene')
    assert result['data']['status'] == 'resolved'
    assert result['data']['name'] == '丁二烯'
    assert result['data']['candidates'][0]['formula'] == 'C4H6'
    assert calls and 'buta-1%2C3-diene' in calls[0]


@pytest.fixture
def resolver_config(tmp_path, monkeypatch):
    import name_resolution
    config = tmp_path/'resolver.toml'
    config.write_text('default_resolver="auto"\n[backends.pubchem]\ncache=false\n'
                      'endpoint="https://pubchem.example/rest/pug"\n'
                      '[backends.opsin]\ncache=false\nendpoint="https://opsin.example/opsin"\n')
    monkeypatch.setenv('CORAGENT_NAME_RESOLVER_CONFIG', str(config))
    return name_resolution


@pytest.mark.parametrize('name,lookup,smiles,formula', [
    ('水分子', 'water', 'O', 'H2O'), ('乙醇', 'ethanol', 'CCO', 'C2H6O'),
    ('丙酮', 'acetone', 'CC(=O)C', 'C3H6O'),
])
def test_all_names_use_pubchem_before_opsin(resolver_config, monkeypatch, name, lookup, smiles, formula):
    calls = []
    def reply(url, **kwargs):
        calls.append(url)
        assert 'pubchem.example' in url
        if '/cids/' in url:
            return {'IdentifierList': {'CID': [1]}}, 'sha256:cids'
        return {'PropertyTable': {'Properties': [{'CID': 1, 'IsomericSMILES': smiles}]}}, 'sha256:properties'
    monkeypatch.setattr(resolver_config, '_http_json', reply)
    result = helper.resolve_name(name, lookup)
    assert len(calls) == 2
    assert result['data']['name'] == name
    assert result['data']['lookup_name'] == lookup
    assert result['data']['next_step'] == 'prepare_geometry'
    assert result['data']['candidates'][0]['formula'] == formula
    assert result['data']['candidates'][0]['source'] == 'pubchem'


@pytest.mark.parametrize('failure', ['404', '429', 'timeout', 'empty', 'malformed_response', 'bad_smiles'])
def test_pubchem_failure_or_unusable_graph_continues_to_opsin(resolver_config, monkeypatch, failure):
    import urllib.error
    calls = []
    def reply(url, **kwargs):
        calls.append(url)
        if 'opsin.example' in url:
            return {'status': 'SUCCESS', 'smiles': 'C=CC=C'}, 'sha256:opsin'
        if failure in {'404', '429'}:
            raise urllib.error.HTTPError(url, int(failure), 'fixture', {}, None)
        if failure == 'timeout':
            raise TimeoutError('fixture')
        if failure == 'malformed_response':
            return [], 'sha256:malformed'
        if '/cids/' in url:
            return {'IdentifierList': {'CID': [] if failure == 'empty' else [1]}}, 'sha256:cids'
        return {'PropertyTable': {'Properties': [{'SMILES': 'C('}]}}, 'sha256:invalid'
    monkeypatch.setattr(resolver_config, '_http_json', reply)
    result = helper.resolve_name('buta-1,3-diene')
    assert calls[-1].startswith('https://opsin.example/')
    assert len(calls) == (3 if failure == 'bad_smiles' else 2)
    assert result['data']['status'] == 'resolved'
    assert result['data']['candidates'][0]['source'] == 'opsin'
    assert result['diagnostics']
    if failure == 'bad_smiles':
        assert result['data']['resolver_provenance']['attempts'][0]['candidate_checks'][0]['status'] == 'failed'


def test_lookup_keeps_rejected_candidate_evidence_while_using_valid_structure(resolver_config, monkeypatch):
    def reply(url, **kwargs):
        assert 'pubchem.example' in url
        if '/cids/' in url:
            return {'IdentifierList': {'CID': [1, 2]}}, 'sha256:cids'
        return {'PropertyTable': {'Properties': [
            {'CID': 1, 'SMILES': 'C('}, {'CID': 2, 'SMILES': 'CCO'}]}}, 'sha256:mixed'
    monkeypatch.setattr(resolver_config, '_http_json', reply)
    result = helper.resolve_name('ethanol')
    assert result['data']['next_step'] == 'prepare_geometry'
    assert result['data']['candidates'][0]['candidate_id'] == 'candidate_2'
    assert [item['status'] for item in result['data']['resolver_provenance']['candidate_checks']] == ['failed', 'passed']


def test_lookup_preserves_service_stereochemistry(resolver_config, monkeypatch):
    def reply(url, **kwargs):
        if '/cids/' in url:
            return {'IdentifierList': {'CID': [1]}}, 'sha256:cids'
        return {'PropertyTable': {'Properties': [{
            'CanonicalSMILES': 'CC(O)F', 'IsomericSMILES': 'C[C@H](O)F'}]}}, 'sha256:stereo'
    monkeypatch.setattr(resolver_config, '_http_json', reply)
    result = helper.resolve_name('stereospecified fixture')
    assert result['data']['next_step'] == 'prepare_geometry'
    assert '@' in result['data']['candidates'][0]['isomeric_smiles']


@pytest.mark.parametrize('failure', ['empty', 'offline', 'missing_config', 'invalid_config', 'bad_type_config'])
def test_failed_lookup_leads_to_inference_without_invalidating_the_molecule(resolver_config, monkeypatch, tmp_path, failure):
    calls = []
    def reply(url, **kwargs):
        calls.append(url)
        if failure == 'offline':
            raise TimeoutError('fixture')
        return {}, 'sha256:empty'
    monkeypatch.setattr(resolver_config, '_http_json', reply)
    if failure == 'missing_config':
        monkeypatch.delenv('CORAGENT_NAME_RESOLVER_CONFIG')
        monkeypatch.delenv('CORAGENT_INSTALL_ROOT', raising=False)
    elif failure == 'invalid_config':
        (tmp_path/'resolver.toml').write_text('not valid TOML')
    elif failure == 'bad_type_config':
        (tmp_path/'resolver.toml').write_text('default_resolver=[]')
    result = helper.resolve_name('fixture molecule')
    assert result['data']['status'] == 'unresolved'
    assert result['data']['next_step'] == 'infer_candidates'
    assert result['verdict'] == 'inconclusive'
    assert len(calls) == (0 if failure.endswith('config') else 2)


@pytest.mark.parametrize('source', ['llm', 'user'])
@pytest.mark.parametrize('smiles,formula', [('O', 'H2O'), ('CCO', 'C2H6O'), ('CC(=O)C', 'C3H6O')])
def test_candidate_files_proceed_to_geometry_regardless_of_source(tmp_path, monkeypatch, source, smiles, formula):
    import name_resolution
    monkeypatch.setattr(name_resolution, '_http_json', lambda *args, **kwargs: pytest.fail('candidate input must stay local'))
    path = tmp_path/'candidates.json'
    document = {'name': 'original input', 'lookup_name': 'normalized input', 'lookup_ref': 'art_lookup',
                'candidates': [{'smiles': smiles, 'source': source, 'reason': 'fixture structural interpretation',
                                'assumptions': ['neutral species'], 'charge': 0, 'multiplicity': 1}]}
    path.write_text(json.dumps(document))
    result = helper.resolve_candidates_file(path)
    assert result['data']['status'] == 'resolved' and result['verdict'] == 'valid'
    assert result['data']['next_step'] == 'prepare_geometry'
    assert result['checks'][0]['status'] == 'passed'
    chosen = result['data']['candidates'][0]
    assert chosen['source'] == source
    assert chosen['reason'] == document['candidates'][0]['reason']
    assert chosen['assumptions'] == ['neutral species']
    assert result['data']['input_provenance']['lookup_ref'] == 'art_lookup'
    geometry = helper.seeds(chosen['canonical_smiles'], chosen['charge'], chosen['multiplicity'], tmp_path/'geometry')
    assert geometry['formula'] == formula
    assert Path(geometry['seeds'][0]['xyz']).is_file()


@pytest.mark.parametrize('proposal,diagnostic', [
    ({'smiles': 'C('}, 'parse'), ({'smiles': 'C(C)(C)(C)(C)C'}, 'parse'),
    ({'smiles': 'CCO', 'charge': 1}, 'charge'), ({'smiles': 'CCO', 'multiplicity': 2}, 'multiplicity'),
])
def test_candidate_errors_are_repairable_without_changing_source(tmp_path, proposal, diagnostic):
    path = tmp_path/'candidates.json'
    document = {'name': 'ethanol', 'candidates': [dict(proposal, source='llm')]}
    path.write_text(json.dumps(document))
    before = helper.resolve_candidates_file(path)
    assert before['data']['next_step'] == 'revise_candidates'
    assert before['checks'][0]['status'] == 'failed'
    assert any(diagnostic in message for message in before['diagnostics'])
    document['candidates'] = [{'smiles': 'CCO', 'source': 'llm', 'charge': 0, 'multiplicity': 1}]
    path.write_text(json.dumps(document))
    after = helper.resolve_candidates_file(path)
    assert after['data']['next_step'] == 'prepare_geometry'
    assert before['data']['input_provenance']['sha256'] != after['data']['input_provenance']['sha256']


@pytest.mark.parametrize('source', [[], {}, 'pubchem'])
def test_candidate_file_reports_invalid_source(tmp_path, source):
    path = tmp_path/'candidates.json'
    path.write_text(json.dumps({'name': 'ethanol', 'candidates': [{'smiles': 'CCO', 'source': source}]}))
    with pytest.raises(ValueError, match='sources must be llm or user'):
        helper.resolve_candidates_file(path)


@pytest.mark.parametrize('smiles', ['CC(O)F', 'CC=CC'])
def test_candidate_alternatives_and_unspecified_stereo_support_branching(tmp_path, smiles):
    path = tmp_path/'candidates.json'
    path.write_text(json.dumps({'name': 'unspecified stereo', 'candidates': [{'smiles': smiles, 'source': 'llm'}]}))
    result = helper.resolve_candidates_file(path)
    assert result['data']['next_step'] == 'select_or_enumerate'
    row = result['data']['candidates'][0]
    branches = helper.seeds(row['canonical_smiles'], row['charge'], 1, tmp_path/'stereo', True)
    assert len(branches['seeds']) == 2
    path.write_text(json.dumps({'name': 'working alternatives', 'candidates': [
        {'smiles': 'CCO', 'source': 'llm'}, {'smiles': 'COC', 'source': 'llm'}]}))
    result = helper.resolve_candidates_file(path)
    assert result['data']['status'] == 'ambiguous'
    assert len(result['data']['candidates']) == 2
    # Choosing a branch is a scientific decision available to the Agent.
    for index, row in enumerate(result['data']['candidates']):
        assert helper.seeds(row['canonical_smiles'], row['charge'], 1, tmp_path/f'branch-{index}')['seeds']
