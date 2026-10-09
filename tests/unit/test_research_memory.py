"""Research identities, immutable provenance, concurrent edits and reconstruction."""
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from research_agent.research import nodes, results, relations, records, basis, retrieval, doctor, views
from research_agent.application.api import execute
from research_agent.application.memory_context import read
from research_agent.foundation.transactions import TransactionCoordinator, read_json, write_json
from tests.unit.test_job_recovery import workspace


def create(root, goal='Find a transition state', **kwargs):
    return nodes.create(root, {'goal': goal, **kwargs})


def test_original_and_repeated_attempts_are_independent(tmp_path):
    workspace(tmp_path)
    request = {'session_id': 's', 'message_id': 'm', 'text': '先计算反应路径，然后发完整报告。'}
    first = records.record_source(tmp_path, request)
    assert records.record_source(tmp_path, request) == first
    with pytest.raises(ValueError, match='identity_reused'):
        records.record_source(tmp_path, {**request, 'text': 'changed'})
    node = create(tmp_path, source_refs=[first['source_ref']])['node']
    for attempt in range(3):
        nodes.update(tmp_path, {'node_id': node['id'], 'note': f'Attempt {attempt} failed to converge'})
    assert len(relations.graph(tmp_path)['nodes']) == 1
    assert nodes.get_node(tmp_path, node['id'])['revision'] == 1
    assert retrieval.search(tmp_path, node_id=node['id'], kind='note')['total'] == 3
    assert records.record(tmp_path, first['source_ref'])['content'] == request['text']


def test_same_request_replays_and_changed_content_rejects(tmp_path):
    workspace(tmp_path)
    request = {'goal': 'Compare paths', 'request_id': 'create:1'}
    first = nodes.create(tmp_path, request)
    assert nodes.create(tmp_path, request) == first
    with pytest.raises(RuntimeError, match='id_reused'):
        nodes.create(tmp_path, {**request, 'goal': 'New question'})
    publication = {'node_id': first['node']['id'], 'conclusion': 'Insufficient evidence', 'request_id': 'result:1'}
    saved = results.publish(tmp_path, publication)
    assert results.publish(tmp_path, publication) == saved
    assert len(relations.graph(tmp_path)['results']) == 1


def test_concurrent_edits_are_atomic_and_runtime_facts_do_not_conflict(tmp_path):
    workspace(tmp_path)
    initial = create(tmp_path)
    node_id = initial['node']['id']
    records.record_event(tmp_path, {'kind': 'job', 'title': 'Failed', 'node_id': node_id, 'content': 'Exit 23'})
    def replace(i):
        try:
            return nodes.update(tmp_path, {'node_id': node_id, 'note': str(i), 'proposal': str(i), 'read_basis': initial['read_basis']})
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(item is not None for item in pool.map(replace, range(8))) == 1
    assert nodes.get_node(tmp_path, node_id)['revision'] == 2
    assert retrieval.search(tmp_path, kind='node_updated')['total'] == 1
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: nodes.update(tmp_path, {'node_id': node_id, 'note': f'observation {i}'}), range(8)))
    assert retrieval.search(tmp_path, kind='note')['total'] == 8


def test_read_basis_only_advances_after_visible_acknowledgement(tmp_path):
    workspace(tmp_path)
    node = create(tmp_path, session_id='s')['node']
    snapshot = read(tmp_path, session_id='s')
    update = {'node_id': node['id'], 'session_id': 's', 'note': 'new plan', 'plan': 'Analyze IRC'}
    with pytest.raises(ValueError, match='read_required'):
        nodes.update(tmp_path, update)
    basis.observe(tmp_path, {'session_id': 's', 'read_basis': snapshot['read_basis']})
    assert nodes.update(tmp_path, update)['node']['revision'] == 2
    other = read(tmp_path, ref=node['id'], session_id='other')
    with pytest.raises(ValueError, match='session_mismatch'):
        basis.observe(tmp_path, {'session_id': 's', 'read_basis': other['read_basis']})


