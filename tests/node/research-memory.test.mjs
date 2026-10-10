import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, mkdir, rm} from 'node:fs/promises';
import {join} from 'node:path';
import {create_workspace_initializer, validate_workspace_files} from '../../apps/agent/host/workspace.mjs';
import {create_python_runtime_bridge, create_runtime_bridge} from '../../apps/agent/bridge/client.mjs';
import {createResearchTools} from '../../apps/agent/tools/research/tools.mjs';
import {createPublicToolContracts} from '../../apps/agent/tools/contracts.mjs';
import Type from '../../apps/agent/pi/typebox.mjs';
import {validateToolArguments} from '@earendil-works/pi-ai';
import {TEST_ROOT} from './native/test-environment.mjs';

test('research tools preserve Nodes, results and original tasks through a restarted Python bridge', async()=>{
  await mkdir(TEST_ROOT,{recursive:true});
  const root=await mkdtemp(join(TEST_ROOT,'memory-'));
  let bridge;
  try {
    const workspaces=create_workspace_initializer();
    await workspaces.initialize_workspace({workspace_root:root,workspace_id:'memory'});
    bridge=create_python_runtime_bridge({workspace_root:root,workspace_id:'memory'});
    await assert.rejects(bridge.execute_command('research.read'),/admission/);
    const manifest=await workspaces.admit_workspace(root);
    await validate_workspace_files(manifest,root);
    const task=await bridge.execute_command('research.source',{session_id:'s',message_id:'m',text:'Compare two pathways, retain uncertainties.'});
    let tools=createResearchTools({commandBridge:bridge});
    assert.deepEqual(tools.map(t=>t.name),['research_read','research_search','research_create','research_update','research_result']);
    const api={callId:'create1',coragent:{workspace_root:root,session_id:'s',operation_id:'operation-1',principal:'root_agent'}};
    const run=async(name,args,callId)=> (await tools.find(t=>t.name===name).execute(args,{...api,callId})).details.result;
    const created=await run('research_create',{goal:'Compare pathways',plan:'Calculate both pathways.'},'create1');
    const nodeId=created.node.id;
    assert.deepEqual(await run('research_create',{goal:'Compare pathways',plan:'Calculate both pathways.'},'create1'),created);
    const updated=await run('research_update',{node_id:nodeId,note:'First attempt failed; retry with another geometry.',plan:'Try another geometry.'},'update1');
    assert.equal(updated.node.plan,'Try another geometry.');
    const published=await run('research_result',{node_id:nodeId,conclusion:'The fixture does not establish a preferred pathway.',as_assessment:true},'result1');
    assert.equal(published.result_saved,true);
    assert.equal(published.assessment_selected,true);
    await assert.rejects(tools.find(t=>t.name==='research_update').execute({node_id:nodeId,note:'forged'},{...api,coragent:{...api.coragent,principal:'guest'}}),/principal/);
    await bridge.close();
    bridge=create_python_runtime_bridge({workspace_root:root,workspace_id:'memory'});
    tools=createResearchTools({commandBridge:bridge});
    const resumed=await run('research_update',{node_id:nodeId,note:'Resume using the revision actually read before restart.',plan:'Resume independent pathway comparison.'},'resumed');
    assert.equal(resumed.node.plan,'Resume independent pathway comparison.');
    const snapshot=await bridge.execute_command('research.read',{session_id:'s'});
    assert.equal(snapshot.schema_version,'research-snapshot/3');
    assert.equal(snapshot.tasks[0].ref,task.source_ref);
    assert.ok(snapshot.nodes.some(node=>node.id===nodeId));
    const detail=await bridge.execute_command('research.read',{ref:nodeId,session_id:'s'});
    assert.equal(detail.node.plan,'Resume independent pathway comparison.');
    assert.equal(detail.results.length,1);
    const otherRead=await bridge.execute_command('research.read',{ref:nodeId,session_id:'other'});
    await bridge.execute_command('research.observe',{session_id:'other',read_basis:otherRead.read_basis});
    await bridge.execute_command('research.update',{node_id:nodeId,note:'Another researcher proposes a change.',plan:'Compare the alternative method.',session_id:'other',request_id:'other-update'});
    await assert.rejects(run('research_update',{node_id:nodeId,note:'This outdated update must not overwrite the new plan.',plan:'Stale plan'},'stale'),/node_revision_conflict/);
    const note=await run('research_update',{node_id:nodeId,note:'Append an observation without replacing shared fields.'},'independent-note');
    assert.equal(note.node.plan,'Compare the alternative method.');
    const original=await bridge.execute_command('research.read',{ref:task.source_ref});
    assert.equal(JSON.parse(original.text).content,'Compare two pathways, retain uncertainties.');
    await assert.rejects(bridge.execute_command('research.change',{}),/unsupported/);
    await assert.rejects(bridge.execute_command('research.update',{content:'old notebook protocol'}),/schema_field_invalid.*unsupported fields: content/);
  } finally {await bridge?.close();await rm(root,{recursive:true,force:true});}
});

test('tool schemas express research choices without exposing receipt and execution internals',()=>{
  const contracts=createPublicToolContracts(Type);
  const validate=(key,args)=>validateToolArguments(contracts[key],{type:'toolCall',id:'c',name:contracts[key].name,arguments:args});
  assert.doesNotThrow(()=>validate('create',{goal:'Find the transition structure.'}));
  assert.doesNotThrow(()=>validate('update',{node_id:'node_1',note:'Failed optimization; inspect gradients.'}));
  assert.doesNotThrow(()=>validate('result',{node_id:'node_1',conclusion:'Evidence is insufficient.'}));
  assert.throws(()=>validate('update',{node_id:'node_1',note:'fake',read_basis:'forged'}));
  assert.throws(()=>validate('state',{event_ids:['event_forged']}));
  assert.throws(()=>validate('state',{entry_node_ids:['node_A'],focus_node_ids:['node_A']}));
  assert.throws(()=>validate('update',{content:'old notebook protocol'}));
  assert.doesNotThrow(()=>validate('jobStart',{command:['true'],node_id:'node_1'}));
  assert.throws(()=>validate('jobStart',{command:['true']}));
  assert.equal(contracts.change,undefined);
});

