from __future__ import annotations

import sys
import time
from pathlib import Path

from ts_agent.compute.local_lifecycle import LocalJobConfig, collect, status, submit


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
