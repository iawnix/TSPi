import { readFileSync } from "node:fs";
import { packagePath } from "./resources.mjs";

const manifest = JSON.parse(readFileSync(packagePath("package.json"), "utf8"));
const pi = JSON.parse(readFileSync(packagePath("config/pi-source.json"), "utf8"));

/** Describes the process serving the connection, independent of client metadata. */
export const hostIdentity = Object.freeze({
  product: Object.freeze({ name: manifest.name, version: manifest.version }),
  runtime: Object.freeze({ node: process.versions.node, pi: Object.freeze({
    version: pi.tag.replace(/^v/u, ""), commit: pi.commit, protocol_version: pi.protocolVersion,
  }) }),
});
