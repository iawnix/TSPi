"""Consume the same verified extension snapshot as the Native Worker.

The Node manifest loader owns discovery and contract/resource validation. A
Worker sends its snapshot over its private bridge before handling commands.
Standalone commands obtain a snapshot through that same loader, never a second
directory scan with a different extension policy.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess

from .env import resolve_package_root

_snapshot = None
_worker_owned = False


def install_snapshot(value):
    global _snapshot, _worker_owned
    if _snapshot is not None or not isinstance(value, dict) or value.get('schema_version') != 'tspi-extension-catalog/1':
        raise ValueError('extension_catalog_invalid_or_already_configured')
    if not isinstance(value.get('extensions'), list):
        raise ValueError('extension_catalog_invalid')
    _snapshot = copy.deepcopy(value)
    _worker_owned = True


def installed_extensions():
    if _worker_owned:
        return copy.deepcopy(_snapshot['extensions'])
    package = resolve_package_root()
    # Standalone commands have no Worker lifecycle to delimit an immutable
    # snapshot. Revalidate on use so an edited manifest/resource cannot reuse a
    # prior successful validation merely because its path is unchanged.
    result = subprocess.run([os.environ.get('TSPI_NODE', 'node'),
                             str(package / 'apps/app-server/extension-manifest-loader.mjs'), str(package)],
                            capture_output=True, text=True, check=False, timeout=30)
    if result.returncode:
        raise ValueError('extension_catalog_rejected: ' + result.stderr.strip())
    return json.loads(result.stdout)['extensions']


def registered_entry(collection, identifier, version):
    if not isinstance(version, str) or not version:
        raise ValueError(collection + '_version_required')
    matches = [(Path(extension['root']), entry) for extension in installed_extensions()
               for entry in extension.get(collection, [])
               if entry['id'] == identifier and entry['version'] == version]
    if len(matches) != 1:
        raise ValueError(collection + '_not_registered: use an installed id and version')
    return matches[0]
