from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from scripts import installer, install_from_github, install_wizard, _install_inputs, _install_relay


ROOT = Path(__file__).resolve().parents[2]
COMMIT = "a" * 40


def test_github_selection_runs_the_resolved_checkout_and_keeps_private_inputs_local(tmp_path, monkeypatch):
    config = tmp_path / "private"
    config.mkdir()
    (config / "auth.json").write_text('{"example":{"key":"fake-private-key"}}')
    seen = []
    def checkout(repo, ref, destination):
        assert ref == "release-tag"
        destination.mkdir()
        seen.append(destination)
        assert not (destination / "auth.json").exists()
        return COMMIT
    def run_selected(root, commit, options, component, remaining):
        assert root == seen[0] and root.exists()
        assert commit == COMMIT
        assert component == "agent"
        assert remaining[remaining.index("--config-dir") + 1] == str(config)
        assert "fake-private-key" not in " ".join(remaining)
        return 0
    monkeypatch.setattr(install_from_github, "checkout_github", checkout)
    monkeypatch.setattr(installer, "run_selected", run_selected)
    assert installer.main(["install", "--source", "github", "--coragent-ref", "release-tag",
                           "--config-dir", str(config), "--install-root", str(tmp_path / "install"),
                           "--non-interactive", "--yes"]) == 0
    assert not seen[0].exists()
    assert (config / "auth.json").is_file()
    assert not (tmp_path / "install").exists()


def test_local_selection_never_downloads_and_pins_actual_head(tmp_path, monkeypatch):
    selected = tmp_path / "source"
    def local(path, *, allow_dirty):
        assert path == str(selected) and allow_dirty
        return selected, COMMIT
    monkeypatch.setattr(installer, "local_source", local)
    monkeypatch.setattr(install_from_github, "checkout_github", lambda *args: pytest.fail("local source must not download"))
    def run(command, **kwargs):
        assert command[2] == str(selected / "scripts/install_wizard.py")
        assert command[command.index("--coragent-commit") + 1] == COMMIT
        assert command[command.index("--coragent-ref") + 1] == COMMIT
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(installer.subprocess, "run", run)
    assert installer.main(["install", "--source-root", str(selected), "--allow-dirty", "--non-interactive"]) == 0


def test_package_source_uses_the_shared_wizard_without_fetching_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(install_from_github, 'checkout_github', lambda *_:pytest.fail('package source must stay local'))
    seen=[]
    monkeypatch.setattr(install_wizard, 'main', lambda arguments:seen.extend(arguments) or 0)
    manifest=tmp_path/'release.json'
    assert installer.main(['install','--source','package','--package-manifest',str(manifest),
                           '--install-root',str(tmp_path/'install'),'--non-interactive']) == 0
    assert seen[seen.index('--package-manifest')+1] == str(manifest)


def test_standalone_relay_routes_to_its_installer(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "local_source", lambda *args, **kwargs: (tmp_path, COMMIT))
    def run(command, **kwargs):
        assert command[2] == str(tmp_path / "scripts/install_link_relay.py")
        assert "--coragent-commit" not in command
        assert command[command.index("--source-root") + 1] == str(tmp_path)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(installer.subprocess, "run", run)
    assert installer.main(["install", "relay", "--source", "local", "--public-url", "https://relay.example",
                           "--service-scope", "none", "--non-interactive"]) == 0


def test_failed_install_cleans_only_the_new_owned_relay(tmp_path, monkeypatch):
    # Exercise rollback with the actual Relay release layout; the old wrapper
    # incorrectly passed current/services/relay as the installation root.
    root = tmp_path / "install"
    relay = root / "runtimes/link-relay"
    state = root / "var/state/link-relay"
    marker = root / "etc/link-relay.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}")
    args = install_wizard.parse_args(["--install-root", str(root)])
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        assert command[command.index("--install-root") + 1] == str(relay)
        assert command[command.index("--state-dir") + 1] == str(state)
        assert "--purge-state" in command
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(_install_relay.subprocess, "run", run)
    _install_relay.rollback(args, {"install_root": str(relay), "service_root": str(relay / "current/services/relay"),
                                 "state_dir": str(state)})
    assert len(calls) == 1
    assert not marker.exists()


def test_configuration_cli_overrides_directory_and_email_secrets_wait_for_confirmation(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "job.toml").write_text("directory-config")
    (config / "email.toml").write_text((ROOT / "config/email.example.toml").read_text())
    (config / "smtp-password").write_text("fake-smtp-password")
    (config / "smtp-password").chmod(0o600)
    root = tmp_path / "installation"
    args = install_wizard.parse_args([
        "--config-dir", str(config), "--install-root", str(root),
        "--job-config", str(tmp_path / "explicit-job.toml"), "--email-recipient", "override@example.invalid",
    ])
    _install_inputs.apply_config_directory(args)
    assert args.job_config == str(tmp_path / "explicit-job.toml")
    assert args.email_recipient == "override@example.invalid"
    assert args.email_username == "sender@example.invalid"
    assert not root.exists()

    existing = root / "etc/email.toml"
    existing.parent.mkdir(parents=True)
    existing.write_text('[notifications.email]\nenabled=true\nprovider="smtp"\nrecipient="old@example.invalid"\n')
    install_wizard._load_existing_email_defaults(args, root)
    assert args.email_recipient == "override@example.invalid"
    assert args.email_username == "sender@example.invalid"

    # A CLI credential reference supersedes the directory's password file,
    # including when that file is absent on this machine.
    (config / "smtp-password").unlink()
    overridden = install_wizard.parse_args([
        "--config-dir", str(config), "--email-password-env", "EXAMPLE_SMTP_PASSWORD",
    ])
    _install_inputs.apply_config_directory(overridden)
    assert overridden.email_password_file is None
    assert overridden.email_password_env == "EXAMPLE_SMTP_PASSWORD"


def test_private_config_does_not_affect_local_source_provenance(tmp_path):
    from scripts._source_capture import REQUIRED_SOURCE_PATHS
    for raw in REQUIRED_SOURCE_PATHS:
        path = tmp_path / raw.decode()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("source fixture\n")
    (tmp_path / ".gitignore").write_text("/config/auth.json\n/local_debug/\n")
    for command in (["git", "init", "-q"], ["git", "add", "."],
                    ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"]):
        subprocess.run(command, cwd=tmp_path, check=True, capture_output=True)
    before = install_from_github.tree_digest(tmp_path)
    for name in ("config/auth.json", "local_debug/private.txt"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fake-private-value")
    assert install_from_github.tree_digest(tmp_path) == before
    (tmp_path / "README.md").write_text("changed source")
    assert install_from_github.tree_digest(tmp_path) != before
    with pytest.raises(ValueError, match="uncommitted changes"):
        installer.local_source(str(tmp_path), allow_dirty=False)
    root, commit = installer.local_source(str(tmp_path), allow_dirty=True)
    assert root == tmp_path and len(commit) == 40
