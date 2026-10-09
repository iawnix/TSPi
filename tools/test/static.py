"""Static gates executed from the same immutable snapshot as tests."""
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.test.manifest import audit
audit(ROOT)
for command in (
    [sys.executable,'tools/version.py','check'],
    [sys.executable,'tools/layout.py','--check'],
    [sys.executable,'scripts/update_resources.py','--check'],
    ['npm','run','typecheck'],
    [sys.executable,'tools/lint_architecture.py'],
    [sys.executable,'tools/lint_public_surface.py'],
    [sys.executable,'tools/lint_skills.py'],
):
    subprocess.run(command,cwd=ROOT,check=True)
