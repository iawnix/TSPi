import assert from 'node:assert/strict';
import test from 'node:test';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {pinnedPiSource} from './test-environment.mjs';
import {slashCompletions} from '../../../apps/agent/tools/commands.mjs';

const source=pinnedPiSource();
const {Editor,CombinedAutocompleteProvider,visibleWidth}=await import(pathToFileURL(join(source,'packages/tui/src/index.ts')));
const themes=await import(pathToFileURL(join(source,'packages/coding-agent/src/modes/interactive/theme/theme.ts')));
const settle=async()=>{for(let i=0;i<4;i++) await new Promise(resolve=>setImmediate(resolve));};

function editor() {
  themes.initTheme('dark');
  const input=new Editor({terminal:{rows:24,columns:100},requestRender(){}},themes.getEditorTheme());
  input.setAutocompleteProvider(new CombinedAutocompleteProvider([
    {name:'monitor',description:'Inspect tasks',getArgumentCompletions:prefix=>slashCompletions('monitor',prefix)},
    {name:'model',description:'Select a model'},
    {name:'usage',description:'Inspect usage'},
  ],process.cwd()));
  return input;
}

test('slash completion keeps a stable viewport and Tab and clicks never submit',async()=>{
  const input=editor(); let submitted=0;input.onSubmit=()=>submitted++;
  input.handleInput('/');await settle();
  const all=input.renderAutocomplete(80,8);
  input.handleInput('mo');await settle();
  assert.equal(input.renderAutocomplete(80,8).length,all.length);
  input.handleInput('\t');
  assert.match(input.getText(),/^\/(monitor|model) /);
  assert.equal(submitted,0);
  input.setText('');input.handleInput('/us');await settle();
  input.handleAutocompleteMouse({type:'press',button:'left',x:1,y:0,width:80,height:8});
  input.handleAutocompleteMouse({type:'click',button:'left',x:1,y:0,width:80,height:8});
  assert.equal(input.getText(),'/usage ');assert.equal(submitted,0);
});

test('Tab reopens argument completion after dismissal and preserves task identity',async()=>{
  const input=editor();let submitted=0;input.onSubmit=()=>submitted++;
  input.handleInput('/monitor task ');await settle();
  assert.ok(input.isShowingAutocomplete());
  input.handleInput('\x1b');
  assert.equal(input.getText(),'/monitor task ');
  assert.deepEqual(input.renderAutocomplete(80,8),[]);
  input.handleInput('\t');await settle();
  assert.ok(input.isShowingAutocomplete());
  input.handleInput('\t');
  assert.equal(input.getText(),'/monitor task pause ');assert.equal(submitted,0);
  input.setText('');input.handleInput('/monitor task cancel TaskABC --k');await settle();
  input.handleInput('\t');
  assert.equal(input.getText(),'/monitor task cancel TaskABC --keep-jobs ');
  assert.equal(submitted,0);
});

test('completion respects terminal widths and bracketed paste does not execute',async()=>{
  const input=editor();let submitted=0;input.onSubmit=()=>submitted++;
  input.handleInput('/');await settle();
  for(const [width,height] of [[100,8],[32,5],[20,4]]) {
    const lines=input.renderAutocomplete(width,height);
    assert.ok(lines.length<=height);
    for(const line of lines) assert.ok(visibleWidth(line)<=width);
  }
  input.setText('');input.handleInput('\x1b[200~/monitor task pause\nThis is pasted text\x1b[201~');
  assert.equal(submitted,0);
  assert.match(input.getText(),/This is pasted text/);
});
