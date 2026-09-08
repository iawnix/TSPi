import { Editor, Input, Markdown, SelectList, Text, matchesKey, truncateToWidth } from "@earendil-works/pi-tui";

const style = (code) => (text) => `\x1b[${code}m${text}\x1b[0m`;
const accent = style(36);
const dim = style(2);
const bold = style(1);
const listTheme = { selectedPrefix: accent, selectedText: bold, description: dim, scrollInfo: dim, noMatch: dim };
const markdownTheme = { heading: bold, link: accent, linkUrl: dim, code: accent, codeBlock: (s) => s,
  codeBlockBorder: dim, quote: dim, quoteBorder: dim, hr: dim, listBullet: dim, bold,
  italic: style(3), strikethrough: style(9), underline: style(4) };
const COMMANDS = ["sessions", "projects", "new", "model", "continue", "abort", "refresh", "receipt",
  "older", "newer", "start", "latest", "approvals", "quit"];

// Host/model text is untrusted terminal content. Only this view may emit ANSI.
export const safeText = (value) => String(value ?? "").replace(/[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]/g, "");

export function messageText(message, expanded = false) {
  if (!message || typeof message !== "object") return "";
  const content = typeof message.content === "string" ? message.content
    : (Array.isArray(message.content) ? message.content : []).map((part) => {
      if (!part || typeof part !== "object") return "";
      if (part.type === "text") return part.text;
      if (part.type === "thinking") return expanded ? `Thinking:\n${part.thinking}` : "";
      if (part.type === "toolCall") return expanded
        ? `${part.name}\n\n\`\`\`json\n${JSON.stringify(part.arguments, null, 2)}\n\`\`\`` : `[tool] ${part.name}`;
      if (part.type === "image") return "[image]";
      return "";
    }).filter(Boolean).join("\n\n");
  if (message.role === "toolResult" && !expanded) {
    return `${message.isError ? "FAILED" : "done"} ${message.toolName ?? "tool"}\n${safeText(content).slice(0, 240)}`;
  }
  const outcome = message.outputState ?? message.stopReason;
  const notice = outcome === "failed" || outcome === "error" ? "[Assistant response failed]"
    : outcome === "aborted" ? "[Generation stopped]"
    : outcome === "empty" || outcome === "not_displayed" ? "[No visible assistant output]" : "";
  return [safeText(content), notice].filter(Boolean).join("\n\n");
}

export class TerminalView {
  constructor(tui, controller, quit) {
    this.tui = tui;
    this.controller = controller;
    this.quit = quit;
    this.scroll = 0;
    this.expanded = false;
    this.cache = new WeakMap();
    this.editor = new Editor(tui, { borderColor: dim, selectList: listTheme }, { paddingX: 1 });
    this.editor.onChange = () => { controller.draft = this.editor.getExpandedText(); };
    this.editor.onSubmit = (text) => {
      if (text.startsWith("/")) {
        controller.draft = "";
        void this.perform(() => this.command(text.slice(1).trim()));
      } else {
        controller.draft = text;
        this.editor.setText(text);
        void this.perform(async () => {
          await controller.send(text);
          this.editor.addToHistory(text);
          this.scroll = 0;
        });
      }
    };
    controller.change = () => {
      if (this.editor.getExpandedText() !== controller.draft) this.editor.setText(controller.draft);
      this.editor.disableSubmit = controller.busy;
      tui.requestRender();
    };
  }

  set focused(value) { this.editor.focused = value; }
  get focused() { return this.editor.focused; }
  invalidate() { this.editor.invalidate(); this.cache = new WeakMap(); }

  async perform(action) {
    if (this.working) return;
    this.working = true;
    try { await action(); }
    catch (error) {
      this.controller.notice = `${error.code ?? "error"}: ${safeText(error.message)}`;
    } finally {
      this.working = false;
      this.controller.change();
    }
  }

  choose(title, items, selected) {
    const input = new Input();
    const list = new SelectList(items.map((item) => ({ ...item, label: safeText(item.label), description: safeText(item.description) })),
      5, listTheme);
    input.focused = true;
    list.onSelect = (item) => { this.menu = null; void this.perform(() => selected(item.value)); };
    list.onCancel = () => { this.menu = null; };
    this.menu = { title, input, list };
    this.tui.requestRender();
  }

  ask(title, submit) {
    const input = new Input();
    input.focused = true;
    input.onSubmit = (text) => {
      if (!text.trim()) return;
      this.menu = null;
      void this.perform(() => submit(text.trim()));
    };
    input.onEscape = () => { this.menu = null; };
    this.menu = { title, input };
    this.tui.requestRender();
  }

  async projects() {
    const projects = await this.controller.client.request("/workspaces");
    this.choose("Projects", [...projects.map((p) => ({ value: p.id, label: p.name,
      description: `${p.id} | ${p.sessionCount} conversations` })), { value: "+", label: "+ New project" }], async (id) => {
      if (id === "+") this.ask("Project name", (name) => this.createProject(name));
      else await this.sessions(id);
    });
  }

