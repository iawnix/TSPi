from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TAXONOMY = ROOT / "src" / "agent-core" / "failure-taxonomy.cjs"


def test_upstream_stream_disconnect_is_not_classified_as_compute_or_program_failure() -> None:
    result = _classify("408 stream disconnected before completion", replay_safe=True)

    assert result == {
        "failure_class": "model_stream_interrupted",
        "failure_stage": "model_stream",
        "failure_domain": "upstream_model_api",
        "upstream_status": 408,
        "retry_safe": True,
    }


def test_stream_disconnect_after_action_is_not_replay_safe() -> None:
    result = _classify("stream closed before response.completed", replay_safe=False)

    assert result["failure_domain"] == "upstream_model_api"
    assert result["upstream_status"] is None
    assert result["retry_safe"] is False


def test_non_stream_error_is_not_claimed_by_upstream_taxonomy() -> None:
    assert _classify("Normal termination missing from Gaussian log", replay_safe=True) is None


def _classify(message: str, *, replay_safe: bool) -> dict[str, object] | None:
    script = (
        f"const taxonomy=require({json.dumps(str(TAXONOMY))});"
        "const result=taxonomy.classifyUpstreamModelFailure("
        "new Error(process.argv[1]),{replaySafe:process.argv[2]==='true'});"
        "process.stdout.write(JSON.stringify(result));"
    )
    completed = subprocess.run(
        ["node", "-e", script, message, str(replay_safe).lower()],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return json.loads(completed.stdout)
