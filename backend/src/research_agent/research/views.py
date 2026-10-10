"""Bounded request views and disposable, human-readable research projections."""
import json
import re
from pathlib import Path
from .records import journal, record, digest
from . import relations, basis
from research_agent.foundation.transactions import read_json
from research_agent.foundation.path_safety import path_has_symlink


def _size(value):
    return len(json.dumps(value, ensure_ascii=False).encode())


def _excerpt(value, max_bytes):
    return value.encode()[:max_bytes].decode('utf-8', errors='ignore') if value is not None else None


def _structure(graph, neighborhood, max_bytes):
    entries, focus = neighborhood['entry_node_ids'], neighborhood['focus_node_ids']
    output = {'entry_node_ids': [], 'focus_node_ids': [], 'nodes': [], 'relations': [],
              'omitted': {'entry_node_ids': len(entries), 'focus_node_ids': len(focus),
                          'nodes': len(neighborhood['node_ids']), 'relations': len(neighborhood['relations']),
                          'unexpanded_nodes': neighborhood['unexpanded_nodes']}}
    included = set()
    for ref in neighborhood['node_ids']:
        node = graph['nodes'][ref]
        title, plan = _excerpt(node['title'], 96), _excerpt(node['plan'], min(240, max_bytes // 6))
        card = {key: node[key] for key in ('id', 'revision', 'status', 'assessment_ref')}
        card.update(title=title, plan=plan, content_omitted=title != node['title'] or plan != node['plan'],
                    read={'ref': ref, 'field': 'relations'})
        added_edges = [{key: edge[key] for key in ('id', 'source', 'kind', 'target')}
                       for edge in neighborhood['relations']
                       if (edge['source'] == ref and edge['target'] in included
                           or edge['target'] == ref and edge['source'] in included)]
        output['nodes'].append(card)
        output['relations'].extend(added_edges)
        for key, refs in (('entry_node_ids', entries), ('focus_node_ids', focus)):
            if ref in refs:
                output[key].append(ref)
        if _size(output) > max_bytes:
            output['nodes'].pop()
            if added_edges:
                del output['relations'][-len(added_edges):]
            for key, refs in (('entry_node_ids', entries), ('focus_node_ids', focus)):
                if ref in refs:
                    output[key].pop()
        else:
            included.add(ref)
    output['entry_node_ids'] = [ref for ref in entries if ref in included]
    output['focus_node_ids'] = [ref for ref in focus if ref in included]
    for key in ('entry_node_ids', 'focus_node_ids', 'nodes', 'relations'):
        output['omitted'][key] -= len(output[key])
    return output


def build_snapshot(root, *, max_bytes=16000, session_id=None, entry_node_ids=(), focus_node_ids=(), events=(), jobs=(), projection=None):
    if not 2048 <= max_bytes <= 32000:
        raise ValueError('snapshot_budget_invalid: use 2048..32000 bytes')
    index, graph = journal(root), relations.graph(root)
    from .retrieval import research_neighborhood
    neighborhood = research_neighborhood(graph, entry_node_ids, focus_node_ids)
    from .results import publication_order
    published = publication_order(root, graph)
    focus = list(dict.fromkeys([e['node_id'] for e in events if e.get('node_id')] + list(focus_node_ids)))
    priority = {node_id: (0, 'trigger_or_explicit_focus') for node_id in focus}
    for node_id in neighborhood['node_ids']:
        priority.setdefault(node_id, (1, 'task_research_scope'))
    for job in jobs:
        if job.get('node_id') and (job.get('execution_conflict') or job.get('collection_state') != 'complete'):
            priority.setdefault(job['node_id'], (2, 'execution_needs_attention'))
    result_owner = {ref: result['node_id'] for ref, result in graph['results'].items()}
    superseded = {r['supersedes'] for r in graph['results'].values() if r['supersedes']}
    for edge in graph['relations'].values():
        if not edge['active']:
            continue
        source = result_owner.get(edge['source'], edge['source'])
        target = result_owner.get(edge['target'], edge['target'])
        if source in focus and target in graph['nodes']:
            priority.setdefault(target, (3, 'explicit_relation_to_focus'))
        if target in focus and source in graph['nodes'] and edge['kind'] in {'alternative_to', 'requires', 'uses', 'cites'}:
            priority.setdefault(source, (3, 'related_research'))
        if edge['target'] in superseded and source in graph['nodes']:
            priority.setdefault(source, (4, 'input_result_superseded'))
    tasks = [r for r in index['records'] if r['origin'] == 'user']
    latest = record(root, tasks[-1]['ref']) if tasks else None
    words = re.findall(r'[\w]{2,}', latest['content'].casefold())[:64] if latest else []
    for node in graph['nodes'].values():
        if any(word in (node['title'] + ' ' + node['goal']).casefold() for word in words):
            priority.setdefault(node['id'], (5, 'request_text_match'))
    for node in graph['nodes'].values():
        if node.get('author', {}).get('session_id') == session_id and session_id:
            priority[node['id']] = min(priority.get(node['id'], (6, 'recent_research')), (4, 'current_session'))
    activity = {row['node_id']: row['sequence'] for row in index['records'] if row.get('node_id')}
    ordered = sorted(graph['nodes'].values(), key=lambda n: (priority.get(n['id'], (6, 'recent_research'))[0],
                     -int(n['status'] == 'open'), -activity.get(n['id'], 0), n['id']))
    execution = []
    for job in jobs:
        key = 'running_jobs' if job.get('state') in {'started','submitted','queued','held','running','unknown'} else 'uncollected_jobs'
        if key == 'running_jobs' or job.get('collection_state') != 'complete' or job.get('execution_conflict'):
            execution.append((key, job))
    view = {'schema_version': 'research-snapshot/3', 'workspace_id': read_json(Path(root) / 'workspace_manifest.json')['workspace_id'],
            'sequence': index['sequence'], 'nodes': [], 'tasks': [], 'new_records': [], 'running_jobs': [], 'uncollected_jobs': [],
            'research': _structure(graph, neighborhood, 0),
            'diagnostics': [{'code': d['code'], 'node_count': len(d['node_ids']), 'node_ids': d['node_ids'][:3]} for d in relations.diagnostics(root)[:3]], 'events': [], 'wake_events': {'requested': len(events), 'included': 0, 'omitted': len(events)},
            'projection': projection or {'pending': 0}, 'bounds': {'max_bytes': max_bytes, 'omitted': {
                'nodes': len(ordered), 'tasks': int(latest is not None), 'new_records': min(40, len(index['records'])),
                'running_jobs': sum(key == 'running_jobs' for key, _ in execution),
                'uncollected_jobs': sum(key == 'uncollected_jobs' for key, _ in execution), 'events': len(events),
                'older_records': max(0, len(index['records']) - 40), 'older_tasks': max(0, len(tasks) - 1)}},
            'read_more': {'nodes': {'tool': 'research_search', 'kind': 'node'}, 'tasks': {'tool': 'research_search', 'origin': 'user'},
                          'records': {'tool': 'research_search'}, 'events': {'tool': 'research_search', 'origin': 'runtime'}},
            'guidance': 'Research is a bounded task neighborhood, not ownership or a workflow gate. Omission counts cover the discovered neighborhood, not the whole graph. Read Node field=relations to expand, field=plan for the full plan. Excerpts do not authorize field replacement. Open Nodes do not schedule runs; events do not imply completed analysis.',
            'read_basis': 'read_' + '0' * 64, 'snapshot_id': 'snapshot_' + '0' * 64}
    # Structure is reserved before execution facts; execution facts precede detail
    # cards. Exact-size placeholders and initial omission counts reserve metadata.
    allowance = max_bytes
    def add(key, value):
        view[key].append(value)
        view['bounds']['omitted'][key] -= 1
        if _size(view) > allowance:
            view[key].pop()
            view['bounds']['omitted'][key] += 1
            return False
        return True
    structure_budget = min(max_bytes // 4 + _size(view['research']), max_bytes - _size(view) + _size(view['research']))
    view['research'] = _structure(graph, neighborhood, structure_budget)
    for event in events:
        compact = {k: event.get(k) for k in ('event_id', 'job_id', 'node_id', 'node_revision', 'state')}
        compact['read'] = {'tool': 'job_status', 'event_id': event['event_id']}
        view['wake_events']['included'] += 1
        view['wake_events']['omitted'] -= 1
        if not add('events', compact):
            view['wake_events']['included'] -= 1
            view['wake_events']['omitted'] += 1
    for key, job in execution:
        add(key, job)
    if latest:
        add('tasks', {'ref': latest['ref'], 'content': latest['content'][:500], 'content_omitted': len(latest['content']) > 500, 'read': {'ref': latest['ref']}})
    full_nodes = []
    def add_node(node):
        from .context import result_notices
        from .results import get_result
        assessment = node.get('assessment_ref')
        notices = result_notices(root, get_result(root, assessment), graph) if assessment and assessment.startswith('result_') else []
        if _size(node) < 2400:
            outputs = [r for r in published if r['node_id'] == node['id']]
            card = {**node, 'recent_results': [{'id': r['id'], 'summary': r['summary'][:240], 'content_omitted': len(r['summary']) > 240, 'read': {'ref': r['id']}} for r in outputs[-2:]], 'ranking_reason': priority.get(node['id'], (6, 'recent_research'))[1], 'read': {'ref': node['id']}}
            card.update(review_notices=notices[:3], review_notice_count=len(notices))
            if add('nodes', card):
                full_nodes.append(node)
        else:
            card = {k: node[k] for k in ('id', 'revision', 'status', 'assessment_ref')}
            card.update(title=_excerpt(node['title'], 100), goal=_excerpt(node['goal'], 300),
                        progress=_excerpt(node.get('progress') or '', 300), plan=_excerpt(node['plan'], 240),
                        content_omitted=True, read={'ref': node['id']})
            card.update(review_notices=notices[:1], review_notice_count=len(notices))
            add('nodes', card)
    for node in ordered:
        add_node(node)
    for row in reversed(index['records'][-40:]):
        value = record(root, row['ref'])
        add('new_records', {**row, 'content': value['content'][:400], 'content_omitted': len(value['content']) > 400, 'read': {'ref': row['ref']}})
    # Snapshot Node cards omit relations, so a receipt cannot authorize their replacement.
    view['read_basis'] = basis.issue(root, full_nodes, session_id, fields=basis.EDIT_FIELDS - {'relations'})
    view['snapshot_id'] = 'snapshot_' + digest({key: value for key, value in view.items() if key != 'snapshot_id'})
    if _size(view) > max_bytes:
        raise ValueError('snapshot_budget_too_small')
    return view


def documents(root):
    """Return disposable Markdown projections without touching the filesystem."""
    root = Path(root)
    graph = relations.graph(root)
    from .results import publication_order
    published = publication_order(root, graph)
    output = {}
    overview = ['# Research Memory', '', 'Generated from immutable research records.']
    history = journal(root)['records']
    for node in graph['nodes'].values():
        overview.append(f"- [{node['title']}](nodes/{node['id']}/README.md) — {node['status']}")
        lines = ['# ' + node['title'], '', 'Generated view; use research tools to change canonical memory.']
        for key in ('goal', 'proposal', 'plan', 'progress', 'assessment_ref'):
            lines.extend(['', '## ' + key, '', node.get(key) or '(not recorded)'])
        lines.extend(['', '## Subjects', '', json.dumps(node.get('subjects', {}), ensure_ascii=False)])
        lines.extend(['', '## Relations', ''])
        lines.extend(f"- {e['source']} {e['kind']} {e['target']} ({e['id']})" for e in graph['relations'].values() if e['active'] and node['id'] in (e['source'], e['target']))
        lines.extend(['', '## Results', ''])
        from .context import result_notices
        from .results import get_result
        for r in published:
            if r['node_id'] == node['id']:
                notices = result_notices(root, get_result(root, r['id']), graph)
                lines.append(f"- [{r['summary']}](results/{r['id']}.json)" + (' — needs review: ' + ', '.join(sorted({n['code'] for n in notices})) if notices else ''))
        lines.extend(['', '## History', ''])
        for row in history:
            if row.get('node_id') == node['id']:
                lines.append(f"- [{row['kind']}: {row['title']}](../../records/{row['ref']}.json)")
        output[f"research/nodes/{node['id']}/README.md"] = '\n'.join(lines) + '\n'
    output['research/README.md'] = '\n'.join(overview) + '\n'
    return output


def render(root):
    """Regenerate Markdown only; no scientific state is read from these files."""
    root = Path(root)
    for relative, content in documents(root).items():
        path = root / relative
        if path_has_symlink(path):
            raise ValueError('view_path_symlink')
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative != 'research/README.md':
            (path.parent / 'work').mkdir(exist_ok=True)
        if not path.exists() or path.read_text(encoding='utf-8') != content:
            path.write_text(content, encoding='utf-8')