def test_short_snapshot_does_not_authorize_unseen_fields(tmp_path):
    workspace(tmp_path)
    node = create(tmp_path, proposal='研究' * 2000, session_id='s')['node']
    snapshot = read(tmp_path, session_id='s', limit=3000)
    basis.observe(tmp_path, {'session_id': 's', 'read_basis': snapshot['read_basis']})
    with pytest.raises(ValueError, match='read_required'):
        nodes.update(tmp_path, {'session_id': 's', 'node_id': node['id'], 'note': 'edit', 'proposal': 'replacement'})


def test_result_immutable_selection_conflict_and_exact_supersession(tmp_path):
    workspace(tmp_path)
    initial = create(tmp_path)
    node_id = initial['node']['id']
    r1 = results.publish(tmp_path, {'node_id': node_id, 'conclusion': 'First observation'})['result']
    b = create(tmp_path, goal='Compare mechanisms', input_refs=[r1['id']])['node']
    nodes.update(tmp_path, {'node_id': node_id, 'note': 'New plan', 'plan': 'Try IRC', 'read_basis': initial['read_basis']})
    saved = results.publish(tmp_path, {'node_id': node_id, 'conclusion': 'Corrected observation', 'supersedes': r1['id'],
                                     'as_assessment': True, 'read_basis': initial['read_basis'], 'request_id': 'r2'})
    assert saved['result_saved'] and not saved['assessment_selected'] and 'conflict' in saved['conflict']
    assert results.get_result(tmp_path, r1['id']) == r1
    assert nodes.get_node(tmp_path, node_id)['assessment_ref'] is None
    notices = retrieval.node_detail(tmp_path, b['id'])['review_notices']
    assert notices[0]['used'] == r1['id'] and notices[0]['superseded_by'] == saved['result']['id']


def test_relations_are_explicit_reversible_and_read_does_not_create_uses(tmp_path):
    workspace(tmp_path)
    a, b = create(tmp_path), create(tmp_path, goal='Other')
    a_id, b_id = a['node']['id'], b['node']['id']
    update = nodes.update(tmp_path, {'node_id': a_id, 'note': 'Needs comparison', 'read_basis': a['read_basis'],
                                   'add_relations': [{'kind': 'part_of', 'target': b_id}]})
    links = relations.links(tmp_path, b_id)
    assert len(links) == 1 and links[0]['source'] == a_id
    before = relations.graph(tmp_path)
    read(tmp_path, ref=a_id)
    retrieval.search(tmp_path, query='comparison')
    assert relations.graph(tmp_path) == before
    with pytest.raises(ValueError, match='containment_cycle'):
        nodes.update(tmp_path, {'node_id': b_id, 'note': 'bad', 'read_basis': b['read_basis'], 'add_relations': [{'kind': 'part_of', 'target': a_id}]})
    assert nodes.get_node(tmp_path, b_id)['revision'] == 1
    nodes.update(tmp_path, {'node_id': a_id, 'note': 'Withdraw', 'read_basis': update['read_basis'], 'remove_relations': [links[0]['id']]})
    assert relations.links(tmp_path, b_id) == []
    assert doctor.inspect_workspace(tmp_path)['valid']


def test_unicode_pagination_and_bounded_snapshot(tmp_path):
    workspace(tmp_path)
    for i in range(12):
        records.record_source(tmp_path, {'session_id': 's', 'message_id': str(i), 'text': f'{i}: '+ '研究任务' * 500})
    snapshot = read(tmp_path, limit=2048)
    assert len(json.dumps(snapshot, ensure_ascii=False).encode()) <= 2048
    rows = retrieval.search(tmp_path, origin='user', limit=5)
    assert rows['total'] == 12 and rows['next_offset'] == 5
    ref = rows['records'][0]['ref']
    pages, offset = [], 0
    while offset is not None:
        page = read(tmp_path, ref=ref, offset=offset, limit=73)
        pages.append(page['text']); offset = page['next_offset']
    assert json.loads(''.join(pages)) == records.record(tmp_path, ref)
    assert retrieval.search(tmp_path, query='研究任务', origin='user')['total'] == 12


