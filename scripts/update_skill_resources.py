"""Regenerate Skill documentation/resource digests without executing extensions."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def digest(path):return 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for manifest in (ROOT/'extensions').glob('*/manifest.json'):
        data=json.loads(manifest.read_text())
        for entry in data.get('skills',[]):
            skill=manifest.parent/entry['path']
            entry['sha256']=digest(skill/'SKILL.md')
            resources=sorted(p for p in skill.rglob('*') if p.is_file()
                             and p.name not in {'resources.json', 'manifest.json'}
                             and '__pycache__' not in p.parts and p.suffix != '.pyc')
            shared=manifest.parent/'skills/_shared'
            if (skill/'scripts').is_dir() and shared.is_dir():resources+=sorted(shared.rglob('*.py'))
            index={'schema_version':'skill-resources/1','base':'extension',
                   'files':{str(p.relative_to(manifest.parent)):digest(p) for p in resources}}
            path=skill/'resources.json';path.write_text(json.dumps(index,indent=2)+'\n')
            entry['resources_sha256']=digest(path)
        for validator in data.get('validators', []):
            validator['sha256'] = digest(manifest.parent / validator['entry'])
            for resource in validator.get('resources', {}).values():
                resource['sha256'] = digest(manifest.parent / resource['path'])
        manifest.write_text(json.dumps(data,indent=2)+'\n')


if __name__=='__main__':main()
