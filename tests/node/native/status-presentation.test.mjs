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
import {stripVTControlCharacters} from 'node:util';
const tui = await import(pathToFileURL(join(pinnedPiSource(),'packages/tui/src/index.ts')));
const nativeTheme = await import(pathToFileURL(join(pinnedPiSource(),'packages/coding-agent/src/modes/interactive/theme/theme.ts')));
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

const task = {user_task_id:'t1',title:'Research',objective:'Compare paths',state:'active',reason:null,criteria:[{id:'c1',description:'Final report'}],wait:null,progress:null,continuation:{reservation:null},updated_at:new Date().toISOString()};
const snapshot = (changes={}) => ({session_id:'s',workspace_id:'w',task, jobs:{items:[{job_id:'j1',state:'running'}],counts:{running:1,queued:0},next_cursor:null},execution:{state:'running'},task_controller:{error:null,last_checked_at:new Date().toISOString(),checking:false,check_interval_ms:1000},automatic_continuation_enabled:true,updated_at:new Date().toISOString(),...changes});

test('task status distinguishes execution, waits and control state, with stale data taking priority',()=>{
 const monitor=snapshot();
 const state={monitor,sessionId:'s'};
 assert.match(activityStatus(state).text,/Researching · 1 jobs running/);
 assert.match(activityStatus({...state,monitor:snapshot({task:{...task,state:'waiting',wait:{job_ids:['j1'],mode:'all'}}})}).text,/Waiting for compute.*Continues when ready/);
 assert.match(activityStatus({...state,monitor:snapshot({task:{...task,state:'paused'}})}).text,/Paused/);
 assert.match(activityStatus({...state,monitor:snapshot({task:{...task,state:'blocked',reason:'Budget exhausted'}})}).text,/Responding · Task blocked/);
 assert.match(activityStatus({...state,monitor:snapshot({execution:{state:'idle'},task:{...task,state:'blocked',reason:'Budget exhausted'}})}).text,/Needs attention · 1 jobs running/);
 assert.match(activityStatus({...state,monitor:snapshot({execution:{state:'idle'}})}).text,/Checking continuation/);
 assert.match(activityStatus({...state,monitor:snapshot({execution:{state:'idle'},task:{...task,continuation:{reservation:'r1'}}})}).text,/Preparing continuation/);
 assert.match(activityStatus({...state,monitor:snapshot({execution:{state:'idle'},automatic_continuation_enabled:false})}).text,/Automatic continuation off/);
 assert.match(activityStatus({...state,monitor:snapshot({task:null})}).text,/No current task/);
 assert.match(activityStatus({...state,monitorError:'offline'}).text,/Connection lost/);
 assert.match(activityStatus({...state,monitor:snapshot({task_controller:{error:{code:'task_reconcile_failed'},last_checked_at:new Date().toISOString(),check_interval_ms:1000}})}).text,/Continuation error: task_reconcile_failed/);
 assert.match(activityStatus({...state,monitor:snapshot({task_controller:{error:null,last_checked_at:null,checking:true,check_interval_ms:1000}})}).text,/Checking recovery/);
 assert.match(activityStatus({...state,monitor:snapshot({task_controller:{error:null,last_checked_at:new Date(Date.now()-31000).toISOString(),check_interval_ms:1000}})}).text,/Continuation check overdue/);
 assert.match(activityStatus({...state,now:Date.now()+31000}).text,/Status is stale/);
 assert.match(activityStatus({...state,sessionId:'other'}).text,/Checking status · — jobs running/);
 assert.match(activityStatus({...state,monitor:snapshot({jobs:{items:[],next_cursor:null}})}).text,/— jobs running/);
});

