"""Tests for the Gaussian External -> xTB backend."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

from transition_state_workflow.backends.ase_neb.contracts import BOHR_TO_ANG
from transition_state_workflow.backends.gaussian_external_xtb import (
    DEFAULT_HESSIAN_FLAG,
    GaussianExternalXtbAdapter,
    GaussianExternalXtbError,
    GaussianExternalXtbOptions,
    atoms_to_xyz_text,
    build_gaussian_external_xtb_argv,
    format_eou_float,
    hessian_lower_triangle_from_square,
    parse_ein_text,
    parse_xtb_hessian_file,
    run_gaussian_external_xtb,
    serialize_eou,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "gaussian_external_xtb.py"


def _float_values(text: str) -> list[float]:
    values: list[float] = []
    for token in re.findall(r"[-+]?\d+\.\d+D[-+]\d+", text):
        values.append(float(token.replace("D", "E")))
    return values


def test_parse_ein_tracks_derivative_charge_spin_and_embedded_charges() -> None:
    request = parse_ein_text(
        "2 2 -1 2\n"
        "6 0.000000 0.000000 0.000000 0.000000\n"
        "1 0.000000 0.000000 1.889725988600 0.000000\n"
        "3.0 4.0 5.0 -0.25\n"
    )

    assert request.natoms == 2
    assert request.derivative_level == 2
    assert request.charge == -1
    assert request.multiplicity == 2
    assert request.atoms[0].atomic_number == 6
    assert request.atoms[1].z_bohr == pytest.approx(1.8897259886)
    assert request.embedded_charges[0].charge == pytest.approx(-0.25)
    assert request.has_embedded_charges is True


def test_atoms_to_xyz_converts_bohr_to_angstrom() -> None:
    request = parse_ein_text(
        "1 1 0 1\n"
        "1 1.000000 2.000000 3.000000 0.000000\n"
    )

    text = atoms_to_xyz_text(request)

    assert text.splitlines()[0] == "1"
    assert f"H {BOHR_TO_ANG:.12f} {2 * BOHR_TO_ANG:.12f} {3 * BOHR_TO_ANG:.12f}" in text


def test_build_xtb_argv_reuses_shared_charge_spin_mapping(tmp_path: Path) -> None:
    request = parse_ein_text(
        "2 2 -1 3\n"
        "6 0 0 0 0\n"
        "1 0 0 1 0\n"
    )
    xyz = tmp_path / "input.xyz"
    options = GaussianExternalXtbOptions(
        executable="/opt/xtb",
        method="gfn1",
        accuracy="0.2",
        iterations="150",
        electronic_temperature="500",
        solvent="water",
        solvent_model="gbsa",
        parallel=24,
    )

    argv = build_gaussian_external_xtb_argv(request, options, xyz)

    assert argv == (
        "/opt/xtb",
        str(xyz),
        "--gfn",
        "1",
        "--chrg",
        "-1",
        "--uhf",
        "2",
        "--acc",
        "0.2",
        "--iterations",
        "150",
        "--etemp",
        "500",
        "--gbsa",
        "water",
        DEFAULT_HESSIAN_FLAG,
    )


def test_eou_format_uses_fixed_width_d_exponents() -> None:
    hessian = hessian_lower_triangle_from_square(
        (
            (0.10, 0.01, 0.02),
            (0.01, 0.20, 0.03),
            (0.02, 0.03, 0.30),
        )
    )

    text = serialize_eou(
        energy_hartree=-1.25,
        natoms=1,
        derivative_level=2,
        gradient=((0.1, -0.2, 0.3),),
        hessian_lower_triangle=hessian,
    )

    assert format_eou_float(-1.25) == " -1.250000000000D+00"
    assert len(text.splitlines()[0]) == 80
    assert "E" not in text
    assert "D" in text
    values = _float_values(text)
    assert len(values) == 4 + 3 + 6 + 9 + 6
    assert values[:7] == pytest.approx([-1.25, 0.0, 0.0, 0.0, 0.1, -0.2, 0.3])
    assert values[-6:] == pytest.approx([0.10, 0.01, 0.20, 0.02, 0.03, 0.30])


def test_dry_run_writes_eou_summary_and_candidate_boundary(tmp_path: Path) -> None:
    ein = tmp_path / "input.EIn"
    eou = tmp_path / "output.EOu"
    msg = tmp_path / "message.txt"
    workdir = tmp_path / "outputs"
    ein.write_text(
        "2 2 0 1\n"
        "1 0 0 0 0\n"
        "1 0 0 1.4 0\n",
        encoding="utf-8",
    )

    result = run_gaussian_external_xtb(
        ein_path=ein,
        eou_path=eou,
        msg_path=msg,
        workdir=workdir,
        options=GaussianExternalXtbOptions(method="gfn2"),
        dry_run=True,
    )

    summary = json.loads((workdir / "gaussian_external_xtb_summary.json").read_text(encoding="utf-8"))
    assert result.energy_hartree == pytest.approx(-0.123456789)
    assert eou.exists()
    assert msg.read_text(encoding="utf-8").startswith("Gaussian-External-xTB completed")
    assert summary["candidate_only"] is True
    assert summary["accepted_ts_capable"] is False
    assert summary["hessian_lower_triangle_values"] == 21
    assert len(_float_values(eou.read_text(encoding="utf-8"))) == 4 + 6 + 6 + 18 + 21


def test_embedded_charges_fail_explicitly(tmp_path: Path) -> None:
    ein = tmp_path / "input.EIn"
    ein.write_text(
        "1 0 0 1\n"
        "1 0 0 0 0\n"
        "1.0 2.0 3.0 -0.1\n",
        encoding="utf-8",
    )

    with pytest.raises(GaussianExternalXtbError, match="embedded"):
        run_gaussian_external_xtb(
            ein_path=ein,
            eou_path=tmp_path / "output.EOu",
            msg_path=tmp_path / "message.txt",
            workdir=tmp_path / "outputs",
            options=GaussianExternalXtbOptions(),
            dry_run=True,
        )


def test_hessian_request_without_hessian_artifact_fails(tmp_path: Path) -> None:
    workdir = tmp_path / "outputs"
    workdir.mkdir()
    hessian_path = workdir / "hessian"

    with pytest.raises(GaussianExternalXtbError, match="Hessian artifact is missing"):
        parse_xtb_hessian_file(hessian_path, natoms=1)


def test_missing_xtb_executable_is_backend_error(tmp_path: Path) -> None:
    ein = tmp_path / "input.EIn"
    ein.write_text("1 0 0 1\n1 0 0 0 0\n", encoding="utf-8")

    with pytest.raises(GaussianExternalXtbError, match="xTB executable not found"):
        run_gaussian_external_xtb(
            ein_path=ein,
            eou_path=tmp_path / "output.EOu",
            msg_path=tmp_path / "message.txt",
            workdir=tmp_path / "outputs",
            options=GaussianExternalXtbOptions(executable=str(tmp_path / "missing_xtb")),
        )


def test_adapter_prepares_script_command_and_parses_summary(tmp_path: Path) -> None:
    ein = tmp_path / "input.EIn"
    ein.write_text("1 0 -1 2\n1 0 0 0 0\n", encoding="utf-8")
    workdir = tmp_path / "outputs"
    summary = workdir / "gaussian_external_xtb_summary.json"
    workdir.mkdir()
    summary.write_text(
        json.dumps({"energy_hartree": -0.5, "candidate_only": True, "accepted_ts_capable": False}),
        encoding="utf-8",
    )

    adapter = GaussianExternalXtbAdapter()
    prepared = adapter.prepare(
        {
            "input_file": ein,
            "workdir": workdir,
            "script": SCRIPT,
            "python": sys.executable,
            "executable": "xtb",
            "method": "gfn2",
            "dry_run": True,
        }
    )
    parsed = adapter.parse((workdir,))

    assert prepared.backend == "gaussian-external-xtb"
    assert prepared.files == (ein,)
    assert prepared.command_argv[:4] == (sys.executable, str(SCRIPT), "--workdir", str(workdir))
    assert prepared.metadata["candidate_only"] is True
    assert prepared.metadata["accepted_ts_capable"] is False
    assert prepared.metadata["charge"] == -1
    assert prepared.metadata["uhf"] == 1
    assert parsed.properties["electronic_energy_hartree"] == pytest.approx(-0.5)
    assert parsed.diagnostics == ()


def test_script_help_smoke() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "Gaussian External" in result.stdout