def test_artifact_file_identity_and_old_protocol_rejected(tmp_path):
    workspace(tmp_path)
    node = execute('research.create', tmp_path, {'goal': 'Report'})['node']
    material = execute('artifact.create', tmp_path, {'name': 'analysis.txt', 'content': 'Preliminary'})
    result = execute('research.result', tmp_path, {'node_id': node['id'], 'conclusion': 'Report prepared',
                     'files': [{'name': 'analysis.txt', 'artifact_ref': material['artifact_ref']}]})
    assert result['result']['files'][0]['artifact_ref'] == material['artifact_ref']
    for command, params in [('research.change', {}), ('research.update', {'content': 'old'}), ('research.create', {'goal': 'x', 'origin': 'runtime'})]:
        with pytest.raises(ValueError):
            execute(command, tmp_path, params)


def test_rebuild_from_immutable_sources_preserves_runtime(tmp_path):
    workspace(tmp_path)
    a = create(tmp_path)
    b = create(tmp_path, goal='Part', relations=[{'kind': 'part_of', 'target': a['node']['id']}])
    results.publish(tmp_path, {'node_id': b['node']['id'], 'conclusion': 'Negative result'})
    expected = relations.graph(tmp_path)
    with TransactionCoordinator(tmp_path).locked():
        write_json(tmp_path / 'operations/jobs/job_preserved.json', {'job_id': 'job_preserved'})
    runtime = (tmp_path / 'operations/jobs/job_preserved.json').read_bytes()
    for path in [tmp_path / 'research/journal.json', tmp_path / 'research/map.json', tmp_path / 'research/nodes' / a['node']['id'] / 'node.json']:
        path.unlink()
    assert doctor.rebuild(tmp_path)['rebuilt']
    assert relations.graph(tmp_path) == expected
    assert doctor.inspect_workspace(tmp_path)['valid']
    assert (tmp_path / 'operations/jobs/job_preserved.json').read_bytes() == runtime
    assert (tmp_path / 'research/README.md').is_file()


def test_unbound_interrupted_job_is_visible(tmp_path):
    workspace(tmp_path)
    write_json(tmp_path / 'operations/jobs/job_uncertain.json', {'job_id': 'job_uncertain'})
    snapshot = read(tmp_path)
    assert snapshot['running_jobs'][0]['state'] == 'unknown'


def test_old_workspaces_and_symlinks_rejected_without_modification(tmp_path):
    from research_agent.research.workspace import initialize_workspace, WorkspaceModeError
    root = tmp_path / 'orphan'; (root / 'research').mkdir(parents=True)
    (root / 'research/journal.json').write_text('important originals')
    with pytest.raises(WorkspaceModeError, match='records_without_manifest'):
        initialize_workspace(root, 'orphan', 'research')
    assert (root / 'research/journal.json').read_text() == 'important originals'
    root = tmp_path / 'new'; workspace(root)
    node = create(root)
    path = root / 'research/records' / (node['ref'] + '.json')
    outside = tmp_path / 'outside.json'; path.rename(outside); path.symlink_to(outside)
    with pytest.raises(ValueError, match='record_path_symlink'):
        read(root, ref=node['ref'])


def test_large_node_read_field_establishes_only_that_field_basis(tmp_path):
    workspace(tmp_path)
    node = create(tmp_path, proposal='研究' * 2000, plan='计划' * 2000, session_id='s')['node']
    page = read(tmp_path, ref=node['id'], field='proposal', session_id='s', limit=32000)
    assert page['next_offset'] is None and page['value'] == node['proposal']
    assert len(json.dumps(page, ensure_ascii=False).encode()) < 50 * 1024
    basis.observe(tmp_path, {'session_id': 's', 'read_basis': page['read_basis']})
    with pytest.raises(ValueError, match='fields_not_read'):
        nodes.update(tmp_path, {'session_id': 's', 'node_id': node['id'], 'note': 'bad', 'plan': 'unseen'})
    changed = nodes.update(tmp_path, {'session_id': 's', 'node_id': node['id'], 'note': 'new proposal', 'proposal': 'Revised'})
    assert changed['node']['proposal'] == 'Revised'


