import type { KeybindingsManager, Theme } from "@earendil-works/pi-coding-agent";
import { Key, matchesKey, truncateToWidth, type Component, type TUI } from "@earendil-works/pi-tui";
import { fitColumns } from "../../ui/render-utils.ts";

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
  const values = Array.isArray(report.agent_runs) ? report.agent_runs : [];
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
  private mode: "list" | "details" = "list";
  private selected = 0;
  private detailPage = 0;
  private detailLines: string[] = [];

  constructor(
    private readonly records: readonly TspiRunRecord[],
    private readonly tui: TUI,
    private readonly theme: Theme,
    private readonly keybindings: KeybindingsManager,
    private readonly done: () => void,
  ) {}

  render(width: number): string[] {
    return this.mode === "details" ? this.renderDetails(width) : this.renderList(width);
  }

  invalidate(): void {}

  handleInput(data: string): void {
    if (this.mode === "details") {
      const pages = Math.max(1, Math.ceil(Math.max(0, this.detailLines.length - 1) / 14));
      if (this.keybindings.matches(data, "tui.select.pageUp")) this.detailPage = Math.max(0, this.detailPage - 1);
      else if (this.keybindings.matches(data, "tui.select.pageDown")) this.detailPage = Math.min(pages - 1, this.detailPage + 1);
      else if (matchesKey(data, Key.home)) this.detailPage = 0;
      else if (matchesKey(data, Key.end)) this.detailPage = pages - 1;
      else if (this.keybindings.matches(data, "tui.select.cancel")) { this.mode = "list"; this.detailPage = 0; }
      else return;
      this.tui.requestRender();
      return;
    }
    if (this.keybindings.matches(data, "tui.select.up")) this.selected = Math.max(0, this.selected - 1);
    else if (this.keybindings.matches(data, "tui.select.down")) this.selected = Math.min(this.records.length - 1, this.selected + 1);
    else if (this.keybindings.matches(data, "tui.select.pageUp")) this.selected = Math.max(0, this.selected - 8);
    else if (this.keybindings.matches(data, "tui.select.pageDown")) this.selected = Math.min(this.records.length - 1, this.selected + 8);
    else if (matchesKey(data, Key.home)) this.selected = 0;
    else if (matchesKey(data, Key.end)) this.selected = this.records.length - 1;
    else if (this.keybindings.matches(data, "tui.select.confirm")) { this.mode = "details"; this.detailPage = 0; }
    else if (this.keybindings.matches(data, "tui.select.cancel")) { this.done(); return; }
    else return;
    this.tui.requestRender();
  }

  private renderList(width: number): string[] {
    const safeWidth = Math.max(16, Math.floor(width));
    const page = Math.floor(this.selected / 8);
    const pages = Math.max(1, Math.ceil(this.records.length / 8));
    const start = page * 8;
    const lines = [
      this.theme.fg("accent", truncateToWidth("TS Subagent History", safeWidth, "")),
      this.theme.fg("muted", `Page ${page + 1}/${pages} · Selected ${this.selected + 1}/${this.records.length}`),
      "",
    ];
    for (let offset = 0; offset < 8; offset += 1) {
      const index = start + offset;
      const record = this.records[index];
      if (!record) { lines.push(""); continue; }
      const prefix = index === this.selected ? "→ " : "  ";
      const left = `${prefix}${record.task_id} · ${roleLabel(record.role)} · ${record.operation}`;
      const right = record.status || record.result_outcome || "pending";
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
    const pages = Math.max(1, Math.ceil(Math.max(0, this.detailLines.length - 1) / 14));
    const page = Math.min(this.detailPage, pages - 1);
    const body = this.detailLines.slice(1, 1 + page * 14 + 14).slice(page * 14);
    const lines = [this.theme.fg("accent", this.detailLines[0] || "TS Subagent Run"), this.theme.fg("muted", `Page ${page + 1}/${pages}`)];
    for (let index = 0; index < 14; index += 1) lines.push(this.theme.fg("text", truncateToWidth(body[index] || "", safeWidth, "")));
    lines.push(this.theme.fg("dim", "PgUp/PgDn page · Home/End · Esc back"));
    return lines;
  }
}

function details(record: TspiRunRecord, width: number): string[] {
  const lines = [`${record.task_id} · ${roleLabel(record.role)} · ${record.status || record.result_outcome || "pending"}`];
  if (record.summary) lines.push("", "Outcome", ...record.summary.split("\n").map((line) => `  ${line}`));
  if (record.error_message) lines.push("", "Error", `  ${record.error_code ? `${record.error_code}: ` : ""}${record.error_message}`);
  lines.push("", "Scope", `  Action: ${record.operation}`);
  if (record.capability) lines.push(`  Capability: ${record.capability}`);
  if (record.intent_id) lines.push(`  Calculation: ${record.intent_id}`);
  if (record.node_refs.length) lines.push(`  Nodes: ${record.node_refs.join(", ")}`);
  if (record.claim_refs.length) lines.push(`  Claims: ${record.claim_refs.join(", ")}`);
  if (record.started_at) lines.push(`  Started: ${record.started_at}`);
  if (record.finished_at) lines.push(`  Finished: ${record.finished_at}`);
  if (record.run_ref) lines.push("", `Audit journal: ${record.run_ref}`);
  return lines.map((line) => truncateToWidth(line, width, ""));
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
