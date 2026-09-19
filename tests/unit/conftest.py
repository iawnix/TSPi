from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def unified_compute_environment(tmp_path, monkeypatch):
    """Give unit tests an explicit local environment without production fallbacks."""

    config = tmp_path / "compute.toml"
    config.write_text(
        """default_environment = \"local\"

[environments.local]
kind = \"local\"

[environments.local.backends.gaussian]
command = \"g16\"

[environments.local.backends.xtb]
command = \"xtb\"

[environments.local.backends.crest]
command = \"crest\"

[environments.local.backends.ase_neb_xtb]
command = \"xtb\"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TS_COMPUTE_CONFIG", str(config))
