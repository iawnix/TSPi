import type { KeybindingsManager, Theme } from "@earendil-works/pi-coding-agent";
import { Key, matchesKey, truncateToWidth, visibleWidth, wrapTextWithAnsi, type Component, type TUI } from "@earendil-works/pi-tui";
import { fitColumns } from "../../ui/render-utils.ts";
import { createDisplayRefFormatter } from "../../shared/ref-presentation.ts";
import { overlayLineBudget } from "./document-viewer.ts";

export interface TspiRunRecord {
  readonly task_id: string;
  readonly role: string;
  readonly operation: string;
  readonly capability?: string;
  readonly status?: string;
  readonly result_outcome?: string;
  readonly node_refs: readonly string[];
  readonly claim_refs: readonly string[];
  readonly intent_id?: string;
  readonly run_ref?: string;
  readonly started_at?: string;
  readonly finished_at?: string;
  readonly summary?: string;
  readonly error_code?: string;
  readonly error_message?: string;
}

export function runRecords(report: Record<string, unknown>): TspiRunRecord[] {
  const values = Array.isArray(report.runs)
    ? report.runs
    : Array.isArray(report.agent_runs)
      ? report.agent_runs
      : [];
  return values
    .filter((value): value is Record<string, unknown> => Boolean(value) && typeof value === "object" && !Array.isArray(value))
    .map((value) => ({
      task_id: stringValue(value.task_id) || "unknown",
      role: stringValue(value.role) || "review",
      operation: stringValue(value.operation) || "operation",
      capability: stringValue(value.capability),
      status: stringValue(value.status),
      result_outcome: stringValue(value.result_outcome),
      node_refs: stringArray(value.node_refs),
      claim_refs: stringArray(value.claim_refs),
      intent_id: stringValue(value.intent_id),
      run_ref: stringValue(value.run_ref),
      started_at: stringValue(value.started_at),
      finished_at: stringValue(value.finished_at),
      summary: stringValue(value.summary),
      error_code: stringValue(value.error_code),
      error_message: stringValue(value.error_message),
    }))
    .sort((left, right) => String(right.finished_at || right.started_at || "").localeCompare(String(left.finished_at || left.started_at || "")));
}

export class RunHistoryBrowser implements Component {
  private readonly records: readonly TspiRunRecord[];
  private readonly tui: TUI;
  private readonly theme: Theme;
  private readonly keybindings: KeybindingsManager;
  private readonly done: () => void;
  private mode: "list" | "details" = "list";
  private selected = 0;
  private detailOffset = 0;
  private detailBodyHeight = 1;
  private detailLines: string[] = [];

  constructor(
    records: readonly TspiRunRecord[],
    tui: TUI,
    theme: Theme,
    keybindings: KeybindingsManager,
    done: () => void,
  ) {
    this.records = records;
    this.tui = tui;
    this.theme = theme;
    this.keybindings = keybindings;
    this.done = done;
  }

  render(width: number): string[] {
    return this.mode === "details" ? this.renderDetails(width) : this.renderList(width);
  }

  invalidate(): void {}

  handleInput(data: string): void {
    if (this.mode === "details") {
      const maxOffset = Math.max(0, this.detailLines.length - 1 - this.detailBodyHeight);
      if (this.keybindings.matches(data, "tui.select.up")) this.detailOffset = Math.max(0, this.detailOffset - 1);
      else if (this.keybindings.matches(data, "tui.select.down")) this.detailOffset = Math.min(maxOffset, this.detailOffset + 1);
      else if (this.keybindings.matches(data, "tui.select.pageUp")) this.detailOffset = Math.max(0, this.detailOffset - this.detailBodyHeight);
      else if (this.keybindings.matches(data, "tui.select.pageDown")) this.detailOffset = Math.min(maxOffset, this.detailOffset + this.detailBodyHeight);
      else if (matchesKey(data, Key.home)) this.detailOffset = 0;
      else if (matchesKey(data, Key.end)) this.detailOffset = maxOffset;
      else if (this.keybindings.matches(data, "tui.select.cancel")) { this.mode = "list"; this.detailOffset = 0; }
      else return;
      this.tui.requestRender();
      return;
    }
    const pageSize = this.listPageSize();
    if (this.keybindings.matches(data, "tui.select.up")) this.selected = Math.max(0, this.selected - 1);
    else if (this.keybindings.matches(data, "tui.select.down")) this.selected = Math.min(this.records.length - 1, this.selected + 1);
    else if (this.keybindings.matches(data, "tui.select.pageUp")) this.selected = Math.max(0, this.selected - pageSize);
    else if (this.keybindings.matches(data, "tui.select.pageDown")) this.selected = Math.min(this.records.length - 1, this.selected + pageSize);
    else if (matchesKey(data, Key.home)) this.selected = 0;
    else if (matchesKey(data, Key.end)) this.selected = this.records.length - 1;
    else if (this.keybindings.matches(data, "tui.select.confirm")) { this.mode = "details"; this.detailOffset = 0; }
    else if (this.keybindings.matches(data, "tui.select.cancel")) { this.done(); return; }
    else return;
    this.tui.requestRender();
  }

