import assert from "node:assert/strict";
import { mkdtemp, mkdir, symlink, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { createPackageSourceReadGuard } from "../../../apps/app-server/pi-harness-policy.mjs";
import { createSkillPathResolver } from "../../../apps/app-server/skill-paths.mjs";

test("registered Skill names resolve without assuming a common directory", () => {
  const resolve = createSkillPathResolver([{ name: "email", filePath: "/package/extensions/email/SKILL.md" }]);
  assert.equal(resolve({ path: "skill:email" }).path, "/package/extensions/email/SKILL.md");
  assert.equal(resolve({ path: "skill:email/references/email_delivery.md" }).path, "/package/extensions/email/references/email_delivery.md");
  assert.throws(() => resolve({ path: "skill:unknown" }), /Unknown registered/);
  assert.throws(() => resolve({ path: "skill:email/../private.py" }), /remain inside/);
});

test("Harness package-source guard blocks private package reads but allows public skills", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-harness-policy-"));
  const packageRoot = join(root, "package");
  const workspace = join(root, "workspace");
  const skillRoot = join(packageRoot, "extensions", "chemical", "skills", "demo");
  await mkdir(skillRoot, { recursive: true });
  await mkdir(join(packageRoot, "src"), { recursive: true });
  await mkdir(workspace, { recursive: true });
  await writeFile(join(skillRoot, "SKILL.md"), "public\n");
  await writeFile(join(packageRoot, "src", "private.mjs"), "private\n");
  const guard = createPackageSourceReadGuard({ packageRoot, cwd: workspace, publicKnowledgeRoots: [skillRoot] });
  try {
    assert.equal(guard({ toolName: "read", args: { path: join(packageRoot, "src", "private.mjs") } }).block !== undefined, true);
    assert.equal(guard({ toolName: "read", args: { path: join(skillRoot, "SKILL.md") } }), undefined);
    const missing = guard({ toolName: "read", args: { path: join(packageRoot, "extensions/other/skills/demo/SKILL.md") } });
    const recovery = JSON.parse(missing.block.reason);
    assert.equal(recovery.code, "skill_resource_not_found");
    assert.deepEqual(recovery.skill_locations, [join(skillRoot, "SKILL.md")]);
    const rejectedJob = guard({ toolName: "job_start", args: { command: ["python", join(packageRoot, "extensions/other/skills/demo/run.py")] } });
    assert.equal(JSON.parse(rejectedJob.block.reason).code, "skill_resource_not_found");
    assert.equal(guard({ toolName: "job_start", args: { command: ["python", "skills/demo/run.py"] } }), undefined);
    assert.equal(guard({ toolName: "job_start", args: { command: ["python", "/remote/python/script.py"] } }), undefined);
    await symlink(join(packageRoot, "src", "private.mjs"), join(skillRoot, "escape.mjs"));
    assert.ok(guard({ toolName: "read", args: { path: join(skillRoot, "escape.mjs") } }).block);
    assert.equal(guard({ toolName: "grep", args: { path: workspace } }), undefined);
    assert.equal(guard({ toolName: "bash", args: { path: join(packageRoot, "src", "private.mjs") } }), undefined);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("Harness package-source guard canonicalizes symlinked private files", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-harness-policy-link-"));
  const packageRoot = join(root, "package");
  const outside = join(root, "outside");
  await mkdir(join(packageRoot, "src"), { recursive: true });
  await mkdir(outside, { recursive: true });
  await writeFile(join(outside, "private.mjs"), "private\n");
  await symlink(outside, join(packageRoot, "src", "linked"));
  const guard = createPackageSourceReadGuard({ packageRoot, cwd: root });
  try {
    // The canonical target is outside the package, so the guard does not
    // claim it; the normal filesystem policy remains responsible for it.
    assert.equal(guard({ toolName: "read", args: { path: join(packageRoot, "src", "linked", "private.mjs") } }), undefined);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
