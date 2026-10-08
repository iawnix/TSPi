import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {resolvePreparedJob} from '../../../apps/app-server/prepared-job.mjs';

test('prepared requests retain identity/environment/metadata and reject mutation',async()=>{
 const root=await mkdtemp(join(tmpdir(),'prepared-job-'));
 try {
  const job={request_id:'stable',work_id:'local-one',command:['true'],environment:{THREADS:'1'},metadata:{python_binding:{prefix:'/configured'},queue:'test'}};
  const bytes=JSON.stringify(job); await writeFile(join(root,'request.json'),bytes);
  const params={request_file:'request.json',request_sha256:createHash('sha256').update(bytes).digest('hex'),node_id:'node_a'};
  assert.deepEqual(await resolvePreparedJob(params,root),{...job,node_id:'node_a',root});
  await assert.rejects(()=>resolvePreparedJob({...params,command:['false']},root),/cannot override/);
  await writeFile(join(root,'request.json'),JSON.stringify({...job,command:['false']}));
  await assert.rejects(()=>resolvePreparedJob(params,root),/digest mismatch/);
 } finally {await rm(root,{recursive:true,force:true});}
});

test('prepared refs use the workspace resolver without allowing request overrides',async()=>{
 const calls=[];
 const bridge={async execute_command(command,params){calls.push({command,params});return {request_id:'frozen',work_id:'one',command:['true'],inputs:[],node_id:params.node_id};}};
 const params={prepared_ref:'p1',node_id:'node_a'};
 assert.deepEqual(await resolvePreparedJob(params,'/workspace',bridge),{request_id:'frozen',work_id:'one',command:['true'],inputs:[],node_id:'node_a',root:'/workspace'});
 assert.deepEqual(calls,[{command:'job.resolve_prepared',params}]);
 await assert.rejects(()=>resolvePreparedJob({...params,request_id:'replace'},'/workspace',bridge),/cannot override/);
 await assert.rejects(()=>resolvePreparedJob(params,'/workspace'),/authoritative/);
});