  private renderList(width: number): string[] {
    const safeWidth = Math.max(16, Math.floor(width));
    const formatter = createDisplayRefFormatter();
    const pageSize = this.listPageSize();
    const page = Math.floor(this.selected / pageSize);
    const pages = Math.max(1, Math.ceil(this.records.length / pageSize));
    const start = page * pageSize;
    const lines = [
      this.theme.fg("accent", truncateToWidth("TS Subagent History", safeWidth, "")),
      this.theme.fg("muted", `Page ${page + 1}/${pages} · Selected ${this.selected + 1}/${this.records.length}`),
      "",
    ];
    for (let offset = 0; offset < pageSize; offset += 1) {
      const index = start + offset;
      const record = this.records[index];
      if (!record) { lines.push(""); continue; }
      const prefix = index === this.selected ? "→ " : "  ";
      const left = `${prefix}${formatter.format(record.task_id, "task_ref")} · ${roleLabel(record.role)} · ${formatter.formatText(record.operation)}`;
      const right = formatter.formatText(record.status || record.result_outcome || "pending");
      const line = fitColumns(left, right, safeWidth);
      lines.push(index === this.selected ? this.theme.bg("selectedBg", this.theme.fg("text", line)) : this.theme.fg("text", line));
    }
    lines.push("", this.theme.fg("dim", "↑/↓ select · PgUp/PgDn page · Home/End · Enter details · Esc close"));
    return lines.map((line) => truncateToWidth(line, safeWidth, ""));
  }

  private renderDetails(width: number): string[] {
    const safeWidth = Math.max(16, Math.floor(width));
    const record = this.records[this.selected];
    this.detailLines = record ? details(record, safeWidth) : [];
    this.detailBodyHeight = Math.max(1, overlayLineBudget(this.tui) - 3);
    const bodyLines = this.detailLines.slice(1);
    const maxOffset = Math.max(0, bodyLines.length - this.detailBodyHeight);
    this.detailOffset = Math.min(this.detailOffset, maxOffset);
    const start = this.detailOffset;
    const end = Math.min(bodyLines.length, start + this.detailBodyHeight);
    const page = Math.floor(start / this.detailBodyHeight) + 1;
    const pages = Math.max(1, Math.ceil(bodyLines.length / this.detailBodyHeight));
    const lines = [
      this.theme.fg("accent", truncateToWidth(this.detailLines[0] || "TS Subagent Run", safeWidth, "")),
      this.theme.fg("muted", truncateToWidth(`Page ${page}/${pages} · Lines ${start + 1}-${Math.max(start + 1, end)}/${bodyLines.length}`, safeWidth, "")),
    ];
    for (let index = start; index < end; index += 1) lines.push(this.theme.fg("text", truncateToWidth(bodyLines[index] || "", safeWidth, "")));
    while (lines.length < overlayLineBudget(this.tui) - 1) lines.push("");
    lines.push(this.theme.fg("dim", truncateToWidth("↑/↓ scroll · PgUp/PgDn page · Home/End · Esc back", safeWidth, "")));
    return lines;
  }

  private listPageSize(): number {
    return Math.max(1, overlayLineBudget(this.tui) - 5);
  }
}

function details(record: TspiRunRecord, width: number): string[] {
  const formatter = createDisplayRefFormatter();
  const lines = [`${formatter.format(record.task_id, "task_ref")} · ${roleLabel(record.role)} · ${formatter.formatText(record.status || record.result_outcome || "pending")}`];
  if (record.summary) lines.push("", "Outcome", ...wrappedBlock(formatter.formatText(record.summary), width));
  if (record.error_message) {
    const error = `${record.error_code ? `${formatter.formatText(record.error_code)}: ` : ""}${formatter.formatText(record.error_message)}`;
    lines.push("", "Error", ...wrappedBlock(error, width));
  }
  lines.push("", "Scope", ...wrappedField("Action", formatter.formatText(record.operation), width));
  if (record.capability) lines.push(...wrappedField("Capability", formatter.formatText(record.capability), width));
  if (record.intent_id) lines.push(...wrappedField("Calculation", formatter.format(record.intent_id, "calculation_ref"), width));
  if (record.node_refs.length) lines.push(...wrappedField("Nodes", record.node_refs.map((value) => formatter.format(value, "node_ref")).join(", "), width));
  if (record.claim_refs.length) lines.push(...wrappedField("Claims", record.claim_refs.map((value) => formatter.format(value, "claim_ref")).join(", "), width));
  if (record.started_at) lines.push(...wrappedField("Started", record.started_at, width));
  if (record.finished_at) lines.push(...wrappedField("Finished", record.finished_at, width));
  if (record.run_ref) lines.push("", ...wrappedField("Audit journal", formatter.format(record.run_ref, "run_ref"), width, ""));
  return lines;
}

function wrappedBlock(value: string, width: number): string[] {
  const prefix = "  ";
  return wrapTextWithAnsi(value, Math.max(1, width - visibleWidth(prefix))).map((line) => `${prefix}${line}`);
}

function wrappedField(label: string, value: string, width: number, indent = "  "): string[] {
  const prefix = `${indent}${label}: `;
  const continuation = " ".repeat(visibleWidth(prefix));
  return wrapTextWithAnsi(value, Math.max(1, width - visibleWidth(prefix)))
    .map((line, index) => `${index === 0 ? prefix : continuation}${line}`);
}

function roleLabel(value: string): string {
  return value === "compute" ? "Compute" : "Review";
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}
