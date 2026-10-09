"""Pure process settings shared by local supervisors and remote wrappers."""
from __future__ import annotations

import hashlib
import os
from pathlib import PurePosixPath
import re


def minimum_environment(home=None):
    return {"PATH": os.defpath, "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1", **({"HOME": home} if home is not None else {})}


def validate_environment(variables):
    if any(not isinstance(key, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key)
           or not isinstance(value, str) or '\0' in value for key, value in variables.items()):
        raise ValueError('invalid Job environment variable')


def job_process_environment(root, metadata, variables, *, home=None):
    validate_environment(variables)
    scratch_root = metadata.get('execution_binding', {}).get('binding', {}).get('scratch_root')
    scratch = str(PurePosixPath(scratch_root) / ('job-' + hashlib.sha256(str(root).encode()).hexdigest()[:32])
                  if scratch_root else PurePosixPath(root) / '.scratch')
    env = {**minimum_environment(home), 'TMPDIR': scratch}
    cpus = metadata.get('resources', {}).get('cpus')
    if cpus:
        env.update({name: str(cpus) for name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS')})
    env.update({key: value.replace('{scratch}', scratch) for key, value in variables.items()})
    return env, scratch
