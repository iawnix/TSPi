import { lstat, readFile, readdir, realpath } from "node:fs/promises";
import { join } from "node:path";
import { validate_workspace_manifest } from "../workspace.mjs";
const MONITOR_ID = /^monitor_[a-f0-9]{24}$/u;
const MONITOR_EVENT_ID = /^event_[a-f0-9]{32}$/u;

export function createMonitorEvents({ listWorkspaces, clients, epoch }) {
  const monitorFiles = new Map();
  let monitorSequence = 0, polling = false, closed = false;
  async function scanMonitorFiles({ notify = true } = {}) {
    if (polling || closed) return;
    polling = true;
    try {
      for (const project of await listWorkspaces()) {
        const identity = await monitorWorkspaceIdentity(project);
        if (!identity) continue;
        const root = join(project.root, "operations", "monitors");
        if (!await isPhysicalDirectory(root)) continue;
        let registrations;
        try { registrations = await readdir(root, { withFileTypes: true }); } catch { continue; }
        for (const registration of registrations) {
          if (!registration.isDirectory() || !MONITOR_ID.test(registration.name)) continue;
          const registrationRoot = join(root, registration.name);
          if (!await isPhysicalDirectory(registrationRoot)) continue;
          const registrationPath = join(registrationRoot, "binding.json");
          if (!await isPhysicalFile(registrationPath)) continue;
          let binding;
          try { binding = JSON.parse(await readFile(registrationPath, "utf8")); } catch { continue; }
          if (!validMonitorBinding(binding, registration.name, identity)) continue;
          const eventsRoot = join(registrationRoot, "events");
          if (!await isPhysicalDirectory(eventsRoot)) continue;
          let entries;
          try { entries = await readdir(eventsRoot, { withFileTypes: true }); } catch { continue; }
          for (const entry of entries) {
            if (!entry.isFile() || !entry.name.endsWith(".json")) continue;
            const eventId = entry.name.slice(0, -5);
            if (!MONITOR_EVENT_ID.test(eventId)) continue;
            const path = join(eventsRoot, entry.name);
            const info = await physicalFileInfo(path);
            if (!info) continue;
            const bindingMarker = [identity.route, identity.canonical, binding.job_id,
              binding.job_digest, binding.node_id, binding.node_revision, binding.user_task_id, binding.session_id, binding.wake_policy, binding.notify_policy].map((value) => JSON.stringify(value)).join(":");
            const marker = `${info.dev}:${info.ino}:${info.size}:${info.mtimeMs}:${bindingMarker}`;
            if (monitorFiles.get(path) === marker) continue;
            let event;
            try { event = JSON.parse(await readFile(path, "utf8")); } catch { continue; }
            // A workspace can contain hand-written or stale monitor files.
            // Do not relay them to Phone clients unless the file, registration,
            // and workspace identity all agree.
            if (!validMonitorEvent(event, eventId, registration.name, identity, binding)) {
              continue;
            }
            monitorFiles.set(path, marker);
            if (!notify) continue;
            const params = { workspace_id: project.workspace_id, epoch, sequence: ++monitorSequence, event };
            for (const client of clients) if (client.monitorWorkspaces.has(project.workspace_id)) {
              try { client.peer.notify("monitor/event", params); } catch { client.peer.close(); }
            }
          }
        }
      }
    } finally { polling = false; }
  }

  async function pollMonitors() {
    return scanMonitorFiles();
  }
  return { scanMonitorFiles, pollMonitors, stop() { closed = true; } };
}

async function isPhysicalDirectory(path) {
  try {
    const info = await lstat(path);
    return info.isDirectory() && !info.isSymbolicLink() && await realpath(path) === path;
  } catch {
    return false;
  }
}

async function isPhysicalFile(path) {
  try {
    const info = await lstat(path);
    return info.isFile() && !info.isSymbolicLink() && await realpath(path) === path;
  } catch {
    return false;
  }
}

