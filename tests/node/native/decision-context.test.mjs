import assert from 'node:assert/strict';
import test from 'node:test';
import { Harness, MemoryStorage, createRegistry, defineExtension, defineTool, hook, GenerationTask, CompactionTask, LiveDoc } from '@earendil-works/pi-durable';
import { createModels, fauxProvider, fauxAssistantMessage, fauxToolCall } from '@earendil-works/pi-ai';
import Type from 'typebox';
import { TODO_CONTEXT as context } from '@earendil-works/chord/context';
import { estimateContextTokens } from '@earendil-works/pi-ai/utils/estimate';
import { createDecisionContextInjector } from '../../../apps/app-server/decision-context.mjs';
import { inspectResearchControlLoop } from '../../../apps/app-server/research-control-loop.mjs';
import { createStateContinuationDriver } from '../../../apps/app-server/state-continuation.mjs';

test('actual generation requests rebuild facts after compaction and never persist snapshots', async t => {
  const faux = fauxProvider();
  const models = createModels(); models.setProvider(faux.provider);
  const requests = [], telemetry = [];
  let revision = 1;
  const inject = createDecisionContextInjector({
    sessionId: 'session_fixture', estimateContextTokens,
    bridge: { async execute_command(command) {
      assert.equal(command, 'research.context');
      return { schema_version: 'research-decision-context/2', context_id: `ctx_${revision}`, revision, events: [],
        goals: [{id: 'claim_goal', statement: 'Validate the transition structure'}],
        attempts: [{id: 'attempt_current', state: revision === 1 ? 'running' : 'failed',
          primary_failure: revision === 1 ? null : 'optimization_limit'}] };
    } },
    coordinator: { async commit_files(record) { telemetry.push(record); } },
  });
  const registry = createRegistry();
  registry.install(defineExtension({name:'context-fixture', hooks:[
    hook(GenerationTask, { beforeRequest: (request, api) => inject(request, String(api.taskId)) }),
    hook(CompactionTask, { beforeCompact: () => ({summary:'Old interpretation: attempt_current was QPErr. This historical claim must be checked against current execution facts.'}) }),
  ]}));
  const harness = await Harness.open(new MemoryStorage(), {models, registry,
    settings: {compaction: {enabled: false, keepRecentTokens: 0}}}, context);
  t.after(() => harness.close(context));
  const conversation = await harness.root(context, {agent:{model:{provider:'faux',modelId:'faux-1'}}});
  faux.setResponses([1,2].map(() => input => { requests.push(input); return fauxAssistantMessage('Research decision recorded.'); }));
  await conversation.submit({type:'input',content:'Initial research task. '.repeat(100)},context);
  await conversation.waitForIdle(context);
  const task = await conversation.compact(undefined, context);
  await harness.waitForTask(task, context);
  await conversation.waitForIdle(context);
  revision = 2;
  await conversation.submit({type:'input',content:'Inspect the latest result.'},context);
  await conversation.waitForIdle(context);
  assert.equal(requests.length, 2);
  const latest = JSON.stringify(requests[1].messages);
  assert.match(latest, /Old interpretation/);
  assert.match(latest, /optimization_limit/);
  assert.match(latest, /claim_goal/);
  assert.equal(requests[1].messages.filter(m => JSON.stringify(m).includes('<research_state_snapshot>')).length, 1);
  const snapshot = requests[1].messages.find(m => JSON.stringify(m).includes('<research_state_snapshot>'));
  assert.equal(snapshot.role, 'system');
  assert.match(snapshot.sections.tspi_research_context, /not a user message or a new turn/);
  assert.equal(requests[1].messages.filter(m => m.role === 'user').at(-1).content, 'Inspect the latest result.');
  assert.equal(telemetry.at(-1).payload.revision, 2);
  const entries = await conversation.entries({}, 100, undefined, context);
  assert.ok(entries.items.some(e => e.kind === 'pi.compaction'));
  assert.equal(JSON.stringify(entries).includes('<research_state_snapshot>'), false);
});

function controlRound(index, revision = 1, name = 'research_read', mode = 'context') {
  const id = `control_${index}`;
  return [fauxAssistantMessage([fauxToolCall(name, {mode, limit: index + 1}, {id})], {stopReason:'toolUse'}),
    {role:'toolResult',toolCallId:id,toolName:name,content:[{type:'text',text:JSON.stringify({workspace_id:'ws_loop',revision,
      checkpoint_id:`checkpoint_${index}`,lifecycle:index % 2 ? 'blocked' : 'continue_required'})}],timestamp:index}];
}

