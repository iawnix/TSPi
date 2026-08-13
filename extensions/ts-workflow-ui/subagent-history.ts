import type { Theme } from "@earendil-works/pi-coding-agent";
import {
  Key,
  matchesKey,
  truncateToWidth,
  type Component,
  type KeybindingsManager,
  type TUI,
} from "@earendil-works/pi-tui";
import {
  agentSelectionLabel,
  readTsAgentRunDocuments,
  renderTsAgentDetails,
  type TsAgentRecord,
  type TsAgentRunDocuments,
} from "./agent-details.ts";

export const SUBAGENT_HISTORY_PAGE_SIZE = 8;
export const SUBAGENT_DETAIL_PAGE_SIZE = 14;

type BrowserMode = "list" | "details";

export interface SubagentHistorySnapshot {
  mode: BrowserMode;
  selectedIndex: number;
  selectedTaskId?: string;
  listPage: number;
  listPageCount: number;
  detailPage: number;
  detailPageCount: number;
}

interface SubagentHistoryBrowserOptions {
  records: TsAgentRecord[];
  workspaceRoot: string;
  tui: TUI;
  theme: Theme;
  keybindings: KeybindingsManager;
  done: () => void;
  notifyWarning: (message: string) => void;
  readDocuments?: (root: string, runRef?: string) => TsAgentRunDocuments;
}

export class SubagentHistoryBrowser implements Component {
  private readonly records: TsAgentRecord[];
  private readonly workspaceRoot: string;
  private readonly tui: TUI;
  private readonly theme: Theme;
  private readonly keybindings: KeybindingsManager;
  private readonly done: () => void;
  private readonly notifyWarning: (message: string) => void;
  private readonly readDocuments: (root: string, runRef?: string) => TsAgentRunDocuments;
  private mode: BrowserMode = "list";
  private selectedIndex = 0;
  private detailPage = 0;
  private documents: TsAgentRunDocuments = {};
  private detailLines: string[] = [];

  constructor(options: SubagentHistoryBrowserOptions) {
    this.records = options.records;
    this.workspaceRoot = options.workspaceRoot;
    this.tui = options.tui;
    this.theme = options.theme;
    this.keybindings = options.keybindings;
    this.done = options.done;
    this.notifyWarning = options.notifyWarning;
    this.readDocuments = options.readDocuments || readTsAgentRunDocuments;
  }

  render(width: number): string[] {
    return this.mode === "details" ? this.renderDetails(width) : this.renderList(width);
  }

  invalidate(): void {}

  handleInput(data: string): void {
    if (this.mode === "details") this.handleDetailInput(data);
    else this.handleListInput(data);
  }

  getSnapshot(): SubagentHistorySnapshot {
    const detailPageCount = pageCount(Math.max(0, this.detailLines.length - 1), SUBAGENT_DETAIL_PAGE_SIZE);
    return {
      mode: this.mode,
      selectedIndex: this.selectedIndex,
      selectedTaskId: this.records[this.selectedIndex]?.task_id,
      listPage: Math.floor(this.selectedIndex / SUBAGENT_HISTORY_PAGE_SIZE),
      listPageCount: pageCount(this.records.length, SUBAGENT_HISTORY_PAGE_SIZE),
      detailPage: this.detailPage,
      detailPageCount,
    };
  }

  private renderList(width: number): string[] {
    const safeWidth = Math.max(16, Math.floor(width));
    const page = Math.floor(this.selectedIndex / SUBAGENT_HISTORY_PAGE_SIZE);
    const pages = pageCount(this.records.length, SUBAGENT_HISTORY_PAGE_SIZE);
    const start = page * SUBAGENT_HISTORY_PAGE_SIZE;
    const lines = [
      this.theme.fg("accent", truncateToWidth("TS Subagent History", safeWidth, "")),
      this.theme.fg(
        "muted",
        truncateToWidth(
          `${this.records.length} runs · Page ${page + 1}/${pages} · Selected ${this.selectedIndex + 1}/${this.records.length}`,
          safeWidth,
          "",
        ),
      ),
      "",
    ];
    for (let offset = 0; offset < SUBAGENT_HISTORY_PAGE_SIZE; offset += 1) {
      const index = start + offset;
      const record = this.records[index];
      if (!record) {
        lines.push("");
        continue;
      }
      const prefix = index === this.selectedIndex ? "→ " : "  ";
      const text = truncateToWidth(`${prefix}${agentSelectionLabel(record)}`, safeWidth, "");
      lines.push(index === this.selectedIndex
        ? this.theme.bg("selectedBg", this.theme.fg("text", text))
        : this.theme.fg("text", text));
    }
    lines.push(
      "",
      this.theme.fg(
        "dim",
        truncateToWidth("↑/↓ select · PgUp/PgDn page · Home/End · Enter details · Esc close", safeWidth, ""),
      ),
    );
    return lines;
  }

