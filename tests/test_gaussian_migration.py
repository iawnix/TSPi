from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ts_backends import gaussian
from ts_remote import gaussian as remote_gaussian


def write_xyz(path: Path, text: str) -> Path:
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def orientation(marker: str = "Standard orientation:") -> str:
    return f"""
 {marker}
 ---------------------------------------------------------------------
 Center     Atomic      Atomic             Coordinates (Angstroms)
 Number     Number       Type             X           Y           Z
 ---------------------------------------------------------------------
      1          6           0        0.100000    0.200000    0.300000
      2          1           0        0.400000    0.500000    0.600000
 ---------------------------------------------------------------------
"""


def convergence(yes: bool = True) -> str:
    flag = "YES" if yes else "NO"
    return f"""
 Maximum Force            0.000010     0.000450     {flag}
 RMS     Force            0.000006     0.000300     {flag}
 Maximum Displacement     0.000020     0.001800     {flag}
 RMS     Displacement     0.000012     0.001200     {flag}
"""


def job(
    frequencies: str = "Frequencies --  -512.3000   47.1000   98.2000",
    *,
    normal: bool = True,
    stationary: bool = True,
    include_convergence: bool = True,
    orientation_marker: str = "Standard orientation:",
) -> str:
    parts = [
        " Entering Link 1 = synthetic",
        " SCF Done:  E(RB3LYP) =  -40.123456     A.U. after 10 cycles",
        orientation(orientation_marker),
    ]
    if include_convergence:
        parts.append(convergence())
    if stationary:
        parts.append(" Stationary point found.")
    parts.append(frequencies)
    parts.append(" Zero-point correction=                           0.012345")
    if normal:
        parts.append(" Normal termination of Gaussian 16")
    else:
        parts.append(" Error termination request processed by link 9999.")
    return "\n".join(parts)


def parse_text(tmp_path: Path, text: str):
    log_path = tmp_path / "case.log"
    log_path.write_text(text, encoding="utf-8")
    return gaussian.parse_log(log_path)


def test_multiframe_xyz_requires_explicit_frame(tmp_path: Path) -> None:
    xyz = write_xyz(
        tmp_path / "candidate.xyz",
        """
        1
        first
        H 0 0 0
        1
        second
        H 1 0 0
        """,
    )

    with pytest.raises(ValueError, match="use --frame"):
        gaussian.read_xyz(xyz)


def test_can_select_last_frame(tmp_path: Path) -> None:
    xyz = write_xyz(
        tmp_path / "candidate.xyz",
        """
        1
        first
        H 0 0 0
        1
        second
        H 1 0 0
        """,
    )

    frame_index, title, coords = gaussian.read_xyz(xyz, "last")

    assert frame_index == 1
    assert title == "second"
    assert coords == [("H", 1.0, 0.0, 0.0)]


def test_write_gjf_appends_extra_section(tmp_path: Path) -> None:
    output = tmp_path / "candidate.gjf"

    gaussian.write_gjf(
        path=output,
        title="candidate",
        coords=[("C", 0.0, 0.0, 0.0)],
        route="#P B3LYP/Gen opt=(ts,calcfc) freq",
        charge=0,
        multiplicity=1,
        nproc=4,
        mem="8GB",
        chk="candidate.chk",
        extra_sections=["C 0\n6-31G(d)\n****\n"],
    )

    text = output.read_text(encoding="utf-8")
    assert "#P B3LYP/Gen opt=(ts,calcfc) freq" in text
    assert "C 0\n6-31G(d)\n****\n" in text


def test_route_requires_extra_section_detects_gen() -> None:
    assert gaussian.route_requires_extra_section("#P B3LYP/Gen opt freq")
    assert gaussian.route_requires_extra_section("#P B3LYP/genecp opt freq")
    assert not gaussian.route_requires_extra_section("#P B3LYP/6-31G(d) opt freq")


def test_valid_ts_section_validates_and_extracts_standard_orientation(tmp_path: Path) -> None:
    parsed = parse_text(tmp_path, job())
    summary = parsed["summary"]

    assert summary["status"] == "validated_ts"
    assert summary["normal_termination"] is True
    assert summary["stationary_point_found"] is True
    assert summary["imaginary_frequency_count"] == 1
    assert summary["final_convergence_satisfied"] is True
    assert summary["validation_failures"] == []
    assert summary["final_geometry_atoms"] == 2
    assert parsed["atoms"][0] == ("C", 0.1, 0.2, 0.3)


