"""Research provenance, derived diagnostics and interrupted publication recovery."""
import copy
import json
import pytest
from research_agent.research import nodes, results, records, relations, doctor, views
from research_agent.foundation.transactions import TransactionCoordinator
from tests.unit.test_job_recovery import workspace


def test_result_runtime_input_expansion_does_not_change_retry_identity(tmp_path):
    workspace(tmp_path)
    node = nodes.create(tmp_path, {'goal':'Analyze a computation'})['node']
    artifact = 'art_' + 'a'*64
    request = {'node_id':node['id'], 'conclusion':'Observed evidence', 'request_id':'publication',
        'inputs':[], 'evidence_refs':['job_fixture'],
        '_reference_details':{'job_fixture':{'kind':'job', 'research_binding':{'node_id':node['id'],'node_revision':1},
                                            'input_refs':[artifact]}}}
    original = copy.deepcopy(request)
    first = results.publish(tmp_path, request)
    assert request == original
    assert first['result']['inputs'] == [artifact]
    assert results.publish(tmp_path, copy.deepcopy(original)) == first
    assert len(relations.graph(tmp_path)['results']) == 1


def test_result_inputs_are_fixed_materials_or_results(tmp_path):
    workspace(tmp_path)
    node = nodes.create(tmp_path, {'goal':'Analyze'})['node']
    with pytest.raises(ValueError, match='result_inputs_require_fixed'):
        results.publish(tmp_path, {'node_id':node['id'], 'conclusion':'Not a frozen input', 'inputs':[node['id']]})
    assert not relations.graph(tmp_path)['results']


def test_requires_cycles_are_diagnostic_and_reversible(tmp_path):
    workspace(tmp_path)
    a, b, c, d = [nodes.create(tmp_path, {'goal':name}) for name in ['A','B','C','D']]
    for source, target in [(a,b),(b,c),(c,a),(d,a)]:
        source['updated'] = nodes.update(tmp_path, {'node_id':source['node']['id'], 'read_basis':source['read_basis'],
            'note':'Requires upstream analysis', 'add_relations':[{'kind':'requires','target':target['node']['id']}]})
    findings = relations.diagnostics(tmp_path)
    assert len(findings) == 1
    assert findings[0]['node_ids'] == sorted(n['node']['id'] for n in [a,b,c])
    assert len(findings[0]['relation_ids']) == 3
    assert doctor.inspect_workspace(tmp_path)['valid']
    edge = next(e for e in relations.links(tmp_path, c['node']['id']) if e['source']==c['node']['id'])
    nodes.update(tmp_path, {'node_id':c['node']['id'], 'read_basis':c['updated']['read_basis'],
        'note':'Change waiting strategy', 'remove_relations':[edge['id']]})
    assert relations.diagnostics(tmp_path) == []
    expected = relations.graph(tmp_path)
    doctor.rebuild(tmp_path)
    assert relations.graph(tmp_path) == expected


def test_doctor_detects_and_rebuilds_modified_markdown_without_rewriting_science(tmp_path):
    workspace(tmp_path)
    node = nodes.create(tmp_path, {'goal':'Preserve the actual conclusion'})['node']
    result = results.publish(tmp_path, {'node_id':node['id'],'conclusion':'Inconclusive'})['result']
    views.render(tmp_path)
    canonical = tmp_path/'research/nodes'/node['id']/'results'/(result['id']+'.json')
    before = canonical.read_bytes()
    readme = tmp_path/'research/nodes'/node['id']/'README.md'
    expected = readme.read_text()
    readme.write_text('A manually edited and misleading conclusion')
    report = doctor.inspect_workspace(tmp_path)
    assert report['valid'] and report['status']=='attention'
    assert any(item['code']=='generated_view_mismatch' and item['path']==str(readme.relative_to(tmp_path)) for item in report['findings'])
    doctor.rebuild(tmp_path)
    assert readme.read_text() == expected
    assert canonical.read_bytes() == before
    assert doctor.inspect_workspace(tmp_path)['status']=='healthy'


