import assert from 'node:assert/strict';
import { mkdir, mkdtemp, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import test from 'node:test';
import { TEST_ROOT, TEST_SOCKET_ROOT, pinnedPiSource } from './test-environment.mjs';

test('upstream Pi server exposes its native services before any product session', { timeout: 30_000 }, async () => {
  const root=await mkdtemp(join(TEST_ROOT,'upstream-'));
  const directory=TEST_SOCKET_ROOT;
  process.env.PI_AGENT_DIR=join(root,'agent');
  process.env.PI_CODING_AGENT_DIR=process.env.PI_AGENT_DIR;
  process.env.PI_EXPERIMENTAL='1';
  process.env.RESEARCH_AGENT_PI_DIAGNOSTIC_FILE=join(root,'pi-diagnostics.log');
  await mkdir(process.env.PI_AGENT_DIR);
  const fromSource=(name)=>import(pathToFileURL(join(pinnedPiSource(),name)).href);
  const { startForegroundServer }=await fromSource('packages/coding-agent/src/experimental/server.ts');
  const { openClientRuntime, activateBuiltinClientServices }=await fromSource('packages/coding-agent/src/experimental/client-runtime.ts');
  let server;
  let client;
  let phase='start';
  try {
    server=await startForegroundServer({directory,sessionDir:join(root,'sessions'),pluginPackages:[]});
    phase='connect';
    client=await openClientRuntime({command:'client',connect:{transport:'unix',serverId:server.serverId,path:server.socketPath}});
    phase='services';
    const services=await activateBuiltinClientServices(client.servers[0]);
    assert.ok(services.directory);
    assert.ok(services.management);
  } catch (error) {
    await writeFile(join(root,'phase.json'),JSON.stringify({phase,class:error.constructor.name}));
    throw error;
  } finally {
    await client?.dispose();
    await server?.close();
  }
});