def test_two_imaginary_frequencies_do_not_validate(tmp_path: Path) -> None:
    parsed = parse_text(tmp_path, job("Frequencies --  -512.3000  -101.4000   98.2000"))
    summary = parsed["summary"]

    assert summary["status"] == "not_validated_ts"
    assert summary["imaginary_frequency_count"] == 2
    assert "imaginary_frequency_count_not_one" in summary["validation_failures"]


def test_failed_final_section_does_not_borrow_normal_first_section(tmp_path: Path) -> None:
    text = "\n--Link1--\n".join(
        [
            job(),
            job(
                "Frequencies --   20.0000   47.1000   98.2000",
                normal=False,
                stationary=False,
                include_convergence=False,
            ),
        ]
    )
    parsed = parse_text(tmp_path, text)
    summary = parsed["summary"]

    assert summary["status"] == "not_validated_ts"
    assert summary["section_count"] == 2
    assert summary["selected_section_index"] == 1
    assert summary["selected_section_reason"] == "default_final_section"
    assert summary["normal_termination"] is False
    assert summary["stationary_point_found"] is False
    assert summary["frequency_count"] == 3
    assert summary["imaginary_frequency_count"] == 0
    assert "missing_normal_termination" in summary["validation_failures"]
    assert "missing_stationary_point" in summary["validation_failures"]


def test_missing_convergence_evidence_is_not_validated_but_input_geometry_is_extracted(tmp_path: Path) -> None:
    parsed = parse_text(
        tmp_path,
        job(include_convergence=False, orientation_marker="Input orientation:"),
    )
    summary = parsed["summary"]

    assert summary["status"] == "not_validated_ts"
    assert summary["final_convergence_evidence_present"] is False
    assert summary["final_convergence_satisfied"] is False
    assert "missing_final_convergence_evidence" in summary["validation_failures"]
    assert summary["final_geometry_atoms"] == 2
    assert parsed["atoms"][1] == ("H", 0.4, 0.5, 0.6)


def test_stationary_point_convergence_is_not_overwritten_by_later_frequency_rows(tmp_path: Path) -> None:
    text = "\n".join(
        [
            job(),
            " Maximum Force            0.000010     0.000450     YES",
            " RMS     Force            0.000006     0.000300     YES",
            " Maximum Displacement     0.002000     0.001800     NO",
            " RMS     Displacement     0.000012     0.001200     YES",
        ]
    )

    parsed = parse_text(tmp_path, text)
    summary = parsed["summary"]

    assert summary["status"] == "validated_ts"
    assert summary["force_convergence_source"] == "stationary_point"
    assert summary["force_convergence"]["Maximum Displacement"]["converged"] == "YES"


