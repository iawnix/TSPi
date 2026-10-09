from __future__ import annotations

import os
import json
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
        [str(ROOT / "install.sh"), "--dry-run"],
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


def test_config_directory_preview_is_private_and_has_no_side_effects(tmp_path: Path) -> None:
    config = tmp_path / "private config"
    config.mkdir()
    (config / "models.json").write_text('{"providers":{"test":{"apiKey":"fake-model-secret"}}}')
    (config / "auth.json").write_text('{"test":{"type":"api_key","key":"fake-auth-secret"}}')
    root = tmp_path / "installation"
    completed = subprocess.run([
        str(ROOT / "install.sh"), "--source", "local", "--config-dir", str(config),
        "--install-root", str(root), "--dry-run",
    ], text=True, capture_output=True, check=True)
    plan = json.loads(completed.stdout)["plan"]
    assert plan["agent_config_dir"] == str(config)
    assert "fake-model-secret" not in completed.stdout + completed.stderr
    assert "fake-auth-secret" not in completed.stdout + completed.stderr
    assert not root.exists()


def test_public_entrypoints_and_relay_help_do_not_fetch_sources() -> None:
    for name in ("install.sh", "uninstall.sh"):
        for component in ([], ["relay"]):
            completed = subprocess.run([str(ROOT / name), *component, "--help"],
                                       text=True, capture_output=True, check=True)
            assert "--install-root" in completed.stdout
    assert {p.name for p in ROOT.glob("*install*.sh")} == {"install.sh", "uninstall.sh"}


def test_environment_defaults_can_be_overridden_by_cli() -> None:
    completed = subprocess.run([
        str(ROOT / "install.sh"), "--dry-run", "--without-web", "--service-scope", "none",
    ], env={**os.environ, "RESEARCH_AGENT_WITH_WEB": "true", "RESEARCH_AGENT_SERVICE_SCOPE": "user"},
        text=True, capture_output=True, check=True)
    plan = json.loads(completed.stdout)["plan"]
    assert plan["with_web"] is False
    assert plan["service_scope"] == "none"