test('control-loop budget uses completed calls and resets on work, changed state or actual input', () => {
  const state = {workspace_id:'ws_loop',revision:1};
  const history = Array.from({length:12}, (_, i) => controlRound(i, 1, i % 2 ? 'research_checkpoint' : 'research_read')).flat();
  assert.match(inspectResearchControlLoop(history,state).block, /research_control_loop/);
  // Rebuilding the inspector (as on worker recovery) or retrying a request
  // cannot consume extra budget or replenish it.
  assert.equal(inspectResearchControlLoop(history,state).count,12);
  assert.equal(inspectResearchControlLoop(history,{...state,revision:2}).count,0);
  assert.equal(inspectResearchControlLoop([...history,{role:'user',content:'Resume with a corrected plan.'}],state).count,0);
  for (const [name, mode] of [['bash',undefined],['artifact_read',undefined],['research_read','evidence']]) {
    assert.equal(inspectResearchControlLoop([...history,...controlRound(13,1,name,mode)],state).count,0);
  }
  assert.ok(inspectResearchControlLoop(history.slice(0,12),state).warning);
  assert.equal(inspectResearchControlLoop(history.slice(0,12),state).block,undefined);
});

test('one native run stops repeated reads/recoveries without synthetic user turns or auto compaction', {timeout:10000}, async t => {
  const faux = fauxProvider();
  const models = createModels(); models.setProvider(faux.provider);
  const registry = createRegistry();
  const state = {context_id:'ctx_loop',workspace_id:'ws_loop',revision:1,events:[]};
  const tools = ['research_read','research_checkpoint'].map(name => defineTool({name,description:name,
    parameters:Type.Object({mode:Type.Optional(Type.String()),limit:Type.Optional(Type.Number()),checkpoint:Type.Optional(Type.Object({id:Type.String()}))}),
    execute: async args => ({content:[{type:'text',text:JSON.stringify({...state,checkpoint_id:args.checkpoint?.id})}]}),
  }));
  registry.install(defineExtension({name:'loop',tools,hooks:[hook(GenerationTask,{
    // Use a fresh injector every time to exercise recovery without in-memory counters.
    beforeRequest:(request,api)=>fixtureInjector({bridge:{async execute_command(){return state;}}})(request,String(api.taskId)),
  })]}));
  const harness = await Harness.open(new MemoryStorage(),{models,registry,settings:{compaction:{enabled:false}}},context);
  t.after(()=>harness.close(context));
  const conversation = await harness.root(context,{agent:{model:{provider:'faux',modelId:'faux-1'},tools}});
  const requests=[];
  faux.setResponses(Array.from({length:14},(_,i)=>request=>{
    requests.push(request);
    assert.equal(request.messages.filter(m=>m.role==='user').length,1);
    const name=i % 2 ? 'research_checkpoint' : 'research_read';
    return fauxAssistantMessage([fauxToolCall(name,name==='research_read'?{mode:'context',limit:i+1}:{checkpoint:{id:`recover_${i}`}})],{stopReason:'toolUse'});
  }));
  const outcome=await (await conversation.submit({type:'input',content:'Run the research task.'},context)).wait(context);
  await conversation.waitForIdle(context);
  assert.equal(outcome.reason,'request_blocked');
  assert.match(outcome.detail,/research_control_loop/);
  assert.equal(requests.length,12);
  assert.match(JSON.stringify(requests[6].messages),/6 consecutive state reads/);
  const live=await harness.snapshot(LiveDoc,conversation.id,context);
  assert.equal(live.run,undefined);
  const entries=await conversation.entries({},100,undefined,context);
  assert.equal(entries.items.filter(e=>e.kind==='pi.user').length,1);
  assert.doesNotMatch(JSON.stringify(entries),/research_state_snapshot/);
  const binding={key:'ws_loop/s',root:'/unused',workspaceId:'ws_loop',summary:{sessionId:'s'},
    snapshot:{operation:null,queues:[],lastResult:null,transcript:[...entries.items].reverse().flatMap(e=>e.model||[])}};
  let continuations=0;
  const drive=createStateContinuationDriver({readState:async()=>({...state,continuation:{admitted:true,session_id:'s',request_id:'continue:1'}}),
    sendInput:async()=>{continuations++;}});
  await drive(binding);
  assert.equal(continuations,0);
  assert.match(binding.continuationError,/research_control_loop/);
  // Explicit user input can resume the task; this is not a permanent block.
  faux.setResponses([fauxAssistantMessage('A corrected plan is ready.')]);
  const resumed=await (await conversation.submit({type:'input',content:'Use the corrected plan.'},context)).wait(context);
  assert.equal(resumed.status,'done');
});