def test_thousand_nodes_ten_thousand_records_rank_page_and_rebuild(tmp_path, monkeypatch):
    """Large canonical corpus: hot retrieval must not reread every record body."""
    workspace(tmp_path)
    template = create(tmp_path)['node']
    record_dir = tmp_path / 'research/records'
    for path in record_dir.glob('*.json'):
        path.unlink()
    graph = {'schema_version': 'research-map/1', 'nodes': {}, 'relations': {}, 'results': {}}
    headers = []
    for i in range(10000):
        node_id = 'node_' + f'{i % 1000:032x}'
        node = {**template, 'id': node_id, 'title': f'Question {i % 1000}', 'goal': f'Compute question {i % 1000}',
                'created_at': '2026-01-01', 'updated_at': f'2026-01-{1 + i % 28:02}'}
        ref = 'note_' + records.digest(['large-corpus', i])
        value = {'schema_version': 'research-record/2', 'ref': ref, 'sequence': i + 1, 'created_at': '2026-01-01',
                 'origin': 'agent', 'kind': 'node_created' if i < 1000 else 'note', 'title': node['title'],
                 'content': f'Observation {i}', 'references': [], 'data': {'node': node} if i < 1000 else {},
                 'node_id': node_id, 'node_revision': 1}
        value['content_digest'] = records.digest(value)
        (record_dir / (ref + '.json')).write_text(json.dumps(value))
        headers.append({k: value[k] for k in ('ref','sequence','origin','kind','title','node_id','created_at')})
        if i < 1000:
            graph['nodes'][node_id] = node
            directory = tmp_path / 'research/nodes' / node_id
            directory.mkdir(exist_ok=True)
            (directory / 'node.json').write_text(json.dumps(node))
    write_json(tmp_path / 'research/journal.json', {'schema_version': 'research-journal/2', 'sequence': 10000, 'records': headers})
    write_json(tmp_path / 'research/map.json', graph)
    focused = 'node_' + '0' * 32
    snapshot = views.build_snapshot(tmp_path, max_bytes=16000,
                                    events=[{'event_id': 'event_focus', 'job_id': 'job_focus', 'node_id': focused, 'state': 'failed'}])
    assert snapshot['nodes'][0]['id'] == focused
    assert snapshot['nodes'][0]['ranking_reason'] == 'trigger_or_explicit_focus'
    assert snapshot['events'][0]['event_id'] == 'event_focus'
    rows = retrieval.search(tmp_path, node_id=focused, kind='note', limit=5)
    assert rows['total'] == 9 and rows['next_offset'] == 5
    def unexpected_body_read(*args, **kwargs):
        raise AssertionError('warm search rescanned a canonical record body')
    with monkeypatch.context() as patch:
        patch.setattr(retrieval, 'record', unexpected_body_read)
        assert retrieval.search(tmp_path, node_id=focused, kind='note', offset=5)['total'] == 9
    replayed_journal, replayed_graph = doctor._replay(tmp_path)
    assert replayed_journal['sequence'] == 10000 and len(replayed_graph['nodes']) == 1000
    assert replayed_graph == graph