  async createProject(name, workspaceId) {
    const created = await this.controller.client.request("/workspaces", { name, ...(workspaceId ? { workspaceId } : {}) });
    await this.open(created.workspace.id, created.session.sessionId);
  }

  async sessions(workspaceId = this.controller.workspaceId) {
    if (!workspaceId) return this.projects();
    const sessions = await this.controller.client.request(`/workspaces/${encodeURIComponent(workspaceId)}/sessions`);
    this.choose(workspaceId, [...sessions.map((s) => ({ value: s.sessionId,
      label: s.sessionName || s.sessionId, description: `${s.sessionId} | ${s.runtimeState} | ${s.accessMode}` })),
      { value: "+", label: "+ New conversation" }], async (id) => {
      if (id === "+") this.ask("Conversation name", (name) => this.createSession(workspaceId, name));
      else await this.open(workspaceId, id);
    });
  }

  async createSession(workspaceId, name) {
    const session = await this.controller.client.request(`/workspaces/${encodeURIComponent(workspaceId)}/sessions`,
      { name, accessMode: "controller" });
    await this.open(workspaceId, session.sessionId);
  }

  async open(workspaceId, sessionId) {
    this.menu = null;
    this.scroll = 0;
    await this.controller.open(workspaceId, sessionId);
  }

  async start({ workspaceId, sessionId, latest }) {
    if (!workspaceId) return this.projects();
    let sessions;
    try { sessions = await this.controller.client.request(`/workspaces/${encodeURIComponent(workspaceId)}/sessions`); }
    catch (error) {
      if (error.code !== "workspace_not_found") throw error;
      this.choose(`Create project ${workspaceId}?`, [{ value: "no", label: "Back to projects" }, { value: "yes", label: "Create project" }],
        (value) => value === "yes" ? this.createProject(workspaceId, workspaceId) : this.projects());
      return;
    }
    if (sessionId) {
      if (!sessions.some((s) => s.sessionId === sessionId)) throw new Error("Requested conversation is not active or does not exist.");
      return this.open(workspaceId, sessionId);
    }
    const running = sessions.find((s) => s.runtimeOwner === "host" && s.currentAccessMode === "controller");
    const recent = [...sessions].sort((a, b) => (b.updatedAt ?? "").localeCompare(a.updatedAt ?? ""))[0];
    const session = running ?? (latest ? recent : sessions.length === 1 ? sessions[0] : null);
    if (session) return this.open(workspaceId, session.sessionId);
    return this.sessions(workspaceId);
  }

  async command(command) {
    const c = this.controller;
    if (command === "quit") { this.quit(); return; }
    if (command === "help" || command === "") {
      this.choose("Commands", COMMANDS.map((value) => ({ value, label: `/${value}` })), (value) => this.command(value));
    } else if (command === "projects") await this.projects();
    else if (command === "sessions") await this.sessions();
    else if (command === "new") {
      if (!c.workspaceId) return this.projects();
      this.ask("Conversation name", (name) => this.createSession(c.workspaceId, name));
    } else if (command === "model") {
      if (!c.session?.capabilities?.includes("command.model")) throw new Error("Model selection requires a ready, idle Host Controller. Continue the conversation first.");
      const models = await c.client.request("/models");
      this.choose("Model", models.map((m, index) => ({ value: String(index), label: m.name,
        description: `${m.provider}/${m.id}` })), (index) => c.setModel(models[Number(index)]));
    } else if (command === "continue") {
      const conflict = c.session?.activation?.conflict;
      if (conflict?.switchable) {
        this.choose(`Switch from ${safeText(conflict.sessionName || conflict.sessionId)}?`, [
          { value: "no", label: "Keep current Worker" }, { value: "yes", label: "Stop idle Worker and continue here" },
        ], (value) => value === "yes" ? c.continue({ sessionId: conflict.sessionId, sessionRevision: conflict.sessionRevision }) : undefined);
      } else await c.continue();
    } else if (command === "abort") await c.abort();
    else if (command === "refresh" || command === "latest") { this.scroll = 0; await c.refresh(); }
    else if (command === "receipt") await c.reconcile();
    else if (command === "start") { await c.history("edge=start"); this.scroll = 100_000; }
    else if (command === "older") {
      if (!c.page?.hasMore || !c.page?.nextBefore) throw new Error("No earlier page is available; refresh history first.");
      this.scroll = 0;
      await c.history(`before=${encodeURIComponent(c.page.nextBefore)}`);
    } else if (command === "newer") {
      if (!c.page?.hasLater || !c.page?.nextAfter) throw new Error("No later page is available; use /latest for live messages.");
      await c.history(`after=${encodeURIComponent(c.page.nextAfter)}`);
      this.scroll = 100_000;
    } else if (command === "approvals") {
      const approvals = await c.client.request(`${c.path}/approvals`);
      c.approvals = new Map(approvals.map((approval) => [approval.id, approval]));
      const pending = [...c.approvals.values()].filter((a) => Date.parse(a.expiresAt) > Date.now());
      this.choose("Pending approvals", pending.map((a) => ({ value: a.id, label: a.toolName ?? a.id,
        description: a.preview })), (id) => {
        const approval = c.approvals.get(id);
        this.choose(safeText(approval?.preview), [{ value: "no", label: "Reject" }, { value: "yes", label: "Approve" }],
          (value) => c.approve(id, value === "yes"));
      });
    } else throw new Error("Unknown terminal command. Native Pi extension commands require --standalone.");
  }

