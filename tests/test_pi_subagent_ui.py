from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "extensions" / "shared" / "subagent-status.ts"
PROFILE = ROOT / "extensions" / "shared" / "package-profile.ts"
UI = ROOT / "extensions" / "ts-workflow-ui" / "index.ts"
EDITOR = ROOT / "extensions" / "ts-workflow-ui" / "editor.ts"
RENDER_UTILS = ROOT / "extensions" / "ts-workflow-ui" / "render-utils.ts"
STARTUP = ROOT / "extensions" / "ts-workflow-ui" / "startup.ts"
THEME = ROOT / "themes" / "ts-theme.json"
SESSION_LIFECYCLE = ROOT / "src" / "agent-core" / "session-lifecycle.cjs"
TS_LOADER = ROOT / "tests" / "typescript_loader.mjs"


def test_status_reporter_emits_versioned_phases_and_classifies_terminal_errors() -> None:
    script = f"""
import {{ createSubagentStatusReporter, isTsSubagentStatus, terminalStatusForError }} from {json.dumps(STATUS.as_uri())};
const updates = [];
const report = createSubagentStatusReporter({{
  tool_call_id: "call-1",
  task_id: "agent-1",
  role: "backend",
  operation: "submit",
  backend: "gaussian",
  node_id: "n003",
  intent_id: "calc_n003_maleic",
}}, (partial) => updates.push(partial.details));
for (const phase of ["preflight", "starting", "running", "validating", "completed"]) report(phase);
const timeout = Object.assign(new Error("late"), {{ code: "TS_SUBAGENT_TIMEOUT" }});
const abort = Object.assign(new Error("stop"), {{ code: "TS_SUBAGENT_ABORTED" }});
const observerFailure = createSubagentStatusReporter({{ tool_call_id: "call-2", task_id: "agent-2", role: "review", operation: "mechanism" }}, () => {{ throw new Error("ui failed"); }})("running");
process.stdout.write(JSON.stringify({{
  updates,
  valid: updates.every(isTsSubagentStatus),
  timeout: terminalStatusForError(timeout),
  abort: terminalStatusForError(abort),
  failure: terminalStatusForError(new Error("boom")),
  observerFailure,
}}));
"""
    result = _node_json(script)
    assert result["valid"] is True
    assert [item["phase"] for item in result["updates"]] == [
        "preflight",
        "starting",
        "running",
        "validating",
        "completed",
    ]
    assert all(item["schema_version"] == "ts-subagent-status/1" for item in result["updates"])
    assert result["timeout"] == {"phase": "failed", "failure_kind": "timeout"}
    assert result["abort"] == {"phase": "cancelled", "failure_kind": "aborted"}
    assert result["failure"] == {"phase": "failed", "failure_kind": "error"}
    assert result["observerFailure"]["phase"] == "running"


def test_session_lifecycle_reports_child_creation_and_validation_in_order() -> None:
    script = f"""
import {{ createRequire }} from "node:module";
const require = createRequire(import.meta.url);
const helper = require({json.dumps(str(SESSION_LIFECYCLE))});
const phases = [];
const onLifecycle = (phase) => phases.push(phase);
const session = {{
  prompt: async () => undefined,
  abort: async () => undefined,
  dispose: () => phases.push("disposed"),
}};
await helper.withDisposableSession(
  async () => ({{ session }}),
  async (created) => helper.promptWithDeadline(created.session, "review", {{ timeoutMs: 1000, onLifecycle }}),
  {{ onLifecycle }},
);
process.stdout.write(JSON.stringify(phases));
"""
    assert _node_json(script) == ["starting", "running", "validating", "disposed"]


