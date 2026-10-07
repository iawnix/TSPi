import assert from 'node:assert/strict';
import test from 'node:test';
import { createStateContinuationDriver } from '../../../apps/app-server/state-continuation.mjs';

test('State continuation survives driver replacement through stable Host receipts; stops on waits', async () => {
  const binding = {key:'w/s',root:'/unused',workspaceId:'w',summary:{sessionId:'s'},snapshot:{operation:null,queues:[]}};
  let state = {continuation:{request_id:'state-continue:one',session_id:'s',admitted:true}};
  const receipts = new Map(); let admitted = 0;
  const sendInput = async params => {
    if (!receipts.has(params.client_message_id)) { admitted++; receipts.set(params.client_message_id,{accepted:true,entry_id:'1'}); }
    return receipts.get(params.client_message_id);
  };
  let drive = createStateContinuationDriver({readState:async()=>state,sendInput});
  await Promise.all([drive(binding),drive(binding)]);
  drive = createStateContinuationDriver({readState:async()=>state,sendInput});
  await drive(binding); assert.equal(admitted,1);
  state={continuation:null}; await drive(binding); assert.equal(admitted,1);
  state={continuation:{request_id:'state-continue:two',session_id:'s',admitted:false}};
  await drive(binding); assert.equal(admitted,1);
  state.continuation.admitted=true; binding.snapshot.operation={id:'user'};
  await drive(binding); assert.equal(admitted,1);
  binding.snapshot.operation=null; await drive(binding); assert.equal(admitted,2);
});
