"""Prepare public domain dependency caches before isolated installation tests."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess

from scripts._job_install import profiles, resource, digest
from tools.test.environment import locked


def prepare(package: Path, root: Path, names: list[str]):
    available = profiles(package)
    conda = os.environ.get('CORAGENT_TEST_CONDA') or shutil.which('conda')
    if not conda:
        raise ValueError('Set CORAGENT_TEST_CONDA before preparing scientific caches')
    for name in dict.fromkeys(names):
        if name not in available:
            raise ValueError('Unknown scientific preparation profile: ' + name)
        profile = available[name]
        lock = resource(Path(profile['root']), profile['lock'])
        identity = digest(lock.read_bytes())[:20]
        prefix = root / 'deps/scientific' / name / identity
        with locked(root, 'scientific-' + name + '-' + identity):
            receipt = prefix / '.prepared.json'
            if receipt.is_file():
                continue
            prefix.parent.mkdir(parents=True, exist_ok=True)
            with (root / 'registry' / ('prepare-scientific-' + name + '.log')).open('w') as log:
                # Download only upstream artifacts named in the public lock.
                # No private test file or environment is sent to a provider.
                subprocess.run([conda, 'create', '--yes', '--prefix', str(prefix), '--file', str(lock)],
                               stdout=log, stderr=subprocess.STDOUT, check=True)
            receipt.write_text(json.dumps({'profile': name, 'lock_sha256': digest(lock.read_bytes())}) + '\n')
