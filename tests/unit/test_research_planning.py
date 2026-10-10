"""Task-scoped navigation retains research plans without becoming a scheduler."""
import json

import pytest

from research_agent.application.memory_context import read
from research_agent.research import basis, nodes, relations, views
from tests.unit.test_job_recovery import workspace


def node(root, title, **kwargs):
    return nodes.create(root, {'goal': title, 'title': title, **kwargs})['node']['id']


def connect(root, source, kind, target):
    receipt = read(root, ref=source, field='relations')['read_basis']
    nodes.update(root, {'node_id': source, 'note': 'Record navigation', 'read_basis': receipt,
                       'add_relations': [{'kind': kind, 'target': target}]})


def ids(structure):
    return {item['id'] for item in structure['nodes']}


def test_unbound_snapshot_does_not_claim_recent_nodes_as_task_structure(tmp_path):
    workspace(tmp_path)
    recent = node(tmp_path, 'Unbound work', plan='Compare the observed outputs')
    snapshot = read(tmp_path)
    assert snapshot['schema_version'] == 'research-snapshot/3'
    assert snapshot['nodes'][0]['id'] == recent
    assert snapshot['research'] == {
        'entry_node_ids': [], 'focus_node_ids': [], 'nodes': [], 'relations': [],
        'omitted': {'entry_node_ids': 0, 'focus_node_ids': 0, 'nodes': 0,
                    'relations': 0, 'unexpanded_nodes': 0}}


def test_entry_neighborhood_descends_two_levels_and_exposes_existing_read_path(tmp_path):
    workspace(tmp_path)
    root = node(tmp_path, 'Whole question')
    child = node(tmp_path, 'Subquestion', relations=[{'kind': 'part_of', 'target': root}])
    grandchild = node(tmp_path, 'Detail', relations=[{'kind': 'part_of', 'target': child}])
    deeper = node(tmp_path, 'Further detail', relations=[{'kind': 'part_of', 'target': grandchild}])
    snapshot = read(tmp_path, entry_node_ids=[root])
    structure = snapshot['research']
    assert ids(structure) == {root, child, grandchild}
    assert structure['omitted']['unexpanded_nodes'] == 1
    card = next(item for item in structure['nodes'] if item['id'] == grandchild)
    detail = read(tmp_path, **card['read'])
    assert any(edge['source'] == deeper for edge in detail['value'])
    assert len(structure['relations']) == 2


def test_focus_includes_children_multiple_parents_dependency_and_alternative(tmp_path):
    workspace(tmp_path)
    parent = node(tmp_path, 'First parent')
    other_parent = node(tmp_path, 'Second parent')
    focus = node(tmp_path, 'Shared question', relations=[
        {'kind': 'part_of', 'target': parent}, {'kind': 'part_of', 'target': other_parent}])
    child = node(tmp_path, 'Focused child', relations=[{'kind': 'part_of', 'target': focus}])
    dependency = node(tmp_path, 'Needed measurement')
    alternative = node(tmp_path, 'Alternative model', relations=[{'kind': 'alternative_to', 'target': focus}])
    connect(tmp_path, focus, 'requires', dependency)
    structure = read(tmp_path, focus_node_ids=[focus])['research']
    assert ids(structure) == {parent, other_parent, focus, child, dependency, alternative}
    assert sum(edge['kind'] == 'part_of' for edge in structure['relations']) == 3
    assert structure['omitted']['nodes'] == structure['omitted']['relations'] == 0


def test_requires_cycle_is_visible_diagnostic_not_traversal_or_execution_gate(tmp_path):
    workspace(tmp_path)
    a, b, c = [node(tmp_path, name) for name in ['Question A', 'Question B', 'Question C']]
    connect(tmp_path, a, 'requires', b)
    connect(tmp_path, b, 'requires', a)
    connect(tmp_path, b, 'requires', c)
    snapshot = read(tmp_path, focus_node_ids=[a])
    assert ids(snapshot['research']) == {a, b}
    assert any(item['code'] == 'requires_cycle' for item in snapshot['diagnostics'])
    assert nodes.update(tmp_path, {'node_id': a, 'note': 'Explore while dependency is unresolved'})['accepted']


def test_multiple_entries_remain_stable_when_other_session_adds_recent_activity(tmp_path):
    workspace(tmp_path)
    first = node(tmp_path, 'First question', session_id='owner')
    second = node(tmp_path, 'Second question', session_id='owner')
    children = [node(tmp_path, 'Related ' + str(i), session_id='owner',
                     relations=[{'kind': 'part_of', 'target': ref}]) for i, ref in enumerate([first, second])]
    request = {'entry_node_ids': [first, second], 'focus_node_ids': [children[0]], 'session_id': 'reader'}
    before = read(tmp_path, **request)
    for i in range(12):
        node(tmp_path, 'Unrelated newest activity ' + str(i), session_id='other', plan='A different project')
    after = read(tmp_path, **request)
    assert before['research'] == after['research']
    assert ids(after['research']) == {first, second, *children}
    assert {item['id'] for item in after['nodes'][:4]} == {first, second, *children}


def test_large_entry_set_is_excerpted_without_losing_focus_or_mutating_scope(tmp_path):
    workspace(tmp_path)
    entries = [node(tmp_path, 'Question ' + str(i), plan='Compare measurements') for i in range(128)]
    original = entries.copy()
    structure = read(tmp_path, entry_node_ids=entries, focus_node_ids=[entries[-1]])['research']
    assert entries == original
    assert structure['focus_node_ids'] == [entries[-1]]
    assert entries[0] in ids(structure) and entries[-1] in ids(structure)
    assert structure['omitted']['entry_node_ids'] == 128 - len(structure['entry_node_ids'])
    assert structure['omitted']['nodes'] == 128 - len(structure['nodes'])
    assert structure['omitted']['entry_node_ids'] > 0