  handleInput(data) {
    if (matchesKey(data, "ctrl+c") || matchesKey(data, "ctrl+d")) { this.quit(); return; }
    if (this.tooSmall) return;
    if (this.working || this.controller.busy) return;
    if (this.menu) {
      if (matchesKey(data, "escape")) this.menu = null;
      else if (this.menu.list && ["up", "down", "enter", "pageUp", "pageDown"].some((key) => matchesKey(data, key))) {
        this.menu.list.handleInput(data);
      } else {
        this.menu.input.handleInput(data);
        this.menu?.list?.setFilter(this.menu.input.getValue());
      }
    } else if (matchesKey(data, "ctrl+k")) void this.perform(() => this.command("help"));
    else if (matchesKey(data, "ctrl+o")) void this.perform(() => this.sessions());
    else if (matchesKey(data, "ctrl+t")) { this.expanded = !this.expanded; this.cache = new WeakMap(); }
    else if (matchesKey(data, "pageUp")) this.scroll += Math.max(1, this.tui.terminal.rows - 10);
    else if (matchesKey(data, "pageDown")) this.scroll = Math.max(0, this.scroll - Math.max(1, this.tui.terminal.rows - 10));
    else this.editor.handleInput(data);
    this.tui.requestRender();
  }

  render(width) {
    const c = this.controller;
    const rows = Math.max(1, this.tui.terminal.rows);
    const clip = (text) => truncateToWidth(text, width);
    this.tooSmall = rows < 14 || width < 24;
    if (this.tooSmall) return [clip("Enlarge terminal (24x14 min).")];
    const session = c.session;
    const model = session?.model || "Model not selected";
    const context = session?.runtime?.context;
    const heading = `${c.workspaceId ?? "TSPi"}  /  ${session?.sessionName || session?.sessionId || "Projects"}`;
    const metadata = `${session?.runtimeState ?? "browse"} | ${model}${context ? ` | context ~${context.usedTokens ?? "?"}/${context.limitTokens}` : ""}`;
    const header = [clip(bold(safeText(heading))), clip(dim(safeText(metadata))), ""];
    const status = `${c.busy ? "Waiting for receipt" : c.connected ? "Connected" : "Disconnected"}${c.unconfirmed ? " | Delivery unconfirmed" : ""}${c.historyPage ? " | History" : ""}`;
    const footer = [clip(dim(status)), clip(safeText(c.notice))];
    if (this.menu) {
      const lines = [clip(bold(safeText(this.menu.title))), ...this.menu.input.render(width), "", ...(this.menu.list?.render(width) ?? [])];
      const room = Math.max(1, rows - header.length - footer.length);
      return [...header, ...lines.slice(0, room), ...Array(Math.max(0, room - lines.length)).fill(""), ...footer];
    }
    const editor = this.editor.render(width);
    const room = Math.max(1, rows - header.length - footer.length - editor.length);
    const content = [];
    for (const message of [...c.messages, ...(c.historyPage || !c.liveMessage ? [] : [c.liveMessage])]) {
      let component = this.cache.get(message);
      const text = messageText(message, this.expanded);
      if (!text) continue;
      if (!component || component.source !== text) {
        component = { source: text, markdown: new Markdown(text, 0, 0, markdownTheme) };
        this.cache.set(message, component);
      }
      content.push(clip(dim(message.role === "user" ? "You" : message.role === "toolResult" ? "Tool" : "TSPi")),
        ...component.markdown.render(width), "");
    }
    if (!c.historyPage) for (const activity of c.activities.values()) {
      content.push(clip(dim(`${activity.status}  ${safeText(activity.name)}`)));
    }
    if (!content.length) content.push(...new Text(session ? "" : "TSPi", 0, 0).render(width));
    const pageKey = `${c.key}/${c.historyPage}/${c.page?.nextBefore ?? ""}/${width}`;
    if (this.scroll > 0 && this.lastPageKey === pageKey && this.lastContentLength < content.length) {
      this.scroll += content.length - this.lastContentLength;
    }
    this.lastPageKey = pageKey;
    this.lastContentLength = content.length;
    this.scroll = Math.min(this.scroll, Math.max(0, content.length - room));
    const end = Math.max(0, content.length - this.scroll);
    const visible = content.slice(Math.max(0, end - room), end);
    return [...header, ...visible.map(clip), ...Array(Math.max(0, room - visible.length)).fill(""), ...footer, ...editor];
  }
}
