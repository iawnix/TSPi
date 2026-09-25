import assert from "node:assert/strict";
import { access, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn } from "node:child_process";
import test from "node:test";

test("Pi App Server rejects the retired backend before starting any runtime", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-native-backend-"));
  const child = spawn(process.execPath, [
    "apps/app-server/pi-app-server.mjs", "server",
    "--workspace", join(root, "workspace"),
    "--directory", join(root, "runtime"),
    "--server-id", "11111111-1111-4111-8111-111111111111",
    "--state-root", join(root, "state"),
  ], {
    cwd: process.cwd(),
    env: { ...process.env, TSPI_HOST_BACKEND: "ordinary", TSPI_INSTALL_ROOT: root },
    stdio: ["ignore", "ignore", "pipe"],
  });
  let stderr = "";
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk) => { stderr += chunk; });
  const result = await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code, signal) => resolve({ code, signal }));
  });
  assert.deepEqual(result, { code: 1, signal: null });
  assert.match(stderr, /Native Pi Harness is the only supported backend/);
  await rm(root, { recursive: true, force: true });
});

test("Native Pi App Server is the only packaged server entrypoint", async () => {
  await access("apps/app-server/pi-app-server.mjs");
  await assert.rejects(access("apps/app-server/pi-experimental-app-server.mjs"));
  await assert.rejects(access("apps/app-server/tspi-terminal-runtime.mjs"));
  await assert.rejects(access("apps/app-server/tspi-history.mjs"));
});