def test_failed_remote_run_still_downloads_expected_artifacts(monkeypatch, tmp_path: Path) -> None:
    input_path = tmp_path / "ts.gjf"
    input_path.write_text("%chk=ts.chk\n# opt\n\nTitle\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")
    output_dir = tmp_path / "pulled"
    calls: list[list[str]] = []

    def fake_run(argv, check):
        calls.append(list(argv))
        is_remote_execution = argv[:2] == ["ssh", "login"] and argv[2:5] == ["ssh", "compute", "bash"]
        if is_remote_execution:
            raise subprocess.CalledProcessError(9, argv)
        if argv and argv[0] == "scp" and argv[-2] == "login:/remote/run/ts.out":
            raise subprocess.CalledProcessError(1, argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    config = remote_gaussian.RemoteGaussianConfig(
        input_path=input_path,
        login_host="login",
        compute_host="compute",
        remote_dir="/remote/run",
        output_dir=output_dir,
    )

    assert remote_gaussian.execute_remote_gaussian(config) == 9

    remote_sources = [call[-2] for call in calls if call and call[0] == "scp" and call[-2].startswith("login:")]
    remote_run_index = next(
        index
        for index, call in enumerate(calls)
        if call[:2] == ["ssh", "login"] and call[2:5] == ["ssh", "compute", "bash"]
    )
    first_download_index = next(
        index
        for index, call in enumerate(calls)
        if call and call[0] == "scp" and call[-2].startswith("login:")
    )

    assert first_download_index > remote_run_index
    assert remote_sources == [
        "login:/remote/run/ts.out",
        "login:/remote/run/ts.log",
        "login:/remote/run/run_metadata.txt",
        "login:/remote/run/g16_driver.out",
        "login:/remote/run/ts.chk",
    ]


def test_remote_runner_relaxes_nounset_for_gaussian_profile_source() -> None:
    config = remote_gaussian.RemoteGaussianConfig(
        input_path=Path("ts.gjf"),
        login_host="login",
        compute_host="compute",
        remote_dir="/remote/run",
        g16="/opt/g16/g16",
        g16root="/opt/gaussian",
        scratch="/scratch/g16",
    )

    text = remote_gaussian.remote_runner_text(config, "ts.gjf")
    lines = text.splitlines()

    assert lines[:2] == ["#!/usr/bin/env bash", "set -euo pipefail"]
    assert lines.index('cd "$RUN_DIR"') < lines.index("export g16root=/opt/gaussian")
    source_index = lines.index('    source "$g16root/g16/bsd/g16.profile"')

    assert lines[source_index - 4] == "    set +e"
    assert lines[source_index - 3] == "    set +u"
    assert lines[source_index - 2] == '    export LD_LIBRARY64_PATH="${LD_LIBRARY64_PATH:-}"'
    assert lines[source_index + 1] == "    profile_status=$?"
    assert lines[source_index + 2] == "    set -u"
    assert lines[source_index + 3] == "    set -e"


def test_submit_async_gaussian_stages_extra_files_and_uses_generic_lifecycle(monkeypatch, tmp_path: Path) -> None:
    input_path = tmp_path / "ts.gjf"
    input_path.write_text("%chk=ts.chk\n# opt=(ts) freq\n\nTitle\n\n0 1\nH 0 0 0\n\n", encoding="utf-8")
    chk_path = tmp_path / "ts.chk"
    chk_path.write_bytes(b"checkpoint")
    output_dir = tmp_path / "pulled"
    calls: list[list[str]] = []
    staged_runner = ""
    staged_receipt = {}

    def fake_run(argv, check):
        nonlocal staged_runner, staged_receipt
        calls.append(list(argv))
        if argv[0] == "scp" and argv[-2].endswith("run_gaussian_on_compute.sh"):
            staged_runner = Path(argv[-2]).read_text(encoding="utf-8")
        if argv[0] == "scp" and argv[-2].endswith("remote_receipt.json"):
            import json

            staged_receipt = json.loads(Path(argv[-2]).read_text(encoding="utf-8"))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    config = remote_gaussian.RemoteGaussianConfig(
        input_path=input_path,
        login_host="login",
        compute_host="compute",
        remote_dir="/remote/run",
        output_dir=output_dir,
        extra_files=(chk_path,),
        g16="/opt/g16/g16",
        g16root="/opt/gaussian",
        scratch="/scratch/g16",
        node_id="n123",
    )

    receipt = remote_gaussian.submit_async_gaussian(config)

    assert receipt.node_id == "n123"
    assert receipt.receipt_path == "/remote/run/remote_receipt.json"
    assert staged_receipt["metadata"]["status_path"] == "/remote/run/remote_status.json"
    assert [call[-1] for call in calls if call[0] == "scp"] == [
        "login:/remote/run/ts.gjf",
        "login:/remote/run/ts.chk",
        "login:/remote/run/run_gaussian_on_compute.sh",
        "login:/remote/run/remote_receipt.json",
    ]
    assert all(not call[-2].startswith("login:") for call in calls if call[0] == "scp")
    assert '"adapter":"gaussian"' in staged_runner
    assert 'source "$g16root/g16/bsd/g16.profile"' in staged_runner
    assert '"$G16" "$INPUT" > g16_driver.out 2> g16_driver.err' in staged_runner
    assert calls[-1][:2] == ["ssh", "login"]
    assert calls[-1][2].startswith("ssh compute ")
    assert "nohup bash ./run_gaussian_on_compute.sh" in calls[-1][2]
