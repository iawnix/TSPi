import { keyText, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import {
  DEVELOPMENT_TEST_CASES,
  findDevelopmentTestCase,
} from "../../src/testing/cases.ts";
import {
  runDevelopmentTest,
  type DevelopmentTestResult,
} from "../../src/testing/runner.ts";

const STATUS_KEY = "ts-development-test";
const WIDGET_KEY = "ts-development-test";
const ENTRY_TYPE = "ts-development-test-run";

export default function (pi: ExtensionAPI) {
  pi.registerEntryRenderer<DevelopmentTestResult>(ENTRY_TYPE, (entry, { expanded }, theme) => {
    const result = entry.data;
    if (!result) return new Text(theme.fg("warning", "TS development test result is unavailable"), 1, 0);
    const color = result.outcome === "passed" ? "success" : result.outcome === "failed" ? "error" : "warning";
    let text = `${theme.fg("accent", "TS development test")} ${theme.fg(color, result.outcome)}`;
    text += ` ${theme.fg("muted", result.caseId)}`;
    const expandKey = theme.fg("dim", keyText("app.tools.expand"));
    if (expanded && result.output) {
      text += `\n${theme.fg("dim", result.output)}`;
      text += `\n${theme.fg("muted", "(")}${expandKey}${theme.fg("muted", " collapse all details)")}`;
    } else if (result.output) {
      text += ` ${theme.fg("muted", "(")}${expandKey}${theme.fg("muted", " expand all details)")}`;
    }
    return new Text(text, 1, 0);
  });

  pi.registerCommand("ts-test", {
    description: "List or run isolated TS package development tests.",
    getArgumentCompletions: (prefix) => commandCompletions(prefix),
    handler: async (args, ctx) => {
      const tokens = args.trim().split(/\s+/).filter(Boolean);
      if (!tokens.length || tokens[0] === "list") {
        showTestCases(ctx);
        return;
      }
      const caseId = tokens[0] === "run" ? tokens[1] : tokens[0];
      const testCase = caseId ? findDevelopmentTestCase(caseId) : undefined;
      if (!testCase || tokens.length > (tokens[0] === "run" ? 2 : 1)) {
        ctx.ui.notify("Usage: /ts-test list | /ts-test run <case-id>", "warning");
        showTestCases(ctx);
        return;
      }

      ctx.ui.setStatus(STATUS_KEY, `TS test · ${testCase.id} · running`);
      ctx.ui.setWidget(WIDGET_KEY, [
        `TS development test · ${testCase.id}`,
        testCase.description,
      ]);
      ctx.ui.notify(`Running isolated development test: ${testCase.id}`, "info");
      try {
        const result = await runDevelopmentTest(pi, testCase);
        pi.appendEntry(ENTRY_TYPE, result);
        const summary = `${result.outcome} · ${(result.durationMs / 1000).toFixed(1)}s`;
        ctx.ui.setWidget(WIDGET_KEY, [
          `TS development test · ${testCase.id} · ${summary}`,
          ...tailLines(result.output, 8),
        ]);
        ctx.ui.notify(
          `TS development test ${testCase.id}: ${summary}`,
          result.outcome === "passed" ? "info" : "error",
        );
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        ctx.ui.setWidget(WIDGET_KEY, [`TS development test · ${testCase.id} · error`, message]);
        ctx.ui.notify(`TS development test ${testCase.id} could not run: ${message}`, "error");
      } finally {
        ctx.ui.setStatus(STATUS_KEY, undefined);
      }
    },
  });
}

function commandCompletions(prefix: string) {
  const value = prefix.trim();
  const choices = [
    { value: "list", label: "list", description: "Show available development tests" },
    ...DEVELOPMENT_TEST_CASES.map((testCase) => ({
      value: `run ${testCase.id}`,
      label: `run ${testCase.id}`,
      description: testCase.description,
    })),
  ];
  return choices.filter((choice) => choice.value.startsWith(value));
}

function showTestCases(ctx: { ui: { setWidget: (key: string, value: string[]) => void; notify: (message: string, level: "info") => void } }) {
  ctx.ui.setWidget(WIDGET_KEY, [
    "TS development tests",
    ...DEVELOPMENT_TEST_CASES.map((testCase) => `${testCase.id} · ${testCase.description}`),
  ]);
  ctx.ui.notify("Use /ts-test run <case-id> to run an isolated package test.", "info");
}

function tailLines(value: string, count: number): string[] {
  if (!value) return ["No test output was returned."];
  return value.split(/\r?\n/).slice(-count);
}
