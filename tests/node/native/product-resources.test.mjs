import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, writeFile, symlink, rm } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
import { TEST_ROOT } from "./test-environment.mjs";
import { loadProductSkills } from "../../../apps/agent/resources/skills.mjs";
import { createSystemPromptManifest } from "../../../apps/agent/pi/prompt.mjs";

async function fixture(t) {
  const root = await mkdtemp(join(TEST_ROOT, "r-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(join(root, "skills", "demo"), { recursive: true });
  await mkdir(join(root, "prompts")); await mkdir(join(root, "config"));
  const files = {
    "skills/demo/SKILL.md": "---\nname: demo\ndescription: Test a managed resource.\n---\nRead references relative to this directory.\n",
    "skills/demo/example.txt": "resource\n",
    "prompts/coragent.md": "Product principles.\n",
  };
  for (const [name, content] of Object.entries(files)) await writeFile(join(root, name), content);
  await writeFile(join(root, "package.json"), JSON.stringify({ pi: { skills: ["./skills"] } }));
  const inventory = { schema_version: "coragent-resources/1", files: Object.fromEntries(Object.entries(files)
    .map(([name, content]) => [name, `sha256:${createHash("sha256").update(content).digest("hex")}`])) };
  await writeFile(join(root, "config/resources.json"), JSON.stringify(inventory));
  return root;
}

test("native Pi discovers managed Skills without mandatory product skill names", async t => {
  const root = await fixture(t);
  const loaded = await loadProductSkills({ packageRoot: root });
  assert.deepEqual(loaded.skills.map(skill => skill.name), ["demo"]);
  assert.equal(loaded.skills[0].filePath, join(root, "skills/demo/SKILL.md"));
  const prompt = createSystemPromptManifest({ native: { source: "product", text: "principles" },
    skills: { source: root, items: loaded.skills } });
  assert.match(prompt.effective, /<available_skills>/);
  assert.ok(prompt.effective.includes(join(root, "skills/demo/SKILL.md")));
  assert.doesNotMatch(prompt.effective, /skill:demo|orchestration/);
});

test("managed Skill modifications and unlisted resources fail integrity validation", async t => {
  const root = await fixture(t);
  await writeFile(join(root, "skills/demo/example.txt"), "changed");
  await assert.rejects(loadProductSkills({ packageRoot: root }), /digest mismatch/);
  await writeFile(join(root, "skills/demo/example.txt"), "resource\n");
  await writeFile(join(root, "skills/demo/unlisted.py"), "print('not allowed')");
  await assert.rejects(loadProductSkills({ packageRoot: root }), /digest mismatch/);
});

test("managed Skill roots cannot escape or redirect through symlinks", async t => {
  const root = await fixture(t);
  await symlink(join(root, "prompts/coragent.md"), join(root, "skills/demo/linked.md"));
  await assert.rejects(loadProductSkills({ packageRoot: root }), /symlink/);
  await rm(join(root, "skills/demo/linked.md"));
  await writeFile(join(root, "package.json"), JSON.stringify({ pi: { skills: ["../outside"] } }));
  await assert.rejects(loadProductSkills({ packageRoot: root }), /escapes package/);
});

test("Skills remain independent of scientific execution catalog discovery", async t => {
  const root = await fixture(t);
  const manifest = JSON.parse(await readFile(join(root, "package.json")));
  manifest.coragent = { execution: ["domains/missing/execution.json"] };
  await writeFile(join(root, "package.json"), JSON.stringify(manifest));
  assert.equal((await loadProductSkills({ packageRoot: root })).skills.length, 1);
});

test("the permanent system prompt is required even if omitted from the inventory", async t => {
  const root = await fixture(t);
  await rm(join(root, "prompts/coragent.md"));
  const path = join(root, "config/resources.json");
  const inventory = JSON.parse(await readFile(path));
  delete inventory.files["prompts/coragent.md"];
  await writeFile(path, JSON.stringify(inventory));
  await assert.rejects(loadProductSkills({ packageRoot: root }), /system prompt is missing/);
});
