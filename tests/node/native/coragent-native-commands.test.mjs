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

test("usage and monitor use separate live panels while documents choose reading surfaces", async () => {
  const shown=[];
  let usage='Total tokens: 10', monitor='Running: 1';
  const commands=createTerminalCommands({
    ui:{showStatus(message){throw new Error(message);}}, session:{sessionId:'one',async monitor(){return {}; }},
    show:async (title,body,context,command,scope,mode)=>shown.push({title,body,command,scope,mode}),
    usage:()=>usage,monitor:()=>monitor,
    queries:{async systemPrompt(){return {session_id:'one',result:{effective:'prompt'}};},
      async research(){return {session_id:'one',result:{note:'result'}};}},
  });
  for(const name of ['usage','monitor','sys-prompt','research']) await commands.find(c=>c.name===name).run('',{});
  assert.deepEqual(shown.map(item=>item.mode),['panel','panel','page','auto']);
  assert.equal(shown[0].body(),'Total tokens: 10');assert.equal(shown[1].body(),'Running: 1');
  usage='Total tokens: 20';monitor='Running: 2';
  assert.equal(shown[0].body(),'Total tokens: 20');assert.equal(shown[1].body(),'Running: 2');
  assert.throws(()=>parseSlashCommand('monitor','unexpected'),/Usage/);
});

test('Monitor grammar separates user tasks, compute jobs and execution records', () => {
  for (const [input, method, fields] of [
    ['', 'monitor/overview', {}], ['tasks --limit 5 --cursor next', 'monitor/tasks', {limit:5,cursor:'next'}],
    ['task t1', 'monitor/task/read', {user_task_id:'t1'}],
    ['task pause t1', 'monitor/task/pause', {user_task_id:'t1'}],
    ['task resume t1', 'monitor/task/resume', {user_task_id:'t1'}],
    ['task cancel t1 --keep-jobs', 'monitor/task/cancel', {user_task_id:'t1',jobs:'keep'}],
    ['task cancel t1 --cancel-jobs', 'monitor/task/cancel', {user_task_id:'t1',jobs:'cancel'}],
    ['jobs --task t1', 'monitor/jobs', {user_task_id:'t1'}],
    ['job j1', 'monitor/job/read', {job_id:'j1'}],
    ['job cancel j1', 'monitor/job/cancel', {job_id:'j1'}],
    ['runs --task t1', 'monitor/runs', {user_task_id:'t1'}],
    ['run r1', 'monitor/run/read', {run_id:'r1'}], ['health', 'monitor/health', {}],
  ]) assert.deepEqual(parseSlashCommand('monitor', input), {command:'client.monitor',params:{method,...fields}});
  for (const input of ['status', 'enable', 'disable', 'task', 'task cancel t1', 'task cancel t1 --keep-jobs --cancel-jobs',
    'task pause', 'job cancel', 'health extra', 'jobs --task', 'jobs --limit 0', 'jobs --limit 101',
    'jobs --task t1 --task t2', 'jobs --root /tmp', 'tasks --task t1']) assert.throws(() => parseSlashCommand('monitor', input), /Usage/);
});

test('Monitor task controls use current revision and direct Host requests without model input', async () => {
  const calls=[];
  const session=createTerminalSession({workspaceId:'w',sessionId:'s',async request(method,params){
    calls.push([method,params]);
    return {items:[{user_task_id:'t1',revision:7}],next_cursor:null};
  }});
  await session.monitor('monitor/tasks',{limit:5});
  assert.deepEqual(calls,[['monitor/tasks',{workspace_id:'w',session_id:'s',limit:5}]]);
  await session.monitor('monitor/task/pause',{user_task_id:'t1'});
  assert.equal(calls[1][0],'monitor/tasks');
  assert.deepEqual(calls[1][1],{workspace_id:'w',session_id:'s',limit:100});
  assert.equal(calls[2][0],'monitor/task/pause');
  assert.equal(calls[2][1].expected_revision,7);
  assert.match(calls[2][1].request_id,/^terminal-monitor-/);
  assert.equal(calls.some(([method])=>method==='input/send'),false);
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

test('Monitor run detail pagination is explicit and bounded', () => {
  assert.deepEqual(parseSlashCommand('monitor', 'run r1 --cursor c2 --limit 10').params,
    {method:'monitor/run/read',run_id:'r1',cursor:'c2',limit:10});
  assert.throws(() => parseSlashCommand('monitor', 'run r1 --limit 0'), /Usage/);
  assert.throws(() => parseSlashCommand('monitor', 'run r1 --cursor c1 --cursor c2'), /Usage/);
});

test('Monitor views keep tool payloads out of user task and Job details', async () => {
  const {formatMonitor} = await import('../../../apps/agent/terminal/commands/monitor.mjs');
  const detail = formatMonitor('monitor/job/read', {job:{job_id:'j1',state:'succeeded',collection_state:'not_collected',
    command:['SECRET_COMMAND'],metadata:{key:'SECRET_METADATA'}}});
  assert.match(detail,/Execution: succeeded/);
  assert.match(detail,/Collection: not_collected/);
  assert.match(detail,/Analysis: Not recorded/);
  assert.doesNotMatch(detail,/SECRET_/);
  assert.match(formatMonitor('monitor/runs',{items:[],next_cursor:'c2'},{user_task_id:'t1',limit:5}),
    /Next page: \/monitor runs --task t1 --limit 5 --cursor c2/);
  assert.match(formatMonitor('monitor/run/read',{run:{run_id:'r1'},items:[],next_cursor:'c3'},{run_id:'r1'}),
    /Next page: \/monitor run r1 --cursor c3/);
});

test('execution records label model and tool operations and expose safe failure facts', async () => {
  const {formatMonitor} = await import('../../../apps/agent/terminal/commands/monitor.mjs');
  const result = formatMonitor('monitor/run/read', {run:{run_id:'r1',user_task_id:'t1'},items:[
    {pi_task_id:'g1',kind:'pi.generation',state:'terminal',outcome:'succeeded',error:null},
    {pi_task_id:'tool1',kind:'pi.tool',state:'terminal',outcome:'succeeded',tool_name:'job_start',result_entry_id:'entry1',
      error:{code:'invalid_request',failure_class:'validation',retryable:false,action_outcome:'not_started'},raw_output:'SECRET_OUTPUT'},
  ],next_cursor:null},{run_id:'r1'});
  assert.match(result,/Model request · terminal \/ succeeded/);
  assert.match(result,/Tool call: job_start/);
  assert.match(result,/Error: invalid_request/);
  assert.match(result,/Retryable: No/);
  assert.match(result,/Result entry: entry1/);
  assert.doesNotMatch(result,/SECRET_OUTPUT/);
});
