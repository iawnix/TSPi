#!/usr/bin/env python3
"""Synchronize TSPi's read-only TS Phone protocol consumer fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
VENDORED_ROOT = ROOT / "contracts" / "ts-phone"
CONSUMER_PATH = ROOT / "extensions" / "ts-phone-bridge" / "protocol.ts"
MANIFEST_PATH = VENDORED_ROOT / "manifest.json"
CANONICAL_FILES = (
    "bridge.schema.json",
    "events.schema.json",
    "openapi.yaml",
    "versions.json",
)
CANONICAL_REPOSITORY = "https://github.com/iawnix/ts-phone"
CANONICAL_DIRECTORY = "packages/protocol"


class ContractSyncError(RuntimeError):
    """The protocol fixture or generated consumer is inconsistent."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sync or verify the vendored TS Phone protocol consumer fixture."
    )
    parser.add_argument(
        "--source",
        type=Path,
        help="Canonical ts-phone packages/protocol directory. Required for --write; optional for --check.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="Copy canonical files and regenerate the consumer.")
    mode.add_argument("--check", action="store_true", help="Verify the checked-in fixture (default).")
    args = parser.parse_args(argv)

    try:
        if args.write:
            if args.source is None:
                raise ContractSyncError("--write requires --source")
            write_fixture(args.source.expanduser().resolve())
        else:
            check_fixture(args.source.expanduser().resolve() if args.source else None)
    except (ContractSyncError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"TS Phone protocol check failed: {exc}", file=sys.stderr)
        return 1
    action = "synchronized" if args.write else "verified"
    print(f"TS Phone protocol fixture {action}: {protocol_summary(VENDORED_ROOT)}")
    return 0


def write_fixture(source: Path) -> None:
    source_files = read_protocol_set(source)
    validate_protocol_set(source_files)
    VENDORED_ROOT.mkdir(parents=True, exist_ok=True)
    for name, payload in source_files.items():
        target = VENDORED_ROOT / name
        target.write_bytes(payload)
        target.chmod(0o644)
    consumer = render_typescript_consumer(source_files)
    CONSUMER_PATH.write_text(consumer, encoding="utf-8")
    CONSUMER_PATH.chmod(0o644)
    manifest = build_manifest(source_files, consumer.encode("utf-8"))
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    MANIFEST_PATH.chmod(0o644)


def check_fixture(source: Path | None = None) -> None:
    fixture_files = read_protocol_set(VENDORED_ROOT)
    validate_protocol_set(fixture_files)
    if source is not None:
        source_files = read_protocol_set(source)
        validate_protocol_set(source_files)
        for name in CANONICAL_FILES:
            if fixture_files[name] != source_files[name]:
                raise ContractSyncError(f"vendored {name} differs from the canonical ts-phone source")

    expected_consumer = render_typescript_consumer(fixture_files).encode("utf-8")
    if not CONSUMER_PATH.is_file() or CONSUMER_PATH.read_bytes() != expected_consumer:
        raise ContractSyncError(
            "generated extensions/ts-phone-bridge/protocol.ts is stale; run this tool with --write"
        )
    expected_manifest = build_manifest(fixture_files, expected_consumer)
    if not MANIFEST_PATH.is_file():
        raise ContractSyncError("contracts/ts-phone/manifest.json is missing")
    actual_manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if actual_manifest != expected_manifest:
        raise ContractSyncError("contracts/ts-phone/manifest.json is stale")


def read_protocol_set(root: Path) -> dict[str, bytes]:
    if not root.is_dir():
        raise ContractSyncError(f"protocol directory does not exist: {root}")
    result: dict[str, bytes] = {}
    for name in CANONICAL_FILES:
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ContractSyncError(f"canonical protocol file is missing or unsafe: {path}")
        result[name] = path.read_bytes()
    return result


def validate_protocol_set(files: dict[str, bytes]) -> None:
    versions = load_json(files["versions.json"], "versions.json")
    bridge = load_json(files["bridge.schema.json"], "bridge.schema.json")
    events = load_json(files["events.schema.json"], "events.schema.json")
    expected_keys = {"schema_version", "api", "events", "bridge"}
    if set(versions) != expected_keys or versions.get("schema_version") != "ts-phone-protocol-set/1":
        raise ContractSyncError("versions.json is not a supported TS Phone protocol set")
    if nested(bridge, "properties", "protocolVersion", "const") != versions["bridge"]:
        raise ContractSyncError("bridge schema version does not match versions.json")
    if nested(events, "properties", "protocolVersion", "const") != versions["events"]:
        raise ContractSyncError("events schema version does not match versions.json")
    protocol_major(str(versions["api"]), "ts-phone-api")


def render_typescript_consumer(files: dict[str, bytes]) -> str:
    bridge = load_json(files["bridge.schema.json"], "bridge.schema.json")
    properties = nested(bridge, "properties")
    version = nested(properties, "protocolVersion", "const")
    # Required command fields are the TSPi adapter's input policy. All field
    # types and value constraints come from the canonical wire schema.
    identity = ["workspaceId", "sessionId", "instanceEpoch", "sessionGeneration"]
    records = {
        "bridge.registered": ("BridgeRegisteredRecord", identity[:-1], []),
        "command.prompt": ("BridgePromptCommand", [*identity, "requestId", "clientMessageId", "message"], ["clientKind"]),
        "command.abort": ("BridgeAbortCommand", [*identity, "requestId", "agentRunId"], []),
        "approval.respond": ("BridgeApprovalResponse", [*identity, "requestId", "approvalId", "approved"], []),
    }
    canonical_types = nested(properties, "type", "enum")
    definitions = []
    for kind, (name, required, optional) in records.items():
        if kind not in canonical_types:
            raise ContractSyncError(f"Bridge record is absent from the wire schema: {kind}")
        fields = ['  protocolVersion: typeof BRIDGE_PROTOCOL_VERSION;', f'  type: {json.dumps(kind)};']
        for field in [*required, *optional]:
            marker = "?" if field in optional else ""
            fields.append(f"  {field}{marker}: {typescript_type(properties[field])};")
        definitions.append(f"export interface {name} {{\n" + "\n".join(fields) + "\n}")
    selected = sorted({field for _, required, optional in records.values() for field in [*required, *optional]})
    validators = {}
    supported = {"type", "enum", "pattern", "minLength", "maxLength", "minimum"}
    for field in selected:
        schema = properties[field]
        unsupported = set(schema) - supported - {"description"}
        if unsupported:
            raise ContractSyncError(f"Bridge field {field} has unsupported constraints: {sorted(unsupported)}")
        validators[field] = {key: value for key, value in schema.items() if key in supported}
    policy = {kind: {"required": required, "optional": optional} for kind, (_, required, optional) in records.items()}
    header = (
        "// Generated by tools/contracts/sync_ts_phone.py from contracts/ts-phone.\n"
        "// Canonical field constraints belong to ts-phone; command field selection belongs to TSPi.\n\n"
        f"export const BRIDGE_PROTOCOL_VERSION = {json.dumps(version)} as const;\n\n"
        + "\n\n".join(definitions)
        + "\n\nexport type BridgeServerRecord = "
        + " | ".join(name for name, _, _ in records.values()) + ";\n\n"
    )
    data = (
        "const RECORDS: Record<string, { required: string[]; optional: string[] }> = "
        + json.dumps(policy, indent=2) + ";\n"
        + "const FIELDS: Record<string, Field> = " + json.dumps(validators, indent=2) + ";\n"
    )
    runtime = """
interface Field {
  type?: string;
  enum?: unknown[];
  pattern?: string;
  minLength?: number;
  maxLength?: number;
  minimum?: number;
}

export function parseBridgeServerRecord(value: unknown): BridgeServerRecord {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Bridge record must be an object");
  const record = value as Record<string, unknown>;
  if (record.protocolVersion !== BRIDGE_PROTOCOL_VERSION) throw new Error("Unsupported TS Phone bridge protocol");
  const type = record.type;
  if (typeof type !== "string" || !Object.hasOwn(RECORDS, type)) {
    throw new Error("Unsupported TS Phone bridge record: " + String(type));
  }
  const policy = RECORDS[type];
  const parsed: Record<string, unknown> = { protocolVersion: BRIDGE_PROTOCOL_VERSION, type };
  for (const name of [...policy.required, ...policy.optional]) {
    if (record[name] === undefined && policy.optional.includes(name)) continue;
    validateField(record[name], name, FIELDS[name]);
    parsed[name] = record[name];
  }
  // Missing clientKind and explicit phone have identical adapter semantics.
  if (type === "command.prompt" && parsed.clientKind === "phone") delete parsed.clientKind;
  return parsed as unknown as BridgeServerRecord;
}

function validateField(value: unknown, name: string, field: Field): void {
  if (field.enum && !field.enum.includes(value)) throw new Error(name + " is invalid");
  if (field.type === "string") {
    if (typeof value !== "string"
      || (field.minLength !== undefined && [...value].length < field.minLength)
      || (field.maxLength !== undefined && [...value].length > field.maxLength)
      || (field.pattern !== undefined && !new RegExp(field.pattern).test(value))) {
      throw new Error(name + " is invalid");
    }
  } else if (field.type === "integer") {
    if (!Number.isSafeInteger(value) || (field.minimum !== undefined && (value as number) < field.minimum)) {
      throw new Error(name + " is invalid");
    }
  } else if (field.type === "boolean" && typeof value !== "boolean") {
    throw new Error(name + " must be boolean");
  }
}
"""
    return header + data + runtime


def typescript_type(schema: dict[str, Any]) -> str:
    if "enum" in schema:
        return " | ".join(json.dumps(value) for value in schema["enum"])
    kind = schema.get("type")
    if kind in {"string", "boolean"}:
        return str(kind)
    if kind == "integer":
        return "number"
    raise ContractSyncError(f"unsupported Bridge consumer field type: {kind}")


def build_manifest(files: dict[str, bytes], consumer: bytes) -> dict[str, Any]:
    versions = load_json(files["versions.json"], "versions.json")
    return {
        "schema_version": "ts-phone-consumer-fixture/1",
        "canonical": {
            "repository": CANONICAL_REPOSITORY,
            "directory": CANONICAL_DIRECTORY,
        },
        "protocols": {
            "api": versions["api"],
            "events": versions["events"],
            "bridge": versions["bridge"],
        },
        "files": {
            name: {"sha256": sha256(payload), "bytes": len(payload)}
            for name, payload in sorted(files.items())
        },
        "generated_consumers": {
            "extensions/ts-phone-bridge/protocol.ts": {
                "sha256": sha256(consumer),
                "bytes": len(consumer),
            }
        },
    }


def protocol_summary(root: Path) -> str:
    versions = load_json((root / "versions.json").read_bytes(), "versions.json")
    return f"{versions['api']}, {versions['events']}, {versions['bridge']}"


def load_json(payload: bytes, label: str) -> dict[str, Any]:
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ContractSyncError(f"{label} must contain a JSON object")
    return value


def nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            raise ContractSyncError(f"protocol schema is missing {'.'.join(keys)}")
        current = current[key]
    return current


def protocol_major(value: str, prefix: str) -> int:
    match = re.fullmatch(rf"{re.escape(prefix)}/([1-9][0-9]*)", value)
    if not match:
        raise ContractSyncError(f"invalid {prefix} version: {value}")
    return int(match.group(1))


def typescript_regex(pattern: Any) -> str:
    if not isinstance(pattern, str) or not pattern.startswith("^") or not pattern.endswith("$"):
        raise ContractSyncError("Bridge identifier pattern must be anchored")
    if "/" in pattern:
        raise ContractSyncError("Bridge identifier pattern cannot be emitted as a TypeScript regex")
    return f"/{pattern}/"


def sha256(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


if __name__ == "__main__":
    raise SystemExit(main())
