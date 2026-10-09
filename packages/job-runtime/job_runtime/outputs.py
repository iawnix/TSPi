"""Collect file facts without interpreting domain results."""
from pathlib import Path
import hashlib


def collect_outputs(root, declarations):
    root=Path(root).resolve();rows=[];errors=[]
    for item in declarations:
        path=(root/item['path']).resolve()
        if not path.is_relative_to(root):raise ValueError('output escapes job cwd')
        if item.get('recursive'):
            files = sorted(child for child in path.rglob('*') if child.is_file()) if path.is_dir() else []
            if not files:
                rows.append({'path':item['path'], 'required':item.get('required', False), 'exists':False})
                if item.get('required'):errors.append({'path':item['path'], 'error':'empty_or_missing_directory'})
                continue
            children = [{**item, 'path':str(child.relative_to(root)), 'recursive':False} for child in files]
            child_rows, validation = collect_outputs(root, children)
            rows.extend(child_rows);errors.extend(validation['errors'])
            continue
        row={'path':item['path'],'required':item.get('required',False),'exists':path.is_file()}
        if path.is_file():
            row.update(size=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            if row['size'] < item.get('min_bytes',0):errors.append({'path':item['path'],'error':'too_small'})
        elif row['required']:errors.append({'path':item['path'],'error':'missing'})
        rows.append(row)
    return list({row['path']:row for row in rows}.values()), {'complete':not errors,'errors':errors}
