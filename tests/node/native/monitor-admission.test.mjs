import assert from 'node:assert/strict';
import test from 'node:test';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';
import { Harness, MemoryStorage, createRegistry, InboxDoc, LiveDoc } from '@earendil-works/pi-durable';
import { createModels, fauxProvider, fauxAssistantMessage } from '@earendil-works/pi-ai';
import { TODO_CONTEXT as context } from '@earendil-works/chord/context';
import { createMonitorAdmission } from '../../../apps/app-server/monitor-admission.mjs';
import { wakeMessage } from '../../../apps/app-server/pi-monitor-worker.mjs';
import { pinnedPiSource } from './test-environment.mjs';

const { admitSubmission } = await import(pathToFileURL(join(pinnedPiSource(), 'packages/durable/src/harness/submissions.ts')));
const text = ids => ['A compute monitor event requires attention.', ...ids.map(id => `event_id=${id}`)].join('\n');

async function setup(t) {
  const faux = fauxProvider();
  const models = createModels();models.setProvider(faux.provider);
  const harness = await Harness.open(new MemoryStorage(), { models, registry:createRegistry(), settings:{} }, context);
  t.after(() => harness.close(context));
  const conversation = await harness.root(context, {agent:{model:{provider:'faux',modelId:'faux-1'}}});
  let obsolete = false;
  let assessments = 0;
  const admission = createMonitorAdmission({harness,conversation,LiveDoc,InboxDoc,admitSubmission,wakeMessage,
    workspaceId:'ws_test',sessionId:'s',kernel:{async turn(request) {
      assessments++;
      return {status:'completed',output:{admitted:!obsolete,obsolete,event:{event_id:request.input.event_id,state:'failed'}}};
    }}});
  return {harness,conversation,admission,faux,setObsolete(value){obsolete=value;},assessments:()=>assessments};
}

test('busy monitor admission leaves no inbox entry; stale batch causes no generation', async t => {
  const state=await setup(t);
  let reached;
  const ready=new Promise(resolve=>{reached=resolve;});
  state.faux.setResponses([(_ctx,options)=>new Promise((_,reject)=>{
    reached();options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true});
  })]);
  await state.conversation.submit({type:'input',content:'user task'},context);
  await ready;
  const rejected=await state.admission.admit({requestId:'batch',text:text(['event_1','event_2'])},context);
  assert.equal(rejected.error.code,'busy');
  assert.equal(state.assessments(),0);
  assert.deepEqual((await state.harness.snapshot(InboxDoc,state.conversation.id,context)).items,[]);
  await state.conversation.abort(context);
  state.setObsolete(true);
  assert.deepEqual(await state.admission.admit({requestId:'batch',text:text(['event_1','event_2'])},context),{accepted:true,skipped:true});
  assert.equal((await state.conversation.entries({},100,undefined,context)).items.filter(e=>e.kind==='pi.user').length,1);
});

test('batch admits once and retries reuse the durable submission', async t => {
  const state=await setup(t);state.faux.setResponses([fauxAssistantMessage('done')]);
  const request={requestId:'batch',text:text(['event_1','event_2'])};
  const first=await state.admission.admit(request,context);
  assert.equal(first.accepted,true);
  await state.conversation.waitForIdle(context);
  const second=await state.admission.admit(request,context);
  assert.equal(second.operation_id,first.operation_id);
  assert.equal(state.assessments(),2);
  const messages=(await state.conversation.entries({},100,undefined,context)).items.filter(e=>e.kind==='pi.user');
  assert.equal(messages.length,1);
  assert.match(JSON.stringify(messages[0]),/event_1/);assert.match(JSON.stringify(messages[0]),/event_2/);
});

test('legacy monitor queue is pruned without removing user input or unhandled failure', async t => {
  const state=await setup(t);
  let reached;
  const ready=new Promise(resolve=>{reached=resolve;});
  state.faux.setResponses([(_ctx,options)=>new Promise((_,reject)=>{
    reached();options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true});
  })]);
  await state.conversation.submit({type:'input',content:'user task'},context);await ready;
  const old=await state.conversation.submit({type:'input',content:text(['event_1']),whenBusy:'followUp'},context);
  const user=await state.conversation.submit({type:'input',content:'next user task',whenBusy:'followUp'},context);
  await state.admission.prune(context);
  assert.equal((await state.harness.snapshot(InboxDoc,state.conversation.id,context)).items.length,2);
  state.setObsolete(true);await state.admission.prune(context);
  assert.equal((await old.status(context)).status,'unanswered');
  assert.deepEqual((await state.harness.snapshot(InboxDoc,state.conversation.id,context)).items.map(i=>i.id),[user.id]);
  await state.conversation.abort(context);
});

test('native input racing a monitor assessment cannot split its admission transaction', async t => {
  const state=await setup(t);state.faux.setResponses([fauxAssistantMessage('done')]);
  const [monitor,user]=await Promise.allSettled([
    state.admission.admit({requestId:'race',text:text(['event_1'])},context),
    state.conversation.submit({type:'input',content:'native user input',whenBusy:'reject'},context),
  ]);
  assert.equal(monitor.status,'fulfilled');
  if (monitor.value.accepted) assert.equal(user.status,'rejected');
  else {assert.equal(monitor.value.error.code,'busy');assert.equal(user.status,'fulfilled');}
  await state.conversation.waitForIdle(context);
  assert.deepEqual((await state.harness.snapshot(InboxDoc,state.conversation.id,context)).items,[]);
});

test('State continuation uses one durable identity and rejects obsolete or busy scope', async t => {
  const state = await setup(t);
  let next = { admitted: true, request_id: 'state-continue:one', session_id: 's' };
  const admission = createMonitorAdmission({ harness: state.harness, conversation: state.conversation,
    LiveDoc, InboxDoc, admitSubmission, wakeMessage, workspaceId: 'ws_test', sessionId: 's',
    kernel: { read_liveness: async () => ({ continuation: next }) } });
  state.faux.setResponses([fauxAssistantMessage('continued')]);
  const request = { requestId: 'state-continue:one', text: 'Research State requests continuation' };
  const first = await admission.admitContinuation(request, context);
  assert.equal(first.accepted, true);
  await state.conversation.waitForIdle(context);
  next = null;
  assert.deepEqual(await admission.admitContinuation(request, context), first);
  const submission = await state.harness.submission(Number(first.operation_id), context);
  assert.equal((await submission.status(context)).requestId, request.requestId);
  assert.equal((await admission.admitContinuation({ ...request, requestId: 'state-continue:old' }, context)).accepted, false);
  let ready;
  const started = new Promise(resolve => { ready = resolve; });
  state.faux.setResponses([(_ctx, options) => new Promise((_, reject) => {
    ready(); options.signal.addEventListener('abort', () => reject(options.signal.reason), { once: true });
  })]);
  await state.conversation.submit({ type: 'input', content: 'real user update' }, context);
  await started;
  next = { admitted: true, request_id: 'state-continue:two', session_id: 's' };
  assert.equal((await admission.admitContinuation({ ...request, requestId: next.request_id }, context)).accepted, false);
  assert.deepEqual((await state.harness.snapshot(InboxDoc, state.conversation.id, context)).items, []);
  await state.conversation.abort(context);
});
