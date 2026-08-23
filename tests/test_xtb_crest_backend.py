from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.v5_helpers import bootstrap_v5_workspace, start_research_node
from ts_backends.base import BackendTask
from ts_backends.crest import prepare_crest
from ts_backends.xtb import (
    parse_vibrational_spectrum,
    parse_xtb_artifacts,
    prepare_xtb,
)
from ts_backends.xtb_scan import parse_xtb_scan_control
from ts_compute import (
    ComputeContractError,
    create_calculation_intent,
    list_calculation_artifacts,
    parse_calculation,
    prepare_calculation,
)
from ts_workspace.io import sha256_json


def test_xtb_prepares_typed_task_matrix() -> None:
    expected = {
        "sp": (["--sp"], ["xtb.out"]),
        "opt": (["--opt", "tight"], ["xtbopt.xyz", "xtb.out"]),
        "freq": (["--hess"], ["vibspectrum", "xtb.out"]),
        "opt_freq": (["--ohess", "tight"], ["xtbopt.xyz", "vibspectrum", "xtb.out"]),
        "scan": (
            ["--opt", "tight", "--input", "scan.inp"],
            ["xtbscan.log", "xtbopt.xyz", "xtb.out"],
        ),
        "md": (["--md", "--input", "md.inp"], ["xtb.trj", "xtb.out"]),
    }
    for task_type, (task_args, artifacts) in expected.items():
        inputs = {"xyz": "candidate.xyz"}
        if task_type in {"scan", "md"}:
            inputs["control"] = f"{task_type}.inp"
        settings = {
            "charge": "-1",
            "uhf": "1",
            "method": "gfn1",
            "solvent_model": "alpb",
            "solvent": "water",
        }
        if task_type in {"opt", "opt_freq", "scan"}:
            settings["opt_level"] = "tight"
        prepared = prepare_xtb(
            BackendTask(
                node_id="node_1",
                task_type=task_type,
                work_dir="nodes/node_1",
                inputs=inputs,
                settings=settings,
            )
        )
        assert prepared.command[0:2] == ["xtb", "candidate.xyz"]
        assert prepared.command[2 : 2 + len(task_args)] == task_args
        assert prepared.command[-8:] == [
            "--chrg",
            "-1",
            "--uhf",
            "1",
            "--gfn",
            "1",
            "--alpb",
            "water",
        ]
        assert prepared.expected_artifacts == artifacts


@pytest.mark.parametrize("task_type", ["scan", "md"])
def test_xtb_control_tasks_require_bound_control_input(task_type: str) -> None:
    with pytest.raises(ValueError, match="input roles"):
        prepare_xtb(
            BackendTask(
                node_id="node_1",
                task_type=task_type,
                work_dir="nodes/node_1",
                inputs={"xyz": "candidate.xyz"},
            )
        )


