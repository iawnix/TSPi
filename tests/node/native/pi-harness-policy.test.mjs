import assert from "node:assert/strict";
import { mkdtemp, mkdir, symlink, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { createPackageSourceReadGuard } from "../../../apps/app-server/pi-harness-policy.mjs";

test("Harness package-source guard blocks private package reads but allows public skills", async () => {
  const root = await mkdtemp(join(tmpdir(), "tspi-harness-policy-"));
  const packageRoot = join(root, "package");
  const workspace = join(root, "workspace");
  await mkdir(join(packageRoot, "skills", "demo"), { recursive: true });
  await mkdir(join(packageRoot, "src"), { recursive: true });
  await mkdir(workspace, { recursive: true });
  await writeFile(join(packageRoot, "skills", "demo", "SKILL.md"), "public\n");
  await writeFile(join(packageRoot, "src", "private.mjs"), "private\n");
  const guard = createPackageSourceReadGuard({ packageRoot, cwd: workspace });
  try {
    assert.equal(guard({ toolName: "read", args: { path: join(packageRoot, "src", "private.mjs") } }).block !== undefined, true);
    assert.equal(guard({ toolName: "read", args: { path: join(packageRoot, "skills", "demo", "SKILL.md") } }), undefined);
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
