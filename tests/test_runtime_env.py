from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ts_runtime.env import configured_python, default_env_prefix, spec_sha256, write_manifest

ROOT = Path(__file__).resolve().parents[1]


def test_default_env_prefix_is_spec_hash_scoped(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    (package / "environment.yml").write_text("name: test\n", encoding="utf-8")

    prefix = default_env_prefix(package, tmp_path / "envs")

    assert prefix.parent == tmp_path / "envs"
    assert prefix.name == spec_sha256(package)[:12]


def test_configured_python_reads_runtime_manifest(tmp_path: Path) -> None:
    package = tmp_path / "skill"
    package.mkdir()
    write_manifest(
        package,
        {
            "schema_version": "ts-agent-runtime-v1",
            "python_executable": sys.executable,
        },
    )

    assert configured_python(package) == Path(sys.executable).resolve()


def test_install_env_dry_run_reports_hashed_prefix(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "install_env.py"),
            "--package-root",
            str(ROOT),
            "--env-root",
            str(tmp_path / "envs"),
            "--dry-run",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["action"] == "create"
    assert payload["dry_run"] is True
    assert payload["env_prefix"].startswith(str(tmp_path / "envs"))
    assert payload["python_executable"].endswith("/bin/python")
