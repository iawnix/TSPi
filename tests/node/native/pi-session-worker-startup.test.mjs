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
    // A package-external manifest must be visible to the real Worker's Python
    // bridge as well as its JS discovery. It needs no scientific imports.
    const externalManifest = join(root, "manifest.json");
    const externalProfile = { id: "fixture.material", version: "1", checks: [
      { id: "material", kind: "registered_artifact" },
    ] };
    await writeFile(externalManifest, JSON.stringify({ schema_version: "tspi-extension/1",
      name: "fixture-extension", version: "1.0.0", skills: [], acceptance_profiles: [externalProfile] }));
    process.env.TSPI_EXTENSION_MANIFESTS = externalManifest;
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
      stateRoot: join(root, "state"), model: { provider: "fixture", id: "fixture" },
    });
    const created = await backend.createSession({ workspace_id: "startup", model: { provider: "fixture", id: "fixture" } });
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
      const telemetry = await queries.telemetry(BACKGROUND_CONTEXT);
      assert.equal(telemetry.session_id, created.session.session_id);
      assert.ok(telemetry.result.contextWindow > 0);
      assert.ok(telemetry.result.contextTokens >= 0);
      assert.equal(telemetry.result.estimated, true);
      const summary = await queries.research("summary", BACKGROUND_CONTEXT);
      assert.equal(summary.workspace_id, "startup");
      assert.equal(summary.result.schema_version, "research-summary/1");
      const profiles = await queries.research("profiles", BACKGROUND_CONTEXT);
      assert.deepEqual(profiles.result.profiles.find(profile => profile.id === externalProfile.id), externalProfile);
      assert.match((await queries.research("storage bootstrap", BACKGROUND_CONTEXT)).error.message, /Usage/);
      const after = await backend.readSession("startup", created.session.session_id);
      assert.deepEqual(after.snapshot.messages, read.snapshot.messages);
      assert.equal(after.snapshot.is_streaming, false);
      // Exercise the actual Pi presentation and service catalogue, not a mock UI.
      const [{ ExperimentalClientTui }, { TuiAltScreen }, { initTheme }, { createStaticFacetLoader, defineFacet: testFacet }] = await Promise.all([
        fromSource("packages/coding-agent/src/experimental/client-tui.ts"),
        fromSource("packages/tui/src/index.ts"),
        fromSource("packages/coding-agent/src/modes/interactive/theme/theme.ts"),
        fromSource("packages/chord/src/index.ts"),
      ]);
      const { createTspiNativeClientFacet } = await import(pathToFileURL(join(packageRoot, "apps/app-server/tspi-native-client-facet.mjs")));
      const { renderLayoutFrame } = await fromSource('packages/tui/src/layout.ts');
      initTheme("dark");
      const { VirtualTerminal } = await fromSource('packages/tui/test/virtual-terminal.ts');
      const terminal = new VirtualTerminal(100, 24);
      const ui = new TuiAltScreen(terminal);
      let quit = false;
      let testUI, finishSlow, finishOperation, operationFinished=false;
      const { PresentationUI } = await fromSource('packages/coding-agent/src/experimental/services/presentation-ui.ts');
      const { SlashCommands: TestCommands } = await fromSource('packages/coding-agent/src/experimental/services/slash-commands.ts');
      const driver = testFacet({ id:'test-command-panels', setup(env) {
        const presentation=env.use(PresentationUI), commands=env.use(TestCommands);
        env.onActivate(()=>{
          testUI=presentation;
          env.own(commands.replace({name:'slow',description:'Delayed read',async run(_args,context){
            await new Promise(resolve=>{finishSlow=resolve});
            await presentation.showDocument({render:()=>['STALE DOCUMENT'],invalidate(){}},context);
            assert.equal(await presentation.select('STALE SELECTOR',[{value:'stale',label:'stale'}],undefined,context),undefined);
            presentation.showStatus('STALE STATUS',context);
          }}));
          env.own(commands.replace({name:'delayed-operation',description:'Delayed mutation',async run(_args,context){
            await new Promise(resolve=>{finishOperation=resolve});
            operationFinished=true;
            presentation.showStatus('STALE OPERATION',context,'success');
          }}));
        });
      }});
      const facet = await createTspiNativeClientFacet({ sourceRoot, session: {
        workspaceId: "startup", sessionId: created.session.session_id, quit() { quit = true; },
        async list() { return [...await backend.listSessions("startup"), {session_id:'another-session'}]; },
        async resume() { throw new Error("Selecting the current session should be a no-op"); },
      } });
      const component = await ExperimentalClientTui.create({
        command: { command: "client", sessionId: created.session.session_id, pluginPackages: [] },
        ui, servers: [{ serverId: server.route.serverId, radius: false, server: server.server, session: server.session }],
        facetLoader: createStaticFacetLoader([facet,driver]), requestRender() { ui.requestRender(); }, finish() {},
      });
      const waitFor = async (predicate) => {
        for (let i = 0; i < 100; i++) {
          if (predicate()) return;
          await new Promise((resolve) => setTimeout(resolve, 10));
        }
        assert.fail(component.render(100).join("\n"));
      };
      const submit = (text) => { terminal.sendInput(text); terminal.sendInput("\u001b"); terminal.sendInput("\r"); };
      try {
        ui.addChild(component); ui.setLayoutRoot(component.layoutRoot); ui.setFocus(component); ui.start();
        const clickEditor = async () => {
          // Separate clicks so xterm does not interpret them as a double click.
          await new Promise(resolve => setTimeout(resolve, 700));
          const frame = renderLayoutFrame(component.layoutRoot, 100, 24, () => {});
          const row = frame.lines.findLastIndex(line => line.includes('────'));
          assert.ok(row > 0);
          terminal.sendInput(`\x1b[<0;2;${row}M`);
          terminal.sendInput(`\x1b[<0;2;${row}m`);
          await new Promise(resolve => setTimeout(resolve, 50));
          assert.notEqual(ui.getFocusedComponent().constructor.name, 'CustomEditor');
        };
        await waitFor(() => !component.render(100).join("\n").includes("Context Unknown"));
        assert.doesNotMatch(component.render(100).join("\n"), /Server:| entries|\/model ·/);
        await clickEditor();
        submit("/usage");
        await waitFor(() => component.render(100).join("\n").includes("Session usage"));
        terminal.sendInput("\u001b");
        await new Promise(resolve => setImmediate(resolve));
        submit("/research summary");
        await waitFor(() => component.render(100).join("\n").includes("Research state"));
        terminal.sendInput("\u001b");
        await new Promise((resolve) => setImmediate(resolve));
        submit("/sys-prompt");
        await waitFor(() => component.render(100).join("\n").includes("TSPi research agent"));
        const originalRows=process.stdout.rows;
        try {
          for (const [width,height] of [[80,24],[120,30],[32,12],[20,10]]) {
            process.stdout.rows=height;
            const frame=renderLayoutFrame(component.layoutRoot,width,height,()=>{});
            assert.equal(frame.lines.length,height);
            assert.match(frame.lines.join('\n'),/\/sys-prompt/);
            assert.match(frame.lines.join('\n'),/Esc Back/);
          }
        } finally { process.stdout.rows=originalRows; }
        terminal.sendInput("\u001b");
        await new Promise((resolve) => setImmediate(resolve));
        await clickEditor();
        submit("/resume");
        await waitFor(() => component.render(100).join("\n").includes("Resume session"));
        terminal.sendInput('\x1b[B');
        testUI.setActivity({render:()=>['background monitor refresh'],invalidate(){}});
        assert.match(component.render(100).join('\n'),/› another-session/);
        assert.match(component.render(100).join('\n'),/\[current\]/);
        terminal.sendInput("\u001b");
        await new Promise((resolve) => setImmediate(resolve));
        await clickEditor();
        terminal.sendInput('draft text');
        terminal.sendInput('\x1b[D');
        terminal.sendInput('\x0c'); // Ctrl+L model selector must retain draft and cursor.
        await waitFor(()=>component.render(100).join('\n').includes('Select model'));
        terminal.sendInput('\x1b');
        await new Promise(resolve=>setImmediate(resolve));
        terminal.sendInput('!');
        assert.match(component.render(100).join('\n').replace(/\x1b\[[0-9;]*m|\x1b_pi:c\x07/g,''),/draft tex!t/);
        terminal.sendInput('\x05'); terminal.sendInput('\x15'); // End, clear draft.
        submit('/slow');
        await waitFor(()=>typeof finishSlow === 'function');
        assert.match(component.render(100).join('\n'),/\/slow · … Running/);
        terminal.sendInput('\x1b');
        submit('/usage');
        await waitFor(()=>component.render(100).join('\n').includes('Session usage'));
        finishSlow();
        await new Promise(resolve=>setImmediate(resolve));
        assert.doesNotMatch(component.render(100).join('\n'),/STALE/);
        assert.match(component.render(100).join('\n'),/Session usage/);
        terminal.sendInput('\x1b');
        await new Promise(resolve=>setImmediate(resolve));
        submit('/delayed-operation');
        await waitFor(()=>typeof finishOperation === 'function');
        terminal.sendInput('working draft');
        assert.match(component.render(100).join('\n'), /working draft/);
        terminal.sendInput('\x05'); terminal.sendInput('\x15');
        terminal.sendInput('\x1b'); finishOperation();
        await waitFor(()=>operationFinished);
        assert.doesNotMatch(component.render(100).join('\n'),/STALE/);
        submit('/thinking invalid');
        await waitFor(()=>component.render(100).join('\n').includes('Unknown thinking level'));
        assert.match(component.render(100).join('\n'),/\/thinking · ! Error/);
        terminal.sendInput('\x1b');
        submit('/unknown');
        await waitFor(()=>component.render(100).join('\n').includes('Unknown command'));
        terminal.sendInput('\x1b');
        submit('/model fixture/fixture');
        await waitFor(()=>component.render(100).join('\n').includes('Selected fixture/fixture'));
        assert.match(component.render(100).join('\n'),/\/model · ✓ Done/);
        terminal.sendInput('\x1b');
        submit('/thinking off');
        await waitFor(()=>component.render(100).join('\n').includes('Thinking level: off'));
        terminal.sendInput('\x1b');
        await clickEditor();
        submit('/compact');
        await waitFor(() => component.render(100).join('\n').includes('Nothing to compact.'));
        assert.doesNotMatch(component.render(100).join('\n'), /Esc (Dismiss|Hide)|Operation submitted/);
        terminal.sendInput('compact draft');
        assert.match(component.render(100).join('\n'), /compact draft/);
        terminal.sendInput('\x05'); terminal.sendInput('\x15');
        submit('/reload');
        await waitFor(()=>component.render(100).join('\n').includes('Reloaded plugins.'));
        assert.match(component.render(100).join('\n'),/\/reload · ✓ Done/);
        terminal.sendInput('reload draft');
        assert.match(component.render(100).join('\n'), /reload draft/);
        terminal.sendInput('\x05'); terminal.sendInput('\x15');
        terminal.sendInput('\x1b');
        submit("/quit");
        await waitFor(() => quit);
      } finally {
        await component.close();
        ui.stop();
      }
      assert.equal((await backend.readSession("startup", created.session.session_id)).session.online, true);
      const second = await backend.createSession({ workspace_id: "startup", session_id: "second", model: { provider: "fixture", id: "fixture" } });
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
