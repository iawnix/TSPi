from __future__ import annotations

from pathlib import Path

from ts_workspace.io import write_json
from ts_workspace.trajectory import project_research_trajectory


def test_research_trajectory_does_not_follow_a_symlinked_decision_directory(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    external = tmp_path / "external-decisions"
    external.mkdir()
    write_json(
        external / "dec_1.json",
        {
            "decision_id": "dec_1",
            "rationale": "This external text must not enter the workspace projection.",
            "basis_refs": [],
            "created_at": "2026-08-24T00:00:00Z",
        },
    )
    (root / "decisions").symlink_to(external, target_is_directory=True)

    trajectory = project_research_trajectory(
        root,
        [
            {
                "phase_id": "phase_1",
                "title": "Test phase",
                "objective": "Verify the read boundary.",
                "created_by_decision": "dec_1",
            }
        ],
        [
            {
                "node_id": "node_1",
                "phase_ref": "phase_1",
                "title": "Test node",
                "objective": "Verify the read boundary.",
                "deliverable": "One projection result.",
                "status": "open",
                "dependency_refs": [],
                "claim_refs": [],
                "created_by_decision": "dec_1",
            }
        ],
    )

    assert trajectory["phases"][0]["opening_decision"] is None
    assert trajectory["nodes"][0]["opening_decision"] is None
