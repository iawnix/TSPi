import { homedir } from "node:os";
import { dirname, isAbsolute, join, parse, resolve, sep } from "node:path";
import { parseArgs } from "node:util";
import { pathToFileURL } from "node:url";
import { hostEnvironment } from "./environment.mjs";

function unitValue(path) {
  if (/[\x00-\x1f\x7f]/.test(path)) throw new Error("Service paths cannot contain control characters.");
  return path.replaceAll("%", "%%");
}

function unitPath(path) {
  return `"${unitValue(path).replaceAll("\\", "\\\\").replaceAll('"', '\\"')}"`;
}

function writablePath(path, root) {
  if (typeof path !== "string" || !isAbsolute(path)) throw new Error("Service write paths must be absolute.");
  const resolved = resolve(path);
  if (resolved === parse(resolved).root || [homedir(), resolve(root)].some((protectedPath) =>
    protectedPath === resolved || protectedPath.startsWith(resolved + sep))) {
    throw new Error("Service write paths cannot cover a home directory or the whole installation.");
  }
  return unitPath("-" + resolved);
}

export function renderService(root, env) {
  const writable = [env.TS_PHONE_STATE_DIR, env.TS_PHONE_WORKSPACES,
    ...[".pi/runtime-cache", ".pi/session-host", ".agents/runtime", ".agents/envs"].map((path) => join(root, path)),
    env.PI_CODING_AGENT_DIR || join(homedir(), ".pi", "agent"),
    ...[env.TS_PHONE_BRIDGE_SOCKET, env.TS_PHONE_BRIDGE_SECRET_FILE].filter(Boolean).map(dirname)];
  // WorkingDirectory is scalar; ExecStart quotes its executable without variable expansion.
  return `[Unit]
Description=TSPi Session Host
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${unitValue(root)}
ExecStart=${unitPath(join(root, "TSPhoneServer"))}
Restart=on-failure
RestartSec=3s
TimeoutStopSec=20s
KillMode=mixed
UMask=0077
RuntimeDirectory=ts-phone
RuntimeDirectoryMode=0700
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
ProtectControlGroups=yes
ProtectKernelModules=yes
ProtectKernelTunables=yes
RestrictSUIDSGID=yes
LockPersonality=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
${[...new Set(writable)].map((path) => `ReadWritePaths=${writablePath(path, root)}`).join("\n")}

[Install]
WantedBy=default.target
`;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const { values } = parseArgs({ options: { "install-root": { type: "string" } } });
  const root = values["install-root"];
  if (!root) throw new Error("Installation root is required.");
  process.stdout.write(renderService(root, await hostEnvironment(root)));
}
