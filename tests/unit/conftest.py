from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def unified_compute_profile(tmp_path, monkeypatch):
    """Give unit tests an explicit local profile without production fallbacks."""

    config = tmp_path / "compute.toml"
    config.write_text(
        """default_profile = \"local\"

[profiles.local]
kind = \"local\"

[profiles.local.software.gaussian]
command = \"g16\"

[profiles.local.software.xtb]
command = \"xtb\"

[profiles.local.software.crest]
command = \"crest\"

[profiles.local.software.ase_neb_xtb]
command = \"xtb\"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TS_COMPUTE_CONFIG", str(config))
