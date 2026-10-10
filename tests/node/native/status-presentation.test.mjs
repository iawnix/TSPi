import assert from 'node:assert/strict';
import test from 'node:test';
import {EventEmitter} from 'node:events';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {pinnedPiSource} from './test-environment.mjs';
import {activityStatus,contextMatches,createStatusPresentation,usageTotals} from '../../../apps/agent/terminal/status/presentation.mjs';
import {createDocumentView} from '../../../apps/agent/terminal/renderers/document.mjs';
import {createCommandPresentation} from '../../../apps/agent/terminal/commands/panel.mjs';
import {subscribeMonitor} from '../../../apps/agent/terminal/status/monitor.mjs';
const tui = await import(pathToFileURL(join(pinnedPiSource(),'packages/tui/src/index.ts')));
const theme = {fg:(_,text)=>text,bold:text=>text};
const agent={model:{provider:'fixture',modelId:'a'},thinkingLevel:'medium'};
const view={entries:[{id:1}],docs:{'pi.agent':agent,'pi.usage':{models:{'fixture/a':{input:10,output:20,cacheRead:30,totalTokens:60}}}}};
const telemetry={entryId:1,firstEntryId:1,model:agent.model,contextTokens:48000,contextWindow:200000};

test('usage ledger survives compacted entries and model switch invalidates context',()=>{
 const status=createStatusPresentation({session:{workspaceId:'工作区',sessionId:'bb7a1aa2-d9c2-454e-9907-bbf519a28faf'},theme,...tui});
 status.update({view,telemetry});
 assert.match(status.footer.render(150).join('\n'),/48.0k\/200.0k \(24%\).*Total tokens: 60/);
 for(const width of [12,30,60,100,180]) for(const line of status.footer.render(width)) assert.ok(tui.visibleWidth(line)<=width,line);
 assert.equal(usageTotals(view.docs['pi.usage']).reasoning,null);
 assert.equal(usageTotals({models:{a:{input:10},b:{}}}).input,null);
 const compacted={...view,entries:[{id:10,kind:'pi.compaction'},{id:1}]};
 assert.equal(contextMatches(compacted,telemetry),false);
 status.update({view:compacted});
 assert.match(status.footer.render(150).join('\n'),/Context Unknown.*Total tokens: 60/);
 assert.equal(contextMatches({...view,docs:{...view.docs,'pi.agent':{model:{provider:'fixture',modelId:'b'}}}},telemetry),false);
});

test('compact monitor is session-scoped and distinguishes delivery from agent inbox',()=>{
 const now=Date.now();
 const monitor={monitors:[{session_id:'s',enabled:true,last_state:'running'},{session_id:'other',last_state:'running'}],
 host_worker_health:{last_successful_poll:new Date(now).toISOString(),last_error:null},supervisor_health:{state:'running'}};
 const state={monitor,sessionId:'s',now};
 assert.equal(activityStatus(state).text,'Monitor ✓ · ⚙1');
 const pending={...monitor,pending_deliveries:[{session_id:'s'},{session_id:'other'}]};
 assert.equal(activityStatus({...state,monitor:pending}).text,'Monitor ✓ · ⚙1 · ↑1');
 assert.equal(activityStatus({...state,monitor:pending}).color,'muted');
 assert.equal(activityStatus({...state,view:{docs:{'pi.inbox':{items:[{mode:'followUp',content:'A compute monitor event requires attention.'}]}}}}).text,'Monitor ✓ · ⚙1');
 assert.equal(activityStatus({...state,sessionId:'absent'}).text,'Monitor ✓ · ⚙0');
 assert.equal(activityStatus({...state,monitor:{...monitor,monitors:[{session_id:'s',last_state:'succeeded'}]}}).text,'Monitor ✓ · ⚙0');
 assert.equal(activityStatus({...state,now:now+31000}).text,'Monitor ! · ⚙1');
 assert.equal(activityStatus({...state,monitorError:'offline',monitorErrorSince:now}).text,'Monitor … · ⚙1');
 assert.equal(activityStatus({...state,monitorError:'offline',monitorErrorSince:now-30000}).text,'Monitor × · ⚙1');
 for (const last_state of ['running','queued','held','pending','submitted']) {
   assert.equal(activityStatus({...state,monitor:{...monitor,monitors:[{session_id:'s',last_state,enabled:false}]}}).text,`Monitor ! · ⚙${last_state === 'running' ? 1 : 0}`);
 }
 assert.equal(activityStatus({...state,monitor:{...monitor,host_worker_health:null}}).text,'Monitor … · ⚙1');
 assert.equal(activityStatus({...state,monitor:{...monitor,supervisor_health:null}}).text,'Monitor … · ⚙1');
 assert.equal(activityStatus({...state,monitor:{...monitor,host_worker_health:{...monitor.host_worker_health,last_error:'poll failed'}}}).text,'Monitor × · ⚙1');
 assert.equal(activityStatus({...state,monitor:{...monitor,supervisor_health:{state:'stopped'}}}).text,'Monitor × · ⚙1');
 assert.equal(activityStatus({...state,monitor:{...pending,pending_deliveries:[{session_id:'s',error:'wake failed'}]}}).text,'Monitor × · ⚙1 · ↑1');
 assert.equal(activityStatus({...state,monitor:{...monitor,monitors:[]},telemetry:{research:{running_jobs:['job']}}}).text,'Monitor ! · ⚙0');
 assert.equal(activityStatus({...state,monitor:undefined,telemetry:{research:{running_jobs:['job']}}}).text,'Monitor … · ⚙—');
});

