import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "node:http";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { TEST_ROOT, TEST_SOCKET_ROOT, managedPython, pinnedPiSource, assertInstalledRuntime } from "./test-environment.mjs";

const execute = promisify(execFile);
const packageRoot = resolve(process.env.CORAGENT_TEST_PACKAGE_ROOT || process.cwd());

for (const scenario of ["single", "branches"]) test(`real Worker continues ${scenario} research after a partial answer and completes one durable delivery`, { timeout: 60_000 }, async () => {
  await assertInstalledRuntime(packageRoot);
  const root = await mkdtemp(join(TEST_ROOT, "task-flow-"));
  const socketRoot = join(TEST_SOCKET_ROOT, "t");
  await mkdir(socketRoot);
  const saved = { ...process.env };
  let backend, server, requests = 0, fixtureError;
  const observedRequests = [];
  const tools = [];
  try {
    const agentDir = join(root, "agent"), workspaceRoot = join(root, "workspaces");
    await mkdir(agentDir); await mkdir(workspaceRoot);
    Object.assign(process.env, { PI_CODING_AGENT_DIR: agentDir, PI_AGENT_DIR: agentDir,
      CORAGENT_PYTHON: managedPython(), PYTHONDONTWRITEBYTECODE: "1" });
    await execute(managedPython(), [join(packageRoot, "apps/agent-cli/workspace_mode.py"),
      "--root", join(workspaceRoot, "task-flow"), "--workspace-id", "task-flow"]);
    server = createServer(async (req, res) => {
      try {
        let body = ""; for await (const part of req) body += part;
        const request = JSON.parse(body); observedRequests.push(request);
        const results = request.messages.filter(message => message.role === "tool").map(message => {
          assert.match(message.content, /^\s*[\[{]/, "fixture tools must return their structured success result");
          return JSON.parse(message.content);
        });
        const injectedTask = request.messages.map(message => message.content).join("\n")
          .match(/\{"task":.*,"actual_user_submission_ids":.*,"automatic_continuation_enabled":(?:true|false)\}/);
        assert.ok(injectedTask, "every request must carry the current task projection");
        const taskContext = JSON.parse(injectedTask[0]);
        const task = taskContext.task;
        const node = results.find(result => result?.node)?.node;
        const result = results.find(result => result?.result)?.result;
        const userIds = taskContext.actual_user_submission_ids;
        const latestNodes = new Map(results.filter(result => result?.node).map(result => [result.node.title, result.node]));
        const published = new Map(results.filter(result => result?.result).map(result => [result.result.conclusion, result.result]));
        const rootNode = latestNodes.get("Compare derivations"), shared = latestNodes.get("Approximation bounds");
        const branchA = latestNodes.get("Derivation A"), branchB = latestNodes.get("Derivation B");
        const snapshotText = request.messages.map(message => message.content).join("\n").match(/<research_memory_snapshot>[\s\S]*?\n(\{[^\n]+\})\n<\/research_memory_snapshot>/);
        assert.ok(snapshotText, "every request carries the current research snapshot");
        const snapshot = JSON.parse(snapshotText[1]);
        assert.equal(snapshot.schema_version, "research-snapshot/3");
        if (task?.research.entry_node_ids.length) {
          assert.deepEqual(snapshot.research.entry_node_ids, task.research.entry_node_ids);
          assert.deepEqual(snapshot.research.focus_node_ids, task.research.focus_node_ids);
          assert.ok(task.research.focus_node_ids.every(id => snapshot.research.nodes.some(node => node.id === id)));
        }
        if (scenario === "branches" && task?.research.entry_node_ids.length) {
          assert.ok(snapshot.research.relations.some(edge => edge.source === branchA.id && edge.target === rootNode.id && edge.kind === "part_of"));
          assert.ok(snapshot.research.nodes.some(node => node.id === rootNode.id && node.plan));
        }
        const bind = (entry, focus) => ({ name: "task_update", arguments: { expected_revision: task?.revision,
          action: "set_research", research: { entry_node_ids: entry, focus_node_ids: focus } } });
        const singleSteps = [
          { name: "task_begin", arguments: { title: "Fixture research", objective: "Record a reproducible fixture finding without external delivery.",
            source_submission_ids: userIds, criteria: [{ id: "finding", description: "Publish the fixture finding and report it." }] } },
          { name: "research_create", arguments: { goal: "Verify continued analysis", plan: "Record a local deterministic observation." } },
          bind([node?.id], [node?.id]),
          "Initial analysis is ready; the finding still needs to be recorded.",
          { name: "task_read", arguments: {} },
          { name: "research_result", arguments: { node_id: node?.id, conclusion: "The local fixture completed its analysis.", limitations: "Deterministic fixture only." } },
          { name: "task_update", arguments: { expected_revision: task?.revision, action: "propose_completion",
            completion: [{ criterion_id: "finding", evidence_refs: [result?.id] }] } },
          "The fixture finding is recorded. Research is complete.",
        ];
        const negative = published.get("Derivation A violates the stated boundary condition.");
        const provisional = published.get("Derivation B satisfies the boundary condition at leading order.");
        const corrected = published.get("Derivation B remains valid with the next-order correction.");
        const bounds = published.get("The approximation has a bounded second-order remainder.");
        const synthesis = published.get("The comparison supports derivation B within the approximation bounds.");
        const branchSteps = [
          { name: "task_begin", arguments: { title: "Compare derivations", objective: "Compare independent derivations and retain their limitations without external delivery.",
            source_submission_ids: userIds, criteria: [{ id: "comparison", description: "Retain both findings, approximation bounds and the comparison." }] } },
          { name: "research_create", arguments: { title: "Compare derivations", goal: "Which derivation satisfies the boundary condition?", plan: "Compare independent candidates against shared approximation bounds." } },
          { name: "research_create", arguments: { title: "Approximation bounds", goal: "What is the approximation error?", plan: "Bound the neglected terms." } },
          { name: "research_create", arguments: { title: "Derivation A", goal: "Does derivation A satisfy the boundary condition?", plan: "Substitute at the boundary.",
            relations: [{ kind: "part_of", target: rootNode?.id }, { kind: "requires", target: shared?.id }] } },
          { name: "research_create", arguments: { title: "Derivation B", goal: "Does derivation B satisfy the boundary condition?", plan: "Evaluate the boundary and next-order correction.",
            relations: [{ kind: "part_of", target: rootNode?.id }, { kind: "requires", target: shared?.id }, { kind: "alternative_to", target: branchA?.id }] } },
          bind([rootNode?.id, shared?.id], [branchA?.id, branchB?.id]),
          { name: "research_result", arguments: { node_id: branchA?.id, conclusion: "Derivation A violates the stated boundary condition.", as_assessment: true } },
          { name: "research_update", arguments: { node_id: branchA?.id, note: "End this route after the boundary counterexample; derivation B remains to be checked.", status: "closed" } },
          "Derivation A fails the boundary condition. Derivation B and the comparison remain unfinished.",
          { name: "task_read", arguments: {} },
          { name: "research_result", arguments: { node_id: branchB?.id, conclusion: "Derivation B satisfies the boundary condition at leading order.", as_assessment: true } },
          { name: "research_result", arguments: { node_id: shared?.id, conclusion: "The approximation has a bounded second-order remainder." } },
          bind([rootNode?.id, shared?.id], [branchB?.id, rootNode?.id]),
          { name: "research_result", arguments: { node_id: branchB?.id, conclusion: "Derivation B remains valid with the next-order correction.", supersedes: provisional?.id, inputs: [bounds?.id], as_assessment: true } },
          { name: "research_result", arguments: { node_id: rootNode?.id, conclusion: "The comparison supports derivation B within the approximation bounds.",
            inputs: [negative?.id, corrected?.id, bounds?.id], limitations: "Synthetic deterministic derivations; this tests research orchestration, not a scientific result." } },
          { name: "task_update", arguments: { expected_revision: task?.revision, action: "propose_completion",
            completion: [{ criterion_id: "comparison", evidence_refs: [synthesis?.id] }] } },
          "Both derivations and the approximation bounds are retained. The comparison is complete.",
        ];
        const steps = scenario === "single" ? singleSteps : branchSteps;
        const step = steps[requests++];
        assert.ok(step, "completed research must not trigger another model request");
        if (typeof step !== "string") tools.push(step.name);
        const delta = typeof step === "string" ? { role: "assistant", content: step } : {
          role: "assistant", tool_calls: [{ index: 0, id: `task_call_${requests}`, type: "function",
            function: { name: step.name, arguments: JSON.stringify(step.arguments) } }],
        };
        res.writeHead(200, { "content-type": "text/event-stream" });
        for (const [value, finish_reason] of [[delta, null], [{}, typeof step === "string" ? "stop" : "tool_calls"]]) {
          res.write(`data: ${JSON.stringify({ id: `reply_${requests}`, object: "chat.completion.chunk", created: 1,
            model: "fixture", choices: [{ index: 0, delta: value, finish_reason }] })}\n\n`);
        }
        res.end("data: [DONE]\n\n");
      } catch (error) {
        fixtureError = error;
        res.writeHead(500); res.end("deterministic fixture failed");
      }
    });
    await new Promise(done => server.listen(0, "127.0.0.1", done));
    await writeFile(join(agentDir, "models.json"), JSON.stringify({ providers: { fixture: {
      baseUrl: `http://127.0.0.1:${server.address().port}/v1`, apiKey: "fixture-only", api: "openai-completions",
      models: [{ id: "fixture", name: "Fixture", reasoning: false, input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 200000, maxTokens: 4096 }],
    } } }));
    const { createCoRAgentHarnessBackend } = await import(pathToFileURL(join(packageRoot, "apps/agent/pi/backend.mjs")));
    const options = { sourceRoot: pinnedPiSource(), packageRoot, workspaceRoot,
      serverDirectory: socketRoot, sessionDir: join(root, "sessions"), stateRoot: join(root, "state"),
      model: { provider: "fixture", id: "fixture" } };
    await assert.doesNotReject(async () => { backend = await createCoRAgentHarnessBackend(options); });
    let created;
    await assert.doesNotReject(async () => { created = await backend.createSession({ workspace_id: "task-flow", model: { provider: "fixture", id: "fixture" } }); });
    const scope = { workspace_id: "task-flow", session_id: created.session.session_id };
    await backend.sendInput({ ...scope, client_message_id: "start-fixture-task", request_id: "start-fixture-task",
      text: "Perform the local fixture research and report the completed finding. Do not send anything externally.", mode: "auto" });
    let overview;
    for (let attempt = 0; attempt < 200; attempt++) {
      assert.ifError(fixtureError);
      await assert.doesNotReject(async () => { overview = await backend.monitor("monitor/overview", scope); });
      if (overview.task?.state === "completed") break;
      await new Promise(done => setTimeout(done, 100));
    }
    assert.equal(overview.task?.state, "completed");
    assert.equal(requests, scenario === "single" ? 8 : 17);
    if (scenario === "single") assert.deepEqual(tools, ["task_begin", "research_create", "task_update", "task_read", "research_result", "task_update"]);
    else assert.equal(tools.filter(name => name === "research_create").length, 4);
    assert.equal(overview.jobs.counts.total, 0, "continued analysis must not require a compute event");
    const runs = await backend.monitor("monitor/runs", { ...scope, user_task_id: overview.task.user_task_id });
    assert.equal(runs.items.length, 2);
    assert.deepEqual(new Set(runs.items.map(run => run.producer)), new Set(["user", "task_controller"]));
    for (const run of runs.items) {
      const detail = await backend.monitor("monitor/run/read", { ...scope, run_id: run.run_id });
      assert.ok(detail.items.some(item => item.kind === "pi.generation"));
      assert.ok(detail.items.some(item => item.kind === "pi.tool"));
      assert.ok(detail.items.some(item => item.kind === "pi.tool" && tools.includes(item.tool_name)));
      assert.ok(detail.items.every(item => item.error === null), "successful research has no execution errors");
    }
    const count = requests;
    const research = await backend.monitor("monitor/task/read", { ...scope, user_task_id: overview.task.user_task_id });
    assert.deepEqual(research.research.research.entry_node_ids, overview.task.research.entry_node_ids);
    if (scenario === "branches") {
      assert.equal(research.research.research.nodes.find(node => node.title === "Derivation A").status, "closed");
      assert.equal(research.research.research.nodes.find(node => node.title === "Approximation bounds").status, "open", "completing a task leaves shared research open");
    }
    await backend.close(); backend = await createCoRAgentHarnessBackend(options);
    const restored = await backend.monitor("monitor/overview", scope);
    assert.equal(restored.task.state, "completed");
    assert.equal(restored.task.user_task_id, overview.task.user_task_id);
    assert.deepEqual(restored.task.research, overview.task.research, "restart retains the same research identities");
    await new Promise(done => setTimeout(done, 100));
    assert.equal(requests, count, "restart and read-only Monitor queries cannot repeat delivery");
    const objective = scenario === "single" ? "Record a reproducible fixture finding" : "Compare independent derivations";
    assert.ok(observedRequests.slice(3).every(request => JSON.stringify(request.messages).includes(objective)));
  } finally {
    try { await backend?.close(); }
    finally {
      if (server) { server.closeAllConnections(); await new Promise(done => server.close(done)); }
      for (const key of Object.keys(process.env)) if (!(key in saved)) delete process.env[key];
      Object.assign(process.env, saved);
      await rm(socketRoot, { recursive: true, force: true });
      await rm(root, { recursive: true, force: true });
    }
  }
});
