"""Prevent public Skill references from drifting from runtime tool contracts."""
from pathlib import Path
import subprocess


def test_generated_skill_public_contract_is_current():
    root = Path(__file__).resolve().parents[2]
    subprocess.run(["node", str(root / "scripts/update_public_contract.mjs"), "--check"], cwd=root, check=True, capture_output=True, text=True)