def test_xtb_scan_control_accepts_numbered_geometry_constraints(tmp_path: Path) -> None:
    control = tmp_path / "scan.inp"
    control.write_text(
        "\n".join(
            [
                "$constrain",
                "  force constant=1.0",
                "  distance: 1, 2, auto",
                "  angle: 1, 2, 3, 90.0",
                "  dihedral: 1, 2, 3, 4, 180.0",
                "$scan",
                "  mode=concerted",
                "  1: 0.9, 1.1, 3",
                "  2: 85.0, 95.0, 3",
                "  3: 170.0, 190.0, 3",
                "$end",
            ]
        ),
        encoding="utf-8",
    )

    plan = parse_xtb_scan_control(control, atom_count=4)

    assert plan.mode == "concerted"
    assert plan.point_count == 3
    assert [constraint.kind for constraint in plan.constraints] == [
        "distance",
        "angle",
        "dihedral",
    ]
    assert [directive.constraint_index for directive in plan.directives] == [1, 2, 3]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("$constrain\n distance: 1, 2, auto\n$end\n", "both.*sections"),
        (
            "$constrain\n distance: 1, 4, auto\n$scan\n 1: 1.0, 2.0, 3\n$end\n",
            "atom index exceeds",
        ),
        (
            "$constrain\n distance: 1, 2, auto\n$scan\n 2: 1.0, 2.0, 3\n$end\n",
            "undefined constraint",
        ),
        (
            "$constrain\n distance: 1, 2, auto\n$scan\n 1: -1.0, 2.0, 3\n$end\n",
            "endpoints must be positive",
        ),
        (
            "$constrain\n distance: 1, 2, auto\n$scan\n mode=concerted\n"
            " 1: 1.0, 2.0, 3\n 1: 2.0, 1.0, 4\n$end\n",
            "equal step counts",
        ),
        (
            "$constrain\n distance: 1, 2, auto\n$metadyn\n save=10\n$scan\n"
            " 1: 1.0, 2.0, 3\n$end\n",
            "unsupported.*section",
        ),
    ],
)
def test_xtb_scan_control_rejects_unsafe_or_inconsistent_input(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    control = tmp_path / "scan.inp"
    control.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        parse_xtb_scan_control(control, atom_count=3)


def test_crest_prepares_distinct_conformer_search_backend() -> None:
    prepared = prepare_crest(
        BackendTask(
            node_id="node_1",
            task_type="conformer_search",
            work_dir="nodes/node_1",
            inputs={"xyz": "candidate.xyz"},
            settings={
                "charge": "0",
                "uhf": "0",
                "method": "gfn2",
                "search_level": "squick",
                "opt_level": "tight",
                "threads": "4",
                "solvent": "water",
                "solvent_model": "gbsa",
            },
        )
    )
    assert prepared.backend == "crest"
    assert prepared.command == [
        "crest",
        "candidate.xyz",
        "-chrg",
        "0",
        "-uhf",
        "0",
        "-gfn2",
        "-squick",
        "-opt",
        "tight",
        "-T",
        "4",
        "-g",
        "water",
    ]
    assert prepared.expected_artifacts == [
        "crest.energies",
        "crest.out",
        "crest_best.xyz",
        "crest_conformers.xyz",
    ]


def test_xtb_opt_freq_parse_consumes_bound_artifact_set_and_advances_collected_result(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    intent_path = _intent(workspace, "xtb", "opt_freq")
    prepared = prepare_calculation(workspace, intent_path)["prepared"]
    output_dir = _output_dir(workspace, prepared["intent_id"])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "xtb.out").write_text(_xtb_opt_freq_log(), encoding="utf-8")
    (output_dir / "xtbopt.xyz").write_text(_xyz(-5.070544409100), encoding="utf-8")
    spectrum = output_dir / "vibspectrum"
    spectrum.write_text(_vibspectrum(), encoding="utf-8")
    intent = json.loads((workspace / prepared["intent_ref"]).read_text(encoding="utf-8"))
    collected = {
        "schema_version": "ts-calculation-result/2",
        "job_id": "123.cluster",
        "intent_id": intent["intent_id"],
        "node_id": intent["node_id"],
        "state": "collected",
        "program_status": "completed",
        "exit_status": 0,
        "artifact_refs": [
            path.relative_to(workspace).as_posix()
            for path in (output_dir / "xtb.out", output_dir / "xtbopt.xyz", spectrum)
        ],
        "parser_facts": {},
        "error_class": None,
        "provenance": {
            "backend": "xtb",
            "intent_digest": sha256_json(intent),
            "intent_schema": "ts-calculation-intent/5",
            "attempt_kind": "primary",
            "recalculation_ref": None,
        },
    }
    (output_dir / "calculation_result.json").write_text(
        json.dumps(collected),
        encoding="utf-8",
    )

    result = parse_calculation(
        workspace,
        intent["intent_id"],
        (output_dir / "xtb.out").relative_to(workspace).as_posix(),
    )

    assert result["state"] == "parsed"
    assert result["program_status"] == "completed"
    assert result["job_id"] == "123.cluster"
    assert result["exit_status"] == 0
    assert result["parser_facts"]["execution_completed"] is True
    assert result["parser_facts"]["task_completed"] is True
    assert result["parser_facts"]["artifacts_complete"] is True
    assert result["parser_facts"]["optimization_converged"] is True
    assert result["parser_facts"]["frequency_count"] == 9
    assert result["parser_facts"]["imaginary_frequency_count"] == 1
    assert result["parser_facts"]["imaginary_frequencies_cm-1"] == [-125.5]
    assert result["provenance"]["parser_contract"] == "xtb-task-parser/1"
    assert len(result["provenance"]["parser_inputs"]) == 3
    assert (output_dir / "parsed/xtb_summary.json").is_file()
    assert (output_dir / "parsed/frequencies.json").is_file()
    assert parse_calculation(
        workspace,
        intent["intent_id"],
        (output_dir / "xtb.out").relative_to(workspace).as_posix(),
    ) == result

    spectrum.write_text(_vibspectrum().replace("-125.50", "-225.50"), encoding="utf-8")
    with pytest.raises(ComputeContractError, match="different source content"):
        parse_calculation(
            workspace,
            intent["intent_id"],
            (output_dir / "xtb.out").relative_to(workspace).as_posix(),
        )


def test_xtb_sp_parse_accepts_native_colon_summary(tmp_path: Path) -> None:
    output = tmp_path / "xtb.out"
    output.write_text(
        "\n".join(
            [
                "* xtb version 6.7.1 (test)",
                "Hamiltonian                  GFN2-xTB",
                "*** convergence criteria satisfied after 8 iterations ***",
                ":: total energy              -5.065772968305 Eh    ::",
                ":: gradient norm              0.097095675437 Eh/a0 ::",
                ":: HOMO-LUMO gap             16.326799898512 eV    ::",
                "* finished run on 2026/08/06 at 19:06:46.679",
            ]
        ),
        encoding="utf-8",
    )

    facts = parse_xtb_artifacts("sp", {"xtb.out": output})["summary"]

    assert facts["execution_completed"] is True
    assert facts["task_completed"] is True
    assert facts["total_energy_hartree"] == pytest.approx(-5.065772968305)
    assert facts["gradient_norm_hartree_per_bohr"] == pytest.approx(0.097095675437)
    assert facts["homo_lumo_gap_ev"] == pytest.approx(16.326799898512)


def test_xtb_gfnff_completion_does_not_require_scc_convergence(tmp_path: Path) -> None:
    output = tmp_path / "xtb.out"
    output.write_text(
        "\n".join(
            [
                "* xtb version 6.7.1 (test)",
                "Hamiltonian                  GFN-FF",
                ":: total energy              -5.065772968305 Eh    ::",
                "* finished run on 2026/08/06 at 19:06:46.679",
            ]
        ),
        encoding="utf-8",
    )

    facts = parse_xtb_artifacts("sp", {"xtb.out": output})["summary"]

    assert facts["scc_convergence_applicable"] is False
    assert facts["scc_converged"] is None
    assert facts["task_completed"] is True


def test_xtb_vibrational_parser_accepts_raman_columns(tmp_path: Path) -> None:
    spectrum = tmp_path / "vibspectrum"
    spectrum.write_text(
        "\n".join(
            [
                "$vibrational spectrum",
                "# mode symmetry wave number IR intensity Raman activity cross-section IR RAMAN",
                "     1                    -0.00       0.00000       0.00000  0.00000E+00  -  -",
                "     2        a         -125.50      10.00000       2.00000  0.10000E-02 YES YES",
                "     3        a         1539.11     133.29925      4.00000  0.20000E-02 YES YES",
                "$end",
            ]
        ),
        encoding="utf-8",
    )

    assert parse_vibrational_spectrum(spectrum) == [-0.0, -125.5, 1539.11]


def test_xtb_scan_parse_binds_control_points_coordinates_and_energies(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    intent_path = _intent(workspace, "xtb", "scan")
    prepared = prepare_calculation(workspace, intent_path)["prepared"]
    output_dir = _output_dir(workspace, prepared["intent_id"])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "xtb.out").write_text(_xtb_scan_log(), encoding="utf-8")
    (output_dir / "xtbscan.log").write_text(
        _scan_xyz(-5.10, 0.90) + _scan_xyz(-5.20, 1.00) + _scan_xyz(-5.15, 1.10),
        encoding="utf-8",
    )
    (output_dir / "xtbopt.xyz").write_text(_xyz(-5.15), encoding="utf-8")

    result = parse_calculation(
        workspace,
        prepared["intent_id"],
        (output_dir / "xtb.out").relative_to(workspace).as_posix(),
    )

    facts = result["parser_facts"]
    assert result["program_status"] == "completed"
    assert facts["scan_mode"] == "sequential"
    assert facts["scan_expected_point_count"] == 3
    assert facts["scan_point_count"] == 3
    assert facts["scan_min_energy_hartree"] == pytest.approx(-5.20)
    assert facts["scan_complete"] is True
    assert len(result["provenance"]["parser_inputs"]) == 4
    parsed = json.loads((output_dir / "parsed/scan_points.json").read_text(encoding="utf-8"))
    assert parsed["schema_version"] == "xtb-scan-points/1"
    assert [point["coordinates"][0]["target_value"] for point in parsed["points"]] == [
        0.9,
        1.0,
        1.1,
    ]
    assert [point["coordinates"][0]["actual_value"] for point in parsed["points"]] == pytest.approx(
        [0.9, 1.0, 1.1]
    )
    assert all("coordinates" not in constraint for constraint in parsed["constraints"])


def test_xtb_concerted_scan_parser_handles_distance_angle_and_dihedral(tmp_path: Path) -> None:
    control = tmp_path / "scan.inp"
    control.write_text(
        "\n".join(
            [
                "$constrain",
                "  distance: 1, 2, auto",
                "  angle: 1, 2, 3, auto",
                "  dihedral: 1, 2, 3, 4, auto",
                "$scan",
                "  mode=concerted",
                "  1: 1.0, 1.1, 2",
                "  2: 90.0, 100.0, 2",
                "  3: -90.0, 90.0, 2",
                "$end",
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "xtb.out"
    output.write_text(_xtb_scan_log(), encoding="utf-8")
    trajectory = tmp_path / "xtbscan.log"
    trajectory.write_text(_four_atom_scan_xyz(-5.0) + _four_atom_scan_xyz(-4.9), encoding="utf-8")
    optimized = tmp_path / "xtbopt.xyz"
    optimized.write_text(_four_atom_scan_xyz(-4.9), encoding="utf-8")

    parsed = parse_xtb_artifacts(
        "scan",
        {"xtb.out": output, "xtbscan.log": trajectory, "xtbopt.xyz": optimized},
        control=control,
    )

    assert parsed["summary"]["task_completed"] is True
    first = parsed["scan_points"]["points"][0]["coordinates"]
    assert [coordinate["kind"] for coordinate in first] == ["distance", "angle", "dihedral"]
    assert first[0]["actual_value"] == pytest.approx(1.0)
    assert first[1]["actual_value"] == pytest.approx(90.0)
    assert first[2]["actual_value"] == pytest.approx(90.0)


def test_xtb_scan_parser_rejects_an_incomplete_point_series(tmp_path: Path) -> None:
    control = tmp_path / "scan.inp"
    control.write_text(
        "$constrain\n  distance: 1, 2, auto\n$scan\n  1: 0.9, 1.1, 3\n$end\n",
        encoding="utf-8",
    )
    output = tmp_path / "xtb.out"
    output.write_text(_xtb_scan_log(), encoding="utf-8")
    trajectory = tmp_path / "xtbscan.log"
    trajectory.write_text(_scan_xyz(-5.10, 0.90) + _scan_xyz(-5.20, 1.00), encoding="utf-8")
    optimized = tmp_path / "xtbopt.xyz"
    optimized.write_text(_xyz(-5.20), encoding="utf-8")

    parsed = parse_xtb_artifacts(
        "scan",
        {"xtb.out": output, "xtbscan.log": trajectory, "xtbopt.xyz": optimized},
        control=control,
    )

    assert parsed["summary"]["scan_expected_point_count"] == 3
    assert parsed["summary"]["scan_point_count"] == 2
    assert parsed["summary"]["scan_complete"] is False
    assert parsed["summary"]["task_completed"] is False


def test_xtb_md_parse_reports_trajectory_without_embedding_coordinates(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    intent_path = _intent(workspace, "xtb", "md")
    prepared = prepare_calculation(workspace, intent_path)["prepared"]
    output_dir = _output_dir(workspace, prepared["intent_id"])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "xtb.out").write_text(_xtb_md_log(), encoding="utf-8")
    (output_dir / "xtb.trj").write_text(_xyz(-5.1) + _xyz(-5.2), encoding="utf-8")

    result = parse_calculation(
        workspace,
        prepared["intent_id"],
        (output_dir / "xtb.out").relative_to(workspace).as_posix(),
    )

    facts = result["parser_facts"]
    assert result["program_status"] == "completed"
    assert facts["md_completed"] is True
    assert facts["md_max_steps"] == 100
    assert facts["trajectory_frame_count"] == 2
    assert facts["trajectory_first_energy_hartree"] == pytest.approx(-5.1)
    assert facts["trajectory_last_energy_hartree"] == pytest.approx(-5.2)
    assert "coordinates" not in json.dumps(facts).lower()
    trajectory = json.loads((output_dir / "parsed/trajectory_summary.json").read_text(encoding="utf-8"))
    assert trajectory["frame_count"] == 2
    assert all(set(frame) == {"index", "title", "energy_hartree"} for frame in trajectory["frames"])


def test_xtb_parse_distinguishes_completed_process_from_missing_task_artifact(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    intent_path = _intent(workspace, "xtb", "opt")
    prepared = prepare_calculation(workspace, intent_path)["prepared"]
    output_dir = _output_dir(workspace, prepared["intent_id"])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "xtb.out").write_text(_xtb_opt_freq_log(), encoding="utf-8")

    result = parse_calculation(
        workspace,
        prepared["intent_id"],
        (output_dir / "xtb.out").relative_to(workspace).as_posix(),
    )

    assert result["program_status"] == "failed"
    assert result["error_class"] == "xtb_artifacts_incomplete"
    assert result["parser_facts"]["execution_completed"] is True
    assert result["parser_facts"]["optimization_converged"] is True
    assert result["parser_facts"]["artifacts_complete"] is False
    assert result["parser_facts"]["missing_artifacts"] == ["xtbopt.xyz"]


def test_crest_parse_reports_ensemble_and_relative_energy_consistency(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    intent_path = _intent(workspace, "crest", "conformer_search")
    prepared = prepare_calculation(workspace, intent_path)["prepared"]
    output_dir = _output_dir(workspace, prepared["intent_id"])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "crest.out").write_text(
        "Version 3.0.2\nCREST terminated normally.\n",
        encoding="utf-8",
    )
    (output_dir / "crest_best.xyz").write_text(_crest_xyz(-5.20000000), encoding="utf-8")
    (output_dir / "crest_conformers.xyz").write_text(
        _crest_xyz(-5.20000000) + _crest_xyz(-5.19840639),
        encoding="utf-8",
    )
    (output_dir / "crest.energies").write_text("  1       0.000\n  2       1.000\n", encoding="utf-8")

    result = parse_calculation(
        workspace,
        prepared["intent_id"],
        (output_dir / "crest.out").relative_to(workspace).as_posix(),
    )

    facts = result["parser_facts"]
    assert result["program_status"] == "completed"
    assert result["provenance"]["parser_contract"] == "crest-conformer-parser/1"
    assert facts["program_version"] == "3.0.2"
    assert facts["conformer_count"] == 2
    assert facts["relative_energy_count"] == 2
    assert facts["relative_energy_max_kcal_mol"] == pytest.approx(1.0)
    assert facts["ensemble_counts_match"] is True
    assert facts["task_completed"] is True
    assert (output_dir / "parsed/crest_summary.json").is_file()
    assert (output_dir / "parsed/conformer_energies.json").is_file()
    assert (output_dir / "parsed/ensemble_summary.json").is_file()


def test_xtb_prepare_requires_task_artifacts_in_intent(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    intent_path = _intent(workspace, "xtb", "opt")
    value = json.loads(intent_path.read_text(encoding="utf-8"))
    value["expected_artifacts"] = [
        f"nodes/{value['node_id']}/attempts/{value['intent_id']}/outputs/xtb.out"
    ]
    intent_path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ComputeContractError, match="missing required files.*xtbopt.xyz"):
        prepare_calculation(workspace, intent_path)


def test_xtb_scan_prepare_rejects_invalid_bound_control_before_execution(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "inputs/scan.inp").write_text(
        "$constrain\n  distance: 1, 2, auto\n$metadyn\n  save=10\n$end\n",
        encoding="utf-8",
    )
    with pytest.raises(ComputeContractError, match="invalid xTB scan control.*unsupported.*section"):
        _intent(workspace, "xtb", "scan")


def _workspace(tmp_path: Path) -> Path:
    workspace = bootstrap_v5_workspace(tmp_path / "workspace")
    start_research_node(
        workspace,
        objective="Exercise the typed xTB and CREST adapter task matrix.",
    )
    inputs = workspace / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    (inputs / "candidate.xyz").write_text(_xyz(-5.0), encoding="utf-8")
    (inputs / "md.inp").write_text(
        "$md\n  time=0.1\n  step=1.0\n  temp=300\n  dump=10\n$end\n",
        encoding="utf-8",
    )
    (inputs / "scan.inp").write_text(
        "$constrain\n  force constant=1.0\n  distance: 1, 2, auto\n"
        "$scan\n  1: 0.9, 1.1, 3\n$end\n",
        encoding="utf-8",
    )
    return workspace


def _intent(workspace: Path, backend: str, task_type: str) -> Path:
    nodes = json.loads((workspace / "research_nodes.json").read_text(encoding="utf-8"))["nodes"]
    node_id = nodes[0]["node_id"]
    catalog = list_calculation_artifacts(workspace)
    by_path = {item["path"]: item for item in catalog["artifacts"]}
    input_artifacts = [
        {"input_role": "xyz", "artifact_id": by_path["inputs/candidate.xyz"]["artifact_id"]}
    ]
    if task_type in {"scan", "md"}:
        control = by_path[f"inputs/{task_type}.inp"]
        input_artifacts.append({"input_role": "control", "artifact_id": control["artifact_id"]})
    created = create_calculation_intent(workspace, {
        "schema_version": "ts-calculation-request/3",
        "node_id": node_id,
        "purpose": f"Exercise deterministic {backend} {task_type} parsing.",
        "attempt_kind": "primary",
        "recalculation_ref": None,
        "backend": backend,
        "task_type": task_type,
        "input_artifacts": input_artifacts,
        "settings": {},
        "execution_target": {"kind": "local"},
        "dry_run": True,
    })
    return workspace / created["intent_ref"]


def _output_dir(workspace: Path, intent_id: str) -> Path:
    matches = list((workspace / "nodes").glob(f"*/attempts/{intent_id}/intent.json"))
    if len(matches) != 1:
        raise AssertionError(f"expected one intent for {intent_id}, found {len(matches)}")
    return matches[0].parent / "outputs"


def _xyz(energy: float) -> str:
    return (
        "3\n"
        f"energy: {energy:.12f} gnorm: 0.000245 xtb: 6.7.1\n"
        "O 0.000000 0.000000 0.000000\n"
        "H 0.758602 0.000000 0.504284\n"
        "H -0.758602 0.000000 0.504284\n"
    )


def _crest_xyz(energy: float) -> str:
    return (
        "3\n"
        f"  {energy:.8f}\n"
        "O 0.000000 0.000000 0.000000\n"
        "H 0.758602 0.000000 0.504284\n"
        "H -0.758602 0.000000 0.504284\n"
    )


def _scan_xyz(energy: float, distance: float) -> str:
    return (
        "3\n"
        f"energy: {energy:.12f} xtb: 6.7.1\n"
        "O 0.000000 0.000000 0.000000\n"
        f"H {distance:.6f} 0.000000 0.000000\n"
        "H 0.000000 0.900000 0.000000\n"
    )


def _four_atom_scan_xyz(energy: float) -> str:
    return (
        "4\n"
        f"energy: {energy:.12f} xtb: 6.7.1\n"
        "C 0.000000 0.000000 0.000000\n"
        "C 1.000000 0.000000 0.000000\n"
        "C 1.000000 1.000000 0.000000\n"
        "C 1.000000 1.000000 1.000000\n"
    )


def _xtb_scan_log() -> str:
    return "\n".join(
        [
            "* xtb version 6.7.1 (test)",
            "program call               : xtb candidate.xyz --opt normal --input scan.inp",
            "Hamiltonian                  GFN2-xTB",
            "net charge                          0",
            "unpaired electrons                  0",
            "*** convergence criteria satisfied after 8 iterations ***",
            "RELAXED SCAN",
            "output written to xtbscan.log",
            "| TOTAL ENERGY               -5.150000000000 Eh   |",
            "* finished run on 2026/08/07 at 17:48:15.853",
            "normal termination of xtb",
        ]
    )


def _xtb_opt_freq_log() -> str:
    return "\n".join(
        [
            "* xtb version 6.7.1 (test)",
            "program call               : xtb candidate.xyz --ohess normal --chrg 0 --uhf 0",
            "Hamiltonian                  GFN2-xTB",
            "net charge                          0",
            "unpaired electrons                  0",
            "*** convergence criteria satisfied after 8 iterations ***",
            "*** GEOMETRY OPTIMIZATION CONVERGED AFTER 7 ITERATIONS ***",
            ":: zero point energy           0.020133304038 Eh   ::",
            "| TOTAL ENERGY               -5.070544409100 Eh   |",
            "| TOTAL ENTHALPY             -5.046630191030 Eh   |",
            "| TOTAL FREE ENERGY          -5.068036196210 Eh   |",
            "| GRADIENT NORM               0.000245040922 Eh/a0 |",
            "| HOMO-LUMO GAP              14.396494730932 eV   |",
            "* finished run on 2026/08/06 at 21:30:02.887",
        ]
    )


def _vibspectrum() -> str:
    return "\n".join(
        [
            "$vibrational spectrum",
            "#  mode symmetry wave number IR intensity selection rules",
            "     1                    -0.00       0.00000          -",
            "     2                    -0.00       0.00000          -",
            "     3                     0.00       0.00000          -",
            "     4                     0.00       0.00000          -",
            "     5                     0.00       0.00000          -",
            "     6                     0.00       0.00000          -",
            "     7        a         -125.50      10.00000        YES",
            "     8        a         1539.11     133.29925        YES",
            "     9        a         3653.25      16.63531        YES",
            "$end",
        ]
    ) + "\n"


def _xtb_md_log() -> str:
    return "\n".join(
        [
            "* xtb version 6.7.1 (test)",
            "Hamiltonian                  GFN2-xTB",
            "*** convergence criteria satisfied after 8 iterations ***",
            "| TOTAL ENERGY               -5.065772968305 Eh   |",
            "MD time /ps        :    0.10",
            "dt /fs             :    1.00",
            "temperature /K     :  300.00",
            "max steps          :   100",
            "average properties",
            "Epot               :  -5.0654561156537685",
            "Ekin               :   0.0007725788528748",
            "Etot               :  -5.0646835368008940",
            "T                  :  69.703238965104902",
            "normal exit of md()",
            "* finished run on 2026/08/06 at 21:30:02.964",
        ]
    )