test('monitor colors only the symbol, fits narrow terminals and explains details',()=>{
 const now=Date.now();
 const colors=[];
 const status=createStatusPresentation({session:{workspaceId:'w',sessionId:'s'},monochrome:false,theme:{fg:(color,text)=>{colors.push([color,text]);return text;}},...tui});
 status.update({monitor:{monitors:[{session_id:'s',last_state:'running',enabled:false}],pending_deliveries:[{session_id:'s'}],
 host_worker_health:{last_successful_poll:new Date(now).toISOString()},supervisor_health:{state:'running'}}});
 assert.equal(status.activity.render(80).join(''),' Monitor ! · ⚙1 · ↑1');
 assert.deepEqual(colors,[['muted','Monitor '],['warning','!'],['muted',' · ⚙1 · ↑1']]);
 for (const width of [0,1,2,8,12,20,80]) for (const line of status.activity.render(width)) assert.ok(tui.visibleWidth(line)<=width);
 assert.match(status.monitorDetails(),/1 active job monitor\(s\) paused/);
 assert.match(status.monitorDetails(),/Running: 1 · Queued: 0\nPending delivery: 1/);
 assert.doesNotMatch(status.monitorDetails(),/worker.*\{|poll_interval_ms/);
 status.update({monitor:undefined,telemetry:null});
 assert.deepEqual(status.activity.render(80),[' Monitor … · ⚙—']);
 const plain=createStatusPresentation({session:{sessionId:'s'},monochrome:true,theme:{fg(){throw new Error('monochrome must not color activity');}},...tui});
 plain.update({monitor:{monitors:[{session_id:'s',last_state:'running'}]}});
 assert.deepEqual(plain.activity.render(80),[' Monitor … · ⚙1']);
});

test('document pages resize without overflowing or losing their logical anchor',()=>{
 let rows=24;
 const doc=createDocumentView({title:'System prompt',body:Array.from({length:70},(_,i)=>`line-${i} 内容 `.repeat(3)).join('\n'),
 theme,command:'sys-prompt',wrapText:tui.wrapTextWithAnsi,truncateToWidth:tui.truncateToWidth,visibleWidth:tui.visibleWidth,rows:()=>rows});
 const first=doc.render(80).join('\n');assert.match(first,/line-0/);
 doc.handleInput('\x1b[C');const second=doc.render(80).join('\n');assert.doesNotMatch(second,/line-0 /);
 const anchor=/line-\d+/.exec(second)[0];rows=30;
 const resized=doc.render(50);assert.ok(resized.some(line=>line.includes(anchor)));
 assert.ok(resized.length<=rows-5);
 for(const line of resized) assert.ok(tui.visibleWidth(line)<=50);
 doc.handleInput('\x1b[H');assert.match(doc.render(80).join('\n'),/line-0/);
});

test('documents clamp at the last full page and short panels never scroll',()=>{
 const make = body => createDocumentView({...tui,wrapText:tui.wrapTextWithAnsi,command:'monitor',title:'Monitor',body,mode:'panel',monochrome:true});
 const doc=make(Array.from({length:40},(_,i)=>`row ${i}`).join('\n'));
 doc.setViewport(12);
 const first=doc.render(80);
 for(let i=0;i<100;i++) { doc.handleInput('\x1b[B'); assert.equal(doc.render(80).length,first.length); }
 const end=doc.render(80);
 assert.match(end[1],/32–40\/40/);
 assert.match(end[2],/row 31/);
 assert.match(end.at(-2),/row 39/);
 doc.handleInput('\x1b[H'); doc.render(80); doc.handleInput('\x1b[F');
 assert.deepEqual(doc.render(80),end);
 for(const key of ['\x1b[B','\x1b[C','\x1b[6~',' ']) { doc.handleInput(key); assert.deepEqual(doc.render(80),end); }
 const short=make('Running: 2\nPending delivery: 1');short.setViewport(12);
 const unchanged=short.render(80);
 assert.doesNotMatch(unchanged.join('\n'),/Scroll|Page|Home\/End|\d+–\d+/);
 for(const key of ['\x1b[B','\x1b[F','\x1b[C']) { short.handleInput(key); assert.deepEqual(short.render(80),unchanged); }
});

test('live documents retain their position and reading pages fill the assigned viewport',()=>{
 let body=Array.from({length:40},(_,i)=>`row ${i}`).join('\n');
 const doc=createDocumentView({...tui,wrapText:tui.wrapTextWithAnsi,command:'monitor',title:'Monitor',body:()=>body,monochrome:true});
 doc.setViewport(12);doc.render(80);doc.handleInput('\x1b[C');
 const anchor=doc.render(80)[2];
 body=body.replace('row 39','updated');doc.invalidate();
 assert.equal(doc.render(80)[2],anchor);
 doc.setViewport(15);assert.equal(doc.render(80)[2],anchor);
 body='Only one line';doc.setViewport(20,true);
 const page=doc.render(80);
 assert.equal(page.length,20);assert.match(page[2],/Only one line/);assert.match(page.at(-1),/Esc Back/);
 assert.doesNotMatch(page.at(-1),/Scroll/);
});

test('widening a wrapped line retains the same logical line',()=>{
 const doc=createDocumentView({...tui,wrapText:tui.wrapTextWithAnsi,command:'research',title:'Research',
   body:Array.from({length:30},(_,i)=>`entry-${i} `+'detail '.repeat(12)).join('\n'),monochrome:true});
 doc.setViewport(10);doc.render(24);
 for(let i=0;i<8;i++) doc.handleInput('\x1b[B');
 doc.render(24);
 assert.match(doc.render(120)[2],/entry-1 /);
});

test('usage and monitor details stay separate with unknown counters and session scope',()=>{
 const status=createStatusPresentation({session:{workspaceId:'w',sessionId:'s'},theme,...tui});
 status.update({view,telemetry,monitor:{monitors:[{session_id:'s',last_state:'queued'},{session_id:'other',last_state:'running'}],
 pending_deliveries:[{session_id:'s'}],host_worker_health:{last_successful_poll:new Date().toISOString()},supervisor_health:{state:'running'}}});
 assert.match(status.activity.render(80).join(''),/Monitor ✓ · ⚙0 · ↑1/);
 const usage=status.usageDetails();
 assert.match(usage,/Total tokens: 60/);assert.match(usage,/Reasoning: —/);assert.match(usage,/Context: 48,000 \/ 200,000/);
 assert.doesNotMatch(usage,/Monitor|Pending|provider-reported|compaction-aware|Tool usage|do not add/);
 assert.match(status.monitorDetails(),/Running: 0 · Queued: 1/);
 assert.doesNotMatch(status.monitorDetails(),/tokens|Context/);
 status.update({monitor:{monitors:[],pending_deliveries:[],host_worker_health:{last_error:'offline'}}});
 assert.match(status.monitorDetails(),/Shared monitor worker: offline/);
});

test('idle monitor keeps its row through startup, disconnects and completed jobs',()=>{
 const status=createStatusPresentation({session:{sessionId:'s'},theme,...tui,monochrome:true});
 assert.deepEqual(status.activity.render(80),[' Monitor … · ⚙—']);
 status.update({monitor:{monitors:[],pending_deliveries:[],host_worker_health:{last_successful_poll:new Date().toISOString()},supervisor_health:{state:'running'}}});
 assert.deepEqual(status.activity.render(80),[' Monitor ✓ · ⚙0']);
 status.update({monitorError:'offline'});
 assert.deepEqual(status.activity.render(80),[' Monitor … · ⚙0']);
 status.update({monitorError:null,monitor:{monitors:[{session_id:'s',last_state:'succeeded'}],pending_deliveries:[{session_id:'s'}],
   host_worker_health:{last_successful_poll:new Date().toISOString()},supervisor_health:{state:'running'}}});
 assert.deepEqual(status.activity.render(80),[' Monitor ✓ · ⚙0 · ↑1']);
});

test('monitor subscription refreshes on reconnect and cleans up its connection',async()=>{
 const peers=[];let updates=0,errors=0;
 const connect=async()=>{const p=new EventEmitter();p.request=async()=>({});p.close=()=>{p.closed=true;p.emit('close')};peers.push(p);return p;};
 const dispose=subscribeMonitor({connect,workspaceId:'w',onChange:()=>updates++,onError:()=>errors++,retryMs:5});
 try{
 await new Promise(r=>setTimeout(r,10));assert.equal(updates,1);
 peers[0].emit('notification',{method:'monitor/event',params:{workspace_id:'other'}});assert.equal(updates,1);
 peers[0].emit('notification',{method:'monitor/event',params:{workspace_id:'w'}});assert.equal(updates,2);
 peers[0].close();await new Promise(r=>setTimeout(r,15));assert.equal(errors,1);assert.equal(peers.length,2);assert.equal(updates,3);
 }finally{dispose();}
 assert.ok(peers.at(-1).closed);
});

test('command panels distinguish current and focus, fit small terminals, and support monochrome',()=>{
 let rows=24, selected, cancelled=false;
 const items=Array.from({length:30},(_,i)=>({value:`id-${i}`,label:`模型 ${i}`,description:'e\u0301 中文 👩‍🔬 '+ 'long-id-'.repeat(20)}));
 for(const monochrome of [true,false]) {
  rows=24;
  const presentation=createCommandPresentation({...tui,monochrome,rows:()=>rows});
  const panel=presentation.selection({command:'model',title:'Select model',items,selectedValue:'id-0',onSelect:value=>{selected=value},onCancel:()=>{cancelled=true}});
  panel.render(80); panel.handleInput('\x1b[B'); panel.invalidate();
  let rendered=panel.render(80).join('\n');
  assert.match(rendered,/\[current\] 模型 0/); assert.match(rendered,/› 模型 1/);
  assert.equal(rendered.includes('\x1b[48;2;122;162;247m'),!monochrome);
  for(const [width,height] of [[80,24],[120,30],[32,12],[20,10]]) {
   rows=height;
   for(const component of [panel,presentation.feedback({command:'reload',kind:'error',message:'错误 '+ 'detail '.repeat(200)}),
    createDocumentView({...tui,wrapText:tui.wrapTextWithAnsi,command:'research summary',title:'Research',body:items.map(i=>i.description).join('\n'),monochrome,rows:()=>rows})]) {
    const lines=component.render(width);
    assert.ok(lines.length<=height-5,`${width}x${height}: ${lines.length}`);
    if (lines.length > 1) assert.match(lines.at(-1),/Esc/);
    else assert.doesNotMatch(lines[0], /Esc|\x1b\[48;/);
    for(const line of lines) assert.ok(tui.visibleWidth(line)<=width);
    if(monochrome) assert.doesNotMatch(lines.join('\n'),/\x1b\[/);
   }
  }
  panel.handleInput('\r'); assert.equal(selected,'id-1');
  panel.handleInput('\x1b'); assert.equal(cancelled,true);
 }
});
