"""Rebuildable SQLite search and bounded, explicit research reads."""
import json
import sqlite3
from pathlib import Path
from research_agent.foundation.transactions import TransactionCoordinator, read_json
from research_agent.foundation.path_safety import path_has_symlink
from .records import workspace, journal, record, digest
from .nodes import get_node
from .results import get_result
from . import relations, basis


def _index(root):
    directory = Path(root) / 'research/search'
    if path_has_symlink(directory / 'index.sqlite'):
        raise ValueError('search_path_symlink')
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / 'index.sqlite')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS meta (sequence INTEGER NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS objects (ref TEXT PRIMARY KEY, sequence INTEGER, origin TEXT, kind TEXT, node_id TEXT, title TEXT, content TEXT, searchable TEXT, created_at TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS object_node ON objects(node_id, sequence)')
    db.execute('CREATE INDEX IF NOT EXISTS object_kind ON objects(kind, sequence)')
    cursor = db.execute('SELECT sequence FROM meta').fetchone()
    sequence = cursor[0] if cursor else 0
    index = journal(root)
    if sequence > index['sequence']:
        db.execute('DELETE FROM objects')
        sequence = 0
    for header in index['records']:
        if header['sequence'] <= sequence:
            continue
        value = record(root, header['ref'])
        items = [(value['ref'], value['kind'], value['title'], value['content'])]
        if value['data'].get('node'):
            node = value['data']['node']
            items.append((node['id'], 'node', node['title'], json.dumps(node, ensure_ascii=False)))
        if value['data'].get('result_id'):
            result = get_result(root, value['data']['result_id'])
            items.append((result['id'], 'result', result['summary'], json.dumps(result, ensure_ascii=False)))
        for ref, kind, title, content in items:
            db.execute('INSERT OR REPLACE INTO objects VALUES (?,?,?,?,?,?,?,?,?)',
                       (ref, value['sequence'], value['origin'], kind, value['node_id'], title, content,
                        (title + '\n' + content).casefold(), value['created_at']))
    db.execute('DELETE FROM meta')
    db.execute('INSERT INTO meta VALUES (?)', (index['sequence'],))
    db.commit()
    return db


def search(root, *, query='', origin=None, node_id=None, kind=None, after_sequence=0, offset=0, limit=20, session_id=None):
    if not isinstance(query, str) or len(query) > 1000 or origin not in {None, 'user', 'runtime', 'agent'}:
        raise ValueError('search_filter_invalid')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('search_pagination_invalid')
    if type(after_sequence) is not int or after_sequence < 0:
        raise ValueError('search_sequence_invalid')
    with TransactionCoordinator(root).locked():
        root = workspace(root)
        where, args = ['sequence > ?', 'instr(searchable, ?) > 0'], [after_sequence, query.casefold()]
        for name, value in [('origin', origin), ('node_id', node_id), ('kind', kind)]:
            if value is not None:
                where.append(name + ' = ?')
                args.append(value)
        condition = ' AND '.join(where)
        db = _index(root)
        try:
            total = db.execute('SELECT count(*) FROM objects WHERE ' + condition, args).fetchone()[0]
            rows = db.execute('SELECT ref,sequence,origin,kind,node_id,title,substr(content,1,600) AS excerpt,created_at FROM objects WHERE ' + condition + ' ORDER BY sequence DESC, ref LIMIT ? OFFSET ?', [*args, limit, offset]).fetchall()
        finally:
            db.close()
        return {'schema_version': 'research-search/2', 'records': [{**dict(row), 'read': {'ref': row['ref']}} for row in rows],
                'total': total, 'next_offset': offset + limit if offset + limit < total else None,
                'index_sequence': journal(root)['sequence']}


def node_detail(root, node_id, *, jobs=()):
    node = get_node(root, node_id)
    graph = relations.graph(root)
    results = [item for item in graph['results'].values() if item['node_id'] == node_id]
    assessment = None
    if node['assessment_ref']:
        ref = node['assessment_ref']
        assessment = get_result(root, ref) if ref.startswith('result_') else record(root, ref)
    links = relations.links(root, node_id)
    # Edges from a Result inherit its producing Node for navigation only.
    result_ids = {item['id'] for item in results}
    links.extend(e for e in graph['relations'].values() if e['active'] and (e['source'] in result_ids or e['target'] in result_ids))
    reviews = [{'used': e['target'], 'superseded_by': replacement['id'], 'relation_id': e['id']}
               for e in links if e['source'] in result_ids | {node_id}
               for replacement in graph['results'].values() if replacement['supersedes'] == e['target']]
    return {'node': node, 'relations': links, 'results': results, 'assessment': assessment,
            'review_notices': reviews, 'diagnostics': [d for d in relations.diagnostics(root) if node_id in d.get('node_ids', [])], 'jobs': [j for j in jobs if j.get('node_id') == node_id],
            'history': {'tool': 'research_search', 'node_id': node_id}}


def read(root, *, ref, offset=0, limit=16000, session_id=None, jobs=(), field=None):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 32000:
        raise ValueError('read_bounds_invalid')
    with TransactionCoordinator(root).locked():
        root = workspace(root)
        value = node_detail(root, ref, jobs=jobs) if ref.startswith('node_') else get_result(root, ref) if ref.startswith('result_') else record(root, ref)
        selected = None
        if field is not None:
            if not ref.startswith('node_') or field not in basis.EDIT_FIELDS:
                raise ValueError('node_field_invalid')
            selected = {'node_id': value['node']['id'], 'node_revision': value['node']['revision'], 'field': field,
                        'value': value['relations'] if field == 'relations' else value['node'][field]}
        full = json.dumps(selected if selected is not None else value, ensure_ascii=False, indent=2)
        chunk = full[offset:offset + limit]
        # Character offsets are stable across Unicode; bytes bound transport size.
        while len(chunk.encode()) > 30000:
            chunk = chunk[:max(1, len(chunk) * 3 // 4)]
        end = offset + len(chunk)
        response = {'schema_version': 'research-read/2', 'ref': ref, 'text': chunk, 'offset': offset,
                    'offset_unit': 'unicode_characters', 'total_characters': len(full),
                    'next_offset': end if end < len(full) else None}
        if ref.startswith('node_'):
            visible = []
            for item_field in ([] if selected is not None else basis.EDIT_FIELDS):
                field_name = item_field
                container = value if field_name == 'relations' else value['node']
                prefix = ('  ' if field_name == 'relations' else '    ') + json.dumps(field_name) + ': '
                start = full.find(prefix)
                serialized = json.dumps(container[field_name], ensure_ascii=False, indent=2)
                # Scalar Node fields are one JSON value. Relations need the complete detail.
                if field_name == 'relations':
                    if offset == 0 and end == len(full):
                        visible.append(field_name)
                elif offset <= start and start + len(prefix) + len(serialized) <= end:
                    visible.append(field_name)
            response['node_id'] = value['node']['id']
            response['node_revision'] = value['node']['revision']
            if selected is not None and offset == 0 and end == len(full):
                visible.append(field)
                response.update(selected)
            segments = {field: {'digest': digest(full), 'total_characters': len(full), 'ranges': [[offset, end]]}} if selected is not None and chunk else None
            if visible or segments:
                response['read_basis'] = basis.issue(root, [value['node']], session_id, fields=visible, segments=segments)
        # Structured convenience fields only when the combined response fits Pi's bound.
        if selected is None and offset == 0 and end == len(full) and len(full.encode()) < 15000:
            response.update(value if ref.startswith('node_') else {'result' if ref.startswith('result_') else 'record': value})
        return response