  private renderDetails(width: number): string[] {
    const safeWidth = Math.max(16, Math.floor(width));
    const record = this.records[this.selectedIndex];
    this.detailLines = record ? renderTsAgentDetails(record, this.documents, safeWidth) : [];
    const title = this.detailLines[0] || "Subagent Run Details";
    const body = this.detailLines.slice(1);
    const pages = pageCount(body.length, SUBAGENT_DETAIL_PAGE_SIZE);
    const page = Math.min(this.detailPage, pages - 1);
    const start = page * SUBAGENT_DETAIL_PAGE_SIZE;
    const lines = [
      this.theme.fg("accent", truncateToWidth(title, safeWidth, "")),
      this.theme.fg("muted", truncateToWidth(`Page ${page + 1}/${pages}`, safeWidth, "")),
    ];
    for (let offset = 0; offset < SUBAGENT_DETAIL_PAGE_SIZE; offset += 1) {
      const line = body[start + offset];
      if (line === undefined) {
        lines.push("");
      } else if (line === "Error") {
        lines.push(this.theme.fg("error", truncateToWidth(line, safeWidth, "")));
      } else {
        lines.push(line ? this.theme.fg("text", truncateToWidth(line, safeWidth, "")) : "");
      }
    }
    lines.push(
      this.theme.fg("dim", truncateToWidth("PgUp/PgDn page · Home/End · Esc back", safeWidth, "")),
    );
    return lines;
  }

  private handleListInput(data: string): void {
    if (this.keybindings.matches(data, "tui.select.up")) {
      this.selectedIndex = Math.max(0, this.selectedIndex - 1);
    } else if (this.keybindings.matches(data, "tui.select.down")) {
      this.selectedIndex = Math.min(this.records.length - 1, this.selectedIndex + 1);
    } else if (this.keybindings.matches(data, "tui.select.pageUp")) {
      this.selectedIndex = Math.max(0, this.selectedIndex - SUBAGENT_HISTORY_PAGE_SIZE);
    } else if (this.keybindings.matches(data, "tui.select.pageDown")) {
      this.selectedIndex = Math.min(this.records.length - 1, this.selectedIndex + SUBAGENT_HISTORY_PAGE_SIZE);
    } else if (matchesKey(data, Key.home)) {
      this.selectedIndex = 0;
    } else if (matchesKey(data, Key.end)) {
      this.selectedIndex = this.records.length - 1;
    } else if (this.keybindings.matches(data, "tui.select.confirm")) {
      this.openSelectedRecord();
    } else if (this.keybindings.matches(data, "tui.select.cancel")) {
      this.done();
      return;
    } else {
      return;
    }
    this.tui.requestRender();
  }

  private handleDetailInput(data: string): void {
    const pageTotal = pageCount(Math.max(0, this.detailLines.length - 1), SUBAGENT_DETAIL_PAGE_SIZE);
    if (this.keybindings.matches(data, "tui.select.pageUp")) {
      this.detailPage = Math.max(0, this.detailPage - 1);
    } else if (this.keybindings.matches(data, "tui.select.pageDown")) {
      this.detailPage = Math.min(pageTotal - 1, this.detailPage + 1);
    } else if (matchesKey(data, Key.home)) {
      this.detailPage = 0;
    } else if (matchesKey(data, Key.end)) {
      this.detailPage = pageTotal - 1;
    } else if (this.keybindings.matches(data, "tui.select.cancel")) {
      this.mode = "list";
      this.detailPage = 0;
    } else {
      return;
    }
    this.tui.requestRender();
  }

  private openSelectedRecord(): void {
    const record = this.records[this.selectedIndex];
    if (!record) return;
    this.documents = {};
    try {
      this.documents = this.readDocuments(this.workspaceRoot, record.run_ref);
    } catch (error) {
      this.notifyWarning(error instanceof Error ? error.message : String(error));
    }
    this.detailLines = renderTsAgentDetails(record, this.documents, 80);
    this.detailPage = 0;
    this.mode = "details";
  }
}

function pageCount(itemCount: number, pageSize: number): number {
  return Math.max(1, Math.ceil(itemCount / pageSize));
}
