import { execFile } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { promisify } from "node:util";

const execute = promisify(execFile);
const quote = (value) => `'${String(value).replaceAll("'", "'\\''")}'`;

export function terminalName(workspace) {
  return `tspi-${createHash("sha256").update(workspace).digest("hex").slice(0, 24)}`;
}

export function terminalSocket(socketPath) {
  return join(dirname(socketPath), "terminal.sock");
}

export function resolveTmux(installRoot) {
  const managed = join(installRoot, ".agents/envs/tspi/bin/tmux");
  return process.env.TSPI_TMUX || (existsSync(managed) ? managed : "tmux");
}

export function createSessionLifecycle({ installRoot, packageRoot, stateRoot, socketPath, tmuxBinary }) {
  return async ({ action, workspace_id, workspace_root, session_id, pi_args = [], columns = 100, rows = 30 }) => {
    const tmux = tmuxBinary || resolveTmux(installRoot);
    const socket = terminalSocket(socketPath);
    const terminal = terminalName(workspace_root);
    try {
      await execute(tmux, ["-V"], { timeout: 5000 });
    } catch {
      throw Object.assign(new Error("Persistent Pi sessions require tmux. Install tmux or set TSPI_TMUX; foreground TSPi remains available."), { code: "tmux_unavailable" });
    }
    const existing = await execute(tmux, ["-S", socket, "has-session", "-t", `=${terminal}`], { timeout: 5000 }).then(() => true, () => false);
    if (existing) {
      throw Object.assign(new Error("This workspace already has a Pi terminal. Attach it, or use Pi's /resume or /new command."), { code: "workspace_busy" });
    }
    const nativeSelection = pi_args.some((arg) => ["--session", "--resume", "-r"].includes(arg.split("=")[0]));
    const sessionId = session_id || (nativeSelection ? undefined : randomUUID());
    mkdirSync(dirname(socket), { recursive: true, mode: 0o700 });
    const argv = [
      "env", `TSPI_TERMINAL_SESSION=${terminal}`, `TSPI_HOST_SOCKET=${socketPath}`,
      `TSPI_BRIDGE_TOKEN_FILE=${join(stateRoot, "bridge-token")}`,
      process.env.TS_AGENT_PYTHON || "python3", join(packageRoot, "scripts/tspi_launcher.py"),
      "--install-root", installRoot, "--", "--workspace", workspace_id,
      "--native-runtime", ...(sessionId ? ["--session-id", sessionId] : []), ...pi_args,
    ];
    const width = Math.max(40, Math.min(500, Number(columns) || 100));
    const height = Math.max(10, Math.min(200, Number(rows) || 30));
    await execute(tmux, ["-S", socket, "-f", "/dev/null", "new-session", "-d", "-s", terminal,
      "-c", workspace_root, "-x", String(width), "-y", String(height), `exec ${argv.map(quote).join(" ")}`,
    ], { timeout: 10000 });
    for (const [name, value] of [["status", "off"], ["extended-keys", "on"], ["focus-events", "on"], ["allow-passthrough", "on"]]) {
      await execute(tmux, ["-S", socket, "set-option", "-g", name, value], { timeout: 5000 }).catch(() => {});
    }
    return { session_id: sessionId, terminal_id: terminal, action };
  };
}
