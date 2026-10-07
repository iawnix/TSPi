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
            scripts=skill/'scripts'
            if not scripts.is_dir():continue
            resources=sorted(scripts.rglob('*.py'))
            shared=manifest.parent/'skills/_shared'
            if shared.is_dir():resources+=sorted(shared.rglob('*.py'))
            index={'schema_version':'skill-resources/1','base':'extension',
                   'files':{str(p.relative_to(manifest.parent)):digest(p) for p in resources}}
            path=skill/'resources.json';path.write_text(json.dumps(index,indent=2)+'\n')
            entry['resources_sha256']=digest(path)
        manifest.write_text(json.dumps(data,indent=2)+'\n')


if __name__=='__main__':main()
