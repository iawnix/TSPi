import { constants } from "node:fs";
import { open } from "node:fs/promises";
import { homedir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";
import { parseEnv } from "node:util";

function configurationError(code, message) {
  return Object.assign(new Error(message), { code });
}

export async function privateFile(path) {
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const info = await file.stat();
    if (!info.isFile() || info.size > 64 * 1024 || info.nlink !== 1 || (info.mode & 0o077)
      || (process.getuid && info.uid !== process.getuid())) {
      throw configurationError("unsafe_config", "Host configuration must be a user-owned private regular file (0600).");
    }
    return await file.readFile("utf8");
  } finally { await file.close(); }
}

export async function hostEnvironment(installRoot, env = process.env) {
  if (!isAbsolute(installRoot)) throw configurationError("invalid_config", "Installation root must be absolute.");
  let config = {};
  try {
    config = parseEnv(await privateFile(join(installRoot, ".pi", "ts-phone", "server.env")));
  } catch (error) { if (error.code !== "ENOENT") throw error; }
  const defaults = {
    TS_PHONE_HOST: "127.0.0.1", TS_PHONE_PORT: "22113",
    TS_PHONE_TSPI: join(installRoot, "TSPi"),
    TS_PHONE_WORKSPACES: join(installRoot, "workspaces"),
    TS_PHONE_STATE_DIR: join(env.XDG_STATE_HOME || join(homedir(), ".local", "state"), "ts-phone"),
  };
  const explicit = Object.fromEntries(Object.entries(env).filter(([, value]) => value !== undefined));
  const selected = { ...defaults, ...config, ...explicit };
  for (const name of ["TS_PHONE_TSPI", "TS_PHONE_WORKSPACES", "TS_PHONE_STATE_DIR", "PI_CODING_AGENT_DIR",
    "TS_PHONE_BRIDGE_SOCKET", "TS_PHONE_BRIDGE_SECRET_FILE"]) {
    if (selected[name] !== undefined && !isAbsolute(selected[name])) {
      throw configurationError("invalid_config", `${name} must be absolute.`);
    }
  }
  for (const name of ["TS_PHONE_TSPI", "TS_PHONE_WORKSPACES"]) {
    if (resolve(selected[name]) !== resolve(defaults[name])) {
      throw configurationError("installation_mismatch", `${name} does not belong to this TSPi installation.`);
    }
  }
  return selected;
}