@pytest.mark.parametrize('kind', ['source','result'])
def test_canonical_content_change_is_not_blessed_by_rebuild(tmp_path, kind):
    workspace(tmp_path)
    if kind == 'source':
        ref = records.record_source(tmp_path, {'session_id':'s','message_id':'m','text':'Original request'})['source_ref']
        path = tmp_path/'research/records'/(ref+'.json')
        value = json.loads(path.read_text()); value['content'] = 'Changed original'
        read = lambda: records.record(tmp_path, ref)
    else:
        node = nodes.create(tmp_path, {'goal':'Preserve results'})['node']
        result = results.publish(tmp_path, {'node_id':node['id'],'conclusion':'Original interpretation'})['result']
        path = tmp_path/'research/nodes'/node['id']/'results'/(result['id']+'.json')
        value = json.loads(path.read_text()); value['conclusion'] = 'Changed interpretation'
        read = lambda: results.get_result(tmp_path, result['id'])
    path.write_text(json.dumps(value))
    changed = path.read_bytes()
    with pytest.raises(ValueError, match='content_changed'):
        read()
    assert not doctor.inspect_workspace(tmp_path)['valid']
    with pytest.raises(ValueError, match='content_changed'):
        doctor.rebuild(tmp_path)
    assert path.read_bytes() == changed


@pytest.mark.parametrize('boundary', ['result','record','node'])
def test_interrupted_result_publication_replays_the_same_compound_commit(tmp_path, monkeypatch, boundary):
    from research_agent.foundation import transactions
    workspace(tmp_path)
    created = nodes.create(tmp_path, {'goal':'Publish an assessed conclusion'})
    node_id = created['node']['id']
    request = {'node_id':node_id, 'conclusion':'The available evidence is insufficient.',
        'as_assessment':True, 'read_basis':created['read_basis'], 'request_id':'compound-publication'}
    original = transactions._atomic_json
    armed = [True]
    def crash(path, value):
        relative = str(path.relative_to(tmp_path))
        selected = (boundary=='result' and relative.startswith(f'research/nodes/{node_id}/results/')) or (
            boundary=='record' and relative.startswith('research/records/')) or (
            boundary=='node' and relative==f'research/nodes/{node_id}/node.json')
        if armed[0] and selected:
            armed[0] = False
            raise OSError('interrupted public replay')
        return original(path, value)
    with monkeypatch.context() as patch:
        patch.setattr(transactions, '_atomic_json', crash)
        with pytest.raises(OSError, match='interrupted public replay'):
            results.publish(tmp_path, copy.deepcopy(request))
    assert not armed[0]
    with TransactionCoordinator(tmp_path).locked():
        saved = results.publish(tmp_path, copy.deepcopy(request))
    assert saved['assessment_selected']
    assert nodes.get_node(tmp_path, node_id)['assessment_ref']==saved['result']['id']
    assert list(relations.graph(tmp_path)['results'])==[saved['result']['id']]
    assert results.publish(tmp_path, copy.deepcopy(request))==saved
    assert len(list((tmp_path/'research/nodes'/node_id/'results').glob('*.json')))==1
    assert doctor.inspect_workspace(tmp_path)['valid']


def test_node_record_preserves_the_updating_session(tmp_path):
    workspace(tmp_path)
    node = nodes.create(tmp_path, {'goal':'Shared research','session_id':'first'})['node']
    written = nodes.update(tmp_path, {'node_id':node['id'],'note':'Second session observation','session_id':'second'})
    note = records.record(tmp_path, written['ref'])
    assert note['data']['author']['session_id']=='second'
    assert nodes.get_node(tmp_path,node['id'])['author']['session_id']=='first'


def test_a_copied_node_cannot_be_used_as_a_cross_workspace_reference(tmp_path):
    from research_agent.research.workspace import initialize_workspace, admit_research_workspace
    first, second = tmp_path/'first', tmp_path/'second'
    for path, identity in [(first,'first'),(second,'second')]:
        initialize_workspace(path, identity, 'research'); admit_research_workspace(path)
    node = nodes.create(first, {'goal':'Only belongs to the first workspace'})['node']
    destination = second/'research/nodes'/node['id']/'node.json'
    destination.parent.mkdir(parents=True)
    destination.write_bytes((first/'research/nodes'/node['id']/'node.json').read_bytes())
    with pytest.raises(ValueError, match='node_identity_invalid'):
        nodes.create(second, {'goal':'Cannot use a copied source','input_refs':[node['id']]})
