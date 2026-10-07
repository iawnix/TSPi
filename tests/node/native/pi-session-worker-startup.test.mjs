import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import test from "node:test";
import { TEST_ROOT, managedPython, pinnedPiSource } from "./test-environment.mjs";

const execute = promisify(execFile);
const sourceRoot = pinnedPiSource();
const packageRoot = resolve(process.env.TSPI_TEST_PACKAGE_ROOT || process.cwd());

test("real worker queries and terminal resume/quit preserve durable sessions without model requests", {
  skip: !sourceRoot || !existsSync(join(sourceRoot, "packages/coding-agent/src/experimental/source-resolver.ts")),
  timeout: 60_000,
}, async () => {
  await mkdir(TEST_ROOT, { recursive: true });
  const root = await mkdtemp(join(TEST_ROOT, "w-"));
  const savedEnvironment = { ...process.env };
  let backend;
  try {
    process.env.PI_CODING_AGENT_DIR = join(root, "agent");
    await mkdir(process.env.PI_CODING_AGENT_DIR);
    await writeFile(join(process.env.PI_CODING_AGENT_DIR, "models.json"), JSON.stringify({ providers: { fixture: {
      baseUrl: "http://127.0.0.1:9/v1", apiKey: "fixture-only", api: "openai-completions",
      models: [{id:"fixture", name:"Fixture", reasoning:false, input:["text"],
        cost:{input:0, output:0, cacheRead:0, cacheWrite:0}, contextWindow:200000, maxTokens:4096}],
    } } }));
    process.env.TSPI_PYTHON = managedPython();
    process.env.PYTHONDONTWRITEBYTECODE = "1";
    const workspaceRoot = join(root, "workspaces");
    await mkdir(workspaceRoot);
    await execute(process.env.TSPI_PYTHON, [
      join(packageRoot, "apps/agent-cli/workspace_mode.py"),
      "--root", join(workspaceRoot, "startup"), "--workspace-id", "startup",
    ]);
    const { createTspiHarnessBackend } = await import(pathToFileURL(join(packageRoot, "apps/app-server/tspi-harness-backend.mjs")));
    backend = await createTspiHarnessBackend({
      sourceRoot, packageRoot, workspaceRoot,
      serverDirectory: join(root, "pi"), sessionDir: join(root, "sessions"),
      stateRoot: join(root, "state"), provider:"fixture", model:"fixture",
    });
    const created = await backend.createSession({ workspace_id: "startup", provider:"fixture", model:"fixture" });
    assert.equal(created.session.runtime_kind, "pi-harness");
    assert.equal(created.session.online, true);
    assert.equal(created.session.is_streaming, false);
    const read = await backend.readSession("startup", created.session.session_id);
    assert.equal(read.session.session_id, created.session.session_id);
    assert.equal(read.snapshot.operation, null);
    assert.ok(existsSync(join(root, "sessions", "startup", created.session.session_id, "session.sqlite")));
    const fromSource = (path) => import(pathToFileURL(join(sourceRoot, path)).href);
    const [{ openClientRuntime, activateBuiltinClientServices }, { defineService }, { BACKGROUND_CONTEXT }] = await Promise.all([
      fromSource("packages/coding-agent/src/experimental/client-runtime.ts"),
      fromSource("packages/chord/src/index.ts"),
      fromSource("packages/chord/src/context/index.ts"),
    ]);
    const runtime = await openClientRuntime({ command: "client", connect: { transport: "unix", path: backend.socketPath } });
    let services;
    try {
      const server = runtime.servers[0];
      const active = await activateBuiltinClientServices(server);
      await active.plugins.prepareSession({ sessionId: created.session.session_id, packagePaths: null }, BACKGROUND_CONTEXT);
      await active.management.attach(created.session.session_id, BACKGROUND_CONTEXT);
      const token = defineService("tspi.client-queries");
      services = server.session.open({ services: [token], assertAccess() {}, onError() {} });
      await services.ready(BACKGROUND_CONTEXT);
      const queries = services.use(token);
      const prompt = await queries.systemPrompt(BACKGROUND_CONTEXT);
      assert.equal(prompt.workspace_id, "startup");
      assert.equal(prompt.session_id, created.session.session_id);
      assert.match(prompt.result.effective, /TSPi research agent/);
      assert.ok(prompt.result.contributors.length > 0);
      const summary = await queries.research("summary", BACKGROUND_CONTEXT);
      assert.equal(summary.workspace_id, "startup");
      assert.equal(summary.result.schema_version, "research-summary/1");
      assert.match((await queries.research("storage bootstrap", BACKGROUND_CONTEXT)).error.message, /Usage/);
      const after = await backend.readSession("startup", created.session.session_id);
      assert.deepEqual(after.snapshot.messages, read.snapshot.messages);
      assert.equal(after.snapshot.is_streaming, false);
      // Exercise the actual Pi presentation and service catalogue, not a mock UI.
      const [{ ExperimentalClientTui }, { TuiMainScreen, ProcessTerminal }, { initTheme }, { createStaticFacetLoader }] = await Promise.all([
        fromSource("packages/coding-agent/src/experimental/client-tui.ts"),
        fromSource("packages/tui/src/index.ts"),
        fromSource("packages/coding-agent/src/modes/interactive/theme/theme.ts"),
        fromSource("packages/chord/src/index.ts"),
      ]);
      const { createTspiNativeClientFacet } = await import("../../../apps/app-server/tspi-native-client-facet.mjs");
      initTheme("dark");
      const ui = new TuiMainScreen(new ProcessTerminal());
      let quit = false;
      const facet = await createTspiNativeClientFacet({ sourceRoot, session: {
        sessionId: created.session.session_id, quit() { quit = true; },
        async list() { return backend.listSessions("startup"); },
        async resume() { throw new Error("Selecting the current session should be a no-op"); },
      } });
      const component = await ExperimentalClientTui.create({
        command: { command: "client", sessionId: created.session.session_id, pluginPackages: [] },
        ui, servers: [{ serverId: server.route.serverId, radius: false, server: server.server, session: server.session }],
        facetLoader: createStaticFacetLoader([facet]), requestRender() {}, finish() {},
      });
      const waitFor = async (predicate) => {
        for (let i = 0; i < 100; i++) {
          if (predicate()) return;
          await new Promise((resolve) => setTimeout(resolve, 10));
        }
        assert.fail(component.render(100).join("\n"));
      };
      const submit = (text) => { component.handleInput(text); component.handleInput("\u001b"); component.handleInput("\r"); };
      try {
        submit("/research summary");
        await waitFor(() => component.render(100).join("\n").includes("research · startup"));
        component.handleInput("\u001b");
        await new Promise((resolve) => setImmediate(resolve));
        submit("/sys-prompt");
        await waitFor(() => component.render(100).join("\n").includes("TSPi research agent"));
        component.handleInput("\u001b");
        await new Promise((resolve) => setImmediate(resolve));
        submit("/resume");
        await waitFor(() => component.render(100).join("\n").includes("Resume session"));
        component.handleInput("\u001b");
        await new Promise((resolve) => setImmediate(resolve));
        submit("/quit");
        await waitFor(() => quit);
      } finally {
        await component.close();
        ui.stop();
      }
      assert.equal((await backend.readSession("startup", created.session.session_id)).session.online, true);
      const second = await backend.createSession({ workspace_id: "startup", session_id: "second", provider: "fixture", model: "fixture" });
      const { startTspiHost } = await import("../../../apps/app-server/tspi-host.mjs");
      const { connectHost } = await import("../../../apps/app-server/tspi-host-client.mjs");
      const { runTerminalSessions } = await import("../../../apps/app-server/tspi-terminal-session.mjs");
      const { runClientTui } = await fromSource("packages/coding-agent/src/experimental/client-tui.ts");
      const { defineFacet } = await fromSource("packages/chord/src/index.ts");
      const { SlashCommands } = await fromSource("packages/coding-agent/src/experimental/services/slash-commands.ts");
      const host = await startTspiHost({ socketPath: join(root, "host.sock"), workspaceRoot, stateRoot: join(root, "hs"), sessionBackend: backend, monitorPollMs: 0 });
      const peer = await connectHost({ socketPath: host.socketPath });
      const opened = [];
      let currentSession;
      let commandDone;
      let timedOut = false;
      try {
        await runTerminalSessions({
          command: { command: "client", sessionId: created.session.session_id, pluginPackages: [], connect: { transport: "unix", path: backend.socketPath } },
          workspaceId: "startup", request: (method, params) => peer.request(method, params),
          async createFacet(session) {
            currentSession = session;
            return createStaticFacetLoader([
              await createTspiNativeClientFacet({ sourceRoot, session }),
              defineFacet({ id: "test-terminal-driver", setup(env) {
                const commands = env.use(SlashCommands);
                env.onActivate(() => {
                  const timer = setTimeout(() => {
                    const name = session.sessionId === created.session.session_id ? "resume" : "quit";
                    commandDone = commands.list().find((item) => item.name === name).run(name === "resume" ? second.session.session_id : "", BACKGROUND_CONTEXT);
                  }, 50);
                  env.own(() => clearTimeout(timer));
                });
              } }),
            ]);
          },
          async run(command, options) {
            opened.push(command.sessionId);
            const timer = setTimeout(() => { timedOut = true; currentSession.quit(); }, 5_000);
            try { await runClientTui(command, options); await commandDone; }
            finally { clearTimeout(timer); }
          },
        });
        assert.equal(timedOut, false);
        assert.deepEqual(opened, [created.session.session_id, "second"]);
        assert.equal((await backend.readSession("startup", created.session.session_id)).session.online, true);
        assert.equal((await backend.readSession("startup", "second")).session.online, true);
        await assert.rejects(ExperimentalClientTui.create({
          command: { command: "client", sessionId: "missing" }, requireExistingSession: true,
          ui, servers: [{ serverId: server.route.serverId, radius: false, server: server.server, session: server.session }],
          requestRender() {}, finish() {},
        }), /does not contain Session/);
        assert.equal((await backend.listSessions("startup")).length, 2);
      } finally { peer.close(); await host.close(); }
    } finally {
      await services?.dispose(BACKGROUND_CONTEXT);
      await runtime.dispose();
    }

  } finally {
    try { await backend?.close(); }
    finally {
      for (const key of Object.keys(process.env)) if (!(key in savedEnvironment)) delete process.env[key];
      Object.assign(process.env, savedEnvironment);
      await rm(root, { recursive: true, force: true });
    }
  }
});
