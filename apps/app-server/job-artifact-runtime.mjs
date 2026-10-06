import { spawn } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";

const digest = (value) => `sha256:${createHash("sha256").update(value).digest("hex")}`;
const rootOf = (params, fallback) => resolve(params.root || fallback);

export function createJobRuntime({ workspaceRoot } = {}) {
  const jobs = new Map();
  async function job_start(params) {
    const root = rootOf(params, workspaceRoot); const cwd = resolve(root, params.cwd || ".");
    const id = `job_${randomUUID().replaceAll("-", "")}`; await mkdir(join(cwd, ".tspi", "jobs", id), { recursive: true });
    const dir = join(cwd, ".tspi", "jobs", id); const stdoutPath = join(dir, "stdout.log"); const stderrPath = join(dir, "stderr.log");
    const child = spawn(params.command[0], params.command.slice(1), { cwd, env: { ...process.env, ...(params.environment || {}) }, detached: true, stdio: ["ignore", "pipe", "pipe"] });
    const stdout = []; const stderr = []; child.stdout.on("data", (x) => stdout.push(x)); child.stderr.on("data", (x) => stderr.push(x));
    const receipt = { job_id: id, command: params.command, cwd, pid: child.pid, submitted_at: new Date().toISOString(), outputs: params.outputs || [], node_id: params.nodeId || null };
    await writeFile(join(dir, "receipt.json"), JSON.stringify(receipt, null, 2)); jobs.set(id, { child, receipt, stdout, stderr });
    child.on("close", async (code, signal) => { await writeFile(stdoutPath, Buffer.concat(stdout)); await writeFile(stderrPath, Buffer.concat(stderr)); receipt.finished_at = new Date().toISOString(); receipt.exit_code = code; receipt.signal = signal; receipt.state = code === 0 ? "succeeded" : "failed"; await writeFile(join(dir, "receipt.json"), JSON.stringify(receipt, null, 2)); });
    return receipt;
  }
  async function load(id, params) { const root = rootOf(params, workspaceRoot); const files = await readFile(join(root, ".tspi", "jobs", id, "receipt.json"), "utf8"); return JSON.parse(files); }
  async function job_status(params) { const r = await load(params.jobId, params); const live = jobs.get(r.job_id); if (live && live.child.exitCode === null) return { ...r, state: "running" }; return { ...r, state: r.state || "unknown" }; }
  async function job_collect(params) { const r = await load(params.jobId, params); const rows = []; for (const item of r.outputs || []) { const path = resolve(r.cwd, item.path); try { const data = await readFile(path); rows.push({ ...item, path: item.path, exists: true, size: data.length, sha256: digest(data) }); } catch { rows.push({ ...item, path: item.path, exists: false }); } } return { ...r, outputs: rows }; }
  async function job_cancel(params) { const live = jobs.get(params.jobId); if (live && live.child.exitCode === null) { live.child.kill("SIGTERM"); return { job_id: params.jobId, state: "cancelled" }; } return job_status(params); }
  async function job_probe() { return { platform: "local", available: true }; }
  async function job_reconcile(params) { return job_status(params); }
  return { job_start, job_status, job_collect, job_cancel, job_probe, job_reconcile };
}

export function createArtifactRuntime({ workspaceRoot } = {}) {
  async function put(params, content) { const root = rootOf(params, workspaceRoot); const id = params.artifactId || `art_${randomUUID().replaceAll("-", "")}`; const path = join(root, ".tspi", "artifacts", id, "payload"); await mkdir(dirname(path), { recursive: true }); await writeFile(path, content); return { artifact_id: id, location: path, size_bytes: content.length, sha256: digest(content), media_type: params.mediaType || "application/octet-stream" }; }
  return {
    async artifact_register(params) { const content = await readFile(resolve(rootOf(params, workspaceRoot), params.path)); return put({ ...params, artifactId: params.artifactId }, content); },
    async artifact_create(params) { return put(params, Buffer.from(params.content)); },
    async artifact_read(params) { const root = rootOf(params, workspaceRoot); const path = join(root, ".tspi", "artifacts", params.artifactId, "payload"); const data = await readFile(path); const offset = params.offset || 0; return { artifact_id: params.artifactId, content: data.subarray(offset, offset + (params.limit || data.length)).toString("utf8"), size_bytes: data.length, sha256: digest(data) }; },
    async artifact_derive(params) { return put(params, Buffer.from(JSON.stringify({ operation: params.operation, inputs: params.inputArtifactIds, parameters: params.parameters || {} }))); },
    async artifact_link(params) { return { artifact_id: params.artifactId, subject_id: params.subjectId, relation: params.relation || "evidence" }; },
  };
}