def test_scope_reference_order_is_preserved_independently_of_card_ranking(tmp_path):
    workspace(tmp_path)
    root, shared, focus = [node(tmp_path, name) for name in ['Root', 'Shared', 'Focus']]
    structure = read(tmp_path, entry_node_ids=[root, shared], focus_node_ids=[focus, root])['research']
    assert structure['entry_node_ids'] == [root, shared]
    assert structure['focus_node_ids'] == [focus, root]


@pytest.mark.parametrize('budget', [2048, 3000, 16000, 32000])
def test_unicode_structure_and_plan_obey_total_byte_budget(tmp_path, budget):
    workspace(tmp_path)
    entry = node(tmp_path, '总问题' * 60, plan='先比较边界条件，再验证误差。' * 100)
    for i in range(12):
        node(tmp_path, f'子问题{i}', plan='计算并检验' * 100,
             relations=[{'kind': 'part_of', 'target': entry}])
    snapshot = read(tmp_path, entry_node_ids=[entry], limit=budget)
    assert len(json.dumps(snapshot, ensure_ascii=False).encode()) <= budget
    structure = snapshot['research']
    assert structure['omitted']['nodes'] == 13 - len(structure['nodes'])
    assert structure['omitted']['relations'] == 12 - len(structure['relations'])
    if structure['nodes']:
        assert structure['nodes'][0]['id'] == entry
        assert structure['nodes'][0]['plan']
        assert structure['nodes'][0]['content_omitted']


def test_excerpt_of_large_plan_never_authorizes_replacing_it(tmp_path):
    workspace(tmp_path)
    plan = '研究计划与不确定性' * 400
    target = node(tmp_path, 'Large investigation', plan=plan)
    snapshot = read(tmp_path, entry_node_ids=[target], focus_node_ids=[target], session_id='reader')
    summary = snapshot['research']['nodes'][0]
    assert plan.startswith(summary['plan']) and summary['plan'] != plan
    assert summary['content_omitted']
    assert snapshot['nodes'][0]['plan'] and snapshot['nodes'][0]['content_omitted']
    basis.observe(tmp_path, {'session_id': 'reader', 'read_basis': snapshot['read_basis']})
    request = {'session_id': 'reader', 'node_id': target, 'note': 'Revise after reading', 'plan': 'A revised investigation'}
    with pytest.raises(ValueError, match='read_required|fields_not_read'):
        nodes.update(tmp_path, request)
    complete = read(tmp_path, ref=target, field='plan', session_id='reader', limit=32000)
    assert complete['value'] == plan
    basis.observe(tmp_path, {'session_id': 'reader', 'read_basis': complete['read_basis']})
    assert nodes.update(tmp_path, request)['node']['plan'] == request['plan']


def test_structure_and_key_execution_facts_survive_large_research_cards(tmp_path):
    workspace(tmp_path)
    entry = node(tmp_path, 'Main project', plan='Investigate evidence ' * 300)
    for i in range(12):
        node(tmp_path, 'Subproblem ' + str(i), plan='A long proposed approach ' * 300,
             relations=[{'kind': 'part_of', 'target': entry}])
    events = [{'event_id': 'event_' + str(i), 'job_id': 'job_' + str(i), 'node_id': entry,
               'node_revision': 1, 'state': 'succeeded'} for i in range(8)]
    jobs = [{'job_id': 'job_' + str(i), 'node_id': entry, 'state': 'running',
             'collection_state': 'not_collected'} for i in range(8)]
    snapshot = views.build_snapshot(tmp_path, entry_node_ids=[entry], events=events, jobs=jobs)
    assert snapshot['wake_events'] == {'requested': 8, 'included': 8, 'omitted': 0}
    assert snapshot['running_jobs'] == jobs
    assert snapshot['research']['entry_node_ids'] == [entry]
    assert snapshot['research']['nodes'][0]['plan']


def test_unknown_scoped_node_is_rejected_instead_of_showing_unrelated_research(tmp_path):
    workspace(tmp_path)
    node(tmp_path, 'Unrelated')
    with pytest.raises(ValueError, match='research_scope_node_not_found'):
        read(tmp_path, entry_node_ids=['node_' + 'f' * 32])


@pytest.mark.parametrize('budget', [2048, 3000, 16000])
def test_execution_flood_retains_structure_and_accounts_for_every_omission(tmp_path, budget):
    workspace(tmp_path)
    entry = node(tmp_path, 'Main question', plan='Investigate the missing measurements')
    events = [{'event_id': 'event_' + str(i), 'job_id': 'job_' + str(i), 'node_id': entry,
               'node_revision': 1, 'state': 'succeeded'} for i in range(120)]
    jobs = [{'job_id': 'job_' + str(i), 'node_id': entry, 'state': 'running',
             'collection_state': 'not_collected'} for i in range(120)]
    snapshot = views.build_snapshot(tmp_path, max_bytes=budget, entry_node_ids=[entry],
                                    focus_node_ids=[entry], events=events, jobs=jobs)
    assert len(json.dumps(snapshot, ensure_ascii=False).encode()) <= budget
    assert snapshot['research']['nodes'][0]['id'] == entry
    assert snapshot['research']['nodes'][0]['plan']
    assert snapshot['wake_events']['included'] + snapshot['wake_events']['omitted'] == 120
    assert len(snapshot['events']) + snapshot['bounds']['omitted']['events'] == 120
    assert len(snapshot['running_jobs']) + snapshot['bounds']['omitted']['running_jobs'] == 120