def test_ui_reducer_handles_success_timeout_abort_failure_and_widths() -> None:
    script = f"""
import {{ createTsSubagentUiState, pruneTsSubagentUiState, reduceTsSubagentUiState, renderTsSubagentPanel }} from {json.dumps(UI.as_uri())};
const state = createTsSubagentUiState();
const args = {{ operation: "submit", backend: "gaussian", nodeId: "n003", intentId: "calc_n003_maleic" }};
reduceTsSubagentUiState(state, {{ type: "tool_execution_start", toolCallId: "call-1", toolName: "ts_subagent_compute", args }}, 1000);
const running = {{ schema_version: "ts-subagent-status/1", tool_call_id: "call-1", task_id: "agent-1", role: "backend", operation: "submit", phase: "running", backend: "gaussian", node_id: "n003", intent_id: "calc_n003_maleic" }};
reduceTsSubagentUiState(state, {{ type: "tool_execution_update", toolCallId: "call-1", toolName: "ts_subagent_compute", args, partialResult: {{ details: running }} }}, 2000);
const active = state.runs.get("call-1");
const panels = [8, 60, 100, 140].map((width) => ({{ width, lines: renderTsSubagentPanel(active, width, 19000) }}));
reduceTsSubagentUiState(state, {{ type: "tool_execution_end", toolCallId: "call-1", toolName: "ts_subagent_compute", result: {{}}, isError: false }}, 20000);
const completed = state.runs.get("call-1").status.phase;
const timeout = {{ ...running, phase: "failed", failure_kind: "timeout" }};
reduceTsSubagentUiState(state, {{ type: "tool_execution_update", toolCallId: "call-1", toolName: "ts_subagent_compute", args, partialResult: {{ details: timeout }} }}, 21000);
const timeoutPhase = state.runs.get("call-1").status;
const abort = {{ ...running, phase: "cancelled", failure_kind: "aborted" }};
reduceTsSubagentUiState(state, {{ type: "tool_execution_update", toolCallId: "call-1", toolName: "ts_subagent_compute", args, partialResult: {{ details: abort }} }}, 22000);
const abortPhase = state.runs.get("call-1").status;
reduceTsSubagentUiState(state, {{ type: "tool_execution_start", toolCallId: "call-2", toolName: "ts_subagent_review", args: {{ reviewType: "connectivity", nodeId: "n006" }} }}, 23000);
reduceTsSubagentUiState(state, {{ type: "tool_execution_end", toolCallId: "call-2", toolName: "ts_subagent_review", result: {{}}, isError: true }}, 24000);
const failed = state.runs.get("call-2").status.phase;
const prunedEarly = pruneTsSubagentUiState(state, 26499);
const prunedLate = pruneTsSubagentUiState(state, 26500);
process.stdout.write(JSON.stringify({{ panels, completed, timeoutPhase, abortPhase, failed, prunedEarly, prunedLate, remaining: state.runs.size }}));
"""
    result = _node_json(script)
    for panel in result["panels"]:
        assert len(panel["lines"]) == 2
        assert all(len(line) <= panel["width"] for line in panel["lines"])
        if panel["width"] >= 60:
            assert panel["lines"][0].endswith("00:18")
            assert panel["lines"][1] == "Gaussian · submit · n003 · calc_n003_maleic"
    assert result["completed"] == "completed"
    assert result["timeoutPhase"]["failure_kind"] == "timeout"
    assert result["abortPhase"]["phase"] == "cancelled"
    assert result["failed"] == "failed"
    assert result["prunedEarly"] is True  # call-1 expired first
    assert result["prunedLate"] is True   # call-2 expires at the boundary
    assert result["remaining"] == 0


def test_tspi_startup_profile_matches_package_manifest() -> None:
    script = f"""
import {{ TS_PACKAGE_PROFILE }} from {json.dumps(PROFILE.as_uri())};
process.stdout.write(JSON.stringify(TS_PACKAGE_PROFILE));
"""
    profile = _node_json(script)
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert profile["version"] == manifest["version"]
    assert [profile["skill"]["path"]] == manifest["pi"]["skills"]
    assert [item["path"] for item in profile["extensions"]] == manifest["pi"]["extensions"]
    assert [profile["theme"]["path"]] == manifest["pi"]["themes"]


