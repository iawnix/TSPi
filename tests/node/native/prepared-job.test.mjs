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
  assert.deepEqual(resolvePreparedJob(params,root),{...job,node_id:'node_a',root});
  assert.throws(()=>resolvePreparedJob({...params,command:['false']},root),/cannot override/);
  await writeFile(join(root,'request.json'),JSON.stringify({...job,command:['false']}));
  assert.throws(()=>resolvePreparedJob(params,root),/digest mismatch/);
 } finally {await rm(root,{recursive:true,force:true});}
});
