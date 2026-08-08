import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { DevelopmentTestCase } from "./cases.ts";

const TESTING_DIR = dirname(fileURLToPath(import.meta.url));
export const PACKAGE_ROOT = resolve(TESTING_DIR, "..", "..");
const RUNTIME_SCRIPT = resolve(PACKAGE_ROOT, "scripts", "ts_runtime.py");
const MAX_OUTPUT_CHARS = 12_000;

export interface DevelopmentTestResult {
  caseId: string;
  description: string;
  outcome: "passed" | "failed" | "error";
  exitCode: number;
  durationMs: number;
  output: string;
}

export async function runDevelopmentTest(
  pi: ExtensionAPI,
  testCase: DevelopmentTestCase,
): Promise<DevelopmentTestResult> {
  const startedAt = Date.now();
  const completed = await pi.exec(
    "python3",
    [RUNTIME_SCRIPT, "run-isolated", "-m", "pytest", "-q", ...testCase.selectors],
    { cwd: PACKAGE_ROOT, timeout: testCase.timeoutMs },
  );
  const output = boundedOutput([completed.stdout, completed.stderr].filter(Boolean).join("\n"));
  return {
    caseId: testCase.id,
    description: testCase.description,
    outcome: completed.killed ? "error" : completed.code === 0 ? "passed" : "failed",
    exitCode: completed.code,
    durationMs: Date.now() - startedAt,
    output,
  };
}

function boundedOutput(value: string): string {
  const text = value.trim();
  if (text.length <= MAX_OUTPUT_CHARS) return text;
  return `[earlier output omitted]\n${text.slice(-MAX_OUTPUT_CHARS)}`;
}
