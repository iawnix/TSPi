import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";

for (const arguments_ of [["-r"], ["--resume"], ["--", "--resume"]]) {
  test(`terminal client rejects unsupported startup resume flag: ${arguments_.join(" ")}`, () => {
    const result = spawnSync(process.execPath, ["apps/app-server/tspi-terminal-client.mjs", ...arguments_], {
      cwd: process.cwd(),
      encoding: "utf8",
    });

    assert.equal(result.status, 1);
    assert.equal(result.stdout, "");
    assert.match(result.stderr, /startup -r\/--resume is not supported/);
    assert.match(result.stderr, /use \/resume inside the terminal/);
    assert.doesNotMatch(result.stderr, /Missing terminal option --socket-path/);
  });
}
