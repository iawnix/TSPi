import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { loadServerExtensions } from "../../../apps/app-server/server-extension-loader.mjs";
import { filterWorkspaceTools } from "../../../apps/app-server/workspace-mode-tools.mjs";

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), "tspi-server-ext-"));
  await mkdir(join(root, "extensions"), { recursive: true });
  const entry = join(root, "extensions", "example.mjs");
  await writeFile(entry, `export function createServerExtension() { return { tools: [{
    name: "ts_example",
    label: "TS Example",
    description: "A contract fixture.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
    metadata: { authority: "host_read", effect: "read", replay: "safe", phase: "orient" },
    execute() {},
  }] }; }\n`);
  const digest = `sha256:${createHash("sha256").update(await readFile(entry)).digest("hex")}`;
  await writeFile(join(root, "extensions.json"), JSON.stringify({
    schema_version: "tspi-server-extensions/1",
    extensions: [{
      name: "example",
      entry: "extensions/example.mjs",
      scope: "server",
      sha256: digest,
      tools: ["ts_example"],
      permissions: ["workspace.read"],
    }],
  }));
  return root;
}

test("server extension loader verifies and inventories package-owned tools", async () => {
  const root = await fixture();
  try {
    const loaded = await loadServerExtensions({ packageRoot: root, manifestPath: "extensions.json" });
    assert.deepEqual(loaded.tools.map((tool) => tool.name), ["ts_example"]);
    assert.equal(loaded.inventory[0].name, "example");
    assert.equal(loaded.inventory[0].permissions[0], "workspace.read");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("server extension loader rejects tools outside the Harness contract", async () => {
  const root = await fixture();
  try {
    const entry = join(root, "extensions", "example.mjs");
    await writeFile(entry, `export function createServerExtension() { return { tools: [{ name: "ts_example", execute() {} }] }; }\n`);
    const digest = `sha256:${createHash("sha256").update(await readFile(entry)).digest("hex")}`;
    const manifestPath = join(root, "extensions.json");
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    manifest.extensions[0].sha256 = digest;
    await writeFile(manifestPath, JSON.stringify(manifest));
    await assert.rejects(
      loadServerExtensions({ packageRoot: root, manifestPath: "extensions.json" }),
      /has no label/,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("server extension loader rejects an integrity mismatch and unknown selection", async () => {
  const root = await fixture();
  try {
    const manifest = JSON.parse(await readFile(join(root, "extensions.json"), "utf8"));
    manifest.extensions[0].sha256 = "sha256:" + "0".repeat(64);
    await writeFile(join(root, "extensions.json"), JSON.stringify(manifest));
    await assert.rejects(loadServerExtensions({ packageRoot: root, manifestPath: "extensions.json" }), /integrity check failed/);
    manifest.extensions[0].sha256 = `sha256:${createHash("sha256").update(await readFile(join(root, "extensions/example.mjs"))).digest("hex")}`;
    await writeFile(join(root, "extensions.json"), JSON.stringify(manifest));
    await assert.rejects(
      loadServerExtensions({ packageRoot: root, manifestPath: "extensions.json", allowlist: ["missing"] }),
      /not in the manifest/,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("default package server manifest keeps complete core and chemical tool inventory", async () => {
  const loaded = await loadServerExtensions({
    packageRoot: process.cwd(),
    reservedToolNames: ["read", "write", "bash", "system_prompt"],
    requiredToolNames: ["research_read", "compute_environment", "compute_run", "analysis_run"],
  });
  assert.deepEqual(loaded.inventory.map((item) => item.name), ["tspi-core-tools", "tspi-chemical-tools"]);
  const coreInventory = loaded.inventory.find((item) => item.name === "tspi-core-tools");
  assert.ok(coreInventory.permissions.includes("notify.send"));
  assert.ok(!loaded.tools.some((tool) => tool.name === "notify_send"));
  assert.deepEqual(loaded.tools.map((tool) => tool.name), [
    "research_read",
    "research_change",
    "research_checkpoint",
    "research_strategy",
    "research_interpretation",
    "research_checkpoint",
    "compute_environment",
    "compute_catalog",
    "compute_readiness",
    "review_run",
    "compute_run",
    "review_respond",
    "execution_dispatch",
    "artifact_import",
    "artifact_render",
    "report_build",
    "artifact_seed",
    "artifact_compare",
    "analysis_run",
  ]);
  const researchNames = filterWorkspaceTools(loaded.tools, "research").map((tool) => tool.name);
  assert.ok(!researchNames.includes("light_compute"));
  assert.ok(researchNames.includes("compute_run"));
});
