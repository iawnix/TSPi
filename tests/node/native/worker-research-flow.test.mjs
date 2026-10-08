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
import { TEST_ROOT, managedPython, pinnedPiSource } from "./test-environment.mjs";

const execute = promisify(execFile);
const sourceRoot = pinnedPiSource();
const packageRoot = resolve(process.env.TSPI_TEST_PACKAGE_ROOT || process.cwd());
const quote = value => `'${value.replaceAll("'", "'\\''")}'`;

test("Worker reads installed Skills, runs a Job, checks configured email and ends a user wait", {
  skip: !sourceRoot || !existsSync(join(sourceRoot, "packages/coding-agent/src/experimental/source-resolver.ts")),
  timeout: 60_000,
}, async () => {
  await mkdir(TEST_ROOT, { recursive: true });
  const root = await mkdtemp(join(TEST_ROOT, "flow-"));
  const saved = { ...process.env };
  let backend, server, monitorRequest;
  const requests = [];
  try {
    const agentDir = join(root, "agent");
    const workspaceRoot = join(root, "workspaces");
    const workspace = join(workspaceRoot, "flow");
    const python = managedPython();
    await mkdir(agentDir); await mkdir(workspaceRoot);
    const config = join(root, "email.toml");
    await writeFile(config, '[notifications.email]\nenabled=true\nprovider="smtp"\npreset="custom"\nhost="127.0.0.1"\nport=9\nsecurity="ssl"\nusername="sender@example.test"\nrecipient="reader@example.test"\npassword_env="FIXTURE_MAIL_PASSWORD"\n', { mode: 0o600 });
    Object.assign(process.env, { PI_CODING_AGENT_DIR: agentDir, TSPI_PYTHON: python,
      PYTHONDONTWRITEBYTECODE: "1", TS_NOTIFICATION_CONFIG: config });
    delete process.env.TS_JOB_CONFIG;
    await execute(python, [join(packageRoot, "apps/agent-cli/workspace_mode.py"), "--root", workspace, "--workspace-id", "flow"]);
    const fixtureJobId = "job_" + createHash("sha256").update("fixture_run").digest("hex").slice(0, 48);
    const preparedPath = join(workspace, "prepared.json");
    const prepared = JSON.stringify({request_id:"fixture_run", work_id:"fixture_work", metadata:{skill:"fixture", configuration_sha256:"fixture"},
      command:[python,"-c","from pathlib import Path;Path('result.txt').write_text('fixture evidence')"],outputs:[{path:"result.txt",required:true,min_bytes:1}]});
    await writeFile(preparedPath, prepared);
    await writeFile(join(workspace, "large-history.txt"), "Historical artifact metadata\n".repeat(12000) + "TAIL_MUST_BE_TRUNCATED\n");
    const call = (name, args) => ({ name, arguments: args });
    const steps = [
      ...["extensions/core/skills/research-state/SKILL.md", "extensions/core/skills/orchestration/SKILL.md",
        "extensions/chemical/skills/method-selection/SKILL.md", "extensions/chemical/skills/cf22d/SKILL.md",
        "extensions/chemical/skills/cf22d/references/cf22d_workflow.md", "extensions/chemical/skills/_shared/science.py",
        "extensions/email/scripts/email_cli.py"].map(path => call("read", { path: join(packageRoot, path) })),
      call("read", { path: "skill:email" }),
      call("bash", { command: [python, join(packageRoot, "extensions/email/scripts/email_cli.py"), "check", "--root", workspace, "--output", join(workspace, "reports/email-check.json")].map(quote).join(" ") }),
      call("research_read", { mode: "context" }),
      call("research_change", { rationale: "Initialize a bounded fixture", operations: [
        { type: "create_claim", id: "claim_flow", statement: "The fixture can produce a file" },
        { type: "create_node", id: "node_flow", title: "Fixture", objective: "Produce evidence", completion_exemption: "Fixture exercises transport and durable evidence only", claim_ids: ["claim_flow"] },
        { type: "set_focus", claim_ids: ["claim_flow"], node_ids: ["node_flow"] },
      ] }),
      call("research_strategy", { strategy_operation: "plan", plan: {
        id: "strategy_flow", claim_id: "claim_flow", node_id: "node_flow", objective: "Produce a file",
        rationale: "Exercise the real execution chain", status: "active",
      } }),
      call("read", { path: join(workspace, "large-history.txt") }),
      call("research_checkpoint", {checkpoint:{id:"checkpoint_continue",disposition:"continue_required",reason:"Continue authorized fixture",node_ids:["node_flow"],claim_ids:["claim_flow"]}}),
      "Preparation complete; continue the authorized plan.",
      call("job_start", {node_id:"node_flow",request_file:preparedPath,request_sha256:createHash("sha256").update(prepared).digest("hex")}),
      call("research_checkpoint", {checkpoint:{id:"checkpoint_job_wait",disposition:"waiting_external",reason:"Wait for fixture process",node_ids:["node_flow"],unresolved_refs:["attempt_"+createHash("sha256").update(fixtureJobId).digest("hex").slice(0,32)]}}),
      "Waiting for the fixture Job.",
      call("job_status", { job_id: fixtureJobId }),
      call("job_collect", { job_id: fixtureJobId }),
      call("research_interpretation", { interpretation: {
        kind: "result", id: "interpretation_flow", claim_id: "claim_flow",
        attempt_ref: "attempt_" + createHash("sha256").update(fixtureJobId).digest("hex").slice(0, 32),
        summary: "The fixture produced and collected its required evidence file.", outcome: "supports",
      } }),
      // First end without a disposition: exactly one repair is expected.
      "Fixture evidence collected.",
      call("research_read", { mode: "context" }),
      call("research_change", { rationale: "The fixture needs an actual user choice", operations: [
        { type: "set_node_state", node_id: "node_flow", state: "blocked", summary: "Choose the next fixture experiment" },
      ] }),
      call("research_checkpoint", { checkpoint: { id: "checkpoint_wait", disposition: "user_input_required",
        claim_ids: ["claim_flow"], node_ids: ["node_flow"], reason: "A genuine fixture user choice is needed" } }),
      "Waiting for the fixture user's choice.",
    ];
    server = createServer(async (req, res) => {
      let body = ""; for await (const part of req) body += part;
      const request = JSON.parse(body); requests.push(request);
      const step = steps[requests.length - 1] || "Unexpected continuation.";
      if (step?.name === "research_interpretation") {
        const ctx = JSON.parse(await readFile(join(workspace, "research_map/context.json"), "utf8"));
        const attempt = ctx.attempts[0];
        step.arguments.interpretation.result_receipt_ref = attempt.metadata.latest_result_receipt_ref;
        step.arguments.interpretation.direct_evidence_refs = attempt.output_artifact_ids;
      }
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
    const { createTspiHarnessBackend } = await import(pathToFileURL(join(packageRoot, "apps/app-server/tspi-harness-backend.mjs")));
    const packageAlias = join(root, "current-package");
    await symlink(packageRoot, packageAlias, "dir");
    const backendOptions = { sourceRoot, packageRoot: packageAlias, workspaceRoot,
      serverDirectory: join(root, "pi"), sessionDir: join(root, "sessions"), stateRoot: join(root, "state"),
      provider: "fixture", model: "fixture" };
    backend = await createTspiHarnessBackend(backendOptions);
    const created = await backend.createSession({ workspace_id: "flow", provider: "fixture", model: "fixture" });
    const session_id = created.session.session_id;
    await assert.rejects(backend.sendInput({ workspace_id: "flow", session_id, request_id: "reserved_input",
      client_message_id: "job-wake-batch:user", source: "phone", text: "A real user request", mode: "follow_up" }),
    error => error.code === "input_id_reserved");
    await backend.sendInput({ workspace_id: "flow", session_id, request_id: "fixture_request", client_message_id: "fixture_message",
      text: "Exercise the local fixture without sending mail.", mode: "auto" });
    const {deliverMonitorEvent, recordMonitorTurn} = await import(pathToFileURL(join(packageRoot,"apps/app-server/pi-monitor-worker.mjs")));
    const runJson = async (command, root, extra=[]) => JSON.parse((await execute(python,[join(packageRoot,"apps/agent-cli/monitor.py"),command,"--root",root,...extra])).stdout);
    let read, restarted=false, monitorDelivered=false;
    for (let i = 0; i < 250; i++) {
      read = await backend.readSession("flow", session_id);
      if (!read.session.is_streaming && existsSync(join(workspace,"lifecycle/liveness.json"))) {
        const live=JSON.parse(await readFile(join(workspace,"lifecycle/liveness.json")));
        if (live.checkpoint_id === "checkpoint_continue" && !restarted) {
          await backend.close();
          backend = await createTspiHarnessBackend(backendOptions);
          restarted=true;
        }
        if (live.checkpoint_id === "checkpoint_job_wait" && !monitorDelivered) {
          await runJson("tick",workspace);
          const pending=await runJson("pending",workspace);
          if (pending.deliveries.length) {
            const delivery=pending.deliveries[0];
            const errors=await deliverMonitorEvent({workspace,delivery,runJson,recordTurn:recordMonitorTurn,sendWake:params=>{monitorRequest=params;return backend.sendInput(params);}});
            assert.deepEqual(errors,[]);
            // Replaying the same outbox cannot enqueue a second turn.
            assert.deepEqual(await deliverMonitorEvent({workspace,delivery,runJson,recordTurn:recordMonitorTurn,sendWake:params=>{monitorRequest=params;return backend.sendInput(params);}}),[]);
            monitorDelivered=(await runJson("pending",workspace)).deliveries.length === 0;
          }
        }
      }
      if (requests.length >= steps.length && !read.session.is_streaming) break;
      await new Promise(done => setTimeout(done, 100));
    }
    assert.equal(read.session.is_streaming, false);
    assert.ok(restarted);
    assert.ok(monitorDelivered, JSON.stringify({ requests: requests.length, failure: read.snapshot.failure,
      messages: requests.at(-1)?.messages.slice(-4) }));
    assert.equal(requests.length, steps.length, JSON.stringify(read.snapshot.failure));
    const toolResults = requests.at(-1).messages.filter(message => message.role === "tool");
    assert.equal(toolResults.length, steps.filter(step => typeof step !== "string").length);
    for (const result of toolResults) assert.doesNotMatch(String(result.content), /Tool call blocked|^research_decision_required|^operation references unknown/);
    const context = JSON.parse(await readFile(join(workspace, "research_map/context.json")));
    assert.equal(context.requirement_sources.length, 1, "only the original user request is a source, including after restart and Monitor wake");
    const source = JSON.parse(await readFile(join(workspace, "operations/user-inputs", context.requirement_sources[0].source_ref + ".json")));
    assert.equal(source.text, "Exercise the local fixture without sending mail.");
    assert.equal(source.session_id, session_id);
    assert.equal(context.attempts.length, 1);
    assert.equal(context.attempts[0].state, "succeeded");
    assert.equal(context.attempts[0].metadata.job_metadata.work_id, "fixture_work");
    assert.equal(context.attempts[0].metadata.job_metadata.configuration_sha256, "fixture");
    assert.ok(context.artifacts.length > 0);
    for (const request of requests) {
      const snapshots = request.messages.filter(m => JSON.stringify(m.content).includes("<research_state_snapshot>"));
      assert.equal(snapshots.length, 1, "each real provider request has exactly one current projection");
      assert.ok(["system", "developer"].includes(snapshots[0].role), "runtime facts must not impersonate user input on the provider wire");
      assert.match(JSON.stringify(snapshots[0].content), /not a user message or a new turn/);
    }
    const snapshotOf = request => JSON.stringify(request.messages.find(m => JSON.stringify(m.content).includes("<research_state_snapshot>")));
    const lastSnapshot = snapshotOf(requests.at(-1));
    const truncated = toolResults.find(result => String(result.content).includes("Historical artifact metadata"));
    assert.ok(truncated, "actual Native read result must reach the provider");
    assert.match(String(truncated.content), /Showing lines|truncated/);
    assert.doesNotMatch(String(truncated.content), /TAIL_MUST_BE_TRUNCATED/);
    const afterTruncation = requests[steps.findIndex(step => step?.name === "read" && step.arguments.path.endsWith("large-history.txt")) + 1];
    assert.match(snapshotOf(afterTruncation), /claim_flow/);
    assert.match(snapshotOf(afterTruncation), /node_flow/);
    assert.match(lastSnapshot, /claim_flow/);
    assert.match(lastSnapshot, /succeeded/);
    assert.equal(read.snapshot.messages.some(m => JSON.stringify(m).includes("<research_state_snapshot>")), false, "projection must not enter durable transcript");
    assert.ok((await readdir(join(workspace, "operations/contexts"))).length > 0);
    assert.equal(context.attempt_interpretations.length, 1);
    assert.equal(context.attempt_interpretations[0].id, "interpretation_flow");
    assert.equal(context.attempt_interpretations[0].claim_id, "claim_flow");
    assert.equal(context.attempt_interpretations[0].attempt_ref, context.attempts[0].id);
    const email = JSON.parse(await readFile(join(workspace, "reports/email-check.json")));
    assert.equal(email.recipient, "reader@example.test");
    assert.equal(email.enabled, true);
    assert.equal(existsSync(join(workspace, "reports/email/deliveries")), false);
    const liveness = JSON.parse(await readFile(join(workspace, "lifecycle/liveness.json")));
    assert.equal(liveness.disposition, "user_input_required");
    const continuations = requests.at(-1).messages.filter(message => message.role === "user" && JSON.stringify(message.content).includes("Research turn ended"));
    assert.equal(continuations.length, 1);
    const autonomous = requests.at(-1).messages.filter(message => message.role === "user" && JSON.stringify(message.content).includes("Research State requests continuation"));
    assert.equal(autonomous.length, 1);
    const receipts = await readdir(join(root,"state","requests"));
    const records = await Promise.all(receipts.filter(file=>file.endsWith(".json")).map(file=>readFile(join(root,"state","requests",file),"utf8").then(JSON.parse)));
    const continuation = records.find(row=>row.source === "state_continuation");
    assert.ok(continuation.operation_id, "real Pi must durably admit the continuation");
    assert.equal(continuation.admission_protocol, "tspi-state-continuation-idempotent/1");
    // Simulate losing the Monitor admission response before the Host persisted
    // its ID. Reopening the Host must recover the same Pi submission.
    const monitorRecord = records.find(row => row.source === "monitor");
    assert.ok(monitorRecord.operation_id);
    assert.equal(monitorRecord.admission_protocol, "tspi-monitor-idempotent/1");
    const requestCount = requests.length;
    const activityBeforeRestart = (await backend.listSessions("flow"))[0].updated_at;
    assert.equal(Date.parse(activityBeforeRestart), Math.max(...read.snapshot.messages.map(message => message.timestamp)));
    await backend.close();
    for (const file of receipts.filter(file => file.endsWith(".json"))) {
      const path = join(root, "state", "requests", file);
      const row = JSON.parse(await readFile(path, "utf8"));
      if (["monitor", "state_continuation"].includes(row.source)) await writeFile(path, JSON.stringify({ ...row,
        state: "uncertain", accepted: false, operation_id: null, reconciled: false,
        error: { code: "dispatch_unknown", message: "fixture lost response" },
      }));
    }
    backend = await createTspiHarnessBackend(backendOptions);
    assert.equal((await backend.listSessions("flow"))[0].updated_at, activityBeforeRestart);
    const recovered = await backend.sendInput(monitorRequest);
    assert.equal(recovered.accepted, true);
    assert.equal(recovered.operation_id, monitorRecord.operation_id);
    const recoveredContinuation = await backend.sendInput({ workspace_id: "flow", session_id,
      request_id: continuation.request_id, client_message_id: continuation.client_message_id,
      source: "state_continuation", mode: "next_run", text: continuation.text });
    assert.equal(recoveredContinuation.accepted, true);
    assert.equal(recoveredContinuation.operation_id, continuation.operation_id);
    await new Promise(done => setTimeout(done, 100));
    assert.equal(requests.length, requestCount);

  } catch (error) {
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
      await rm(root, { recursive: true, force: true });
    }
  }
});
