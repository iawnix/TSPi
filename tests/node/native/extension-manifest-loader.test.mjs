import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { discoverInstalledExtensions, readExtensionManifest } from "../../../apps/app-server/extension-manifest-loader.mjs";
import { loadInstalledServerExtensions } from "../../../apps/app-server/server-extension-loader.mjs";

function digest(bytes) {
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), "tspi-extension-"));
  await mkdir(join(root, "skills", "amber"), { recursive: true });
  await mkdir(join(root, "providers"), { recursive: true });
  await writeFile(join(root, "skills", "amber", "SKILL.md"), "---\nname: amber\ndescription: Amber workflow.\n---\nUse Amber.\n");
  await writeFile(join(root, "providers", "amber.json"), JSON.stringify({ capability: "amber.md", version: "1" }));
  const entry = join(root, "providers", "amber.mjs");
  await writeFile(entry, "export function createProvider() {}\n");
  const serverEntry = join(root, "server.mjs");
  await writeFile(serverEntry, `export function createServerExtension() { return { tools: [{
    name: "amber_run",
    label: "Amber tool",
    description: "An installed extension fixture.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
    metadata: { authority: "runtime_read", effect: "read", replay: "safe", phase: "prepare" },
    execute() { return { content: [{ type: "text", text: "ok" }] }; },
  }] }; }\n`);
  const manifest = {
    schema_version: "tspi-extension/1",
    name: "amber-tools",
    version: "1.2.0",
    skills: [{ name: "amber", path: "skills/amber" }],
    providers: [{
      id: "amber.md",
      version: "1",
      kind: "compute",
      descriptor: "providers/amber.json",
      entry: "providers/amber.mjs",
      sha256: digest(await readFile(entry)),
    }],
    server: {
      entry: "server.mjs",
      sha256: digest(await readFile(serverEntry)),
      tools: ["amber_run"],
      permissions: ["workspace.read"],
    },
  };
  const manifestPath = join(root, "manifest.json");
  await writeFile(manifestPath, JSON.stringify(manifest));
  return { root, manifestPath };
}

