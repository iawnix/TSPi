import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { cp, mkdtemp, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execute = promisify(execFile);
const pi = process.env.TS_PI_TEST_EXECUTABLE
  || fileURLToPath(import.meta.resolve("@earendil-works/pi-coding-agent"));

test("installed terminal and model catalog load without checkout dependencies or credentials", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-installed-node-"));
  await mkdir(join(root, "scripts"));
  await mkdir(join(root, "agent-profile"));
  await cp(resolve("scripts/pi-loader.mjs"), join(root, "scripts/pi-loader.mjs"));
  await cp(resolve("src/terminal"), join(root, "src/terminal"), { recursive: true });
  await cp(resolve("src/host"), join(root, "src/host"), { recursive: true });
  await cp(resolve("extensions/ts-phone-bridge/runtime.mjs"), join(root, "runtime.mjs"));
  const args = ["--import", join(root, "scripts/pi-loader.mjs")];
  const options = { cwd: root, timeout: 20_000,
    env: { PATH: process.env.PATH, PI_OFFLINE: "1", TS_PI_EXECUTABLE: pi,
      PI_CODING_AGENT_DIR: join(root, "agent-profile") } };
  const check = await execute(process.execPath, [...args, "--input-type=module", "-e", `
    import * as ui from "@earendil-works/pi-tui";
    import { TerminalView } from "./src/terminal/view.mjs";
    const Renderer = ui.TuiMainScreen ?? ui.TUI;
    if (typeof Renderer !== "function" || typeof TerminalView !== "function") throw new Error("missing renderer");
    new Renderer({ columns: 80, rows: 24 }, true);
    console.log("renderer ready");
  `], options);
  assert.match(check.stdout, /renderer ready/);
  await assert.rejects(execute(process.execPath, [...args, join(root, "src/terminal/index.mjs"),
    "--install-root", root], options), (error) => {
    assert.equal(error.code, 1);
    assert.match(error.stderr, /thin terminal requires a TTY/);
    assert.doesNotMatch(error.stderr, /MODULE_NOT_FOUND|does not provide an export/);
    return true;
  });
  const catalog = await execute(process.execPath, [...args, join(root, "runtime.mjs"), "--catalog"], options);
  assert.deepEqual(JSON.parse(catalog.stdout), { schemaVersion: "ts-phone-models/1", models: [] });
});
