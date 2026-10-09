import assert from "node:assert/strict";
import test from "node:test";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { createResearchAgentToolRenderers } from "../../../apps/agent/terminal/renderers/tools.mjs";
import { pinnedPiSource } from "./test-environment.mjs";

const source = pinnedPiSource();
const fromSource = path => import(pathToFileURL(join(source, path)));
const tui = await fromSource("packages/tui/src/index.ts");
const colors = [];
const theme = { fg(color, text) { colors.push(color); return text; }, bold(text) { return text; } };

test("tool summaries stay bounded while full arguments and output remain available", () => {
  const renderer = createResearchAgentToolRenderers(tui, ["research_read"]).research_read;
  const raw = JSON.stringify({ nodes: Array.from({ length: 100 }, (_, i) => ({ id: i, summary: "x".repeat(100) })) }, null, 2);
  const call = renderer.renderCall({ mode: "context", payload: raw }, theme, { expanded: false });
  assert.ok(call.render(60).length <= 4);
  const args = renderer.renderCall({ payload: raw }, theme, { expanded: true });
  assert.ok(args.render(60).length > 100);
  const result = { content: [{ type: "text", text: raw }] };
  assert.ok(renderer.renderResult(result, { expanded: false }, theme, {}).render(60).length <= 4);
  assert.ok(renderer.renderResult(result, { expanded: true }, theme, {}).render(60).length > 100);
});

test("job submission and running are distinct from completed and failed states", () => {
  const renderer = createResearchAgentToolRenderers(tui, ["job_start"]).job_start;
  for (const [state, color] of [["running", "warning"], ["succeeded", "success"], ["failed", "error"]]) {
    colors.length = 0;
    const result = renderer.renderResult({ content: [], details: { result: { state } } }, {}, theme, {});
    assert.match(result.render(60).join("\n"), new RegExp(state));
    assert.ok(colors.includes(color));
  }
  const result = renderer.renderResult({ content: [] }, {}, theme, {});
  assert.match(result.render(60).join("\n"), /Submitted/);
  const timed = renderer.renderResult({ content: [] }, {}, theme, { durationMs: 1200 });
  assert.match(timed.render(60).join("\n"), /Submitted · 1\.2s/);
  for (const durationMs of [undefined, null, NaN, -1]) {
    assert.doesNotMatch(renderer.renderResult({ content: [] }, {}, theme, { durationMs }).render(60).join("\n"), /\d+\.\ds/);
  }
  assert.doesNotMatch(renderer.renderResult({ content: [] }, { isPartial: true }, theme,
    { durationMs: 1200 }).render(60).join("\n"), /1\.2s/);
});

test("native chat applies registered renderers and expands cards without losing their transcript", async () => {
  const { ExperimentalChatView, configureToolRenderers } = await fromSource("packages/coding-agent/src/experimental/client-tui-chat.ts");
  const { initTheme } = await fromSource("packages/coding-agent/src/modes/interactive/theme/theme.ts");
  initTheme("dark");
  configureToolRenderers(createResearchAgentToolRenderers(tui, ["research_read"]));
  const view = new ExperimentalChatView({ requestRender() {} }, process.cwd());
  const raw = "evidence\n".repeat(100);
  try {
    const persisted = { docs: {}, entries: [
      { id: 1, kind: "pi.assistant", model: [{ role: "assistant", stopReason: "toolUse", content: [{ type: "toolCall", id: "one", name: "research_read", arguments: { mode: "context" } }] }] },
      { id: 2, kind: "pi.tool-result", model: [{ role: "toolResult", toolCallId: "one", toolName: "research_read", isError: false, durationMs: 1250, content: [{ type: "text", text: raw }] }] },
    ] };
    view.apply(persisted);
    assert.match(view.transcript.render(60).join("\n"), /1\.3s/);
    const collapsed = view.transcript.render(60).length;
    view.toggleTools();
    assert.ok(view.transcript.render(60).length > collapsed + 50);
    assert.match(view.transcript.render(60).join("\n"), /Tool execution: 1\.3s/);
    view.toggleTools();
    assert.equal(view.transcript.render(60).length, collapsed);
    // A newly attached presentation gets the recorded duration without a live timer.
    const reattached = new ExperimentalChatView({ requestRender() {} }, process.cwd());
    try {
      reattached.apply(persisted);
      assert.match(reattached.transcript.render(60).join("\n"), /1\.3s/);
    } finally { reattached.dispose(); }
  } finally { view.dispose(); configureToolRenderers({}); }
});
