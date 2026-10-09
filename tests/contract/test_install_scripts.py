from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_configured_dry_run_redacts_secret_arguments() -> None:
    environment = {
        **os.environ,
        "RESEARCH_AGENT_WEB_AUTH_TOKEN": "web-secret-for-test",
        "RESEARCH_AGENT_PHONE_ACCESS": "link",
        "RESEARCH_AGENT_LINK_URL": "https://relay.example",
        "RESEARCH_AGENT_LINK_ENROLLMENT_CODE": "enrollment-secret-for-test",
    }
    completed = subprocess.run(
        [str(ROOT / "install-configured.sh"), "--dry-run"],
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "web-secret-for-test" not in completed.stdout
    assert "enrollment-secret-for-test" not in completed.stdout
    assert completed.stdout.count("REDACTED") == 2
