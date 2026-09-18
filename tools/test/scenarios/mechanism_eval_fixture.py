"""Isolated synthetic inputs for live capability-choice evaluation; no remote jobs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages/ts-agent-kernel"))
from tests.support.workspace_helpers import bootstrap_workspace_fixture, start_research_node
from tests.unit.test_scientific_analysis import gaussian_log, barrier, reaction, source
from ts_agent.analysis.engine import evaluate
from ts_agent.compute.artifacts import list_calculation_artifacts
from ts_agent.workspace.dispatch import set_node_dispatch


def create(root, case_id):
    workspace = bootstrap_workspace_fixture(root)
    node = start_research_node(workspace)["node_id"]
    cases = {}
    directory = workspace / "nodes" / node / "inputs"
    directory.mkdir(parents=True)
    files = {
        "ts.log": gaussian_log(imaginary=True),
        "reaction.json": json.dumps(reaction()),
        "mapping.json": json.dumps(evaluate("reaction.mapping.generate", source(reaction=reaction()), {})),
        "barrier_a.json": json.dumps(barrier(activation=50)),
        "barrier_b.json": json.dumps(barrier(activation=45)),
        "candidate.xyz": "2\nSynthetic alternative\nH 0 0 0\nH 0.8 0 0\n",
        "failed.json": json.dumps({"normal_termination": False, "reason": "optimization did not converge; synthetic fixture"}),
        "irc.log": "\n".join([" #P HF/STO-3G IRC=(Forward,CalcFC,MaxPoints=2)", " -----", " SCF Done: E(RHF) = -1.0 A.U.",
            " Point Number 1 in FORWARD path direction.", " Point Number: 1 Path Number: 1", " CURRENT STRUCTURE", " 1 1 0.0 0.0 0.0", " 2 1 0.8 0.0 0.0",
            " NET REACTION COORDINATE UP TO THIS POINT = 0.1", " Calculation of FORWARD path complete.", " Normal termination of Gaussian 16", ""]),
    }
    selected = {"definition": [], "existing_ts": ["ts.log"], "existing_irc": ["irc.log"], "ambiguous_mapping": ["reaction.json", "mapping.json"],
                "failed_search": ["failed.json", "candidate.xyz"], "competing_paths": ["barrier_a.json", "barrier_b.json"], "node_management": []}[case_id]
    for name, content in files.items():
        if name not in selected:
            continue
        (directory / name).write_text(content)
    artifacts = {Path(row["path"]).name: {"id": row["artifact_id"], "path": row["path"]} for row in list_calculation_artifacts(workspace)["artifacts"]}
    return {"workspace": str(workspace), "node": node, "artifacts": artifacts}


if __name__ == "__main__":
    print(json.dumps(create(Path(sys.argv[1]), sys.argv[2])))
