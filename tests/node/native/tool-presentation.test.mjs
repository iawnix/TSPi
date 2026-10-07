import assert from "node:assert/strict";
import test from "node:test";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { createTspiToolRenderers } from "../../../apps/app-server/tspi-tool-renderers.mjs";
import { pinnedPiSource } from "./test-environment.mjs";

const source = pinnedPiSource();
const fromSource = path => import(pathToFileURL(join(source, path)));
const tui = await fromSource("packages/tui/src/index.ts");
const colors = [];
const theme = { fg(color, text) { colors.push(color); return text; }, bold(text) { return text; } };

test("tool summaries stay bounded while full arguments and output remain available", () => {
  const renderer = createTspiToolRenderers(tui, ["research_read"]).research_read;
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
  const renderer = createTspiToolRenderers(tui, ["job_start"]).job_start;
  for (const [state, color] of [["running", "warning"], ["succeeded", "success"], ["failed", "error"]]) {
    colors.length = 0;
    const result = renderer.renderResult({ content: [], details: { result: { state } } }, {}, theme, {});
    assert.match(result.render(60).join("\n"), new RegExp(state));
    assert.ok(colors.includes(color));
  }
  const result = renderer.renderResult({ content: [] }, {}, theme, {});
  assert.match(result.render(60).join("\n"), /已提交/);
});

test("native chat applies registered renderers and expands cards without losing their transcript", async () => {
  const { ExperimentalChatView, configureToolRenderers } = await fromSource("packages/coding-agent/src/experimental/client-tui-chat.ts");
  const { initTheme } = await fromSource("packages/coding-agent/src/modes/interactive/theme/theme.ts");
  initTheme("dark");
  configureToolRenderers(createTspiToolRenderers(tui, ["research_read"]));
  const view = new ExperimentalChatView({ requestRender() {} }, process.cwd());
  const raw = "evidence\n".repeat(100);
  try {
    view.apply({ docs: {}, entries: [
      { id: 1, kind: "pi.assistant", model: [{ role: "assistant", stopReason: "toolUse", content: [{ type: "toolCall", id: "one", name: "research_read", arguments: { mode: "context" } }] }] },
      { id: 2, kind: "pi.tool-result", model: [{ role: "toolResult", toolCallId: "one", toolName: "research_read", isError: false, content: [{ type: "text", text: raw }] }] },
    ] });
    const collapsed = view.transcript.render(60).length;
    view.toggleTools();
    assert.ok(view.transcript.render(60).length > collapsed + 50);
    view.toggleTools();
    assert.equal(view.transcript.render(60).length, collapsed);
  } finally { view.dispose(); configureToolRenderers({}); }
});
