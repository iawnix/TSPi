from __future__ import annotations

import sys
import time
from pathlib import Path

from ts_agent.compute import local_lifecycle
from ts_agent.compute.local_lifecycle import LocalJobConfig, collect, status, submit


def test_systemd_user_preflight_rejects_an_unavailable_user_bus(monkeypatch) -> None:
    calls = []

    monkeypatch.setattr(
        local_lifecycle.shutil,
        "which",
        lambda name: "/usr/bin/systemctl" if name == "systemctl" else None,
    )

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return local_lifecycle.subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(local_lifecycle.subprocess, "run", fake_run)

    assert local_lifecycle._systemd_user_available() is False
    assert calls[0][0] == ["/usr/bin/systemctl", "--user", "show-environment"]
    assert calls[0][1]["timeout"] == 1.0


def test_local_submit_is_idempotent_and_status_survives_worker_completion(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    artifact = "result.out"
    script = (
        "from pathlib import Path; "
        f"Path({str(run_dir / artifact)!r}).write_text('completed\\n', encoding='utf-8')"
    )
    config = LocalJobConfig(
        intent_id="calc_1",
        run_dir=run_dir,
        command=(sys.executable, "-c", script),
        input_paths=(),
        expected_artifacts=(artifact,),
        environment={},
    )

    first = submit(config)
    assert (run_dir / "local_receipt.json").is_file()
    assert (run_dir / "program_status.json").is_file()
    second = submit(config)

    assert second == first
    deadline = time.monotonic() + 10
    observed = status(config, first)
    while observed.get("state") == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
        observed = status(config, first)
    assert observed["state"] == "completed"
    assert observed["program_status"] == "completed"
    assert (run_dir / "program_status.json").is_file()

    staging = tmp_path / "staging"
    copied, manifest = collect(config, [artifact], staging)
    assert copied == [artifact]
    assert manifest[0]["size"] == len(b"completed\n")
    assert (staging / artifact).read_text(encoding="utf-8") == "completed\n"


def test_local_submit_sources_activation_script_before_exec(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    activation = tmp_path / "activate.sh"
    activation.write_text("#!/usr/bin/env bash\nexport TSPI_TEST_ACTIVATED=ready\n", encoding="utf-8")
    activation.chmod(0o755)
    artifact = "activation.txt"
    script = (
        "import os; from pathlib import Path; "
        f"Path({str(run_dir / artifact)!r}).write_text(os.environ['TSPI_TEST_ACTIVATED'], encoding='utf-8')"
    )
    config = LocalJobConfig(
        intent_id="calc_2",
        run_dir=run_dir,
        command=(sys.executable, "-c", script),
        input_paths=(),
        expected_artifacts=(artifact,),
        environment={},
        activation_script=str(activation),
    )

    receipt = submit(config)
    deadline = time.monotonic() + 10
    observed = status(config, receipt)
    while observed.get("state") == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
        observed = status(config, receipt)

    assert observed["state"] == "completed"
    assert (run_dir / artifact).read_text(encoding="utf-8") == "ready"


def test_local_submit_rebinds_attempt_scratch_after_activation(tmp_path: Path) -> None:
    """Activation profiles cannot redirect Gaussian scratch out of an Attempt."""

    run_dir = tmp_path / "run"
    scratch_dir = run_dir / "scratch"
    activation = tmp_path / "activate.sh"
    # Vendor profiles occasionally change cwd and export a shared scratch
    # directory.  The worker must restore both bindings before exec.
    activation.write_text(
        "#!/usr/bin/env bash\n"
        "cd /\n"
        "export GAUSS_SCRDIR=/tmp/shared-gaussian-scratch\n"
        "export TMPDIR=/tmp/shared-gaussian-scratch\n",
        encoding="utf-8",
    )
    activation.chmod(0o755)
    artifact = "scratch-binding.txt"
    script = (
        "import os; from pathlib import Path; "
        f"Path({str(run_dir / artifact)!r}).write_text("
        "os.getcwd() + '\\n' + os.environ['GAUSS_SCRDIR'] + '\\n' + os.environ['TMPDIR'], "
        "encoding='utf-8')"
    )
    config = LocalJobConfig(
        intent_id="calc_scratch",
        run_dir=run_dir,
        command=(sys.executable, "-c", script),
        input_paths=(),
        expected_artifacts=(artifact,),
        environment={},
        activation_script=str(activation),
        scratch_dir=scratch_dir,
    )

    receipt = submit(config)
    deadline = time.monotonic() + 10
    observed = status(config, receipt)
    while observed.get("state") == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
        observed = status(config, receipt)

    assert observed["state"] == "completed"
    lines = (run_dir / artifact).read_text(encoding="utf-8").splitlines()
    assert lines == [str(run_dir), str(scratch_dir), str(scratch_dir)]


def test_local_submit_restores_attempt_cwd_after_activation_script(tmp_path: Path) -> None:
    """Vendor activation profiles must not redirect relative scratch files."""

    run_dir = tmp_path / "attempt" / "execution" / "local"
    leaked_dir = tmp_path / "outside"
    leaked_dir.mkdir()
    activation = tmp_path / "activate.sh"
    activation.write_text(
        "#!/usr/bin/env bash\n"
        f"cd -- {str(leaked_dir)!r}\n",
        encoding="utf-8",
    )
    activation.chmod(0o755)
    config = LocalJobConfig(
        intent_id="calc_cwd",
        run_dir=run_dir,
        command=(
            sys.executable,
            "-c",
            "from pathlib import Path; Path('Gau-1705102.inp').write_text('scratch\\n', encoding='utf-8')",
        ),
        input_paths=(),
        expected_artifacts=("Gau-1705102.inp",),
        environment={},
        activation_script=str(activation),
    )

    receipt = submit(config)
    deadline = time.monotonic() + 10
    observed = status(config, receipt)
    while observed.get("state") == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
        observed = status(config, receipt)

    assert observed["state"] == "completed"
    assert (run_dir / "Gau-1705102.inp").read_text(encoding="utf-8") == "scratch\n"
    assert not (leaked_dir / "Gau-1705102.inp").exists()
