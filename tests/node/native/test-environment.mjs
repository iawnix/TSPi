import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

// Keep persistent installations separate from short-lived, writable fixtures.
export const TEST_ROOT = process.env.TSPI_TEST_ROOT || "/tmp/tspi-test-root";

export function pinnedPiSource() {
  if (process.env.TSPI_PI_SOURCE) return process.env.TSPI_PI_SOURCE;
  try {
    const pin = JSON.parse(readFileSync(join(process.cwd(), "config", "pi-source.json"), "utf8"));
    if (typeof pin.commit === "string" && pin.commit) {
      return join(process.env.TSPI_TEST_ENV_ROOT || "/home/iaw/debug/tspi-test-env", ".pi", "runtime-cache", "pi", pin.commit);
    }
  } catch {
    // The native runner reports a missing prepared Pi source separately.
  }
  return undefined;
}

export function managedPython() {
  if (process.env.TS_AGENT_PYTHON) return process.env.TS_AGENT_PYTHON;
  const envRoot = process.env.TSPI_TEST_ENV_ROOT || "/home/iaw/debug/tspi-test-env";
  try {
    const manifest = JSON.parse(readFileSync(join(envRoot, "runtime", "env.json"), "utf8"));
    if (typeof manifest.python_executable === "string" && existsSync(manifest.python_executable)) {
      return manifest.python_executable;
    }
    const candidates = readdirSync(join(envRoot, "kernels"), { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => join(envRoot, "kernels", entry.name, "bin", "python"))
      .filter((candidate) => existsSync(candidate))
      .sort();
    if (candidates.length > 0) return candidates[candidates.length - 1];
  } catch {
    // Let the subprocess report a missing managed environment clearly.
  }
  return "python3";
}
