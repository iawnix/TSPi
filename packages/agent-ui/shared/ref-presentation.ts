/**
 * Human-readable labels for canonical references.
 *
 * Workspace and artifact identities are intentionally content- or UUID-bound
 * at the protocol boundary.  This module is presentation-only: callers keep
 * the original value in their records and use the formatter only while
 * building a line for a person to read.
 */

export interface DisplayRefFormatterOptions {
  workspaceLabel?: string;
  artifactLabels?: ReadonlyMap<string, string> | Record<string, string>;
}

export interface DisplayRefFormatter {
  format(value: unknown, key?: string): string;
  formatText(value: string): string;
}

const WORKSPACE_ID = /^ws_[0-9a-f]{12,}$/i;
const ARTIFACT_ID = /^art_[0-9a-f]{12,}$/i;
const DIGEST = /^sha256:[0-9a-f]{32,}$/i;
const STRUCTURE_SEED = /^structure_seed_[0-9a-f]{16,}(?<suffix>(?:\.[A-Za-z0-9]+)+)$/i;
const STRUCTURE_SEED_IN_PATH = /(?:^|[\\/])structure_seed_[0-9a-f]{16,}(?:\.[A-Za-z0-9]+)+$/i;

/**
 * Collects semantic names from artifact records embedded in tool results.
 * The returned map is safe to pass to createDisplayRefFormatter.
 */
export function collectArtifactDisplayLabels(values: readonly unknown[]): Map<string, string> {
  const labels = new Map<string, string>();
  const visit = (value: unknown) => {
    if (Array.isArray(value)) {
      for (const item of value) visit(item);
      return;
    }
    if (!isObject(value)) return;
    const id = stringValue(value.artifact_id) || stringValue(value.artifactId);
    const path = stringValue(value.path) || stringValue(value.artifact_ref) || stringValue(value.artifactRef);
    if (id && ARTIFACT_ID.test(id) && path && !ARTIFACT_ID.test(path) && !DIGEST.test(path)) {
      labels.set(id, path);
    }
    for (const child of Object.values(value)) visit(child);
  };
  for (const value of values) visit(value);
  return labels;
}

export function createDisplayRefFormatter(options: DisplayRefFormatterOptions = {}): DisplayRefFormatter {
  const aliases = new Map<string, string>();
  const counters = new Map<string, number>();
  const usedLabels = new Map<string, string>();
  const artifactLabels = normalizeLabels(options.artifactLabels);

  const nextAlias = (value: string, kind: string, preferred?: string): string => {
    const existing = aliases.get(value);
    if (existing) return existing;
    const ordinal = (counters.get(kind) || 0) + 1;
    counters.set(kind, ordinal);
    let label = preferred?.trim() || `${kind} ${ordinal}`;
    const owner = usedLabels.get(label);
    if (owner && owner !== value) label = `${label} ${ordinal}`;
    usedLabels.set(label, value);
    aliases.set(value, label);
    return label;
  };

  const format = (value: unknown, key = ""): string => {
    if (typeof value !== "string" || !value) return String(value ?? "");
    const artifact = artifactLabel(value);
    if (artifact) return artifact;
    if (WORKSPACE_ID.test(value)) {
      return nextAlias(value, "workspace", options.workspaceLabel || undefined);
    }
    if (ARTIFACT_ID.test(value)) return nextAlias(value, "artifact");
    if (DIGEST.test(value)) return nextAlias(value, "content digest");
    if (STRUCTURE_SEED.test(value)) return structureSeedLabel(value);
    if (STRUCTURE_SEED_IN_PATH.test(value)) return structureSeedLabel(lastPathPart(value));
    if (isArtifactPathKey(key) && /[\\/]/.test(value)) return lastPathPart(value);
    // A field named *_path may contain an absolute path to a content-addressed
    // seed. Do not expose the machine-specific prefix in the UI.
    if (key.endsWith("_path") && /[\\/]/.test(value) && value.length > 96) {
      const part = lastPathPart(value);
      if (STRUCTURE_SEED.test(part)) return structureSeedLabel(part);
    }
    return value;
  };

  const formatText = (value: string): string => {
    if (!value) return value;
    let formatted = value;
    for (const [artifactId, artifactPath] of artifactLabels) {
      if (artifactPath && artifactPath !== artifactId && formatted.includes(artifactPath)) {
        const label = artifactLabel(artifactId);
        if (!label) continue;
        formatted = formatted.split(artifactPath).join(label);
      }
    }
    // Replace the most specific path-shaped token first, then canonical IDs.
    const seedsAndDigests = formatted
      .replace(/(?:[A-Za-z]:)?[^\s"'`<>]+[\\/]structure_seed_[0-9a-f]{16,}(?:\.[A-Za-z0-9]+)+/gi, (token) => format(token))
      .replace(/structure_seed_[0-9a-f]{16,}(?:\.[A-Za-z0-9]+)+/gi, (token) => format(token))
      .replace(/sha256:[0-9a-f]{32,}/gi, (token) => format(token));
    return replaceCanonicalTokens(seedsAndDigests);
  };

  const replaceCanonicalTokens = (value: string): string => value
    .replace(/(?<![A-Za-z0-9])ws_[0-9a-f]{12,}(?=$|[^A-Za-z0-9])/gi, (token) => nextAlias(token, "workspace", options.workspaceLabel || undefined))
    .replace(/(?<![A-Za-z0-9])art_[0-9a-f]{12,}(?=$|[^A-Za-z0-9])/gi, (token) => artifactLabel(token) || nextAlias(token, "artifact"));

  const artifactLabel = (value: string): string | undefined => {
    if (!ARTIFACT_ID.test(value)) return undefined;
    const path = artifactLabels.get(value);
    if (!path) return undefined;
    const name = lastPathPart(path);
    if (!name) return undefined;
    if (STRUCTURE_SEED.test(name)) return structureSeedLabel(name);
    return nextAlias(value, "artifact", name);
  };

  const structureSeedLabel = (value: string): string => {
    const match = STRUCTURE_SEED.exec(value);
    const suffix = match?.groups?.suffix || ".xyz";
    const ordinal = (counters.get("structure seed") || 0) + 1;
    return nextAlias(value, "structure seed", `structure seed ${ordinal}${suffix}`);
  };

  return { format, formatText };
}

/** Format one value without exposing a content-addressed identity. */
export function formatDisplayRef(value: unknown, options: DisplayRefFormatterOptions = {}): string {
  return createDisplayRefFormatter(options).format(value);
}

/** Format free text for a human-facing summary while retaining its meaning. */
export function formatDisplayText(value: string, options: DisplayRefFormatterOptions = {}): string {
  return createDisplayRefFormatter(options).formatText(value);
}

function normalizeLabels(value: DisplayRefFormatterOptions["artifactLabels"]): Map<string, string> {
  if (!value) return new Map();
  if (value instanceof Map) return new Map(value);
  return new Map(Object.entries(value));
}

function lastPathPart(value: string): string {
  return value.split(/[\\/]/).filter(Boolean).pop() || value;
}

function isArtifactPathKey(key: string): boolean {
  return key === "artifact_ref"
    || key === "artifact_path"
    || key.endsWith("_artifact_ref")
    || key.endsWith("_artifact_path");
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