async function physicalFileInfo(path) {
  try {
    const info = await lstat(path);
    if (!info.isFile() || info.isSymbolicLink() || await realpath(path) !== path) return null;
    return info;
  } catch {
    return null;
  }
}

async function monitorWorkspaceIdentity(project) {
  const manifestPath = join(project.root, "workspace_manifest.json");
  if (!await isPhysicalFile(manifestPath)) return null;
  try {
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    validate_workspace_manifest(manifest, project.root);
    if (manifest.state !== "ready") return null;
    const canonical = manifest.workspace_id;
    return { route: project.workspace_id, canonical };
  } catch {
    return null;
  }
}

function validMonitorBinding(binding, monitorId, identity) {
  return Boolean(binding && typeof binding === "object" && !Array.isArray(binding)
    && binding.schema_version === "coragent-job-monitor/2"
    && binding.monitor_id === monitorId
    && binding.workspace_id === identity.canonical
    && typeof binding.job_id === "string" && /^job_[A-Za-z0-9_.:-]+$/u.test(binding.job_id)
    && validResearchBinding(binding)
    && validTaskBinding(binding)
    && !Object.hasOwn(binding, "intent_id") && !Object.hasOwn(binding, "intent_digest")
    && typeof binding.job_digest === "string" && /^sha256:[0-9a-f]{64}$/u.test(binding.job_digest)
    && (binding.session_id === null || (typeof binding.session_id === "string" && binding.session_id.length > 0))
    && ["none", "next_run"].includes(binding.wake_policy)
    && binding.notify_policy === "none"
    && (binding.enabled === undefined || binding.enabled === true)
    && typeof binding.created_at === "string" && binding.created_at.length > 0);
}

function validMonitorEvent(event, eventId, monitorId, identity, binding) {
  return Boolean(event && typeof event === "object" && !Array.isArray(event)
    && event.schema_version === "coragent-job-monitor-event/2"
    && validResearchBinding(event)
    && validTaskBinding(event)
    && event.node_id === binding.node_id && event.node_revision === binding.node_revision
    && event.user_task_id === binding.user_task_id
    && !Object.hasOwn(event, "intent_id") && !Object.hasOwn(event, "intent_digest")
    && event.event_id === eventId
    && event.monitor_id === monitorId
    && event.workspace_id === identity.canonical
    && event.job_id === binding.job_id
    && event.job_digest === binding.job_digest
    && event.session_id === binding.session_id
    && event.wake_policy === binding.wake_policy
    && event.notify_policy === binding.notify_policy
    && Number.isSafeInteger(event.sequence) && event.sequence > 0
    && typeof event.status_digest === "string" && /^sha256:[0-9a-f]{64}$/u.test(event.status_digest)
    && (typeof event.previous_state === "string" || event.previous_state === null)
    && ["queued", "held", "running", "succeeded", "failed", "timed_out", "cancelled", "unknown"].includes(event.state)
    && (typeof event.program_status === "string" || event.program_status === null)
    && (typeof event.job_id === "string" || event.job_id === null)
    && (Number.isSafeInteger(event.exit_status) || event.exit_status === null)
    && (typeof event.error_class === "string" || event.error_class === null)
    && (typeof event.error === "string" || event.error === null)
    && typeof event.observed_at === "string" && event.observed_at.length > 0
    && event.status && typeof event.status === "object" && !Array.isArray(event.status));
}

function validResearchBinding(value) {
  if (Object.hasOwn(value, "attempt_id")) return false;
  return (value.node_id === null && value.node_revision === null)
    || (typeof value.node_id === "string" && /^node_[A-Za-z0-9_-]+$/u.test(value.node_id)
      && Number.isSafeInteger(value.node_revision) && value.node_revision > 0);
}

function validTaskBinding(value) {
  return value.user_task_id === undefined || value.user_task_id === null
    || (typeof value.user_task_id === "string" && /^task_[A-Za-z0-9_-]+$/u.test(value.user_task_id));
}
