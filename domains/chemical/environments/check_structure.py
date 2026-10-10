"""Offline installation check, executed inside the selected structure Job."""
import json
import os
from pathlib import Path
import tomllib

from rdkit import Chem

path = os.environ.get('RESEARCH_AGENT_NAME_RESOLVER_CONFIG')
if not path and os.environ.get('RESEARCH_AGENT_INSTALL_ROOT'):
    path = str(Path(os.environ['RESEARCH_AGENT_INSTALL_ROOT']) / 'etc/name-resolver.toml')
if not path:
    raise RuntimeError('resolver configuration is not bound to this Job')
with Path(path).open('rb') as stream:
    configuration = tomllib.load(stream)
if configuration.get('default_resolver', 'auto') not in {'auto', 'pubchem', 'opsin'}:
    raise RuntimeError('invalid resolver preference')
if not isinstance(configuration.get('backends', {}), dict):
    raise RuntimeError('invalid resolver backends')
assert Chem.MolFromSmiles('CCO').GetNumAtoms() == 3
Path('structure-check.json').write_text(json.dumps({'graph': 'passed', 'resolver_binding': 'passed',
                                                  'external_services': 'not_checked'}) + '\n')