function fixtureInjector(overrides = {}) {
  return createDecisionContextInjector({ sessionId: 'budget-fixture', estimateContextTokens,
    bridge: { async execute_command() { return {context_id:'ctx_test', revision:1, events:[]}; } },
    coordinator: { async commit_files() {} }, ...overrides });
}

test('token budget ignores tool metadata and counts system/tools once, with provider usage when available', async () => {
  const records = [];
  const inject = fixtureInjector({ coordinator: { async commit_files(record) { records.push(record.payload); } } });
  const messages = [
    {role:'system', content:'system '.repeat(4500), toolsAdded:[{name:'research_read',description:'read facts',parameters:{type:'object'}}], timestamp:1},
    {role:'user',content:[{type:'text',text:'研究问题'.repeat(3000)}],timestamp:2},
    {...fauxAssistantMessage('working', {timestamp:3}), usage:{input:16449,output:100,cacheRead:0,cacheWrite:0,totalTokens:16549}},
    {role:'toolResult',content:[{type:'text',text:'facts'}],details:{log:'metadata '.repeat(40000)},timestamp:4},
  ];
  const request = {messages, model:{contextWindow:240000,maxTokens:128000}, maxTokens:128000};
  assert.ok(Buffer.byteLength(JSON.stringify(messages)) > request.model.contextWindow);
  const result = await inject(request, 'budget');
  assert.ok(result.messages);
  assert.equal(records[0].input_tokens, 16551);
  assert.equal(records[0].usage_tokens, 16549);
  assert.equal(records[0].max_bytes, 16000);
  assert.equal(records[0].output_reserve_tokens, 128000);
  const withoutUsage = await inject({...request, messages:messages.slice(0,2)}, 'no-usage');
  assert.ok(withoutUsage.messages);
  assert.equal(records[1].input_tokens, estimateContextTokens(messages.slice(0,2)).tokens);
  const full = await inject({...request, maxTokens:239000}, 'full');
  assert.equal(full.compact, true);
  assert.match(full.block, /context_budget_exceeded/);
  const smallerOutput = await inject({...request, maxTokens:1024}, 'small-output');
  assert.ok(smallerOutput.messages);
});

test('oversized projection and State/record errors preserve a bounded diagnostic model request', async () => {
  const request = {messages:[],model:{contextWindow:10000},maxTokens:1000};
  const large = fixtureInjector({bridge:{async execute_command(){return {context_id:'ctx_big',events:[],data:'x'.repeat(24000)};}}});
  assert.match(JSON.stringify((await large(request,'large')).messages), /projection exceeds its byte budget/);
  for (const [code, override] of [
    ['research_context_unavailable',{bridge:{async execute_command(){throw Error('read failed');}}}],
    ['research_context_unavailable',{bridge:{async execute_command(){return {};}}}],
    ['research_context_record_failed',{coordinator:{async commit_files(){throw Error('record failed');}}}],
  ]) {
    const result = await fixtureInjector(override)(request,'failed');
    assert.equal(result.block,undefined);
    assert.match(JSON.stringify(result.messages),new RegExp(code));
    assert.equal(result.compact,undefined);
    assert.ok(result.messages);
    assert.ok(JSON.stringify(result.messages).length < 4000);
  }
});

test('unavailable State exposes no readiness and records omitted wake events; telemetry failure retains readable State', async () => {
  const request = {messages:[{role:'user',content:'event_id=event_pending'}],model:{contextWindow:10000},maxTokens:1000};
  const unavailable = await fixtureInjector({bridge:{async execute_command(){throw Error('State offline');}}})(request,'offline');
  const section = unavailable.messages.at(-1).sections.tspi_research_context;
  assert.match(section, /"availability":"unavailable"/);
  assert.match(section, /"execution_ready":null/);
  assert.match(section, /"revision":null/);
  assert.match(section, /"wake_events":\{"requested":1,"included":0,"omitted":1\}/);
  assert.match(section, /side-effect admission still requires current State/);
  const unrecorded = await fixtureInjector({coordinator:{async commit_files(){throw Error('Disk unavailable');}}})(request,'unrecorded');
  const retained = unrecorded.messages.at(-1).sections.tspi_research_context;
  assert.match(retained, /"context_id":"ctx_test"/);
  assert.match(retained, /"revision":1/);
  assert.match(retained, /research_context_record_failed/);
  assert.doesNotMatch(retained, /"availability":"unavailable"/);
});

