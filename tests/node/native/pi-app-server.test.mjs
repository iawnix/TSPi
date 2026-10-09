import assert from "node:assert/strict";
import { access, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn } from "node:child_process";
import test from "node:test";

test("Native Pi App Server is the only packaged server entrypoint", async () => {
  await access("apps/app-server/pi-app-server.mjs");
  await assert.rejects(access("apps/app-server/pi-experimental-app-server.mjs"));
  await assert.rejects(access("apps/app-server/tspi-terminal-runtime.mjs"));
  await assert.rejects(access("apps/app-server/tspi-history.mjs"));
});
