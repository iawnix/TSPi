import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import test from "node:test";
import { createServer } from "node:http";
import { TEST_ROOT, TEST_SOCKET_ROOT, retainPiDiagnostics, managedPython, pinnedPiSource, assertInstalledRuntime } from "./test-environment.mjs";

const execute = promisify(execFile);
const sourceRoot = pinnedPiSource();
const packageRoot = resolve(process.env.RESEARCH_AGENT_TEST_PACKAGE_ROOT || process.cwd());

test("real worker terminal isolates monitor refresh, command feedback and task cancellation", {
  timeout: 90_000,
}, async () => {
  await assertInstalledRuntime(packageRoot);
  await mkdir(TEST_ROOT, { recursive: true });
  const root = await mkdtemp(join(TEST_ROOT, "w-"));
  const socketRoot = join(TEST_SOCKET_ROOT, "w");
  await mkdir(socketRoot);
  const savedEnvironment = { ...process.env };
  let completed = false;
  let backend;
  let modelRequests = 0;
  const modelServer = createServer((_request, response) => {
    modelRequests++;
    response.writeHead(200, {'content-type':'text/event-stream'});
    response.write(`data: ${JSON.stringify({id:'fixture',object:'chat.completion.chunk',created:1,model:'fixture',
      choices:[{index:0,delta:{role:'assistant',content:'Local deterministic response'},finish_reason:null}]})}\n\n`);
    // Keep this local stream open until the user aborts; no remote provider is used.
  });
  await new Promise(resolve => modelServer.listen(0, '127.0.0.1', resolve));
  try {
    process.env.RESEARCH_AGENT_DEBUG = "1";
    process.env.RESEARCH_AGENT_PI_DIAGNOSTIC_FILE = join(root, "pi-child.log");
    process.env.PI_CODING_AGENT_DIR = join(root, "agent");
    process.env.PI_AGENT_DIR = process.env.PI_CODING_AGENT_DIR;
    await mkdir(process.env.PI_CODING_AGENT_DIR);
    await writeFile(join(process.env.PI_CODING_AGENT_DIR, "models.json"), JSON.stringify({ providers: { fixture: {
      baseUrl: `http://127.0.0.1:${modelServer.address().port}/v1`, apiKey: "fixture-only", api: "openai-completions",
      models: [{id:"fixture", name:"Fixture", reasoning:false, input:["text"],
        cost:{input:0, output:0, cacheRead:0, cacheWrite:0}, contextWindow:200000, maxTokens:4096}],
    } } }));
    process.env.RESEARCH_AGENT_PYTHON = managedPython();
    process.env.PYTHONDONTWRITEBYTECODE = "1";
    const workspaceRoot = join(root, "workspaces");
    await mkdir(workspaceRoot);
    await execute(process.env.RESEARCH_AGENT_PYTHON, [
      join(packageRoot, "apps/agent-cli/workspace_mode.py"),
      "--root", join(workspaceRoot, "startup"), "--workspace-id", "startup",
    ]);
    const { createResearchAgentHarnessBackend } = await import(pathToFileURL(join(packageRoot, "apps/agent/pi/backend.mjs")));
    backend = await createResearchAgentHarnessBackend({
      sourceRoot, packageRoot, workspaceRoot,
      serverDirectory: socketRoot, sessionDir: join(root, "sessions"),
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
      const token = defineService("research-agent.client-queries");
      services = server.session.open({ services: [token], assertAccess() {}, onError() {} });
      await services.ready(BACKGROUND_CONTEXT);
      const queries = services.use(token);
      const prompt = await queries.systemPrompt(BACKGROUND_CONTEXT);
      assert.equal(prompt.workspace_id, "startup");
      assert.equal(prompt.session_id, created.session.session_id);
      assert.match(prompt.result.effective, /ResearchAgent/);
      assert.ok(prompt.result.contributors.length > 0);
      const telemetry = await queries.telemetry(BACKGROUND_CONTEXT);
      assert.equal(telemetry.session_id, created.session.session_id);
      assert.ok(telemetry.result.contextWindow > 0);
      assert.ok(telemetry.result.contextTokens >= 0);
      assert.equal(telemetry.result.estimated, true);
      const summary = await queries.research("read", BACKGROUND_CONTEXT);
      assert.equal(summary.workspace_id, "startup");
      assert.equal(summary.result.schema_version, "research-snapshot/2");
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
      const { createResearchAgentNativeClientFacet } = await import(pathToFileURL(join(packageRoot, "apps/agent/terminal/commands/facet.mjs")));
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
          env.own(commands.replace({name:'feedback',description:'Fixture feedback',run(_args,context){
            presentation.showStatus('Fixture completed',context,'success');
          }}));
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
      let monitorRunning=1, monitorPending=0, refreshMonitor;
      const facet = await createResearchAgentNativeClientFacet({ sourceRoot, session: {
        workspaceId: "startup", sessionId: created.session.session_id, quit() { quit = true; },
        async monitorStatus() { return {workspace_id:'startup',
          monitors:Array.from({length:monitorRunning},()=>({session_id:created.session.session_id,last_state:'running',enabled:true})),
          pending_deliveries:Array.from({length:monitorPending},()=>({session_id:created.session.session_id})),
          host_worker_health:{last_successful_poll:new Date().toISOString()},supervisor_health:{state:'running'}}; },
        subscribeMonitor(onChange) { refreshMonitor=onChange; return ()=>{refreshMonitor=undefined;}; },
        async list() { return [...await backend.listSessions("startup"), {session_id:'another-session'}]; },
        async resume() { throw new Error("Selecting the current session should be a no-op"); },
      } });
      const component = await ExperimentalClientTui.create({
        command: { command: "client", sessionId: created.session.session_id, pluginPackages: [] },
        ui, servers: [{ serverId: server.route.serverId, radius: false, server: server.server, session: server.session }],
        facetLoader: createStaticFacetLoader([facet,driver]), requestRender() { ui.requestRender(); }, finish() {},
      });
      const waitFor = async (predicate, timeout = 2000) => {
        for (let i = 0; i < timeout / 10; i++) {
          if (await predicate()) return;
          await new Promise((resolve) => setTimeout(resolve, 10));
        }
        assert.fail(component.render(100).join("\n"));
      };
      const submit = (text) => { terminal.sendInput(text); terminal.sendInput("\r"); };
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
        testUI.setActivity({render:()=>['Monitor ✓ · ↑1'],invalidate(){}});
        submit("/usage");
        await waitFor(() => component.render(100).join("\n").includes("Session usage"));
        const usageFrame=renderLayoutFrame(component.layoutRoot,100,24,()=>{});
        assert.ok(usageFrame.lines.findIndex(line=>line.includes('/usage'))>0);
        assert.doesNotMatch(usageFrame.lines.join('\n'),/Scroll|provider-reported|Monitor|compaction-aware/);
        for(let i=0;i<20;i++) terminal.sendInput('\x1b[B');
        assert.deepEqual(renderLayoutFrame(component.layoutRoot,100,24,()=>{}).lines,usageFrame.lines);
        assert.doesNotMatch(component.render(100).join('\n'),/Monitor ✓ · ↑1/);
        const beforeRefresh=component.render(100).join('\n');
        const documentFocus=ui.getFocusedComponent();
        testUI.setActivity({render:()=>['Monitor ✓ · ↑2'],invalidate(){}});
        assert.equal(component.render(100).join('\n'),beforeRefresh);
        assert.equal(ui.getFocusedComponent(),documentFocus);
        terminal.sendInput("\u001b");
        await waitFor(()=>component.render(100).join('\n').includes('Monitor ✓ · ↑2'));
        await new Promise(resolve => setImmediate(resolve));
        submit('/monitor');
        await waitFor(()=>component.render(100).join('\n').includes('Running: 1'));
        const monitorFocus=ui.getFocusedComponent();
        monitorRunning=2;monitorPending=1;refreshMonitor();
        await waitFor(()=>component.render(100).join('\n').includes('Running: 2'));
        assert.equal(ui.getFocusedComponent(),monitorFocus);
        assert.match(component.render(100).join('\n'),/Pending delivery: 1/);
        assert.doesNotMatch(component.render(100).join('\n'),/Total tokens:.*\n.*Status:|Monitor ✓ · ⚙/);
        terminal.sendInput('\x1b');
        await waitFor(()=>component.render(100).join('\n').includes('Monitor ✓ · ⚙2 · ↑1'));
        await new Promise(resolve=>setImmediate(resolve));
        submit("/research read");
        await waitFor(() => component.render(100).join("\n").includes("Research state"));
        terminal.sendInput("\u001b");
        await new Promise((resolve) => setImmediate(resolve));
        submit("/sys-prompt");
        await waitFor(() => component.render(100).join("\n").includes("You are ResearchAgent"));
        terminal.sendInput('\x1b[C');
        const scrolledDocument=component.render(100).join('\n');
        testUI.setActivity({render:()=>['Monitor !'],invalidate(){}});
        assert.equal(component.render(100).join('\n'),scrolledDocument);
        terminal.sendInput('\x1b[H');
        for (const [width,height] of [[80,24],[120,30],[32,12],[20,10]]) {
          const frame=renderLayoutFrame(component.layoutRoot,width,height,()=>{});
          assert.equal(frame.lines.length,height);
          assert.match(frame.lines[0],/\/sys-prompt/);
          assert.match(frame.lines[height-3],/Esc Back/);
          assert.equal(frame.primaryScrollView,undefined);
          component.handleInput('\x1b[F');
          const end=renderLayoutFrame(component.layoutRoot,width,height,()=>{});
          for(let i=0;i<10;i++) component.handleInput('\x1b[B');
          assert.deepEqual(renderLayoutFrame(component.layoutRoot,width,height,()=>{}).lines,end.lines);
        }
        terminal.sendInput("\u001b");
        await new Promise((resolve) => setImmediate(resolve));
        await clickEditor();
        submit("/resume");
        await waitFor(() => component.render(100).join("\n").includes("Resume session"));
        terminal.sendInput('\x1b[B');
        const selectorFocus=ui.getFocusedComponent();
        testUI.setActivity({render:()=>['Monitor ✓ · ↑3'],invalidate(){}});
        assert.equal(ui.getFocusedComponent(),selectorFocus);
        assert.doesNotMatch(component.render(100).join('\n'),/Monitor ✓ · ↑3/);
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
        const commandLines=component.render(100);
        const monitorIndex=commandLines.findIndex(line=>line.includes('Monitor ✓'));
        assert.ok(monitorIndex > commandLines.findIndex(line=>line.includes('/model ·')));
        assert.match(commandLines[monitorIndex+1],/─/);
        terminal.sendInput('timer draft');
        await waitFor(()=>!component.render(100).join('\n').includes('/model ·'),4500);
        assert.match(component.render(100).join('\n'),/timer draft/);
        terminal.sendInput('\x05'); terminal.sendInput('\x15');
        submit('/feedback');
        await waitFor(()=>component.render(100).join('\n').includes('Fixture completed'));
        // A prior success timer must not dismiss a newer error.
        submit('/unknown');
        await waitFor(()=>component.render(100).join('\n').includes('Unknown command'));
        await new Promise(resolve=>setTimeout(resolve,3200));
        assert.match(component.render(100).join('\n'),/Unknown command/);
        terminal.sendInput('\x1b');
        submit('/thinking off');
        await waitFor(()=>component.render(100).join('\n').includes('Thinking level: off'));
        terminal.sendInput('\x1b');
        await clickEditor();
        submit('/compact');
        await waitFor(() => component.render(100).join('\n').includes('Nothing to compact.'));
        assert.doesNotMatch(component.render(100).join('\n'), /Esc (Dismiss|Hide)|Operation submitted/);
        await waitFor(()=>!component.render(100).join('\n').includes('Nothing to compact.'),6500);
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
        assert.equal(modelRequests,0);
        submit('/feedback');
        await waitFor(()=>component.render(100).join('\n').includes('Fixture completed'));
        terminal.sendInput('\x1b[200~Run the local deterministic fixture\n'+'Local fixture line\n'.repeat(50)+'\x1b[201~'); terminal.sendInput('\r');
        assert.doesNotMatch(component.render(100).join('\n'),/Fixture completed/);
        await waitFor(()=>modelRequests===1,10000);
        await waitFor(()=>component.render(100).join('\n').includes('Working'),10000);
        const transcript=renderLayoutFrame(component.layoutRoot,100,24,()=>{}).primaryScrollView;
        transcript.scrollTo(5,{disableFollow:true});
        const position=transcript.scrollTop;
        assert.equal(position,5);
        submit('/monitor');
        await waitFor(()=>component.render(100).join('\n').includes('/monitor ·'));
        refreshMonitor();
        await new Promise(resolve=>setTimeout(resolve,100));
        assert.doesNotMatch(renderLayoutFrame(component.layoutRoot,100,24,()=>{}).lines.join('\n'),/Esc to abort|Working/);
        terminal.sendInput('\x1b');
        await new Promise(resolve=>setImmediate(resolve));
        const restored=renderLayoutFrame(component.layoutRoot,100,24,()=>{}).primaryScrollView;
        assert.equal(restored,transcript);assert.equal(restored.scrollTop,position);assert.equal(restored.isFollowingEnd,false);
        assert.equal((await backend.readSession('startup',created.session.session_id)).session.is_streaming,true);
        submit('/sys-prompt');
        await waitFor(()=>component.render(100).join('\n').includes('You are ResearchAgent'));
        assert.ok(!renderLayoutFrame(component.layoutRoot,100,24,()=>{}).primaryScrollView);
        terminal.sendInput('\x1b');
        await new Promise(resolve=>setImmediate(resolve));
        assert.equal(renderLayoutFrame(component.layoutRoot,100,24,()=>{}).primaryScrollView.scrollTop,position);
        submit('/feedback');
        await waitFor(()=>component.render(100).join('\n').includes('Fixture completed'));
        terminal.sendInput('\x1b');
        await waitFor(async()=>!(await backend.readSession('startup',created.session.session_id)).session.is_streaming,10000);
        assert.doesNotMatch(component.render(100).join('\n'),/Fixture completed/);
        submit("/quit");
        await waitFor(() => quit);
      } finally {
        await component.close();
        ui.stop();
      }
      assert.equal((await backend.readSession("startup", created.session.session_id)).session.online, true);
      const second = await backend.createSession({ workspace_id: "startup", session_id: "second", model: { provider: "fixture", id: "fixture" } });
      const { startResearchAgentHost } = await import(pathToFileURL(join(packageRoot, "apps/agent/host/server.mjs")));
      const { connectHost } = await import(pathToFileURL(join(packageRoot, "apps/agent/transport/host-client.mjs")));
      const { runTerminalSessions } = await import(pathToFileURL(join(packageRoot, "apps/agent/terminal/session.mjs")));
      const { runClientTui } = await fromSource("packages/coding-agent/src/experimental/client-tui.ts");
      const { defineFacet } = await fromSource("packages/chord/src/index.ts");
      const { SlashCommands } = await fromSource("packages/coding-agent/src/experimental/services/slash-commands.ts");
      const host = await startResearchAgentHost({ socketPath: join(root, "host.sock"), workspaceRoot, stateRoot: join(root, "hs"), sessionBackend: backend, monitorPollMs: 0 });
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
              await createResearchAgentNativeClientFacet({ sourceRoot, session }),
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

    completed = true;
  } finally {
    modelServer.closeAllConnections();
    await new Promise(resolve => modelServer.close(resolve));
    try { await backend?.close(); }
    finally {
      for (const key of Object.keys(process.env)) if (!(key in savedEnvironment)) delete process.env[key];
      Object.assign(process.env, savedEnvironment);
      if (!completed) await retainPiDiagnostics(socketRoot, join(root, "pi-diagnostics"));
      if (completed) await rm(root, { recursive: true, force: true });
      await rm(socketRoot, { recursive: true, force: true });
    }
  }
});
