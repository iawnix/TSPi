from __future__ import annotations

import json
from pathlib import Path

from ts_workspace import validate_workspace


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_NAMES = [
    "single_step_success",
    "single_to_multistep_backtrack",
    "multistep_to_single_backtrack",
]


def test_plan_fixtures_are_executable_workspaces() -> None:
    for name in FIXTURE_NAMES:
        fixture = ROOT / "fixtures" / name
        assert fixture.is_dir()
        assert (fixture / "validate_workspace.ok.json").exists()
        assert (fixture / "report_workspace.golden.json").exists()
        assert (fixture / "web_normalized.golden.json").exists()
        assert validate_workspace(fixture)["valid"] is True


def test_backtrack_fixtures_use_canonical_events() -> None:
    for name in ["single_to_multistep_backtrack", "multistep_to_single_backtrack"]:
        fixture = ROOT / "fixtures" / name
        tree = json.loads((fixture / "tree.json").read_text(encoding="utf-8"))
        normalized = json.loads((fixture / "web_normalized.golden.json").read_text(encoding="utf-8"))
        assert normalized["backtrack_events"] == tree["backtrack_events"]
        for event in tree["backtrack_events"]:
            assert {"from_node", "to_node", "new_branch_node", "changed_variable", "reason_code"} <= set(event)
