import { createHash } from "node:crypto";
import { lstat, readFile, realpath } from "node:fs/promises";
import { dirname, isAbsolute, join, resolve, sep } from "node:path";

export async function phoneComponent(root, suite) {
  const bundled = join(suite, "phone");
  try {
    if ((await lstat(bundled)).isDirectory()) return bundled;
  } catch (error) { if (error.code !== "ENOENT") throw error; }

  const releases = join(resolve(root), ".pi", "ts-phone", "releases");
  const selected = await realpath(join(root, ".pi", "ts-phone", "current"));
  if (dirname(selected) !== releases) throw new Error("TS Phone release is outside this installation.");
  const metadata = join(selected, "installation.json");
  const info = await lstat(metadata);
  if (!info.isFile() || info.size > 1024 * 1024 || (info.mode & 0o022)) {
    throw new Error("TS Phone installation record must be a regular file writable only by its owner.");
  }
  const record = JSON.parse(await readFile(metadata, "utf8"));
  if (record.schema_version !== "tspi-phone-install/1" || !/^[a-f0-9]{40}$/.test(record.commit)
    || selected !== join(releases, record.commit)) {
    throw new Error("TS Phone installation record does not match the selected release.");
  }
  const protocols = JSON.parse(await readFile(join(suite, "agent", "contracts", "ts-phone", "versions.json"), "utf8"));
  if (Object.entries(protocols).some(([name, value]) => record.protocols?.[name] !== value)) {
    throw new Error("TS Phone protocols do not match this TSPi release.");
  }
  const required = ["package.json", "services/server/dist/index.js", "services/server/dist/cli.js"];
  if (!record.files || required.some((name) => !Object.hasOwn(record.files, name))) {
    throw new Error("TS Phone installation record is missing runtime files.");
  }
  for (const [name, expected] of Object.entries(record.files)) {
    const path = resolve(selected, name);
    if (isAbsolute(name) || !path.startsWith(selected + sep) || await realpath(path) !== path
      || !(await lstat(path)).isFile()) {
      throw new Error(`Invalid TS Phone runtime file: ${name}`);
    }
    const actual = createHash("sha256").update(await readFile(path)).digest("hex");
    if (actual !== expected) throw new Error(`TS Phone runtime file failed verification: ${name}`);
  }
  return selected;
}
