import assert from "node:assert/strict";
import test from "node:test";
import { createTerminalCommands } from "../../../apps/agent/terminal/commands/facet.mjs";
import { createClientQueries } from "../../../apps/agent/pi/services/queries.mjs";
import { createTerminalSession, runTerminalSessions } from "../../../apps/agent/terminal/session.mjs";
import { parseSlashCommand, SLASH_COMMAND_NAMES } from "../../../apps/agent/tools/commands.mjs";

const row = (id, workspace = "remote") => ({ session_id: id, workspace_id: workspace });

test("worker queries bind identity and admit only read-only research arguments", async () => {
  const calls = [];
  const prompt = { effective: "worker prompt", contributors: [] };
  const queries = createClientQueries({ workspaceId: "remote", sessionId: "one", promptManifest: prompt,
    commandBridge: { async execute_command(...args) { calls.push(args); return { root: "/remote/workspace" }; } },
  });
  assert.deepEqual(await queries.research("read note_123"), {
    workspace_id: "remote", session_id: "one", result: { root: "/remote/workspace" },
  });
  assert.deepEqual(calls, [["research.read", { ref: "note_123" }]]);
  for (const input of ["change x", "storage bootstrap", "summary --root /local", { root: "/local" }]) {
    assert.ok((await queries.research(input)).error);
  }
  assert.equal(calls.length, 1);
  assert.equal((await queries.systemPrompt()).result, prompt);
});

test("command registry, parsing, native selection, and worker reads agree", async () => {
  const shown = [];
  let quit = 0;
  const resumed = [];
  const queries = createClientQueries({ workspaceId: "remote", sessionId: "one",
    promptManifest: { effective: "actual worker prompt", contributors: [{ origin: "native", source: "/remote/prompt" }], sha256: "digest" },
    commandBridge: { async execute_command() { return { summary: "remote research result" }; } },
  });
  let choice;
  const ui = { showStatus(text) { shown.push(text); }, async select(title) { shown.push(title); return choice; } };
  const commands = createTerminalCommands({ ui, queries, show: async (title, body) => shown.push(`${title}\n${body}`), session: {
    sessionId: "one", quit() { quit++; }, async list() { return [row("one"), row("two")]; }, async resume(id) { resumed.push(id); },
  } });
  assert.deepEqual(commands.map((c) => `/${c.name}`), SLASH_COMMAND_NAMES);
  assert.throws(() => parseSlashCommand("debug", "prompt"), /unsupported/);
  assert.throws(() => parseSlashCommand("sys-prompt", "unexpected"), /Usage/);
  const run = (name, args = "") => commands.find((c) => c.name === name).run(args, {});
  await run("research");
  await run("sys-prompt");
  assert.match(shown.join("\n"), /remote research result/);
  assert.match(shown.join("\n"), /actual worker prompt/);
  assert.match(shown.join("\n"), /\/remote\/prompt/);
  await run("resume"); // Escape/cancel
  assert.deepEqual(resumed, []);
  choice = "two";
  await run("resume");
  assert.deepEqual(resumed, ["two"]);
  await run("quit", "bad");
  assert.equal(quit, 0);
  await run("quit");
  assert.equal(quit, 1);
});

test("resume rejects unavailable or foreign sessions and checks Host response identity", async () => {
  const calls = [];
  const switched = [];
  let wrong = false;
  const session = createTerminalSession({ workspaceId: "remote", sessionId: "one", switchSession: (id) => switched.push(id),
    async request(method, params) {
      calls.push([method, params]);
      if (method === "session/list") return { sessions: [row("one"), row("two"), row("foreign", "elsewhere")] };
      return { session: row("two", wrong ? "elsewhere" : "remote"), client: { session_id: "two" } };
    },
  });
  await session.resume("one");
  assert.equal(calls.length, 0);
  for (const id of ["missing", "foreign"]) await assert.rejects(session.resume(id), /not available/);
  assert.equal(calls.some(([method]) => method === "session/resume"), false);
  wrong = true;
  await assert.rejects(session.resume("two"), /unexpected/);
  assert.deepEqual(switched, []);
  wrong = false;
  await session.resume("two");
  assert.deepEqual(switched, ["two"]);
  assert.equal(calls.at(-1)[1].workspace_id, "remote");
});

test("session loop waits for disposal before switching and quit does not call the Host", async () => {
  const events = [];
  let session;
  await runTerminalSessions({ command: { sessionId: "one" }, workspaceId: "remote",
    async request(method) {
      if (method === "session/list") return { sessions: [row("one"), row("two")] };
      assert.equal(method, "session/resume");
      return { session: row("two"), client: { session_id: "two" } };
    },
    createFacet(value) { session = value; return {}; },
    async run(command, { signal }) {
      events.push(`open ${command.sessionId}`);
      if (command.sessionId === "one") await session.resume("two");
      else session.quit();
      assert.equal(signal.aborted, true);
      await new Promise((resolve) => setImmediate(resolve));
      events.push(`disposed ${command.sessionId}`);
    },
  });
  assert.deepEqual(events, ["open one", "disposed one", "open two", "disposed two"]);
});

test("document commands pass complete text to the document surface", async () => {
  const shown = [];
  const commands = createTerminalCommands({
    ui: { showStatus() {} },
    show: async (title,body) => shown.push({title,body}),
    queries: { async systemPrompt() { return { workspace_id: "remote", session_id: "one", result: { effective: Array.from({length:40},(_,i)=>`line ${i}`).join("\n") } }; } },
    session: { sessionId: "one" },
  });
  await commands.find(c=>c.name === "sys-prompt").run("",{});
  assert.equal(shown[0].title,"System prompt");
  assert.match(shown[0].body,/line 0\n/);
  assert.match(shown[0].body,/line 39/);
});

test("closing a presentation prevents a delayed Host response from reopening it", async () => {
  let session;
  let reply;
  let started;
  const requested = new Promise((resolve) => { started = resolve; });
  let resume;
  await runTerminalSessions({ command: { sessionId: "one" }, workspaceId: "remote",
    async request(method) {
      if (method === "session/list") return { sessions: [row("two")] };
      started();
      return new Promise((resolve) => { reply = resolve; });
    },
    createFacet(value) { session = value; return {}; },
    async run() { resume = session.resume("two"); await requested; },
  });
  assert.equal(session.signal.aborted, true);
  const rejected = assert.rejects(resume, { name: "AbortError" });
  reply({ session: row("two"), client: { session_id: "two" } });
  await rejected;
});
