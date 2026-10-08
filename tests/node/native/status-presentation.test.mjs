import assert from 'node:assert/strict';
import test from 'node:test';
import {EventEmitter} from 'node:events';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {pinnedPiSource} from './test-environment.mjs';
import {activityStatus,contextMatches,createStatusPresentation,usageTotals} from '../../../apps/app-server/tspi-status-presentation.mjs';
import {createDocumentView} from '../../../apps/app-server/tspi-document-view.mjs';
import {createCommandPresentation} from '../../../apps/app-server/tspi-command-panel.mjs';
import {subscribeMonitor} from '../../../apps/app-server/tspi-monitor-subscription.mjs';
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

test('monitor waiting, outbox and inbox are distinct, scoped and health-aware',()=>{
 const now=Date.now();
 const monitor={monitors:[{session_id:'s',enabled:true,last_state:'running'},{session_id:'other',last_state:'running'}],
 host_worker_health:{last_successful_poll:new Date(now).toISOString(),last_error:null},supervisor_health:{state:'running'}};
 const state={view:{docs:{}},monitor,sessionId:'s',now};
 assert.equal(activityStatus(state).text,'Waiting for jobs · 1 running · Monitor active');
 assert.match(activityStatus({...state,monitor:{...monitor,pending_deliveries:[{session_id:'s'}]}}).text,/Wake pending delivery/);
 assert.match(activityStatus({...state,view:{docs:{'pi.inbox':{items:[{mode:'followUp',content:'A compute monitor event requires attention.\nevent_id=event_one'}]}}}}).text,/Wake queued/);
 assert.doesNotMatch(activityStatus({...state,view:{docs:{'pi.inbox':{items:[{mode:'followUp',content:'ordinary user input'}]}}}}).text,/Wake queued/);
 assert.equal(activityStatus({...state,sessionId:'absent'}).text,'');
 assert.match(activityStatus({...state,now:now+31000}).text,/stale/);
 assert.match(activityStatus({...state,monitorError:'offline'}).text,/unavailable/);
 assert.match(activityStatus({...state,monitor:{...monitor,monitors:[{session_id:'s',last_state:'running',enabled:false}]}}).text,/disabled/);
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
    assert.match(lines.at(-1),/Esc/);
    for(const line of lines) assert.equal(tui.visibleWidth(line),width);
    if(monochrome) assert.doesNotMatch(lines.join('\n'),/\x1b\[/);
   }
  }
  panel.handleInput('\r'); assert.equal(selected,'id-1');
  panel.handleInput('\x1b'); assert.equal(cancelled,true);
 }
});
