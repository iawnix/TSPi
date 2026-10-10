"""A branding cutover must reject old state without adopting or rewriting it."""
import json
from pathlib import Path

import pytest

from research_agent.foundation.layout import paths
from scripts._installation_metadata import read_installation_metadata
from scripts.install_wizard import parse_args
from scripts.installer import source_options
from scripts.uninstall_link_relay import unit_belongs_to_root


def test_old_installation_is_rejected_without_rewriting_ownership(tmp_path):
    root = tmp_path / "installation"
    marker = root / "etc/installation.json"
    marker.parent.mkdir(parents=True)
    before = json.dumps({"schema_version": "research-agent-installation/2", "install_root": str(root)})
    marker.write_text(before)
    with pytest.raises(ValueError, match="unsupported or mismatched"):
        paths(root).read_config()
    with pytest.raises(ValueError, match="does not match"):
        read_installation_metadata(root, require_ownership=True)
    assert marker.read_text() == before


def test_old_installer_option_is_not_an_alias():
    with pytest.raises(SystemExit) as error:
        parse_args(["--research-agent-repo", "https://example.invalid/old.git"])
    assert error.value.code == 2


def test_old_environment_does_not_select_installation_source(monkeypatch):
    monkeypatch.delenv("CORAGENT_INSTALL_REPO", raising=False)
    monkeypatch.setenv("RESEARCH_AGENT_INSTALL_REPO", "https://example.invalid/old.git")
    options, _ = source_options([])
    assert options.coragent_repo == "https://github.com/iawnix/coragent.git"
    monkeypatch.setenv("CORAGENT_INSTALL_REPO", "https://example.invalid/new.git")
    options, _ = source_options([])
    assert options.coragent_repo == "https://example.invalid/new.git"


def test_relay_uninstaller_requires_new_identity_and_matching_root(tmp_path):
    root = tmp_path / "relay"
    unit = tmp_path / "coragent-relay.service"
    directory = root / "current/services/relay"
    unit.write_text(f"Description=CoRAgent Link Relay\nWorkingDirectory={directory}\n")
    assert unit_belongs_to_root(unit, root)
    assert not unit_belongs_to_root(unit, tmp_path / "another-installation")
    unit.write_text(f"Description=ResearchAgent Link Relay\nWorkingDirectory={directory}\n")
    assert not unit_belongs_to_root(unit, root)
