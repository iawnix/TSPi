from __future__ import annotations

import json
import hashlib
import subprocess
import sys
from pathlib import Path

from PIL import Image

from ts_agent.render import MolVisualizer
from ts_agent.render.config import ENGINES


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


def test_mechanism_composes_labeled_arrow_panels_without_xyzrender_annotations(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake = _fake_png_xyzrender(tmp_path)
    monkeypatch.setenv("TS_RENDER_XYZRENDER", str(fake))
    inputs = []
    for index in range(3):
        path = tmp_path / f"structure-{index + 1}.xyz"
        path.write_text(f"1\nstructure {index + 1}\nH {index} 0 0\n", encoding="utf-8")
        inputs.append(path)
    with_arrow = tmp_path / "mechanism.png"
    without_arrow = tmp_path / "mechanism-no-arrow.png"
    visualizer = MolVisualizer(resolution=(900, 300))

    result = visualizer.render_reaction_mechanism(
        inputs,
        ["Reactant", "Transition state", "Product"],
        with_arrow,
    )
    no_arrow_result = visualizer.render_reaction_mechanism(
        inputs,
        ["Reactant", "Transition state", "Product"],
        without_arrow,
        show_arrow=False,
    )

    assert result.ok is True
    assert no_arrow_result.ok is True
    assert len(result.commands) == 3
    assert all("-l" not in command for command in result.commands)
    assert all("-t" in command for command in result.commands)
    with Image.open(with_arrow) as image:
        assert image.size == (900, 300)
    assert hashlib.sha256(with_arrow.read_bytes()).digest() != hashlib.sha256(without_arrow.read_bytes()).digest()


def test_compare_honors_vertical_panel_layout(tmp_path: Path, monkeypatch) -> None:
    fake = _fake_png_xyzrender(tmp_path)
    monkeypatch.setenv("TS_RENDER_XYZRENDER", str(fake))
    inputs = []
    for index in range(2):
        path = tmp_path / f"candidate-{index + 1}.xyz"
        path.write_text(f"1\ncandidate {index + 1}\nH 0 {index} 0\n", encoding="utf-8")
        inputs.append(path)
    output = tmp_path / "vertical.png"

    result = MolVisualizer(resolution=(320, 640)).compare_structures(
        inputs,
        output,
        titles=["Candidate A", "Candidate B"],
        layout="vertical",
    )

    assert result.ok is True
    with Image.open(output) as image:
        assert image.size == (320, 640)


def test_panel_render_preserves_xyzrender_failure(tmp_path: Path, monkeypatch) -> None:
    fake = tmp_path / "xyzrender"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "print('xyzrender: error: deliberate panel failure', file=sys.stderr)\n"
        "raise SystemExit(2)\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("TS_RENDER_XYZRENDER", str(fake))
    inputs = [tmp_path / "a.xyz", tmp_path / "b.xyz"]
    for path in inputs:
        path.write_text("1\nprobe\nH 0 0 0\n", encoding="utf-8")

    result = MolVisualizer().compare_structures(inputs, tmp_path / "failed.png")

    assert result.ok is False
    assert result.returncode == 2
    assert "deliberate panel failure" in result.stderr
    assert result.commands == [result.command]


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


def _fake_png_xyzrender(tmp_path: Path) -> Path:
    script = tmp_path / "xyzrender"
    script.write_text(
        """#!/usr/bin/env python3
import sys
from pathlib import Path
from PIL import Image, ImageDraw
if "-l" in sys.argv:
    print("unexpected xyzrender annotation", file=sys.stderr)
    raise SystemExit(2)
output = Path(sys.argv[sys.argv.index("-o") + 1])
output.parent.mkdir(parents=True, exist_ok=True)
image = Image.new("RGBA", (240, 240), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.ellipse((40, 40, 200, 200), fill=(40, 120, 200, 255))
image.save(output)
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
