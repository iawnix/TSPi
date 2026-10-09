"""Write the job.toml editor schema from its installation/runtime contract."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    spec = importlib.util.spec_from_file_location('job_contract', ROOT / 'backend/src/research_agent/jobs/config_contract.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (ROOT / 'config/job.schema.json').write_text(json.dumps(module.job_config_schema(), indent=2) + '\n')

if __name__ == '__main__':
    main()
