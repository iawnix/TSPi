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


def build_snapshot(root, *, max_bytes=16000, session_id=None, focus_node_ids=(), events=(), jobs=(), projection=None):
    if not 2048 <= max_bytes <= 32000:
        raise ValueError('snapshot_budget_invalid: use 2048..32000 bytes')
    index, graph = journal(root), relations.graph(root)
    focus = list(dict.fromkeys([e['node_id'] for e in events if e.get('node_id')] + list(focus_node_ids)))
    priority = {node_id: (0, 'trigger_or_explicit_focus') for node_id in focus}
    for job in jobs:
        if job.get('node_id') and (job.get('execution_conflict') or job.get('collection_state') != 'complete'):
            priority.setdefault(job['node_id'], (1, 'execution_needs_attention'))
    result_owner = {ref: result['node_id'] for ref, result in graph['results'].items()}
    superseded = {r['supersedes'] for r in graph['results'].values() if r['supersedes']}
    for edge in graph['relations'].values():
        if not edge['active']:
            continue
        source = result_owner.get(edge['source'], edge['source'])
        target = result_owner.get(edge['target'], edge['target'])
        if source in focus and target in graph['nodes']:
            priority.setdefault(target, (2, 'explicit_relation_to_focus'))
        if target in focus and source in graph['nodes'] and edge['kind'] in {'alternative_to', 'requires', 'uses', 'cites'}:
            priority.setdefault(source, (2, 'related_research'))
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
            priority[node['id']] = min(priority.get(node['id'], (6, 'recent_research')), (3, 'current_session'))
    activity = {row['node_id']: row['sequence'] for row in index['records'] if row.get('node_id')}
    ordered = sorted(graph['nodes'].values(), key=lambda n: (priority.get(n['id'], (6, 'recent_research'))[0],
                     -int(n['status'] == 'open'), -activity.get(n['id'], 0), n['id']))
    view = {'schema_version': 'research-snapshot/2', 'workspace_id': read_json(Path(root) / 'workspace_manifest.json')['workspace_id'],
            'sequence': index['sequence'], 'nodes': [], 'tasks': [], 'new_records': [], 'running_jobs': [], 'uncollected_jobs': [],
            'diagnostics': [{'code': d['code'], 'node_count': len(d['node_ids']), 'node_ids': d['node_ids'][:3]} for d in relations.diagnostics(root)[:3]], 'events': [], 'wake_events': {'requested': len(events), 'included': 0, 'omitted': len(events)},
            'projection': projection or {'pending': 0}, 'bounds': {'max_bytes': max_bytes, 'omitted': {}},
            'read_more': {'nodes': {'tool': 'research_search', 'kind': 'node'}, 'tasks': {'tool': 'research_search', 'origin': 'user'},
                          'records': {'tool': 'research_search'}, 'events': {'tool': 'research_search', 'origin': 'runtime'}},
            'guidance': 'Original requests, authored research, and execution facts are distinct. Excerpts are incomplete; read the referenced object before replacing fields. Open Nodes do not schedule runs. Events shown do not imply analysis completed.'}
    # Reserve receipt/digest and omission counters before admitting any content.
    allowance = max_bytes - 600
    def add(key, value):
        view[key].append(value)
        if _size(view) > allowance:
            view[key].pop()
            view['bounds']['omitted'][key] = view['bounds']['omitted'].get(key, 0) + 1
            return False
        return True
    for event in events:
        compact = {k: event.get(k) for k in ('event_id', 'job_id', 'node_id', 'node_revision', 'state')}
        compact['read'] = {'tool': 'job_status', 'event_id': event['event_id']}
        if add('events', compact):
            view['wake_events']['included'] += 1
            view['wake_events']['omitted'] -= 1
    if latest:
        add('tasks', {'ref': latest['ref'], 'content': latest['content'][:500], 'content_omitted': len(latest['content']) > 500, 'read': {'ref': latest['ref']}})
    full_nodes = []
    def add_node(node):
        if _size(node) < 2400:
            outputs = [r for r in graph['results'].values() if r['node_id'] == node['id']]
            card = {**node, 'recent_results': [{'id': r['id'], 'summary': r['summary'][:240], 'content_omitted': len(r['summary']) > 240, 'read': {'ref': r['id']}} for r in outputs[-2:]], 'ranking_reason': priority.get(node['id'], (6, 'recent_research'))[1], 'read': {'ref': node['id']}}
            if add('nodes', card):
                full_nodes.append(node)
        else:
            card = {k: node[k] for k in ('id', 'revision', 'status', 'assessment_ref')}
            card.update(title=node['title'][:100], goal=node['goal'][:300], progress=(node.get('progress') or '')[:300], content_omitted=True, read={'ref': node['id']})
            add('nodes', card)
    # Reserve room for actual execution facts before expanding more research.
    leading = min(3, len(ordered))
    for node in ordered[:leading]:
        add_node(node)
    for job in jobs:
        key = 'running_jobs' if job.get('state') in {'started','submitted','queued','held','running','unknown'} else 'uncollected_jobs'
        if key == 'running_jobs' or job.get('collection_state') != 'complete' or job.get('execution_conflict'):
            add(key, job)
    for node in ordered[leading:]:
        add_node(node)
    for row in reversed(index['records'][-40:]):
        value = record(root, row['ref'])
        add('new_records', {**row, 'content': value['content'][:400], 'content_omitted': len(value['content']) > 400, 'read': {'ref': row['ref']}})
    view['bounds']['omitted']['older_records'] = max(0, len(index['records']) - 40)
    view['bounds']['omitted']['older_tasks'] = max(0, len(tasks) - 1)
    # Snapshot Node cards omit relations, so a receipt cannot authorize their replacement.
    view['read_basis'] = basis.issue(root, full_nodes, session_id, fields=basis.EDIT_FIELDS - {'relations'})
    view['snapshot_id'] = 'snapshot_' + digest(view)
    if _size(view) > max_bytes:
        raise ValueError('snapshot_budget_too_small')
    return view


def documents(root):
    """Return disposable Markdown projections without touching the filesystem."""
    root = Path(root)
    graph = relations.graph(root)
    output = {}
    overview = ['# Research Memory', '', 'Generated from immutable research records.']
    history = journal(root)['records']
    for node in graph['nodes'].values():
        overview.append(f"- [{node['title']}](nodes/{node['id']}/README.md) — {node['status']}")
        lines = ['# ' + node['title'], '', 'Generated view; use research tools to change canonical memory.']
        for key in ('goal', 'proposal', 'plan', 'progress', 'assessment_ref'):
            lines.extend(['', '## ' + key, '', node.get(key) or '(not recorded)'])
        lines.extend(['', '## Relations', ''])
        lines.extend(f"- {e['source']} {e['kind']} {e['target']} ({e['id']})" for e in graph['relations'].values() if e['active'] and node['id'] in (e['source'], e['target']))
        lines.extend(['', '## Results', ''])
        lines.extend(f"- [{r['summary']}](results/{r['id']}.json)" for r in graph['results'].values() if r['node_id'] == node['id'])
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