def test_tspi_startup_render_is_compact_and_width_safe() -> None:
    script = f"""
import {{ createTspiStartupHeader, renderTspiStartupLines }} from {json.dumps(STARTUP.as_uri())};
import {{ visibleWidth }} from "@earendil-works/pi-tui";
const widths = [18, 40, 47, 60, 80, 100, 140];
const details = {{
  remoteDisplayTarget: "cluster-login · Torque",
  remoteConfigured: true,
  modelLabel: "openai/gpt-5",
  thinkingLabel: "high thinking",
}};
const rendered = widths.map((width) => {{
  const lines = renderTspiStartupLines("/home/iaw/TS-pi-agent", width, details);
  return {{ width, lines, lineWidths: lines.map(visibleWidth) }};
}});
const fallback = renderTspiStartupLines("/home/iaw/TS-pi-agent", 140);
const blockColors = [];
const theme = {{
  fg: (color, text) => {{ if (text.includes("█")) blockColors.push(color); return text; }},
  bold: (text) => text,
}};
const pi = {{ getThinkingLevel: () => "high" }};
const ctx = {{ ui: {{ theme }}, cwd: "/home/iaw/TS-pi-agent", model: {{ provider: "openai", id: "gpt-5" }} }};
let renderRequests = 0;
const tui = {{ terminal: {{ rows: 30 }}, requestRender: () => renderRequests++ }};
process.env.TS_REMOTE_CONFIG = "/tmp/remote.toml";
process.env.TS_REMOTE_DISPLAY_TARGET = "cluster-login · Torque";
const header = createTspiStartupHeader(pi, ctx, tui, "/home/iaw/TS-pi-agent");
const initial = header.render(100).join("\\n").split("█").length;
await new Promise((resolve) => setTimeout(resolve, 120));
const next = header.render(100).join("\\n").split("█").length;
header.dispose();
const liveHeader = header.render(140);
process.stdout.write(JSON.stringify({{ rendered, fallback, blockColors, initial, next, liveHeader, renderRequests }}));
"""
    result = _node_json(script)
    rendered = result["rendered"]

    for view in rendered[1:]:
        assert 7 <= len(view["lines"]) <= 16
        assert all(line_width <= view["width"] for line_width in view["lineWidths"])
        assert view["lines"][0].startswith("╭")
        assert "TSπ" in view["lines"][0]
        assert view["lines"][-1].startswith("╰")
        assert all(line.endswith(("╮", "╯", "│")) for line in view["lines"])

    assert rendered[0]["lines"] == ["TSπ TSPi"]
    assert rendered[0]["lineWidths"] == [8]

    compact = next(view["lines"] for view in rendered if view["width"] == 60)
    assert not any("█" in line for line in compact)
    assert any("TSπ" in line for line in compact)

    single_column = next(view["lines"] for view in rendered if view["width"] == 47)
    assert len([line for line in single_column if "█" in line]) == 7
    assert not any("Workspace" in line for line in single_column)

    standard = next(view["lines"] for view in rendered if view["width"] == 80)
    assert any("1 skill · 5 extensions" in line for line in standard)
    assert any("1 theme" in line for line in standard)
    assert not any("…" in line for line in standard if "skill" in line or "theme" in line)

    wide = rendered[-1]["lines"]
    pixel_lines = [line for line in wide if "█" in line]
    assert len(pixel_lines) == 7
    assert all("■" not in line for line in pixel_lines)
    assert any("██████████    ██████████    ██████████████" in line for line in pixel_lines)
    assert pixel_lines[-1].split("│")[1].strip() == "██        ██████████    ████      ████"
    assert sum("TSPi" in line for line in wide) == 1
    assert any("Evidence-driven transition-state workflow." in line for line in wide)
    assert any("openai/gpt-5 · high thinking" in line for line in wide)
    assert any("Workspace" in line for line in wide)
    assert any("Remote configured" in line for line in wide)
    assert any("cluster-login · Torque" in line for line in wide)
    assert any("not configured" in line for line in result["fallback"])
    assert any("cluster-login · Torque" in line for line in result["liveHeader"])
    assert any("1 skill · 5 extensions" in line for line in wide)
    assert any("1 theme" in line for line in wide)
    assert not any("ts-theme" in line for line in wide)
    for command in ("/ts-context", "/ts-validate", "/ts-remote"):
        assert any(command in line for line in wide)
    assert "mdLink" in result["blockColors"]
    assert result["next"] > result["initial"]
    assert result["renderRequests"] >= 1


def test_tspi_editor_replaces_default_borders_with_width_safe_rounded_frame() -> None:
    script = f"""
import {{ visibleWidth }} from "@earendil-works/pi-tui";
import {{ applyTspiRoundedEditorBorders, tspiEditorMode }} from {json.dumps(EDITOR.as_uri())};
const rendered = [12, 40].map((width) => {{
  const lines = applyTspiRoundedEditorBorders(["─".repeat(width), "  input", "─".repeat(width)], width, (value) => value, "COMMAND");
  return {{ width, lines, widths: lines.map(visibleWidth) }};
}});
const modes = ["hello", "/model", "!pwd"].map(tspiEditorMode);
process.stdout.write(JSON.stringify({{ rendered, modes }}));
"""
    result = _node_json(script)
    rendered = result["rendered"]

    for view in rendered:
        assert view["widths"] == [view["width"]] * 3
        assert view["lines"][0].startswith("╭") and view["lines"][0].endswith("╮")
        assert view["lines"][1].startswith("  input") and view["lines"][1].endswith("│")
        assert view["lines"][2].startswith("╰") and view["lines"][2].endswith("╯")
    assert "COMMAND" in rendered[-1]["lines"][0]
    assert result["modes"] == [
        {"label": "", "marker": ">", "color": "accent"},
        {"label": "COMMAND", "marker": ":", "color": "warning"},
        {"label": "BASH", "marker": "$", "color": "bashMode"},
    ]