for (const scenario of ['recovered','still-full','declined','compaction-failed','state-failed','hook-threw']) {
  test(`request admission ${scenario} terminates without a model repair loop`, {timeout:10000}, async t => {
    const faux = fauxProvider({models:[{id:'faux-1',contextWindow:10000,maxTokens:1024}]});
    const models = createModels(); models.setProvider(faux.provider);
    const registry = createRegistry();
    let second = false, reads = 0, compactions = 0, requests = 0, revision = 1;
    const inject = fixtureInjector({bridge:{async execute_command(){
      reads++;
      if (second && scenario === 'state-failed') throw Error('State offline');
      return {context_id:`ctx_${revision}`,revision,events:[]};
    }}});
    registry.install(defineExtension({name:'bounded-admission',hooks:[
      hook(GenerationTask,{beforeRequest(request,api){
        if (second && scenario === 'hook-threw') throw Error('unexpected hook failure');
        return inject(request,String(api.taskId));
      }}),
      hook(CompactionTask,{beforeCompact(){
        compactions++; revision++;
        if (scenario === 'declined') return {decline:true};
        if (scenario === 'compaction-failed') return undefined;
        return {summary:scenario === 'still-full' ? 'large summary '.repeat(1800) : 'Short authoritative history.'};
      }}),
    ]}));
    const harness = await Harness.open(new MemoryStorage(),{models,registry,
      settings:{compaction:{enabled:false,keepRecentTokens:0},retry:{enabled:false}}},context);
    t.after(()=>harness.close(context));
    const conversation = await harness.root(context,{agent:{model:{provider:'faux',modelId:'faux-1'}}});
    faux.setResponses([() => {requests++;return fauxAssistantMessage('first');}, () => {
      requests++;
      return scenario === 'compaction-failed' ? fauxAssistantMessage('',{stopReason:'error',errorMessage:'summary unavailable'}) : fauxAssistantMessage('recovered');
    }]);
    const first = await conversation.submit({type:'input',content:'x'.repeat(['state-failed','hook-threw'].includes(scenario) ? 100 : 15000)},context);
    await first.wait(context);
    second = true;
    // Read errors should stop directly while there is still request room.
    const input = ['state-failed','hook-threw'].includes(scenario) ? 'next' : 'y'.repeat(8000);
    const submission = await conversation.submit({type:'input',content:input},context);
    const result = await submission.wait(context);
    await conversation.waitForIdle(context);
    const proceeds = ['recovered','state-failed'].includes(scenario);
    assert.equal(result.status === 'unanswered',!proceeds);
    if (!proceeds) assert.equal(result.reason, 'request_blocked');
    assert.equal(compactions,['state-failed','hook-threw'].includes(scenario) ? 0 : 1);
    assert.equal(requests,['recovered','compaction-failed','state-failed'].includes(scenario) ? 2 : 1);
    if (scenario === 'recovered') assert.equal(reads,3);
    const entries = await conversation.entries({},100,undefined,context);
    assert.doesNotMatch(JSON.stringify(entries),/Use research_read to diagnose|<research_state_snapshot>/);
    const live = await harness.snapshot(LiveDoc, conversation.id, context);
    assert.equal(live.run,undefined);
  });
}

test('an uncompactable first request stops before contacting the provider', {timeout:10000}, async t => {
  const faux = fauxProvider({models:[{id:'faux-1',contextWindow:10000,maxTokens:1024}]});
  const models = createModels(); models.setProvider(faux.provider);
  const registry = createRegistry(); let compacted = 0, requests = 0;
  const inject = fixtureInjector();
  registry.install(defineExtension({name:'no-cut',hooks:[
    hook(GenerationTask,{beforeRequest:(request,api)=>inject(request,String(api.taskId))}),
    hook(CompactionTask,{beforeCompact(){compacted++;return {summary:'short'};}}),
  ]}));
  const harness = await Harness.open(new MemoryStorage(),{models,registry,settings:{compaction:{enabled:false,keepRecentTokens:0}}},context);
  t.after(()=>harness.close(context));
  const conversation = await harness.root(context,{agent:{model:{provider:'faux',modelId:'faux-1'}}});
  faux.setResponses([()=>{requests++;return fauxAssistantMessage('must not run');}]);
  const submission = await conversation.submit({type:'input',content:'x'.repeat(30000)},context);
  const outcome = await submission.wait(context);
  assert.equal(outcome.reason,'request_blocked');
  assert.match(outcome.detail,/context_budget_exceeded/);
  assert.equal(compacted,0); assert.equal(requests,0);
});