def test_selected_field_pages_only_authorize_after_all_visible_ranges(tmp_path):
    workspace(tmp_path)
    initial = create(tmp_path, proposal='研究方案' * 1000, session_id='s')
    node_id = initial['node']['id']
    pages, offset = [], 0
    while offset is not None:
        page = read(tmp_path, ref=node_id, field='proposal', session_id='s', offset=offset, limit=777)
        pages.append(page)
        offset = page['next_offset']
    for page in pages[1:]:
        basis.observe(tmp_path, {'session_id': 's', 'read_basis': page['read_basis']})
    request = {'session_id': 's', 'node_id': node_id, 'note': 'Replace after reading', 'proposal': 'new'}
    with pytest.raises(ValueError, match='fields_not_read'):
        nodes.update(tmp_path, request)
    basis.observe(tmp_path, {'session_id': 's', 'read_basis': pages[0]['read_basis']})
    assert nodes.update(tmp_path, request)['node']['proposal'] == 'new'
    # Replaying a page of an older revision cannot authorize another replacement.
    basis.observe(tmp_path, {'session_id': 's', 'read_basis': pages[-1]['read_basis']})
    with pytest.raises(ValueError, match='revision_conflict'):
        nodes.update(tmp_path, {**request, 'proposal': 'stale'})


def test_opposite_alternative_endpoint_cannot_overwrite_stale_relation(tmp_path):
    workspace(tmp_path)
    a = create(tmp_path)
    b = create(tmp_path, relations=[{'kind': 'alternative_to', 'target': a['node']['id'], 'reason': 'compare'}])
    a_read = read(tmp_path, ref=a['node']['id'])
    edge = relations.links(tmp_path, a['node']['id'])[0]
    nodes.update(tmp_path, {'node_id': b['node']['id'], 'note': 'Withdraw comparison', 'remove_relations': [edge['id']], 'read_basis': b['read_basis']})
    with pytest.raises(ValueError, match='relations_conflict'):
        nodes.update(tmp_path, {'node_id': a['node']['id'], 'note': 'stale comparison', 'read_basis': a_read['read_basis'],
                               'add_relations': [{'kind': 'alternative_to', 'target': b['node']['id'], 'reason': 'overwrite'}]})
    assert not relations.links(tmp_path, a['node']['id'])


def test_result_retains_job_fact_original_proposal_revision(tmp_path):
    workspace(tmp_path)
    initial = create(tmp_path, proposal='Original proposal')
    node_id = initial['node']['id']
    fact = records.record_event(tmp_path, {'kind': 'job', 'title': 'Completed old calculation', 'node_id': node_id,
                 'node_revision': 1, 'data': {'metadata': {'research_binding': {'node_id': node_id, 'node_revision': 1}}}})
    changed = nodes.update(tmp_path, {'node_id': node_id, 'note': 'Revised proposal', 'proposal': 'New proposal', 'read_basis': initial['read_basis']})
    result = execute('research.result', tmp_path, {'node_id': node_id, 'conclusion': 'Old test observed', 'evidence_refs': [fact['ref']], 'read_basis': changed['read_basis']})['result']
    assert result['authored_node_revision'] == 2
    assert result['basis_refs'] == [{'ref': fact['ref'], 'node_id': node_id, 'node_revision': 1}]


def test_generated_view_failure_reports_saved_result_without_republication(tmp_path, monkeypatch):
    workspace(tmp_path)
    node = create(tmp_path)['node']
    def render_failure(root):
        raise ValueError('view_path_symlink')
    monkeypatch.setattr(views, 'render', render_failure)
    request = {'node_id': node['id'], 'conclusion': 'Preserved despite view failure', 'request_id': 'publication-view-failure'}
    first = execute('research.result', tmp_path, request)
    second = execute('research.result', tmp_path, request)
    assert first['result_saved'] and first['view_error'] == 'view_path_symlink'
    assert first['result']['id'] == second['result']['id']
    assert len(relations.graph(tmp_path)['results']) == 1


def test_result_search_distinguishes_product_from_publication_history(tmp_path):
    workspace(tmp_path)
    node = create(tmp_path)['node']
    saved = execute('research.result', tmp_path, {'node_id': node['id'], 'conclusion': 'One distinct research product'})['result']
    products = execute('research.search', tmp_path, {'kind': 'result'})
    assert products['total'] == 1
    assert products['records'][0]['ref'] == saved['id']
    history = execute('research.search', tmp_path, {'kind': 'result_published'})
    assert history['total'] == 1
    assert records.record(tmp_path, history['records'][0]['ref'])['data']['result_id'] == saved['id']
