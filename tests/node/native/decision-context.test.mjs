import assert from 'node:assert/strict';
import test from 'node:test';
import { Harness, MemoryStorage, createRegistry, defineExtension, hook, GenerationTask, CompactionTask, LiveDoc } from '@earendil-works/pi-durable';
import { createModels, fauxProvider, fauxAssistantMessage } from '@earendil-works/pi-ai';
import { TODO_CONTEXT as context } from '@earendil-works/chord/context';
import { estimateContextTokens } from '@earendil-works/pi-ai/utils/estimate';
import { createDecisionContextInjector } from '../../../apps/app-server/decision-context.mjs';

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
  assert.equal(telemetry.at(-1).payload.revision, 2);
  const entries = await conversation.entries({}, 100, undefined, context);
  assert.ok(entries.items.some(e => e.kind === 'pi.compaction'));
  assert.equal(JSON.stringify(entries).includes('<research_state_snapshot>'), false);
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

test('oversized projection and State/record errors have distinct bounded dispositions', async () => {
  const request = {messages:[],model:{contextWindow:10000},maxTokens:1000};
  const large = fixtureInjector({bridge:{async execute_command(){return {context_id:'ctx_big',events:[],data:'x'.repeat(24000)};}}});
  assert.equal((await large(request,'large')).compact,true);
  for (const [code, override] of [
    ['research_context_unavailable',{bridge:{async execute_command(){throw Error('read failed');}}}],
    ['research_context_unavailable',{bridge:{async execute_command(){return {};}}}],
    ['research_context_record_failed',{coordinator:{async commit_files(){throw Error('record failed');}}}],
  ]) {
    const result = await fixtureInjector(override)(request,'failed');
    assert.match(result.block,new RegExp(code));
    assert.equal(result.compact,undefined);
    assert.equal(result.messages,undefined);
  }
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
    assert.equal(result.status === 'unanswered',scenario !== 'recovered');
    if (scenario !== 'recovered') assert.equal(result.reason, 'request_blocked');
    assert.equal(compactions,['state-failed','hook-threw'].includes(scenario) ? 0 : 1);
    assert.equal(requests,['recovered','compaction-failed'].includes(scenario) ? 2 : 1);
    if (scenario === 'recovered') assert.equal(reads,2);
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