test('blocked task details stay in Monitor while the activity line remains short and tracks recovery',()=>{
 const status=createStatusPresentation({session:{workspaceId:'w',sessionId:'s'},theme,...tui});
 const reason='输入构造失败，需要修正结构。'.repeat(40)+'\n等待进一步指令。';
 status.update({monitor:snapshot({execution:{state:'idle'},task:{...task,state:'blocked',reason}})});
 const line=status.activity.render(80).join('');
 assert.match(line,/Needs attention · 1 jobs running/);
 assert.doesNotMatch(line,/输入构造|等待进一步/);
 assert.ok(tui.visibleWidth(line)<=80);
 assert.ok(status.monitorDetails().includes(reason));
 status.update({monitor:snapshot({task:{...task,state:'blocked',reason}})});
 assert.match(status.activity.render(80).join(''),/Responding · Task blocked · 1 jobs running/);
 status.update({monitor:snapshot()});
 assert.match(status.activity.render(80).join(''),/Researching · 1 jobs running/);
 assert.doesNotMatch(status.monitorDetails(),/输入构造|Task blocked|Needs attention/);
});

test('monitor symbol colors and narrow width do not hide state in the normal layout',()=>{
 const colors=[];
 const status=createStatusPresentation({session:{workspaceId:'w',sessionId:'s'},monochrome:false,theme:{fg:(color,text)=>{colors.push([color,text]);return text;}},...tui});
 status.update({monitor:snapshot({task:{...task,state:'paused'}})});
 assert.match(status.activity.render(80).join(''),/Monitor Ⅱ · Paused · 1 jobs running/);
 assert.deepEqual(colors.map(([color])=>color),['muted','muted','muted']);
 for(const width of [0,1,2,8,12,20,80]) for(const line of status.activity.render(width)) assert.ok(tui.visibleWidth(line)<=width);
 assert.match(status.monitorDetails(),/Task: Research · Paused/);
 assert.match(status.monitorDetails(),/Goal: Compare paths/);
 assert.doesNotMatch(status.monitorDetails(),/control_epoch|producer|generation/);
 const plain=createStatusPresentation({session:{sessionId:'s'},monochrome:true,theme:{fg(){throw new Error('monochrome must not color activity');}},...tui});
 assert.match(plain.activity.render(80).join(''),/Checking status · — jobs running/);
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

test('usage and monitor details stay separate while disconnection overrides cached progress',()=>{
 const status=createStatusPresentation({session:{workspaceId:'w',sessionId:'s'},theme,...tui});
 status.update({view,telemetry,monitor:snapshot()});
 assert.match(status.usageDetails(),/Total tokens: 60/);
 assert.match(status.usageDetails(),/Reasoning: —/);
 assert.doesNotMatch(status.usageDetails(),/Monitor|Task:/);
 assert.doesNotMatch(status.monitorDetails(),/tokens|Context/);
 status.update({monitorError:'offline'});
 assert.match(status.activity.render(80).join(''),/Connection lost/);
 assert.match(status.monitorDetails(),/Connection: offline/);
 status.update({monitorError:null,monitor:snapshot({task:{...task,state:'completed'}})});
 assert.match(status.activity.render(80).join(''),/Completed/);
});

test('monitor subscription refreshes on reconnect and cleans up its connection',async()=>{
 const peers=[];let updates=0,errors=0;
 const connect=async()=>{const p=new EventEmitter();p.request=async(method,params)=>{assert.equal(method,'monitor/overview');assert.deepEqual(params,{workspace_id:'w',session_id:'s'});return {};};p.close=()=>{p.closed=true;p.emit('close')};peers.push(p);return p;};
 const dispose=subscribeMonitor({connect,workspaceId:'w',sessionId:'s',onChange:()=>updates++,onError:()=>errors++,retryMs:5});
 try{
 await new Promise(r=>setTimeout(r,10));assert.equal(updates,1);
 peers[0].emit('notification',{method:'monitor/event',params:{workspace_id:'other'}});assert.equal(updates,1);
 peers[0].emit('notification',{method:'monitor/event',params:{workspace_id:'w'}});assert.equal(updates,2);
 peers[0].close();await new Promise(r=>setTimeout(r,15));assert.equal(errors,1);assert.equal(peers.length,2);assert.equal(updates,3);
 }finally{dispose();}
 assert.ok(peers.at(-1).closed);
});

test('command panels distinguish current and focus, fit small terminals, and support monochrome',()=>{
 nativeTheme.initTheme('dark');
 let rows=24, selected, cancelled=false;
 const items=Array.from({length:30},(_,i)=>({value:`id-${i}`,label:`模型 ${i}`,description:'e\u0301 中文 👩‍🔬 '+ 'long-id-'.repeat(20)}));
 for(const monochrome of [true,false]) {
  rows=24;
  const presentation=createCommandPresentation({...tui,theme:()=>nativeTheme.theme,monochrome,rows:()=>rows});
  const panel=presentation.selection({command:'model',title:'Select model',items,selectedValue:'id-0',onSelect:value=>{selected=value},onCancel:()=>{cancelled=true}});
  panel.render(80); panel.handleInput('\x1b[B'); panel.invalidate();
  let rendered=panel.render(80).join('\n');
  assert.match(rendered,/\[current\] 模型 0/); assert.match(rendered,/› 模型 1/);
  assert.equal(rendered !== stripVTControlCharacters(rendered), !monochrome);
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

test('theme changes repaint open command surfaces without changing their selection',()=>{
 nativeTheme.initTheme('dark');
 const presentation=createCommandPresentation({...tui,theme:()=>nativeTheme.theme,monochrome:false});
 const panel=presentation.selection({command:'model',title:'Select model',items:[
  {value:'a',label:'Model A'},{value:'b',label:'Model B'},
 ],selectedValue:'a',onSelect(){},onCancel(){}});
 panel.handleInput('\x1b[B');
 const dark=panel.render(80).join('\n');
 nativeTheme.initTheme('light');
 const light=panel.render(80).join('\n');
 assert.notEqual(dark,light);
 assert.equal(stripVTControlCharacters(dark),stripVTControlCharacters(light));
 assert.match(stripVTControlCharacters(light),/› Model B/);
 nativeTheme.initTheme('dark');
});

test('selector clicks retain their pressed item when the viewport recenters',()=>{
 let selected;
 const panel=createCommandPresentation({...tui,monochrome:true}).selection({
  command:'model',title:'Select model',items:Array.from({length:20},(_,i)=>({value:String(i),label:`Model ${i}`})),
  selectedValue:'0',onSelect:value=>{selected=value;},onCancel(){},
 });
 panel.setViewport(12); panel.render(80);
 panel.handleMouse({type:'press',button:'left',y:8});
 panel.render(80);
 panel.handleMouse({type:'click',button:'left',y:8});
 assert.equal(selected,'3');
 panel.handleMouse({type:'wheel',wheelDelta:1});
 assert.match(panel.render(80).join('\n'),/› Model 4/);
 panel.handleMouse({type:'click',button:'left',y:0});
 assert.equal(selected,'3');
});

test('long errors expose complete details while the feedback remains bounded',()=>{
 const body='Missing task ID\nUsage: /monitor task pause <id>\n'+'A useful explanation. '.repeat(30);
 const presentation=createCommandPresentation({...tui,monochrome:true,createDocument:options=>createDocumentView({
  ...tui,wrapText:tui.wrapTextWithAnsi,monochrome:true,...options,
 })});
 const feedback=presentation.feedback({command:'monitor',kind:'error',message:body});
 assert.match(feedback.render(60)[0],/F2 Details/);
 const details=feedback.details(); details.setViewport(40); const rendered=details.render(120).join('\n');
 assert.match(rendered,/Missing task ID/); assert.match(rendered,/Usage: \/monitor task pause/);
 const plain=createStatusPresentation({session:{workspaceId:'w',sessionId:'s'},monochrome:true,theme:{fg(){throw Error('unexpected color');}},...tui});
 assert.doesNotMatch(plain.footer.render(80).join('\n'),/\x1b\[/);
});
