from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TS_LOADER = ROOT / "tests" / "support" / "typescript_loader.mjs"
PRESENTATION = ROOT / "extensions" / "pi" / "shared" / "native-tool-presentation.ts"
TUI_PACKAGE = ROOT / "extensions" / "pi" / "tui-package" / "src" / "tui.ts"


def test_native_tool_presentation_hides_canonical_refs_but_keeps_semantics() -> None:
    script = f"""
import {{ renderTsNativeCall, renderTsNativeResult }} from {json.dumps(PRESENTATION.as_uri())};
const theme = {{ fg: (_color, value) => value }};
const workspace = "ws_" + "a".repeat(24);
const artifact = "art_" + "b".repeat(24);
const seed = "structure_seed_" + "c".repeat(64) + ".xyz";
const raw = {{ mode: "map", workspace_id: workspace, artifact_id: artifact, seed_path: seed, node_id: "node_1", status: "completed" }};
const result = {{ content: [{{ type: "text", text: JSON.stringify(raw) }}], details: {{ result: raw }} }};
const call = renderTsNativeCall("ts_state", {{ mode: "map", nodeId: "node_1", root: workspace }}, theme).render(120).join("\\n");
const rendered = renderTsNativeResult("ts_state", result, {{ expanded: true, isPartial: false }}, theme, false).render(120).join("\\n");
process.stdout.write(JSON.stringify({{ call, rendered }}));
"""
    completed = subprocess.run(
        ["node", "--experimental-loader", str(TS_LOADER), "--input-type=module", "--eval", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    value = json.loads(completed.stdout)
    for canonical in ("ws_" + "a" * 24, "art_" + "b" * 24, "structure_seed_" + "c" * 64):
        assert canonical not in value["call"]
        assert canonical not in value["rendered"]
    assert "TS State" in value["call"]
    assert "node_1" in value["rendered"]


def test_native_tui_registers_all_server_tool_renderer_families() -> None:
    source = TUI_PACKAGE.read_text(encoding="utf-8")
    native_source = PRESENTATION.read_text(encoding="utf-8")
    for name in ("ts_state", "ts_change", "ts_workflow", "ts_environment", "ts_calc", "ts_dispatch", "ts_reply", "ts_notify"):
        assert name in native_source
    for name in ("seed", "compare", "analyze", "import", "render", "report"):
        assert f'"{name}"' in source
    assert "ts_review" in source
    assert "setToolRenderers(PRESENTATION_TOOL_RENDERERS)" in source
    assert "env.own(layout.setToolRenderers(PRESENTATION_TOOL_RENDERERS))" in source
    assert "removeToolRenderers()" in source
    assert "setToolRenderers(undefined)" not in source
    assert "TSPI_PRESENTATION_RENDERERS_ONLY" in source
    assert "if (rendererOnly)" in source