test('tools acknowledge returned revisions and bind writes to their trusted session',async()=>{
  const calls=[];
  const bridge={async execute_command(command,params){
    calls.push({command,params});
    if(command==='research.read') return {node:{id:params.ref},read_basis:`basis_${params.ref}`};
    return {};
  }};
  const tools=createResearchTools({commandBridge:bridge});
  const run=(name,args,session='s')=>tools.find(t=>t.name===name).execute(args,{callId:'call',coragent:{workspace_root:'/tmp/memory',session_id:session,operation_id:'operation-1',principal:'root_agent'}});
  await run('research_read',{ref:'node_A'});
  await run('research_read',{ref:'node_B'});
  await run('research_update',{node_id:'node_A',note:'interpret A'});
  assert.equal(calls.at(-1).params.read_basis,undefined);
  assert.equal(calls.at(-1).params.session_id,'s');
  await run('research_update',{node_id:'node_A',note:'another session'},'other');
  assert.equal(calls.at(-1).params.read_basis,undefined);
  assert.deepEqual(calls.filter(call=>call.command==='research.observe').map(call=>call.params), [
    {session_id:'s',read_basis:'basis_node_A'}, {session_id:'s',read_basis:'basis_node_B'},
  ]);
});

test('bridge binds command root and rejects alternate roots in transaction requests',async()=>{
  const calls=[];
  const bridge=create_runtime_bridge({workspace_root:'/tmp/a',workspace_id:'a',transport:{async request(method,payload){calls.push({method,payload});return {};}}});
  await bridge.execute_command('research.read');
  assert.equal(calls[0].payload.workspace_root,'/tmp/a');
  await assert.rejects(bridge.transaction_get({request_id:'x',workspace_root:'/tmp/b'}),/workspace_root_mismatch/);
});

test('oversized Unicode replies preserve saved outcomes without acknowledging omitted fields',async()=>{
  const calls=[];
  const node={id:'node_large',revision:2,goal:'研究'.repeat(12000)};
  const result={accepted:true,node,result:{id:'result_large',node_id:node.id,conclusion:'结果'.repeat(12000)},result_saved:true,assessment_selected:true,conflict:null,read_basis:'read_unseen'};
  const tools=createResearchTools({commandBridge:{async execute_command(command,params){calls.push({command,params});return result;}}});
  const tool=tools.find(t=>t.name==='research_result');
  const response=await tool.execute({node_id:node.id,conclusion:'Published outcome'},{callId:'large',coragent:{workspace_root:'/tmp/memory',session_id:'s',operation_id:'operation-1',principal:'root_agent'}});
  assert.deepEqual(calls.map(call=>call.command),['research.result']);
  const visible=JSON.parse(response.content[0].text);
  assert.equal(visible.content_omitted,true);
  assert.equal(visible.result_saved,true);
  assert.equal(visible.assessment_selected,true);
  assert.equal(visible.node.id,node.id);
  assert.equal(visible.result.id,'result_large');
  assert.equal(visible.read_basis,undefined);
  assert.deepEqual(visible.read.map(item=>item.ref),['node_large','result_large']);
  assert.ok(Buffer.byteLength(response.content[0].text) < tool.outputLimits.maxBytes);
  assert.ok(response.content[0].text.split('\n').length <= tool.outputLimits.maxLines);
});

test('an oversized committed Node reply cannot silently advance its read revision',async()=>{
  await mkdir(TEST_ROOT,{recursive:true});
  const root=await mkdtemp(join(TEST_ROOT,'large-'));
  let bridge;
  try {
    const workspaces=create_workspace_initializer();
    await workspaces.initialize_workspace({workspace_root:root,workspace_id:'large'});
    await workspaces.admit_workspace(root);
    bridge=create_python_runtime_bridge({workspace_root:root,workspace_id:'large'});
    const tools=createResearchTools({commandBridge:bridge});
    const run=async(name,args,callId)=>(await tools.find(t=>t.name===name).execute(args,{callId,coragent:{workspace_root:root,session_id:'large-session',operation_id:callId,principal:'root_agent'}})).details.result;
    const created=await run('research_create',{goal:'g'.repeat(7900),proposal:'研'.repeat(5300),plan:'究'.repeat(5300)},'create');
    assert.ok(created.read_basis);
    const nodeId=created.node.id;
    const expanded=await run('research_update',{node_id:nodeId,note:'Record a substantial progress analysis.',progress:'果'.repeat(5300)},'expand');
    assert.equal(expanded.accepted,true);
    assert.equal(expanded.content_omitted,true);
    assert.equal(expanded.read_basis,undefined);
    await assert.rejects(run('research_update',{node_id:nodeId,note:'Cannot replace a field without seeing its current revision.',plan:'New plan'},'unseen'),/node_revision_conflict/);
    const field=await run('research_read',{ref:nodeId,field:'plan',limit:32000},'field');
    assert.ok(field.read_basis);
    const updated=await run('research_update',{node_id:nodeId,note:'Read the current plan before revising it.',plan:'New plan'},'seen');
    assert.equal(updated.accepted,true);
  } finally {await bridge?.close();await rm(root,{recursive:true,force:true});}
});