test("extension discovery inventories Skills and providers without importing provider code", async () => {
  const { root, manifestPath } = await fixture();
  try {
    const discovered = await discoverInstalledExtensions({ manifestPaths: [manifestPath] });
    assert.deepEqual(discovered.manifests, [manifestPath]);
    assert.equal(discovered.extensions[0].name, "amber-tools");
    assert.equal(discovered.extensions[0].skills[0].name, "amber");
    assert.equal(discovered.providers[0].id, "amber.md");
    assert.equal(discovered.providers[0].kind, "compute");
    assert.equal(discovered.providers[0].entry, join(root, "providers", "amber.mjs"));
    assert.equal(discovered.providers[0].descriptor_data.capability, "amber.md");
    assert.match(discovered.providers[0].descriptor_digest, /^sha256:[0-9a-f]{64}$/u);
    assert.equal(discovered.extensions[0].server.tools[0], "amber_run");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("extension discovery fails closed for duplicate providers and escaped paths", async () => {
  const { root, manifestPath } = await fixture();
  try {
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    manifest.skills[0].path = "../outside";
    await writeFile(manifestPath, JSON.stringify(manifest));
    await assert.rejects(readExtensionManifest(manifestPath), /escaped extension root/);

    manifest.skills[0].path = "skills/amber";
    manifest.providers.push(manifest.providers[0]);
    await writeFile(manifestPath, JSON.stringify(manifest));
    await assert.rejects(discoverInstalledExtensions({ manifestPaths: [manifestPath] }), /duplicate installed provider id/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("empty explicit extension configuration leaves the core package unchanged", async () => {
  const discovered = await discoverInstalledExtensions({ manifestPaths: [] });
  assert.deepEqual(discovered.extensions, []);
  assert.deepEqual(discovered.skillRoots, []);
  assert.deepEqual(discovered.providers, []);
});

test("package-owned manifest is optional and discovered when present", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-extension-package-"));
  try {
    await mkdir(join(root, "extensions"), { recursive: true });
    await writeFile(join(root, "extensions", "manifest.json"), JSON.stringify({
      schema_version: "tspi-extension/1",
      name: "package-addon",
      version: "1.0.0",
      skills: [],
      providers: [],
    }));
    const discovered = await discoverInstalledExtensions({ packageRoot: root });
    assert.equal(discovered.extensions[0].name, "package-addon");
    const explicitlyEmpty = await discoverInstalledExtensions({ packageRoot: root, manifestPaths: [] });
    assert.deepEqual(explicitlyEmpty.extensions, []);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("provider descriptors are validated before inventory is exposed", async () => {
  const { root, manifestPath } = await fixture();
  try {
    await writeFile(join(root, "providers", "amber.json"), "not-json");
    await assert.rejects(readExtensionManifest(manifestPath), /descriptor is not valid JSON/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("installed server entries require an explicit allowlist and pass the Harness tool contract", async () => {
  const { root, manifestPath } = await fixture();
  try {
    const discovered = await discoverInstalledExtensions({ manifestPaths: [manifestPath] });
    const skipped = await loadInstalledServerExtensions({ extensions: discovered.extensions });
    assert.deepEqual(skipped.tools, []);
    const loaded = await loadInstalledServerExtensions({
      extensions: discovered.extensions,
      allowlist: ["amber-tools"],
      reservedToolNames: ["read"],
    });
    assert.deepEqual(loaded.tools.map((tool) => tool.name), ["amber_run"]);
    assert.deepEqual(loaded.tools[0].metadata, {
      authority: "runtime_read",
      effect: "read",
      replay: "safe",
      phase: "prepare",
    });
    assert.equal(loaded.inventory[0].permissions[0], "workspace.read");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("installed server entries are rechecked for digest and tool inventory before import", async () => {
  const { root, manifestPath } = await fixture();
  try {
    const discovered = await discoverInstalledExtensions({ manifestPaths: [manifestPath] });
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    manifest.server.tools = ["ts_other"];
    await writeFile(manifestPath, JSON.stringify(manifest));
    const changed = await discoverInstalledExtensions({ manifestPaths: [manifestPath] });
    await assert.rejects(
      loadInstalledServerExtensions({ extensions: changed.extensions, allowlist: ["amber-tools"] }),
      /tool inventory does not match/,
    );
    await writeFile(join(root, "server.mjs"), "export function createServerExtension() { return { tools: [] }; }\n");
    await assert.rejects(
      loadInstalledServerExtensions({ extensions: discovered.extensions, allowlist: ["amber-tools"] }),
      /integrity check failed/,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("extension manifests reject fields outside the versioned contract", async () => {
  const { root, manifestPath } = await fixture();
  try {
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    manifest.untrusted_entry = "providers/evil.mjs";
    await writeFile(manifestPath, JSON.stringify(manifest));
    await assert.rejects(readExtensionManifest(manifestPath), /unknown field/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Skill-only extension rejects a changed executable resource", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-skill-resources-"));
  try {
    const script = join(root, "run.py");
    await writeFile(script, "print('verified')\n");
    await writeFile(join(root, "SKILL.md"), "---\nname: sample\ndescription: Run a sample task\n---\n");
    const hash = (text) => "sha256:" + createHash("sha256").update(text).digest("hex");
    const index = JSON.stringify({ schema_version: "skill-resources/1", base: "extension", files: { "run.py": hash(await readFile(script)) } });
    await writeFile(join(root, "resources.json"), index);
    const manifest = join(root, "manifest.json");
    await writeFile(manifest, JSON.stringify({ schema_version: "tspi-extension/1", name: "sample", version: "1.0.0",
      skills: [{ name: "sample", path: ".", resources_sha256: hash(index) }] }));
    const loaded = await discoverInstalledExtensions({ manifestPaths: [manifest] });
    assert.equal(loaded.skills?.length || loaded.skillRoots.length, 1);
    await writeFile(script, "print('changed')\n");
    await assert.rejects(discoverInstalledExtensions({ manifestPaths: [manifest] }), /integrity/i);
  } finally { await rm(root, { recursive: true, force: true }); }
});