def test_mypi_render_mechanics_cover_columns_cursor_and_path_compaction() -> None:
    script = f"""
import {{ visibleWidth }} from "@earendil-works/pi-tui";
import {{
  cursorOpenFromFgAnsi,
  formatCwd,
  headerColumnWidths,
  restyleEditorCursor,
  twoColumn,
}} from {json.dumps(RENDER_UTILS.as_uri())};
const narrow = headerColumnWidths(50);
const wide = headerColumnWidths(110);
const columns = twoColumn("left", "right", wide.leftWidth, wide.rightWidth, (value) => value);
const open = cursorOpenFromFgAnsi("\u001b[38;2;125;196;181m");
const cursor = restyleEditorCursor("value \u001b[7mX\u001b[0m", open);
process.stdout.write(JSON.stringify({{
  narrow,
  wide,
  columnsWidth: visibleWidth(columns),
  cwd: formatCwd("/home/iaw/TS-pi-agent", "/home/iaw"),
  open,
  cursor,
}}));
"""
    result = _node_json(script)
    assert result["narrow"] == {"leftWidth": 50, "rightWidth": 0, "useRightColumn": False}
    assert result["wide"]["useRightColumn"] is True
    assert result["columnsWidth"] == 110
    assert result["cwd"] == "~/TS-pi-agent"
    assert "\x1b[48;2;125;196;181m" in result["open"]
    assert "\x1b[7m" not in result["cursor"]
    assert f'{result["open"]}X' in result["cursor"]


def test_ts_theme_inherits_mypi_dark_palette() -> None:
    theme = json.loads(THEME.read_text(encoding="utf-8"))
    assert theme["name"] == "ts-theme"
    assert theme["vars"] == {
        "bg": "#171B24",
        "fg": "#C8D3DC",
        "accent": "#7DC4B5",
        "cyan": "#7DCFFF",
        "blue": "#7AA2F7",
        "green": "#9ECE6A",
        "red": "#F7768E",
        "yellow": "#E0AF68",
        "violet": "#BB9AF7",
        "orange": "#FF9E64",
        "operator": "#89DDFF",
        "muted": "#8292A2",
        "dimmed": "#5F6B78",
        "border": "#53697E",
        "borderMuted": "#3B4A59",
        "selectedBg": "#293746",
        "userMessageBg": "#263348",
        "customMessageBg": "#202832",
        "toolPendingBg": "#332F25",
        "toolSuccessBg": "#253229",
        "toolErrorBg": "#38282E",
    }
    assert theme["colors"]["thinkingMedium"] == "blue"
    assert theme["colors"]["mdListBullet"] == "accent"


