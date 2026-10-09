import { createHash } from "node:crypto";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, writeFile, rm, readdir, symlink } from "node:fs/promises";
import { createServer } from "node:http";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import test from "node:test";
import { TEST_ROOT, TEST_SOCKET_ROOT, retainPiDiagnostics, managedPython, pinnedPiSource, assertInstalledRuntime } from "./test-environment.mjs";

const execute = promisify(execFile);
const sourceRoot = pinnedPiSource();
const packageRoot = resolve(process.env.RESEARCH_AGENT_TEST_PACKAGE_ROOT || process.cwd());
const quote = value => `'${value.replaceAll("'", "'\\''")}'`;

test("Worker reads installed Skills, runs a Job, publishes a Node result after a Monitor next_run and restart", {
  timeout: 60_000,
}, async () => {
  await assertInstalledRuntime(packageRoot);
  await mkdir(TEST_ROOT, { recursive: true });
  const root = await mkdtemp(join(TEST_ROOT, "flow-"));
  const socketRoot = join(TEST_SOCKET_ROOT, "f");
  await mkdir(socketRoot);
  const saved = { ...process.env };
  let completed = false;
  let backend, server, monitorRequest;
  let nodeId, outputArtifact;
  const requests = [];
  let stage = "prepare";
  try {
    process.env.RESEARCH_AGENT_DEBUG = "1";
    process.env.RESEARCH_AGENT_PI_DIAGNOSTIC_FILE = join(root, "pi-child.log");
    const agentDir = join(root, "agent");
    const workspaceRoot = join(root, "workspaces");
    const workspace = join(workspaceRoot, "flow");
    const python = managedPython();
    await mkdir(agentDir); await mkdir(workspaceRoot);
    const config = join(root, "email.toml");
    await writeFile(config, '[notifications.email]\nenabled=true\nprovider="smtp"\npreset="custom"\nhost="127.0.0.1"\nport=9\nsecurity="ssl"\nusername="sender@example.test"\nrecipient="reader@example.test"\npassword_env="FIXTURE_MAIL_PASSWORD"\n', { mode: 0o600 });
    Object.assign(process.env, { PI_CODING_AGENT_DIR: agentDir, PI_AGENT_DIR: agentDir, RESEARCH_AGENT_PYTHON: python,
      PYTHONDONTWRITEBYTECODE: "1", RESEARCH_AGENT_NOTIFICATION_CONFIG: config });
    const jobConfig = join(root, "job.toml");
    await writeFile(jobConfig, 'default_environment="local"\n[environments.local]\nkind="local"\nsupervisor="process"\n');
    process.env.RESEARCH_AGENT_JOB_CONFIG = jobConfig;
    await execute(python, [join(packageRoot, "apps/agent-cli/workspace_mode.py"), "--root", workspace, "--workspace-id", "flow"]);
    const fixtureJobId = "job_" + createHash("sha256").update("fixture_run").digest("hex").slice(0, 48);
    const preparedPath = join(workspace, "prepared.json");
    const prepared = JSON.stringify({request_id:"fixture_run", work_id:"fixture_work", metadata:{skill:"fixture", configuration_sha256:"fixture"},
      command:[python,"-c","from pathlib import Path;Path('result.txt').write_text('fixture evidence')"],outputs:[{path:"result.txt",required:true,min_bytes:1}]});
    await writeFile(preparedPath, prepared);
    await writeFile(join(workspace, "large-history.txt"), "Historical artifact metadata\n".repeat(12000) + "TAIL_MUST_BE_TRUNCATED\n");
    const call = (name, args) => ({ name, arguments: args });
    const steps = [
      ...["skills/research-memory/SKILL.md", "skills/research-workflow/SKILL.md",
        "domains/chemical/skills/method-selection/SKILL.md", "domains/chemical/skills/cf22d/SKILL.md",
        "domains/chemical/skills/cf22d/references/cf22d_workflow.md", "domains/chemical/skills/_shared/science.py",
        "skills/email/scripts/email_cli.py"].map(path => call("read", { path: join(packageRoot, path) })),
      call("read", { path: join(packageRoot, "skills/email/SKILL.md") }),
      call("bash", { command: [python, join(packageRoot, "skills/email/scripts/email_cli.py"), "check", "--root", workspace, "--output", join(workspace, "reports/email-check.json")].map(quote).join(" ") }),
      call("read", { path: join(packageRoot, "domains/chemical/skills/chemical-input/references/reaction_mapping.md") }),
      call("write", {path: join(workspace, "工具 verification.txt"), content: "initial marker\n"}),
      call("edit", {path: join(workspace, "工具 verification.txt"), edits: [{oldText: "initial marker", newText: "verified native tools"}]}),
      call("grep", {pattern: "verified native tools", path: workspace, literal: true}),
      call("find", {pattern: "*verification.txt", path: workspace}),
      call("ls", {path: workspace}),
      call("research_read", {}),
      call("research_create", {goal: "Check the fixture output", plan: "Run the fixture and inspect its actual outputs."}),
      () => call("research_update", {node_id:nodeId, note: "Prepare the first attempt."}),
      call("read", { path: join(workspace, "large-history.txt") }),
      () => call("job_start", {node_id:nodeId,request_file:preparedPath,request_sha256:createHash("sha256").update(prepared).digest("hex")}),
      "Waiting for the fixture Job.",
      call("job_status", {job_id:fixtureJobId}),
      call("job_collect", {job_id:fixtureJobId}),
      () => call("research_result", {node_id:nodeId, conclusion:"The fixture produced its required output. User delivery remains unrequested.", evidence_refs:[fixtureJobId], files:[{name:"result.txt",artifact_ref:outputArtifact}], as_assessment:true}),
      "Fixture evidence collected.",
    ];
    server = createServer(async (req, res) => {
      let body = ""; for await (const part of req) body += part;
      const request = JSON.parse(body); requests.push(request);
      const createdResult = request.messages.filter(message => message.role === "tool").map(message => {
        try { return JSON.parse(message.content); } catch { return null; }
      }).find(result => result?.node?.goal === "Check the fixture output");
      if (createdResult) nodeId = createdResult.node.id;
      const collected = request.messages.filter(message => message.role === "tool").map(message => {
        try { return JSON.parse(message.content); } catch { return null; }
      }).find(result => result?.artifacts?.some(artifact => artifact.provenance?.source_path?.endsWith("result.txt")));
      if (collected) outputArtifact = collected.artifacts.find(artifact => artifact.provenance?.source_path?.endsWith("result.txt")).artifact_id;
      const pendingStep = steps[requests.length - 1] || "Unexpected continuation.";
      const step = typeof pendingStep === "function" ? pendingStep() : pendingStep;
      if (step?.name === "job_status") {
        const statusFile = join(workspace, `runs/jobs/${fixtureJobId}/status.json`);
        for (let i = 0; i < 100 && !existsSync(statusFile); i++) await new Promise(done => setTimeout(done, 20));
        assert.ok(existsSync(statusFile), "fixture process must finish before collection");
      }
      const delta = typeof step === "string" ? { role: "assistant", content: step } : {
        role: "assistant", tool_calls: [{ index: 0, id: `call_${requests.length}`, type: "function",
          function: { name: step.name, arguments: JSON.stringify(step.arguments) } }],
      };
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      for (const [chunk, finish] of [[delta, null], [{}, typeof step === "string" ? "stop" : "tool_calls"]]) {
        res.write(`data: ${JSON.stringify({ id: `reply_${requests.length}`, object: "chat.completion.chunk", created: 1,
          model: "fixture", choices: [{ index: 0, delta: chunk, finish_reason: finish }] })}\n\n`);
      }
      res.end("data: [DONE]\n\n");
    });
    await new Promise(done => server.listen(0, "127.0.0.1", done));
    await writeFile(join(agentDir, "models.json"), JSON.stringify({ providers: { fixture: {
      baseUrl: `http://127.0.0.1:${server.address().port}/v1`, apiKey: "fixture-only", api: "openai-completions",
      models: [{ id: "fixture", name: "Fixture", reasoning: false, input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 400000, maxTokens: 4096 }],
    } } }));
    const { createResearchAgentHarnessBackend } = await import(pathToFileURL(join(packageRoot, "apps/agent/pi/backend.mjs")));
    const packageAlias = join(root, "current-package");
    await symlink(packageRoot, packageAlias, "dir");
    const backendOptions = { sourceRoot, packageRoot: packageAlias, workspaceRoot,
      serverDirectory: socketRoot, sessionDir: join(root, "sessions"), stateRoot: join(root, "state"),
      model: { provider: "fixture", id: "fixture" } };
    stage = "start-backend";
    backend = await createResearchAgentHarnessBackend(backendOptions);
    stage = "create-session";
    const created = await backend.createSession({ workspace_id: "flow", model: { provider: "fixture", id: "fixture" } });
    const session_id = created.session.session_id;
    stage = "send-input";
    await backend.sendInput({ workspace_id: "flow", session_id, request_id: "fixture_request", client_message_id: "fixture_message",
      text: "Exercise the local fixture without sending mail.", mode: "auto" });
    const {deliverMonitorEvent} = await import(pathToFileURL(join(packageRoot,"apps/agent/host/monitor/worker.mjs")));
    const runJson = async (command, root, extra=[]) => JSON.parse((await execute(python,[join(packageRoot,"apps/agent-cli/monitor.py"),command,"--root",root,...extra])).stdout);
    let read, restarted=false, monitorDelivered=false;
    stage = "wait-flow";
    for (let i = 0; i < 250; i++) {
      read = await backend.readSession("flow", session_id);
      if (!read.session.is_streaming && existsSync(join(workspace, `operations/jobs/${fixtureJobId}.json`)) && !monitorDelivered) {
        if (!restarted) { await backend.close(); backend = await createResearchAgentHarnessBackend(backendOptions); restarted=true; }
        await runJson("tick",workspace);
        const pending=await runJson("pending",workspace);
        if (pending.deliveries.length) {
          const delivery=pending.deliveries[0];
          const errors=await deliverMonitorEvent({workspace,delivery,runJson,sendWake:params=>{monitorRequest=params;return backend.sendInput(params);}});
          assert.deepEqual(errors,[]);
          assert.deepEqual(await deliverMonitorEvent({workspace,delivery,runJson,sendWake:params=>backend.sendInput(params)}),[]);
          monitorDelivered=(await runJson("pending",workspace)).deliveries.length===0;
        }
      }
      if (requests.length >= steps.length && !read.session.is_streaming) break;
      await new Promise(done => setTimeout(done, 100));
    }
    assert.equal(read.session.is_streaming, false);
    assert.ok(restarted);
    assert.ok(monitorDelivered, JSON.stringify({ requests: requests.length, failure: read.snapshot.runtime_error,
      lastResult: read.snapshot.last_result }));
    assert.equal(requests.length, steps.length, JSON.stringify(read.snapshot.failure));
    const toolResults = requests.at(-1).messages.filter(message => message.role === "tool");
    assert.equal(toolResults.length, steps.filter(step => typeof step !== "string").length);
    for (const result of toolResults) assert.doesNotMatch(String(result.content), /Tool call blocked|^research_decision_required|^operation references unknown/);
    assert.equal(await readFile(join(workspace, "工具 verification.txt"), "utf8"), "verified native tools\n");
    const nativeNames = ["read", "write", "edit", "bash", "grep", "find", "ls"];
    for (const name of nativeNames) {
      assert.ok(requests[0].tools.some(tool => tool.function.name === name));
      assert.ok(steps.some(step => step?.name === name));
    }
    for (const name of ["grep", "find", "ls"]) {
      const index = steps.findIndex(step => step?.name === name);
      const result = requests[index + 1].messages.filter(message => message.role === "tool").at(-1);
      assert.match(String(result.content), /verification\.txt/, `${name} output must reach the model`);
    }
    const journal = JSON.parse(await readFile(join(workspace, "research/journal.json")));
    const originals = journal.records.filter(r => r.origin === "user");
    assert.equal(originals.length, 1);
    const source = JSON.parse(await readFile(join(workspace, "research/records", originals[0].ref + ".json")));
    assert.equal(source.content, "Exercise the local fixture without sending mail.");
    assert.equal(source.data.session_id, session_id);
    const execution = JSON.parse(await readFile(join(workspace, `operations/executions/${fixtureJobId}.json`)));
    assert.equal(execution.state, "succeeded");
    assert.equal(execution.metadata.work_id, "fixture_work");
    assert.equal(execution.node_id, nodeId);
    assert.equal(monitorRequest.mode, "next_run");
    const node = JSON.parse(await readFile(join(workspace, "research/nodes", nodeId, "node.json")));
    assert.ok(node.assessment_ref);
    const result = JSON.parse(await readFile(join(workspace, "research/nodes", nodeId, "results", node.assessment_ref + ".json")));
    assert.match(result.conclusion, /fixture produced its required output/);
    const intent = JSON.parse(await readFile(join(workspace, `operations/jobs/${fixtureJobId}.json`)));
    assert.equal(intent.prepared_ref, "p1", "Worker submits the file through Runtime's atomic preparation/dispatch boundary");
    const preparedRecord = JSON.parse(await readFile(join(workspace, "operations/references/records/p1.json")));
    assert.equal(preparedRecord.payload.source_sha256, createHash("sha256").update(prepared).digest("hex"));
    assert.ok(journal.records.some(r => r.kind === "material"));
    for (const request of requests) {
      const snapshots = request.messages.filter(m => JSON.stringify(m.content).includes("<research_memory_snapshot>"));
      assert.equal(snapshots.length, 1, "each real provider request has exactly one current projection");
      assert.ok(["system", "developer"].includes(snapshots[0].role), "runtime facts must not impersonate user input on the provider wire");
      assert.match(JSON.stringify(snapshots[0].content), /not a user message or a new turn/);
    }
    const snapshotOf = request => JSON.stringify(request.messages.find(m => JSON.stringify(m.content).includes("<research_memory_snapshot>")));
    const lastSnapshot = snapshotOf(requests.at(-1));
    const truncated = toolResults.find(result => String(result.content).includes("Historical artifact metadata"));
    assert.ok(truncated, "actual Native read result must reach the provider");
    assert.match(String(truncated.content), /Showing lines|truncated/);
    assert.doesNotMatch(String(truncated.content), /TAIL_MUST_BE_TRUNCATED/);
    const afterTruncation = requests[steps.findIndex(step => step?.name === "read" && step.arguments.path.endsWith("large-history.txt")) + 1];
    assert.match(snapshotOf(afterTruncation), /Exercise the local fixture/);
    assert.match(lastSnapshot, /Exercise the local fixture/);
    assert.match(lastSnapshot, /succeeded/);
    assert.equal(read.snapshot.messages.some(m => JSON.stringify(m).includes("<research_memory_snapshot>")), false, "projection must not enter durable transcript");
    assert.ok((await readdir(join(workspace, "operations/contexts"))).length > 0);
    assert.ok(journal.records.filter(r => r.origin === "agent").length >= 3);
    const email = JSON.parse(await readFile(join(workspace, "reports/email-check.json")));
    assert.equal(email.recipient, "reader@example.test");
    assert.equal(email.enabled, true);
    assert.equal(existsSync(join(workspace, "reports/email/deliveries")), false);
    assert.equal(requests.at(-1).messages.some(message => JSON.stringify(message.content).includes("Research turn ended")), false);
    assert.equal(existsSync(join(workspace, "lifecycle")), false);
    const monitorRecord = await backend.inputStatus(monitorRequest);
    assert.ok(monitorRecord.operation_id);
    // Forget all process memory and recover by Pi's durable business ID.
    const requestCount = requests.length;
    read = await backend.readSession("flow", session_id);
    const activityBeforeRestart = (await backend.listSessions("flow"))[0].updated_at;
    assert.equal(Date.parse(activityBeforeRestart), Math.max(...read.snapshot.messages.map(message => message.timestamp)));
    await backend.close();
    backend = await createResearchAgentHarnessBackend(backendOptions);
    assert.equal((await backend.listSessions("flow"))[0].updated_at, activityBeforeRestart);
    const recovered = await backend.sendInput(monitorRequest);
    assert.equal(recovered.accepted, true);
    assert.equal(recovered.operation_id, monitorRecord.operation_id);
    await new Promise(done => setTimeout(done, 100));
    assert.equal(requests.length, requestCount);

    completed = true;
  } catch (error) {
    console.error("Fixture stage:", stage, "requests:", requests.length);
    for (const file of await readdir(root, { recursive: true })) {
      if (file.endsWith(".log")) console.error(file, await readFile(join(root, file), "utf8"));
    }
    throw error;
  } finally {
    try { await backend?.close(); }
    finally {
      if (server) { server.closeAllConnections(); await new Promise(done => server.close(done)); }
      for (const key of Object.keys(process.env)) if (!(key in saved)) delete process.env[key];
      Object.assign(process.env, saved);
      if (!completed) await retainPiDiagnostics(socketRoot, join(root, "pi-diagnostics"));
      if (completed) await rm(root, { recursive: true, force: true });
      await rm(socketRoot, { recursive: true, force: true });
    }
  }
});
