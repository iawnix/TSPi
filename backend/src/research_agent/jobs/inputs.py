"""Byte identity for immutable Job inputs, including directory resources."""
import hashlib
import json


def content_digest(path):
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {str(f.relative_to(path)): hashlib.sha256(f.read_bytes()).hexdigest()
                for f in sorted(path.rglob("*")) if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc"}
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