def test_ui_extension_is_observational_and_registers_history_renderers() -> None:
    script = f"""
import installUi from {json.dumps(UI.as_uri())};
const handlers = {{}};
const renderers = [];
let registeredTools = 0;
const pi = {{
  on: (name, handler) => {{ handlers[name] = handler; }},
  registerEntryRenderer: (name) => renderers.push(name),
  registerTool: () => registeredTools++,
  getThinkingLevel: () => "high",
}};
installUi(pi);
const calls = [];
let footerFactory;
const theme = {{ fg: (_color, text) => text, bold: (text) => text }};
const ui = {{
  theme,
  setStatus: (...args) => calls.push(["status", ...args]),
  setWidget: (...args) => calls.push(["widget", ...args]),
  setHeader: (...args) => calls.push(["header", ...args]),
  setFooter: (factory) => {{ footerFactory = factory; calls.push(["footer", factory]); }},
  setEditorComponent: (...args) => calls.push(["editor", ...args]),
  setWorkingIndicator: (...args) => calls.push(["indicator", ...args]),
  setWorkingMessage: (...args) => calls.push(["working", ...args]),
  setTitle: (...args) => calls.push(["title", ...args]),
}};
const ctx = {{
  ui,
  mode: "tui",
  cwd: "/home/iaw/TS-pi-agent",
  model: {{ id: "gpt-5" }},
  getContextUsage: () => ({{ percent: 42 }}),
  sessionManager: {{
    getSessionName: () => "maleic-ts",
    getSessionId: () => "1234567890abcdef",
    getSessionFile: () => "/tmp/session.jsonl",
  }},
}};
let renderRequests = 0;
const tui = {{ requestRender: () => renderRequests++, terminal: {{ rows: 30 }} }};
const footerData = {{
  getGitBranch: () => "pi_ts_subagents",
  getExtensionStatuses: () => new Map([["ts-subagent", "duplicate"], ["cluster", "queue: batch"]]),
  onBranchChange: () => () => {{}},
}};
const args = {{ operation: "compare", nodeId: "n009" }};
await handlers.session_start({{ type: "session_start", reason: "startup" }}, ctx);
const footer = footerFactory(tui, theme, footerData);
await handlers.agent_start({{ type: "agent_start" }}, ctx);
await handlers.tool_execution_start({{ type: "tool_execution_start", toolCallId: "call", toolName: "ts_subagent_render", args }}, ctx);
await handlers.tool_execution_update({{ type: "tool_execution_update", toolCallId: "call", toolName: "ts_subagent_render", args, partialResult: {{ details: {{ schema_version: "ts-subagent-status/1", tool_call_id: "call", task_id: "agent", role: "render", operation: "compare", phase: "running", node_id: "n009" }} }} }}, ctx);
const activeFooter = [50, 100, 140].map((width) => footer.render(width)[0]);
await handlers.tool_execution_end({{ type: "tool_execution_end", toolCallId: "call", toolName: "ts_subagent_render", result: {{}}, isError: false }}, ctx);
await handlers.agent_settled({{ type: "agent_settled" }}, ctx);
const idleFooter = footer.render(100)[0];
await handlers.session_shutdown({{ type: "session_shutdown" }}, ctx);
footer.dispose();
process.stdout.write(JSON.stringify({{
  handlerNames: Object.keys(handlers).sort(),
  renderers: renderers.sort(),
  registeredTools,
  statuses: calls.filter((item) => item[0] === "status").map((item) => item[2]),
  widgets: calls.filter((item) => item[0] === "widget").length,
  headers: calls.filter((item) => item[0] === "header").length,
  footers: calls.filter((item) => item[0] === "footer").length,
  editors: calls.filter((item) => item[0] === "editor").length,
  titles: calls.filter((item) => item[0] === "title").map((item) => item[1]),
  working: calls.filter((item) => item[0] === "working").map((item) => item[1]),
  activeFooter,
  idleFooter,
  renderRequests,
}}));
"""
    result = _node_json(script)
    assert result["registeredTools"] == 0
    assert result["handlerNames"] == [
        "agent_settled",
        "agent_start",
        "model_select",
        "session_before_compact",
        "session_compact",
        "session_info_changed",
        "session_shutdown",
        "session_start",
        "thinking_level_select",
        "tool_execution_end",
        "tool_execution_start",
        "tool_execution_update",
    ]
    assert result["renderers"] == sorted(
        [
            "ts-workspace-subagent-run",
            "ts-workspace-subagent-failed",
            "ts-workspace-compute-operator-run",
            "ts-workspace-compute-operator-failed",
            "ts-workspace-artifact-operator-run",
            "ts-workspace-artifact-operator-failed",
        ]
    )
    assert any(value and "running" in value for value in result["statuses"])
    assert result["statuses"][-1] is None
    assert result["widgets"] >= 4
    assert result["headers"] == 2
    assert result["footers"] == 2
    assert result["editors"] == 2
    assert len(result["titles"]) == 1 and result["titles"][0].startswith("TSPi · ")
    assert result["working"][0] == "[o_o] TSPi is thinking"
    assert result["working"][-1] is None
    assert all("Render running" in line for line in result["activeFooter"])
    assert "queue: batch" in result["activeFooter"][-1]
    assert "duplicate" not in result["activeFooter"][-1]
    assert "Render completed" in result["idleFooter"]
    assert result["renderRequests"] >= 4


def test_all_five_public_subagent_tools_emit_status_updates() -> None:
    review = (ROOT / "extensions" / "ts-workflow-review" / "index.ts").read_text(encoding="utf-8")
    compute = (ROOT / "extensions" / "ts-workflow-compute" / "index.ts").read_text(encoding="utf-8")
    artifacts = (ROOT / "extensions" / "ts-workflow-artifacts" / "index.ts").read_text(encoding="utf-8")
    ui = UI.read_text(encoding="utf-8")

    assert review.count("createSubagentStatusReporter({") == 1
    assert compute.count("createSubagentStatusReporter({") == 1
    assert artifacts.count("createSubagentStatusReporter({") == 3
    for source in (review, compute, artifacts):
        assert "reportStatus(\"preflight\")" in source
        assert "onLifecycle: reportStatus" in source
        assert "reportStatus(\"completed\"" in source
        assert "terminalStatusForError(error)" in source
    assert "setHeader" in ui
    assert "setFooter" in ui
    assert "setEditorComponent" in ui
    assert "setTitle" in ui
    assert "setWorkingMessage" in ui
    assert "registerTool" not in ui


def _node_json(script: str):
    completed = subprocess.run(
        ["node", "--experimental-loader", str(TS_LOADER), "--input-type=module", "--eval", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)
