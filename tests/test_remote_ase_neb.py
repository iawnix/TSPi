"""Remote ASE-NEB adapter and generic remote-job CLI tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from conftest import REMOTE_JOB_CLI

from transition_state_workflow.remote import ase_neb_runner as remote_ase_neb  # noqa: E402
from transition_state_workflow.remote import job_runner as remote_job_runner  # noqa: E402


def write_xyz(path: Path, *, z: float) -> None:
    path.write_text(
        f"2\nunit\nH 0.0 0.0 0.0\nH 0.0 0.0 {z:.3f}\n",
        encoding="utf-8",
    )


def write_ase_neb_config(node_inputs: Path) -> Path:
    write_xyz(node_inputs / "reactant.xyz", z=0.74)
    write_xyz(node_inputs / "product.xyz", z=1.10)
    config = {
        "version": 1,
        "reactant": "reactant.xyz",
        "product": "product.xyz",
        "output": "../outputs/ase_neb_xtb",
        "project": {"system_slug": "unit_xtb_neb"},
        "images": 3,
        "interpolation": "linear",
        "neb": {
            "climb": False,
            "dynamic": False,
            "k": 0.1,
            "method": "improvedtangent",
            "remove_rotation_and_translation": True,
        },
        "optimizer": {"name": "FIRE", "fmax": 0.1, "steps": 2},
        "calculator": {
            "type": "xtb",
            "method": "GFN2-xTB",
            "charge": 0,
            "uhf": 0,
            "env": {"OMP_NUM_THREADS": 2},
        },
    }
    config_path = node_inputs / "ase_neb_xtb_config.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config_path


def make_args(config_path: Path, *, output_dir: Path | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        root="/remote/tssearch_unit",
        node="n030_xtb_neb",
        tool_root=None,
        output_name=None,
        output_dir=output_dir,
        config=config_path,
        job_stem=None,
        python="/remote/python",
        xtb_bin_dir="/remote/xtb/bin",
        gaussian_lib_dir="/remote/g16",
        openmpi_lib_dir="/remote/mpi/lib",
        preserve_ld_library_path=False,
        allow_gaussian_neb=False,
        env=[],
        extra_file=[],
    )


def test_ase_neb_remote_spec_stages_runtime_and_remote_config(tmp_path: Path) -> None:
    node_inputs = tmp_path / "tssearch_unit" / "nodes" / "n030_xtb_neb" / "inputs"
    node_inputs.mkdir(parents=True)
    config_path = write_ase_neb_config(node_inputs)
    args = make_args(config_path)
    layout = remote_ase_neb.build_layout(args, config_path)
    archive = tmp_path / "runtime.tar.gz"
    archive.write_bytes(b"fake archive")

    spec = remote_ase_neb.build_remote_job_spec(
        args,
        config_path,
        layout,
        staging_dir=tmp_path,
        runtime_archive=archive,
    )

    assert spec.engine == "ase-neb"
    assert spec.remote_run_dir == "/remote/tssearch_unit/nodes/n030_xtb_neb/outputs"
    assert spec.runner_name == "ase_neb_xtb.run_ase_neb_on_compute.sh"
    assert spec.metadata_name == "ase_neb_xtb.run_metadata.txt"
    assert "TOOL_ROOT=/remote/tssearch_unit/tools/transition-state-workflow" in spec.runner_text
    assert 'ASE_NEB="$TOOL_ROOT/scripts/ase_neb_framework.py"' in spec.runner_text
    assert "/home/iaw/.codex/skills/transition-state-workflow/scripts/ase_neb_framework.py" not in spec.runner_text
    assert "validate-config" in spec.runner_text
    assert '"$PYTHON" "$ASE_NEB" run "$CONFIG"' in spec.runner_text
    assert any(upload.remote_path.endswith("/tools/transition-state-workflow.runtime.tar.gz") for upload in spec.uploads)

    remote_config_upload = next(upload for upload in spec.uploads if upload.remote_path.endswith(".remote.json"))
    remote_config = json.loads(remote_config_upload.local_path.read_text(encoding="utf-8"))
    assert remote_config["reactant"] == "/remote/tssearch_unit/nodes/n030_xtb_neb/inputs/reactant.xyz"
    assert remote_config["product"] == "/remote/tssearch_unit/nodes/n030_xtb_neb/inputs/product.xyz"
    assert remote_config["output"] == "/remote/tssearch_unit/nodes/n030_xtb_neb/outputs/ase_neb_xtb"


def test_ts_remote_job_ase_neb_dry_run_never_calls_local_installed_skill(tmp_path: Path) -> None:
    node_inputs = tmp_path / "tssearch_unit" / "nodes" / "n030_xtb_neb" / "inputs"
    node_inputs.mkdir(parents=True)
    config_path = write_ase_neb_config(node_inputs)

    result = subprocess.run(
        [
            sys.executable,
            str(REMOTE_JOB_CLI),
            "submit",
            "--engine",
            "ase-neb",
            "--config",
            str(config_path),
            "--root",
            "/remote/tssearch_unit",
            "--node",
            "n030_xtb_neb",
            "--login-host",
            "login.example",
            "--compute-host",
            "compute-0-30",
            "--no-download",
            "--dry-run",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    stdout = result.stdout
    assert "login.example:/remote/tssearch_unit/nodes/n030_xtb_neb/inputs/ase_neb_xtb_config.remote.json" in stdout
    assert "login.example:/remote/tssearch_unit/tools/transition-state-workflow.runtime.tar.gz" in stdout
    assert "TOOL_ROOT=/remote/tssearch_unit/tools/transition-state-workflow" in stdout
    assert "ASE_NEB=\"$TOOL_ROOT/scripts/ase_neb_framework.py\"" in stdout
    assert "/home/iaw/.codex/skills/transition-state-workflow/scripts/ase_neb_framework.py" not in stdout
    assert "ssh compute-0-30 --" in stdout
    assert "shell=True" not in stdout


def test_ts_remote_job_status_tail_fetch_help_and_recursive_fetch_command(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(REMOTE_JOB_CLI), "fetch", "--help"],
        check=True,
        text=True,
        capture_output=True,
    )
    assert "--engine" in result.stdout
    assert "ase-neb" in result.stdout
    assert "--pattern" in result.stdout

    layout = remote_job_runner.RemoteNodeLayout(
        remote_root="/remote/tssearch_unit",
        node_id="n030_xtb_neb",
        remote_outputs_dir="/remote/tssearch_unit/nodes/n030_xtb_neb/outputs",
    )
    command = remote_job_runner.fetch_tree_list_command(layout, ["*"])
    assert "find . -type f" in command
    assert "-printf '%P\\n'" in command
    assert "maxdepth 1" not in command


def test_ts_remote_job_status_dry_run_uses_generic_node_outputs() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REMOTE_JOB_CLI),
            "status",
            "--engine",
            "ase-neb",
            "--root",
            "/remote/tssearch_unit",
            "--node",
            "n030_xtb_neb",
            "--login-host",
            "login.example",
            "--compute-host",
            "compute-0-30",
            "--dry-run",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "RUN_DIR=/remote/tssearch_unit/nodes/n030_xtb_neb/outputs" in result.stdout
    assert "run_metadata.*.txt" in result.stdout
    assert "ssh compute-0-30 --" in result.stdout
