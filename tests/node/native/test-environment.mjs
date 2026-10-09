import { existsSync } from "node:fs";

function requiredPath(name) {
  const path = process.env[name];
  if (!path || !existsSync(path)) throw new Error(`${name} must be supplied by tools/test/runner.py`);
  return path;
}

export const TEST_ROOT = requiredPath("RESEARCH_AGENT_TEST_ROOT");
export function pinnedPiSource() { return requiredPath("RESEARCH_AGENT_TEST_PI_RUNTIME_ROOT"); }
export function managedPython() { return requiredPath("RESEARCH_AGENT_PYTHON"); }

export const TEST_SOCKET_ROOT = requiredPath("RESEARCH_AGENT_TEST_SOCKET_ROOT");

export async function assertInstalledRuntime(packageRoot) {
  const installRoot = process.env.RESEARCH_AGENT_TEST_INSTALLED_ROOT;
  if (!installRoot) return;
  const assert = (await import("node:assert/strict")).default;
  const { realpath } = await import("node:fs/promises");
  const { join, relative, sep, dirname } = await import("node:path");
  const { execFile } = await import("node:child_process");
  const { promisify } = await import("node:util");
  const inside = (root, path) => {
    const child = relative(root, path);
    return child !== ".." && !child.startsWith(`..${sep}`) && !child.startsWith(sep);
  };
  const installation = await realpath(installRoot);
  const product = await realpath(packageRoot);
  const pi = await realpath(pinnedPiSource());
  assert.ok(inside(installation, product), "product code must come from the installed release");
  assert.ok(inside(installation, pi), "Pi code must come from the installed runtime");
  assert.equal(await realpath(join(product, "node_modules")), await realpath(join(pi, "node_modules")));
  assert.equal(process.env.PYTHONPATH, undefined, "installed acceptance must not import source Python");
  assert.equal(await realpath(process.env.RESEARCH_AGENT_PACKAGE_ROOT), product);
  const modules = ["research_agent", "research_agent.application", "research_agent.research", "research_agent.jobs", "research_agent.artifacts"];
  const program = `import importlib,json,sys; print(json.dumps({"prefix":sys.prefix,"origins":[importlib.import_module(name).__file__ for name in ${JSON.stringify(modules)}]}))`;
  const { stdout } = await promisify(execFile)(managedPython(), ["-I", "-c", program], { cwd: TEST_ROOT });
  const python = JSON.parse(stdout);
  assert.equal(await realpath(python.prefix), await realpath(dirname(dirname(managedPython()))));
  for (const origin of python.origins) assert.ok(inside(await realpath(python.prefix), await realpath(origin)), "business modules must come from the installed wheel");
}

export async function retainPiDiagnostics(source, destination) {
  const { readdir, lstat, mkdir, copyFile } = await import("node:fs/promises");
  const { join, dirname } = await import("node:path");
  for (const entry of await readdir(source, { recursive: true })) {
    const path = join(source, entry);
    if (!(await lstat(path)).isFile()) continue;
    const target = join(destination, entry);
    await mkdir(dirname(target), { recursive: true });
    await copyFile(path, target);
  }
}
