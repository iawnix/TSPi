from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ts_render import MolVisualizer
from ts_render.config import ENGINES


def test_ts_render_exposes_only_xyzrender_engine() -> None:
    assert ENGINES == ("xyzrender",)

ROOT = Path(__file__).resolve().parents[1]


def test_ts_render_builds_command_and_writes_output(tmp_path: Path, monkeypatch) -> None:
    fake = _fake_xyzrender(tmp_path)
    monkeypatch.setenv("TS_RENDER_XYZRENDER", str(fake))
    input_xyz = tmp_path / "h2.xyz"
    output = tmp_path / "out" / "h2.png"
    input_xyz.write_text("2\nh2\nH 0 0 0\nH 0 0 0.74\n", encoding="utf-8")

    result = MolVisualizer().render_molecule(input_xyz, output)

    assert result.ok is True
    assert result.output_path == str(output)
    assert output.exists()
    assert result.command[0] == str(fake)
    assert str(input_xyz) in result.command
    assert "-S" in result.command


def test_ts_render_missing_xyzrender_is_structured_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TS_RENDER_XYZRENDER", str(tmp_path / "missing_xyzrender"))
    monkeypatch.setenv("PATH", "")

    result = MolVisualizer().render_molecule(tmp_path / "missing.xyz", tmp_path / "out.png")

    assert result.ok is False
    assert result.command == []
    assert "xyzrender" in result.stderr


def test_ts_render_cli_diagnostic_json(tmp_path: Path, monkeypatch) -> None:
    fake = _fake_xyzrender(tmp_path)
    env = dict(**os_environ_without_runtime_reexec(), TS_RENDER_XYZRENDER=str(fake))
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "ts_render.py"), "diagnostic", "--json"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["xyzrender"]["available"] is True
    assert payload["xyzrender"]["path"] == str(fake)
    assert "blender" not in payload
    assert "ffmpeg" not in payload
    assert "obabel" not in payload


def _fake_xyzrender(tmp_path: Path) -> Path:
    script = tmp_path / "xyzrender"
    script.write_text(
        """#!/usr/bin/env python3
import sys
from pathlib import Path
if "--help" in sys.argv:
    print("xyzrender fake")
    raise SystemExit(0)
if "-o" in sys.argv:
    output = Path(sys.argv[sys.argv.index("-o") + 1])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"fake image")
print("ok")
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def os_environ_without_runtime_reexec() -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["TS_AGENT_DISABLE_RUNTIME_REEXEC"] = "1"
    return env
