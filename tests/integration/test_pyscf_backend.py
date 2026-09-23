from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.support.workspace_helpers import bootstrap_workspace_fixture, start_research_node
from ts_agent.backends.pyscf import PYSCF_ARTIFACTS, normalize_pyscf_settings
from ts_agent.compute import (
    create_calculation_intent,
    list_calculation_artifacts,
    parse_calculation,
    prepare_calculation,
)


def test_pyscf_compute_flow_binds_runtime_and_parses_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compute_config = tmp_path / "compute.toml"
    compute_config.write_text(
        """default_environment = \"local\"

[environments.local]
kind = \"local\"

[environments.local.backends.pyscf]
command = \"/opt/pyscf/bin/python\"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TS_COMPUTE_CONFIG", str(compute_config))

    workspace = bootstrap_workspace_fixture(tmp_path / "workspace")
    node_id = start_research_node(workspace, objective="Run one CF22D single point.")["node_id"]
    input_path = workspace / "inputs" / "molecule.xyz"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text("2\nH2\nH 0 0 0\nH 0 0 0.7\n", encoding="utf-8")
    catalog = {
        item["path"]: item for item in list_calculation_artifacts(workspace)["artifacts"]
    }

    created = create_calculation_intent(
        workspace,
        {
            "schema_version": "ts-calculation-request/5",
            "node_id": node_id,
            "purpose": "Compute one bounded CF22D single point.",
            "attempt_kind": "primary",
            "lineage": None,
            "capability": "pyscf.sp",
            "capability_version": "1",
            "input_artifacts": [
                {"input_role": "xyz", "artifact_id": catalog["inputs/molecule.xyz"]["artifact_id"]}
            ],
            "parameters": {"basis": "def2-svp", "threads": 2},
            "execution_target": {"kind": "local"},
            "dry_run": True,
        },
    )
    prepared = prepare_calculation(workspace, created["intent_ref"])["prepared"]
    assert prepared["prepared_task"]["command"][0] == "/opt/pyscf/bin/python"
    assert [Path(ref).name for ref in prepared["prepared_task"]["expected_artifacts"]] == list(
        PYSCF_ARTIFACTS["sp"]
    )

    output_dir = workspace / "nodes" / node_id / "attempts" / created["intent_id"] / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    settings = normalize_pyscf_settings({"basis": "def2-svp", "threads": "2"}, "sp")
    (output_dir / "pyscf.out").write_text(
        "PYSCF_RUN_COMPLETED {\"task_type\": \"sp\"}\n", encoding="utf-8"
    )
    (output_dir / "pyscf_result.json").write_text(
        json.dumps(
            {
                "schema_version": "pyscf-run/1",
                "backend": "pyscf",
                "task_type": "sp",
                "execution_completed": True,
                "pyscf_version": "2.8.0",
                "settings": settings,
                "summary": {
                    "electronic_energy_hartree": -1.1,
                    "scf_converged": True,
                },
            }
        ),
        encoding="utf-8",
    )

    result = parse_calculation(
        workspace,
        created["intent_id"],
        (output_dir / "pyscf_result.json").relative_to(workspace).as_posix(),
    )

    assert result["program_status"] == "completed"
    assert result["task_validation"] == {"status": "completed", "failures": []}
    assert result["provenance"]["parser_contract"] == "pyscf.output/1"
    assert (output_dir / "parsed/pyscf_summary.json").is_file()
