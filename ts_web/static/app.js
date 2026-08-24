"use strict";

const state = {
  workspaceId: null,
  workspaces: [],
  view: null,
  graph: null,
  currentView: "roadmap",
  query: "",
  locator: null,
  locatorQuery: null,
  locatorRequest: 0,
  locatorTimer: null,
  detail: null,
  detailKind: null,
  detailId: null,
  filePath: null,
  nodeTab: "overview",
  refreshing: false,
  liveTimer: null,
  liveStale: false,
  toastTimer: null,
};

const content = document.getElementById("content");
const workspaceMain = document.getElementById("workspace-main");
const workspaceSelect = document.getElementById("workspace-select");
const health = document.getElementById("health");
const healthLabel = document.getElementById("health-label");
const themeButton = document.getElementById("theme-button");
const themeIcon = document.getElementById("theme-icon");
const refreshButton = document.getElementById("refresh-button");
const refreshStatus = document.getElementById("refresh-status");
const inspector = document.getElementById("inspector");
const inspectorKicker = document.getElementById("inspector-kicker");
const inspectorTitle = document.getElementById("inspector-title");
const inspectorBody = document.getElementById("inspector-body");
const toast = document.getElementById("toast");
const themeStorageKey = "ts-explorer-theme";
const workspaceStorageKey = "ts-explorer-workspace";
const liveRefreshIntervalMs = 5000;

async function api(path) {
  const response = await fetch(path, { cache: "no-store", headers: { Accept: "application/json" } });
  const text = await response.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch (_error) {
    throw new Error(`Invalid JSON from ${path}`);
  }
  if (!response.ok) throw new Error(payload.error || `${response.status} ${response.statusText}`);
  return payload;
}

async function boot() {
  setHealth("loading", "Loading");
  updateThemeControl();
  try {
    await loadWorkspaceCatalog();
    await loadWorkspace();
    scheduleLiveRefresh();
  } catch (error) {
    renderFatal(error);
  }
}

async function loadWorkspaceCatalog() {
  const payload = await api("/api/workspaces");
  state.workspaces = array(payload.workspaces);
  if (!state.workspaces.length) throw new Error("No workspace is registered.");
  let saved = state.workspaceId;
  if (!saved) {
    try { saved = localStorage.getItem(workspaceStorageKey); } catch (_error) {}
  }
  state.workspaceId = state.workspaces.some(row => row.workspace_id === saved)
    ? saved
    : (payload.default_workspace || state.workspaces[0].workspace_id);
  renderWorkspaceOptions();
}

async function loadWorkspace({ preserveInteraction = false } = {}) {
  state.locatorRequest += 1;
  clearTimeout(state.locatorTimer);
  const catalogRow = state.workspaces.find(row => row.workspace_id === state.workspaceId);
  if (catalogRow && catalogRow.available === false) {
    state.view = null;
    state.graph = null;
    state.locator = null;
    state.locatorQuery = null;
    clearInspectorState();
    try { localStorage.setItem(workspaceStorageKey, state.workspaceId); } catch (_error) {}
    renderUnavailableWorkspace(catalogRow);
    return;
  }
  const workspaceId = state.workspaceId;
  const base = `/api/workspace/${encodeURIComponent(state.workspaceId)}`;
  const payload = await api(`${base}/snapshot`);
  if (workspaceId !== state.workspaceId) return;
  if (!payload.changed || !payload.view || !payload.graph) {
    throw new Error("Initial workspace snapshot is incomplete.");
  }
  state.liveStale = false;
  await applyWorkspaceSnapshot(payload, { preserveInteraction });
  try { localStorage.setItem(workspaceStorageKey, state.workspaceId); } catch (_error) {}
}

async function applyWorkspaceSnapshot(payload, { preserveInteraction = false } = {}) {
  const interaction = preserveInteraction ? captureInteraction() : null;
  state.view = payload.view;
  state.graph = payload.graph;
  state.locator = null;
  state.locatorQuery = null;
  const workspaceIndex = state.workspaces.findIndex(row => row.workspace_id === state.workspaceId);
  if (workspaceIndex >= 0 && payload.workspace) state.workspaces[workspaceIndex] = payload.workspace;
  if (!interaction || !interaction.inspectorOpen) clearInspectorState();
  updateChrome();
  renderCurrentView({ resetScroll: !interaction });
  if (!interaction) return;
  workspaceMain.scrollTop = interaction.scrollTop;
  await restoreInspector(interaction);
}

async function refreshExplorer() {
  if (state.refreshing) return;
  clearTimeout(state.liveTimer);
  state.refreshing = true;
  refreshButton.disabled = true;
  refreshButton.classList.add("refreshing");
  refreshStatus.textContent = "Refreshing workspace";
  const previousWorkspaceId = state.workspaceId;
  try {
    await loadWorkspaceCatalog();
    await loadWorkspace({ preserveInteraction: previousWorkspaceId === state.workspaceId });
    refreshStatus.textContent = "Workspace refreshed";
    showToast("Workspace refreshed");
  } catch (error) {
    refreshStatus.textContent = "Refresh failed";
    showToast(`Refresh failed: ${error.message || error}`);
    if (state.view) {
      state.liveStale = true;
      updateChrome();
    } else {
      renderFatal(error);
    }
  } finally {
    state.refreshing = false;
    refreshButton.disabled = false;
    refreshButton.classList.remove("refreshing");
    scheduleLiveRefresh();
  }
}

async function pollLiveRefresh() {
  state.liveTimer = null;
  if (document.hidden || state.refreshing || !state.view || !state.graph) {
    scheduleLiveRefresh();
    return;
  }
  state.refreshing = true;
  refreshButton.disabled = true;
  const workspaceId = state.workspaceId;
  const query = new URLSearchParams({
    workspace_revision: state.view.workspace_revision,
    operational_revision: state.view.operational_revision,
  });
  try {
    const payload = await api(`/api/workspace/${encodeURIComponent(workspaceId)}/snapshot?${query}`);
    if (workspaceId !== state.workspaceId) return;
    const wasStale = state.liveStale;
    state.liveStale = false;
    if (payload.changed) {
      if (!payload.view || !payload.graph) throw new Error("Changed workspace snapshot is incomplete.");
      await applyWorkspaceSnapshot(payload, { preserveInteraction: true });
      refreshStatus.textContent = "Workspace updated automatically";
    } else if (wasStale) {
      updateChrome();
      refreshStatus.textContent = "Live refresh restored";
    }
  } catch (error) {
    if (workspaceId === state.workspaceId && state.view) {
      state.liveStale = true;
      updateChrome();
      refreshStatus.textContent = "Live refresh unavailable; showing the last valid snapshot";
    }
  } finally {
    state.refreshing = false;
    refreshButton.disabled = false;
    scheduleLiveRefresh();
  }
}

function scheduleLiveRefresh(delay = liveRefreshIntervalMs) {
  clearTimeout(state.liveTimer);
  if (document.hidden) return;
  state.liveTimer = setTimeout(pollLiveRefresh, delay);
}

function captureInteraction() {
  const search = document.activeElement?.id === "search-input" ? document.activeElement : null;
  return {
    scrollTop: workspaceMain.scrollTop,
    inspectorOpen: document.body.classList.contains("inspector-open"),
    inspectorScrollTop: inspectorBody.scrollTop,
    detailKind: state.detailKind,
    detailId: state.detailId,
    filePath: state.filePath,
    nodeTab: state.nodeTab,
    searchFocused: Boolean(search),
    searchSelectionStart: search?.selectionStart ?? null,
    searchSelectionEnd: search?.selectionEnd ?? null,
  };
}

async function restoreInspector(interaction) {
  if (interaction.inspectorOpen) {
    state.nodeTab = interaction.nodeTab;
    if (interaction.detailKind === "file" && interaction.filePath) {
      await openFile(interaction.filePath);
    } else if (interaction.detailKind && interaction.detailId) {
      await openDetail(interaction.detailKind, interaction.detailId, { preserveNodeTab: true });
    } else {
      closeInspector();
    }
    inspectorBody.scrollTop = interaction.inspectorScrollTop;
  }
  if (interaction.searchFocused) {
    const search = document.getElementById("search-input");
    if (search) {
      search.focus();
      search.setSelectionRange(interaction.searchSelectionStart, interaction.searchSelectionEnd);
    }
  }
}

function renderWorkspaceOptions() {
  workspaceSelect.innerHTML = state.workspaces.map(row =>
    `<option value="${escapeHtml(row.workspace_id)}">${escapeHtml(row.label || row.workspace_id)}${row.available === false ? " (incompatible)" : ""}</option>`
  ).join("");
  workspaceSelect.value = state.workspaceId;
}

function renderUnavailableWorkspace(row) {
  setHealth("invalid", "Incompatible");
  for (const name of ["phases", "claims", "validation", "findings", "activity"]) setCount(name, 0);
  document.getElementById("sidebar-meta").innerHTML = [
    escapeHtml(row.workspace_id),
    "ts-research-kernel/5 required",
  ].join("<br>");
  content.innerHTML = [
    renderHeader(row.label || row.workspace_id, "Registered workspace cannot be read by this release."),
    `<div class="fatal"><strong>Incompatible workspace</strong><br>${escapeHtml(row.load_error || "The workspace is unavailable.")}</div>`,
  ].join("");
}

function updateChrome() {
  const view = state.view;
  if (state.liveStale) {
    setHealth("stale", "Stale");
  } else {
    setHealth(view.valid ? "valid" : "invalid", view.valid ? "Valid" : "Invalid");
  }
  setCount("phases", view.research_phases.length);
  setCount("claims", view.claims.length);
  setCount("validation", view.validation_results.length);
  setCount("findings", view.findings.length);
  setCount("activity", view.deterministic_activities.length + view.agent_runs.length);
  document.getElementById("sidebar-meta").innerHTML = [
    escapeHtml(view.workspace.workspace_id),
    escapeHtml(shortDigest(view.workspace_revision)),
    escapeHtml(shortDigest(view.operational_revision)),
  ].join("<br>");
}

function setHealth(kind, label) {
  health.className = `health ${kind}`;
  healthLabel.textContent = label;
}

function setCount(name, value) {
  const target = document.querySelector(`[data-count="${name}"]`);
  if (target) target.textContent = String(value);
}

function renderCurrentView({ resetScroll = true } = {}) {
  if (!state.view || !state.graph) return;
  document.querySelectorAll("[data-view]").forEach(button => {
    button.classList.toggle("active", button.dataset.view === state.currentView);
  });
  const renderers = {
    roadmap: renderRoadmap,
    conclusions: renderConclusions,
    files: renderResearchFiles,
    validation: renderValidation,
    findings: renderFindings,
    activity: renderActivity,
    graphs: renderGraphs,
  };
  (renderers[state.currentView] || renderRoadmap)();
  if (resetScroll) workspaceMain.scrollTop = 0;
}

function renderHeader(title, subtitle, searchable = false, placeholder = "Filter") {
  return `<div class="view-header">
    <div class="view-heading"><h1>${escapeHtml(title)}</h1><p>${escapeHtml(subtitle)}</p></div>
    ${searchable ? `<div class="view-tools">${icon("search")}<input class="search-input" id="search-input" type="search" value="${escapeHtml(state.query)}" placeholder="${escapeHtml(placeholder)}" aria-label="${escapeHtml(placeholder)}"></div>` : ""}
  </div>`;
}

function renderRoadmap() {
  const view = state.view;
  const summary = state.graph.semantic_summary;
  const phases = array(view.research_phases);
  const nodes = array(view.research_nodes);
  const query = state.query.trim().toLowerCase();
  const claimById = new Map(view.claims.map(claim => [claim.claim_id, claim]));
  const phaseHtml = phases.map(phase => {
    const phaseNodes = nodes.filter(node => node.phase_ref === phase.phase_id && matchesNode(node, phase, claimById, query));
    if (query && !phaseNodes.length && !matchesText(phase, ["phase_id", "title", "objective"], query)) return "";
    return renderPhaseBand(phase, phaseNodes, claimById);
  }).filter(Boolean).join("");
  content.innerHTML = [
    renderHeader(view.label, `${view.workspace.kernel_protocol} | ${shortDigest(view.workspace_revision)}`, true, "Filter phases, nodes, or claims"),
    renderNotices(),
    `<div class="summary-strip">
      ${summaryItem(summary.phase_count, "Research Phases")}
      ${summaryItem(summary.node_count, "Research Nodes")}
      ${summaryItem(summary.claim_count, "Claims")}
      ${summaryItem(summary.observation_count, "Observations")}
      ${summaryItem(summary.open_finding_count, "Open Findings")}
      ${summaryItem(summary.current_acceptance_count, "Current Acceptances")}
    </div>`,
    phaseHtml || `<div class="empty">No Research Phase matches the current filter.</div>`,
  ].join("");
  bindSearch();
}

function renderNotices() {
  const rows = [];
  if (!state.view.valid) {
    rows.push(notice("error", "findings", `${state.view.validation_findings.length} workspace validation finding(s)`, "Workspace invalid"));
  }
  if (state.view.unresolved_controls.length) {
    rows.push(notice("error", "activity", `${state.view.unresolved_controls.length} unresolved remote control effect(s)`, "Reconcile before replay"));
  }
  if (state.view.pending_review_dispositions.length) {
    rows.push(notice("info", "conclusions", `${state.view.pending_review_dispositions.length} Review response(s) pending Root disposition`, "Advisory only"));
  }
  if (state.view.acceptance_summary.stale_refs.length) {
    rows.push(notice("warning", "validation", `${state.view.acceptance_summary.stale_refs.length} historical acceptance record(s) are stale`, "Reassess before acceptance"));
  }
  return rows.length ? `<div class="notice-stack">${rows.join("")}</div>` : "";
}

function notice(kind, iconName, message, tail) {
  return `<div class="notice ${kind}">${icon(iconName)}<span>${escapeHtml(message)}</span><code>${escapeHtml(tail)}</code></div>`;
}

function summaryItem(value, label) {
  return `<div class="summary-item"><div class="summary-value">${escapeHtml(value)}</div><div class="summary-label">${escapeHtml(label)}</div></div>`;
}

function renderPhaseBand(phase, nodes, claimById) {
  return `<section class="phase-band" data-phase="${escapeHtml(phase.phase_id)}">
    <div class="phase-header">
      <div class="phase-id">${escapeHtml(phase.phase_id)}</div>
      <div><h2 class="phase-title">${escapeHtml(phase.title)}</h2><p class="phase-objective">${escapeHtml(phase.objective)}</p></div>
      <div class="phase-count">${nodes.length} node${nodes.length === 1 ? "" : "s"}${phase.focused ? " | focus" : ""}</div>
    </div>
    <div class="node-timeline">${nodes.length ? nodes.map(node => renderNodeCard(node, claimById)).join("") : `<div class="empty">No nodes in this phase.</div>`}</div>
  </section>`;
}

function renderNodeCard(node, claimById) {
  const claim = claimById.get(node.primary_claim_ref);
  const focused = state.view.focus.node_refs.includes(node.node_id);
  const opening = object(node.opening_decision);
  const result = object(node.result);
  const execution = `${node.attempts.length} attempt${node.attempts.length === 1 ? "" : "s"} | ${node.compute_run_count || 0} run${node.compute_run_count === 1 ? "" : "s"}`;
  const lineage = node.dependency_refs.length ? `from ${node.dependency_refs.join(", ")}` : "entry decision";
  const successors = array(node.dependent_refs);
  return `<div class="node-step"><span class="node-step-marker ${tone(node.status)}" aria-hidden="true"></span><button class="node-card ${focused ? "focused" : ""}" type="button" data-detail="node" data-id="${escapeHtml(node.node_id)}">
    <div class="node-card-head"><div><div class="node-id">${escapeHtml(node.node_id)}</div><div class="node-title">${escapeHtml(node.title)}</div></div>${badge(node.status)}</div>
    <div class="node-decision"><div class="node-field-label">Research decision</div><p class="node-rationale">${escapeHtml(opening.rationale || node.objective)}</p><div class="node-question">${escapeHtml(node.objective)}</div></div>
    <div class="node-outcome ${result.summary ? "resolved" : "pending"}"><div class="node-field-label">Outcome</div><p>${result.summary ? escapeHtml(result.summary) : "Pending"}</p></div>
    <div class="node-meta"><span>${icon("branch")}${escapeHtml(lineage)}</span><span>${escapeHtml(execution)}</span><span>${successors.length ? `${successors.length} successor${successors.length === 1 ? "" : "s"}` : "no successor"}</span>${claim ? `<span>${escapeHtml(claim.claim_id)}</span>` : ""}</div>
  </button></div>`;
}

function matchesNode(node, phase, claimById, query) {
  if (!query) return true;
  const claims = array(node.related_claim_refs).map(ref => claimById.get(ref)).filter(Boolean);
  return matchesText(node, ["node_id", "title", "objective", "deliverable", "status", "tags", "opening_decision", "result"], query)
    || matchesText(phase, ["phase_id", "title", "objective"], query)
    || claims.some(claim => matchesText(claim, ["claim_id", "statement", "claim_type", "status"], query));
}

function renderConclusions() {
  const graphClaims = new Map(state.graph.claim_graph.nodes.map(row => [row.claim_id, row]));
  const rows = filterRecords(state.view.claims, ["claim_id", "claim_type", "statement", "status", "assumptions", "falsifiers", "tags"]);
  content.innerHTML = renderHeader("Scientific Conclusions", "Claims remain separate from execution nodes and carry assumptions, falsifiers, validation, and acceptance.", true, "Filter claims")
    + renderNotices()
    + section("Claims", `${rows.length}`, table(
      ["Claim", "Statement", "Type", "Status", "Acceptance"],
      rows.map(claim => {
        const projected = graphClaims.get(claim.claim_id) || {};
        return [
          detailButton("claim", claim.claim_id, claim.claim_id),
          `<div class="statement">${escapeHtml(claim.statement)}</div>`,
          `<span class="mono">${escapeHtml(claim.claim_type)}</span>`,
          badge(claim.status),
          badge(projected.acceptance_state || "none"),
        ];
      }),
    ));
  bindSearch();
}

function renderValidation() {
  const specs = filterRecords(state.view.validation_specs, ["spec_id", "title", "dimension", "target_claim_ref", "template_ref"]);
  const results = filterRecords(state.view.validation_results, ["result_id", "dimension", "verdict", "target_claim_ref", "spec_ref"]);
  const acceptances = filterRecords(state.view.acceptances, ["acceptance_id", "claim_ref", "profile_id", "current", "stale_reasons"]);
  content.innerHTML = renderHeader("Validation", "Frozen GateSpecs, deterministic results, and revision-bound acceptance records.", true, "Filter validation records")
    + renderNotices()
    + section("GateSpecs", `${specs.length}`, table(["GateSpec", "Title", "Dimension", "Target Claim"], specs.map(row => [detailButton("validation-spec", row.spec_id, row.spec_id), escapeHtml(row.title), mono(row.dimension), detailButton("claim", row.target_claim_ref, row.target_claim_ref)])))
    + section("Validation Results", `${results.length}`, table(["Result", "Dimension", "Verdict", "Target Claim", "GateSpec"], results.map(row => [detailButton("validation-result", row.result_id, row.result_id), mono(row.dimension), badge(row.verdict), detailButton("claim", row.target_claim_ref, row.target_claim_ref), mono(row.spec_ref)])))
    + section("Acceptance Records", `${acceptances.length}`, table(["Acceptance", "Claim", "Profile", "State"], acceptances.map(row => [detailButton("acceptance", row.acceptance_id, row.acceptance_id), detailButton("claim", row.claim_ref, row.claim_ref), mono(row.profile_id || "profile"), badge(row.current ? "current" : "historical")])))
    ;
  bindSearch();
}

function renderFindings() {
  const rows = filterRecords(state.view.findings, ["finding_id", "finding_type", "severity", "status", "statement", "claim_refs", "node_refs"]);
  content.innerHTML = renderHeader("Findings", "Explicit anomalies, limitations, conflicts, and unresolved questions.", true, "Filter findings")
    + renderNotices()
    + section("Scientific Findings", `${rows.length}`, table(["Finding", "Statement", "Severity", "Status", "Scope"], rows.map(row => [
      detailButton("finding", row.finding_id, row.finding_id),
      `<div class="statement">${escapeHtml(row.statement)}</div>`,
      badge(row.severity),
      badge(row.status),
      `<div class="mono">${escapeHtml([...array(row.claim_refs), ...array(row.node_refs)].join(", ") || "none")}</div>`,
    ])));
  bindSearch();
}

function renderActivity() {
  const activities = filterRecords(state.view.deterministic_activities, ["activity_id", "kind", "operation", "status", "summary", "node_refs"]);
  const runs = filterRecords(state.view.agent_runs, ["task_id", "role", "operation", "status", "summary", "claim_refs", "node_refs"]);
  content.innerHTML = renderHeader("Activity", "Deterministic host operations and isolated Compute or Review runs.", true, "Filter operations and runs")
    + renderNotices()
    + section("Deterministic Operations", `${activities.length}`, recordList(activities.map(row => ({
      kind: "activity",
      id: row.activity_id,
      title: compact([row.kind, row.operation]) || "Deterministic operation",
      subtitle: row.summary || array(row.node_refs).join(", "),
      status: row.status,
    }))))
    + section("Subagent Runs", `${runs.length}`, recordList(runs.map(row => ({
      kind: "agent",
      id: row.task_id,
      title: compact([row.role, row.operation]) || "Subagent run",
      subtitle: row.summary || compact([...array(row.claim_refs), ...array(row.node_refs)]),
      status: row.status,
    }))));
  bindSearch();
}

function renderResearchFiles() {
  const query = state.query.trim();
  content.innerHTML = renderHeader("Research Files", "Locate canonical records, ResearchNodes, calculation attempts, and artifact-bound files.", true, "Search claim_1, node_2, calc_3, concept, or path")
    + `<div id="locator-results">${renderLocatorBody(query)}</div>`;
  bindSearch();
  if (state.locatorQuery !== query) scheduleLocator(query);
}

function scheduleLocator(query) {
  clearTimeout(state.locatorTimer);
  const request = ++state.locatorRequest;
  state.locatorTimer = setTimeout(async () => {
    try {
      const payload = await api(`/api/workspace/${encodeURIComponent(state.workspaceId)}/files?query=${encodeURIComponent(query)}`);
      if (request !== state.locatorRequest || state.currentView !== "files") return;
      state.locator = payload;
      state.locatorQuery = query;
      const target = document.getElementById("locator-results");
      if (target) target.innerHTML = renderLocatorBody(query);
    } catch (error) {
      if (request !== state.locatorRequest) return;
      const target = document.getElementById("locator-results");
      if (target) target.innerHTML = `<div class="fatal">${escapeHtml(error.message || error)}</div>`;
    }
  }, query ? 180 : 0);
}

function renderLocatorBody(query) {
  if (state.locatorQuery !== query || !state.locator) return `<div class="empty">Loading research index...</div>`;
  const locator = state.locator;
  const summary = `<div class="locator-summary"><span>${array(locator.matches).length} matches</span><span>${escapeHtml(locator.query_mode || "index")}</span><span>${escapeHtml(locator.query || "workspace index")}</span></div>`;
  if (!array(locator.matches).length) return summary + `<div class="empty">No matching research records or artifacts.</div>`;
  return summary + locator.matches.map(renderLocatorMatch).join("");
}

function renderLocatorMatch(match) {
  const refs = [
    ...array(match.claim_refs).map(ref => `<span class="ref-chip">Claim ${escapeHtml(ref)}</span>`),
    ...array(match.node_refs).map(ref => `<span class="ref-chip">Node ${escapeHtml(ref)}</span>`),
    ...array(match.observation_refs).map(ref => `<span class="ref-chip">Observation ${escapeHtml(ref)}</span>`),
  ].join("");
  const directories = array(match.directories).map(row => pathRow(row.path, row.label || "directory", null)).join("");
  const attempts = array(match.attempts).map(row => `<div class="record-row"><div><div class="record-title mono">${escapeHtml(row.intent_id || row.ref)}</div><div class="record-subtitle">${escapeHtml(compact([row.backend, row.task_type, row.state]))}</div></div>${row.state ? badge(row.state) : ""}</div>`).join("");
  const artifacts = array(match.artifacts).map(row => pathRow(row.path, compact([row.artifact_id, row.relation, row.sha256 && shortDigest(row.sha256)]), row.path)).join("");
  const files = array(match.files).map(row => pathRow(row.path, formatBytes(row.size || row.size_bytes || 0), row.path)).join("");
  return `<section class="locator-match">
    <div class="locator-head"><div><strong>${escapeHtml(match.ref || match.label || "Result")}</strong><div class="record-subtitle">${escapeHtml(match.kind || "record")}</div></div>${refs ? `<div class="ref-chips">${refs}</div>` : ""}</div>
    <div class="locator-groups">
      ${directories ? `<div class="locator-group"><h3>Directories</h3>${directories}</div>` : ""}
      ${attempts ? `<div class="locator-group"><h3>Calculation Attempts</h3>${attempts}</div>` : ""}
      ${artifacts ? `<div class="locator-group wide"><h3>Artifacts and Semantic Bindings</h3>${artifacts}</div>` : ""}
      ${files ? `<div class="locator-group wide"><h3>Files</h3>${files}</div>` : ""}
    </div>
  </section>`;
}

function renderGraphs() {
  content.innerHTML = renderHeader("Advanced Graphs", "Claim relations and the cross-Phase ResearchNode dependency DAG.")
    + renderNotices()
    + `<div class="graph-grid">${graphPanel("Scientific Claim Graph", state.graph.claim_graph, "claim")}${graphPanel("Cross-Phase ResearchNode DAG", state.graph.research_node_dag, "node")}</div>`;
  requestAnimationFrame(drawAllGraphs);
}

function graphPanel(title, graph, kind) {
  return `<section class="graph-panel"><div class="section-header"><h2>${escapeHtml(title)}</h2><span class="section-meta">${array(graph.nodes).length} records | ${array(graph.edges).length} edges</span></div><div class="graph-stage" data-graph-kind="${kind}">${array(graph.nodes).length ? `<canvas></canvas>` : `<div class="graph-empty">No graph records.</div>`}</div></section>`;
}

function drawAllGraphs() {
  document.querySelectorAll("[data-graph-kind]").forEach(stage => {
    const graph = stage.dataset.graphKind === "claim" ? state.graph.claim_graph : state.graph.research_node_dag;
    drawGraph(stage, graph);
  });
}

function drawGraph(stage, graph) {
  const canvas = stage.querySelector("canvas");
  if (!canvas) return;
  const width = Math.max(320, stage.clientWidth);
  const height = Math.max(260, stage.clientHeight);
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  const styles = getComputedStyle(document.documentElement);
  const nodes = array(graph.nodes);
  const edges = array(graph.edges).filter(edge => nodes.some(node => node.id === edge.source) && nodes.some(node => node.id === edge.target));
  const depth = graphDepths(nodes, edges);
  const columns = new Map();
  nodes.forEach(node => {
    const value = depth.get(node.id) || 0;
    if (!columns.has(value)) columns.set(value, []);
    columns.get(value).push(node);
  });
  const maxDepth = Math.max(...columns.keys(), 0);
  const positions = new Map();
  const boxWidth = Math.min(180, Math.max(118, (width - 52) / Math.max(maxDepth + 1, 1) - 24));
  const boxHeight = 54;
  for (const [column, rows] of columns.entries()) {
    rows.forEach((node, index) => {
      const x = maxDepth ? 26 + column * ((width - 52 - boxWidth) / maxDepth) : (width - boxWidth) / 2;
      const y = 26 + index * ((height - 52 - boxHeight) / Math.max(rows.length - 1, 1));
      positions.set(node.id, { x, y });
    });
  }
  context.clearRect(0, 0, width, height);
  context.strokeStyle = styles.getPropertyValue("--line-strong").trim();
  context.lineWidth = 1.2;
  edges.forEach(edge => {
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    if (!source || !target) return;
    context.beginPath();
    context.moveTo(source.x + boxWidth, source.y + boxHeight / 2);
    context.lineTo(target.x, target.y + boxHeight / 2);
    context.stroke();
  });
  nodes.forEach(node => {
    const position = positions.get(node.id);
    if (!position) return;
    context.fillStyle = styles.getPropertyValue("--surface-raised").trim();
    context.strokeStyle = node.focus ? styles.getPropertyValue("--green").trim() : styles.getPropertyValue("--line-strong").trim();
    roundedRect(context, position.x, position.y, boxWidth, boxHeight, 5);
    context.fill();
    context.stroke();
    context.fillStyle = styles.getPropertyValue("--text").trim();
    context.font = "600 11px ui-monospace, monospace";
    context.fillText(String(node.id || "record").slice(0, 24), position.x + 9, position.y + 20, boxWidth - 18);
    context.fillStyle = styles.getPropertyValue("--muted").trim();
    context.font = "11px system-ui, sans-serif";
    context.fillText(String(node.title || node.statement || node.status || "").slice(0, 26), position.x + 9, position.y + 39, boxWidth - 18);
  });
}

function graphDepths(nodes, edges) {
  const incoming = new Map(nodes.map(node => [node.id, []]));
  edges.forEach(edge => incoming.get(edge.target)?.push(edge.source));
  const memo = new Map();
  function visit(id, stack = new Set()) {
    if (memo.has(id)) return memo.get(id);
    if (stack.has(id)) return 0;
    stack.add(id);
    const parents = incoming.get(id) || [];
    const value = parents.length ? 1 + Math.max(...parents.map(parent => visit(parent, new Set(stack)))) : 0;
    memo.set(id, value);
    return value;
  }
  nodes.forEach(node => visit(node.id));
  return memo;
}

function roundedRect(context, x, y, width, height, radius) {
  context.beginPath();
  context.roundRect(x, y, width, height, radius);
}

async function openDetail(kind, id, { preserveNodeTab = false } = {}) {
  const workspaceId = state.workspaceId;
  state.detailKind = kind;
  state.detailId = id;
  state.filePath = null;
  if (!preserveNodeTab || kind !== "node") state.nodeTab = "overview";
  inspectorKicker.textContent = labelForKind(kind);
  inspectorTitle.textContent = id;
  inspectorBody.innerHTML = `<div class="empty">Loading details...</div>`;
  document.body.classList.add("inspector-open");
  inspector.setAttribute("aria-hidden", "false");
  try {
    let payload;
    if (kind === "node" || kind === "claim") {
      payload = await api(`/api/workspace/${encodeURIComponent(state.workspaceId)}/${kind}/${encodeURIComponent(id)}`);
    } else {
      payload = localRecord(kind, id);
    }
    if (workspaceId !== state.workspaceId || state.detailKind !== kind || state.detailId !== id) return;
    state.detail = payload;
    renderInspector();
  } catch (error) {
    if (workspaceId !== state.workspaceId || state.detailKind !== kind || state.detailId !== id) return;
    inspectorBody.innerHTML = `<div class="fatal">${escapeHtml(error.message || error)}</div>`;
  }
}

function renderInspector() {
  if (state.detailKind === "node") {
    renderNodeDetail(state.detail);
    return;
  }
  if (state.detailKind === "claim") {
    renderClaimDetail(state.detail);
    return;
  }
  const record = state.detail || {};
  inspectorTitle.textContent = recordId(record);
  inspectorBody.innerHTML = `<section class="detail-section">${detailFields(record)}</section>`;
}

function renderNodeDetail(payload) {
  const node = payload.research_node;
  inspectorKicker.textContent = `${payload.phase.phase_id} | ${node.node_id}`;
  inspectorTitle.textContent = node.title;
  const tabs = ["overview", "conclusions", "evidence", "runs", "files", "history"];
  const tabLabels = { overview: "Overview", conclusions: "Conclusions", evidence: "Evidence", runs: "Runs", files: "Files", history: "History" };
  inspectorBody.innerHTML = `<div class="detail-summary"><div class="detail-meta">${badge(node.status)}<span>${escapeHtml(payload.phase.title)}</span><span>${escapeHtml(node.node_id)}</span></div><p>${escapeHtml(node.objective)}</p></div>
    <div class="tabs" role="tablist">${tabs.map(tab => `<button class="tab-button ${tab === state.nodeTab ? "active" : ""}" type="button" role="tab" data-node-tab="${tab}" aria-selected="${tab === state.nodeTab}">${tabLabels[tab]}</button>`).join("")}</div>
    <div id="node-tab-content">${renderNodeTab(payload, state.nodeTab)}</div>`;
}

function renderNodeTab(payload, tab) {
  if (tab === "conclusions") return renderNodeConclusions(payload);
  if (tab === "evidence") return renderNodeEvidence(payload);
  if (tab === "runs") return renderNodeRuns(payload);
  if (tab === "files") return renderNodeFiles(payload);
  if (tab === "history") return renderNodeHistory(payload);
  return renderNodeOverview(payload);
}

function renderNodeOverview(payload) {
  const node = payload.research_node;
  const result = object(node.result);
  const opening = object(node.opening_decision);
  return `<section class="detail-section"><h3>Research Decision</h3><div class="detail-callout info"><div class="detail-meta"><span class="mono">${escapeHtml(opening.decision_id || node.created_by_decision)}</span><span>${escapeHtml(formatTime(opening.created_at || node.created_at))}</span></div><p class="detail-copy">${escapeHtml(opening.rationale || node.objective)}</p></div></section>
    <section class="detail-section"><h3>Research Contract</h3><dl class="detail-grid"><dt>Phase</dt><dd><span class="mono">${escapeHtml(payload.phase.phase_id)}</span> ${escapeHtml(payload.phase.title)}</dd><dt>Question</dt><dd>${escapeHtml(node.objective)}</dd><dt>Principal deliverable</dt><dd>${escapeHtml(node.deliverable)}</dd><dt>Primary Claim</dt><dd>${node.primary_claim_ref ? detailButton("claim", node.primary_claim_ref, node.primary_claim_ref) : "none"}</dd></dl></section>
    <section class="detail-section"><h3>Outcome</h3>${result.outcome ? `<div class="detail-callout ${tone(result.outcome)}"><div class="detail-meta">${badge(result.outcome)}<span>${escapeHtml(formatTime(result.completed_at))}</span></div><p class="detail-copy">${escapeHtml(result.summary)}</p>${bulletGroup("Open Questions", result.open_questions)}</div>` : `<div class="detail-empty">No terminal result has been recorded.</div>`}</section>
    <section class="detail-section"><h3>Lineage</h3>${linkedNodeGroup("Depends on", payload.dependencies)}${linkedNodeGroup("Continued by", payload.dependents)}</section>
    <section class="detail-section"><h3>Related Claims</h3>${linkedClaimRows(payload.claims)}</section>`;
}

function renderNodeConclusions(payload) {
  const node = payload.research_node;
  const result = object(node.result);
  return `<section class="detail-section"><h3>Node Outcome</h3>${result.summary ? `<div class="detail-callout ${tone(result.outcome)}"><p class="detail-copy">${escapeHtml(result.summary)}</p></div>` : `<div class="detail-empty">This Node has no terminal conclusion.</div>`}</section>
    <section class="detail-section"><h3>Claims</h3>${linkedClaimRows(payload.claims)}</section>
    <section class="detail-section"><h3>Findings</h3>${detailRecordRows(payload.findings, "finding", "finding_id", "statement", "status")}</section>`;
}

function renderNodeEvidence(payload) {
  return `<section class="detail-section"><h3>Observations</h3>${detailRecordRows(payload.observations, "observation", "observation_id", "summary", "concept_id")}</section>
    <section class="detail-section"><h3>Frozen GateSpecs</h3>${detailRecordRows(payload.validation_specs, "validation-spec", "spec_id", "title", "dimension")}</section>
    <section class="detail-section"><h3>Validation Results</h3>${detailRecordRows(payload.validation_results, "validation-result", "result_id", "dimension", "verdict")}</section>`;
}

function renderNodeRuns(payload) {
  const node = payload.research_node;
  const attempts = array(node.attempts).map(row => `<div class="record-row"><div><div class="record-title mono">${escapeHtml(row.intent_id)}</div><div class="record-subtitle">${escapeHtml(compact([row.backend, row.task_type, row.program_status, row.error_class]))}</div></div><div class="record-meta">${badge(row.state || "unknown")}<span class="ref-chip">${row.run_count} runs</span></div></div>`).join("");
  return `<section class="detail-section"><h3>Calculation Attempts</h3>${attempts || `<div class="detail-empty">No calculation attempts.</div>`}</section>
    <section class="detail-section"><h3>Deterministic Operations</h3>${detailRecordRows(node.activities, "activity", "activity_id", "operation", "status")}</section>
    <section class="detail-section"><h3>Subagent Runs</h3>${detailRecordRows(payload.agent_runs, "agent", "task_id", "operation", "status")}</section>
    <section class="detail-section"><h3>Unresolved Controls</h3>${detailRecordRows(node.unresolved_controls, "control", "control_id", "operation", "state")}</section>`;
}

function renderNodeFiles(payload) {
  const files = array(payload.files?.files);
  return `<section class="detail-section"><h3>Node Files</h3>${files.length ? files.map(row => pathRow(row.path, compact([formatBytes(row.size), formatTime(row.modified * 1000)]), row.path)).join("") : `<div class="detail-empty">No current v5 files are present for this Node.</div>`}</section>`;
}

function renderNodeHistory(payload) {
  const node = payload.research_node;
  const audit = {
    phase_ref: node.phase_ref,
    created_by_decision: node.created_by_decision,
    completion_decision: node.result?.decision_id,
    artifact_root: node.artifact_root,
    observation_refs: node.observation_refs,
    finding_refs: node.finding_refs,
    validation_spec_refs: node.validation_spec_refs,
    validation_result_refs: node.validation_result_refs,
  };
  const decisions = array(payload.history).map(row => `<div class="record-row"><div><div class="record-title mono">${escapeHtml(row.decision_id || "Decision")}</div><div class="record-subtitle">${escapeHtml(row.rationale || "Canonical mutation")}</div></div><div class="record-meta"><span>${escapeHtml(formatTime(row.created_at))}</span></div></div>`).join("");
  return `<section class="detail-section"><h3>Decision History</h3>${decisions || `<div class="detail-empty">No matching decisions were projected.</div>`}</section><section class="detail-section"><h3>Audit References</h3>${detailFields(audit)}</section>`;
}

function renderClaimDetail(payload) {
  const claim = payload.claim;
  inspectorKicker.textContent = `${claim.claim_type} | ${claim.claim_id}`;
  inspectorTitle.textContent = claim.statement;
  inspectorBody.innerHTML = `<div class="detail-summary"><div class="detail-meta">${badge(claim.status)}<span>${escapeHtml(claim.claim_id)}</span></div><p>${escapeHtml(claim.statement)}</p></div>
    <section class="detail-section"><h3>Scientific Contract</h3>${bulletGroup("Assumptions", claim.assumptions)}${bulletGroup("Falsifiers", claim.falsifiers)}</section>
    <section class="detail-section"><h3>ResearchNodes</h3>${linkedNodeGroup("Related Nodes", payload.research_nodes)}</section>
    <section class="detail-section"><h3>Observations</h3>${detailRecordRows(payload.observations, "observation", "observation_id", "summary", "concept_id")}</section>
    <section class="detail-section"><h3>Validation</h3>${detailRecordRows(payload.validation_results, "validation-result", "result_id", "dimension", "verdict")}</section>
    <section class="detail-section"><h3>Findings</h3>${detailRecordRows(payload.findings, "finding", "finding_id", "statement", "status")}</section>
    <section class="detail-section"><h3>Acceptance</h3>${detailRecordRows(payload.acceptances, "acceptance", "acceptance_id", "profile_id", "current")}</section>
    <section class="detail-section"><h3>Review Runs</h3>${detailRecordRows(payload.review_runs, "agent", "task_id", "summary", "status")}</section>`;
}

async function openFile(path) {
  const workspaceId = state.workspaceId;
  state.detail = null;
  state.detailKind = "file";
  state.detailId = path;
  state.filePath = path;
  inspectorKicker.textContent = "Research File";
  inspectorTitle.textContent = pathName(path);
  inspectorBody.innerHTML = `<div class="empty">Loading file...</div>`;
  document.body.classList.add("inspector-open");
  inspector.setAttribute("aria-hidden", "false");
  try {
    const payload = await api(`/api/workspace/${encodeURIComponent(state.workspaceId)}/file?path=${encodeURIComponent(path)}`);
    if (workspaceId !== state.workspaceId || state.filePath !== path) return;
    inspectorBody.innerHTML = `<section class="detail-section"><dl class="detail-grid"><dt>Path</dt><dd class="mono">${escapeHtml(payload.path)}</dd><dt>Size</dt><dd>${escapeHtml(formatBytes(payload.size))}</dd></dl><pre class="file-preview">${escapeHtml(payload.text)}</pre></section>`;
  } catch (error) {
    if (workspaceId !== state.workspaceId || state.filePath !== path) return;
    inspectorBody.innerHTML = `<div class="fatal">${escapeHtml(error.message || error)}</div>`;
  }
}

function closeInspector() {
  document.body.classList.remove("inspector-open");
  inspector.setAttribute("aria-hidden", "true");
}

function clearInspectorState() {
  state.detail = null;
  state.detailKind = null;
  state.detailId = null;
  state.filePath = null;
  state.nodeTab = "overview";
  closeInspector();
}

function localRecord(kind, id) {
  const sources = {
    observation: [state.view.observations, "observation_id"],
    "validation-spec": [state.view.validation_specs, "spec_id"],
    "validation-result": [state.view.validation_results, "result_id"],
    finding: [state.view.findings, "finding_id"],
    acceptance: [state.view.acceptances, "acceptance_id"],
    activity: [state.view.deterministic_activities, "activity_id"],
    agent: [state.view.agent_runs, "task_id"],
    control: [state.view.unresolved_controls, "control_id"],
  };
  const [records, key] = sources[kind] || [[], "id"];
  const record = array(records).find(row => String(row[key]) === String(id));
  if (!record) throw new Error(`Unknown ${labelForKind(kind)}: ${id}`);
  return record;
}

function linkedNodeGroup(label, records) {
  const rows = array(records);
  if (!rows.length) return `<div class="detail-empty">${escapeHtml(label)}: none.</div>`;
  return `<div class="record-subtitle">${escapeHtml(label)}</div>${recordList(rows.map(row => ({ kind: "node", id: row.node_id, title: row.title, subtitle: row.objective, status: row.status })))}`;
}

function linkedClaimRows(records) {
  const rows = array(records);
  if (!rows.length) return `<div class="detail-empty">No Claims are linked.</div>`;
  return recordList(rows.map(row => ({ kind: "claim", id: row.claim_id, title: row.statement, subtitle: compact([row.claim_id, row.claim_type]), status: row.status })));
}

function detailRecordRows(records, kind, idKey, titleKey, statusKey) {
  const rows = array(records);
  if (!rows.length) return `<div class="detail-empty">No records.</div>`;
  return recordList(rows.map(row => ({
    kind,
    id: row[idKey],
    title: formatValue(row[titleKey]) || row[idKey],
    subtitle: row[idKey],
    status: formatValue(row[statusKey]),
  })));
}

function recordList(rows) {
  if (!rows.length) return `<div class="empty">No records.</div>`;
  return `<div class="record-list">${rows.map(row => `<button class="record-row" type="button" data-detail="${escapeHtml(row.kind)}" data-id="${escapeHtml(row.id)}"><div><div class="record-title">${escapeHtml(row.title || row.id)}</div><div class="record-subtitle mono">${escapeHtml(row.subtitle || row.id || "")}</div></div><div class="record-meta">${row.status ? badge(row.status) : ""}${icon("chevron")}</div></button>`).join("")}</div>`;
}

function detailButton(kind, id, label) {
  if (!id) return `<span class="muted">none</span>`;
  return `<button class="record-button mono" type="button" data-detail="${escapeHtml(kind)}" data-id="${escapeHtml(id)}">${escapeHtml(label || id)}</button>`;
}

function pathRow(path, meta, previewPath) {
  if (!path) return "";
  const label = `<div class="mono">${escapeHtml(path)}</div>${meta ? `<div class="path-meta">${escapeHtml(meta)}</div>` : ""}`;
  return `<div class="path-row"><div>${previewPath ? `<button class="path-button" type="button" data-file="${escapeHtml(previewPath)}">${label}</button>` : label}</div>${previewPath ? icon("external") : ""}</div>`;
}

function section(title, meta, body) {
  return `<section class="section"><div class="section-header"><h2>${escapeHtml(title)}</h2><span class="section-meta">${escapeHtml(meta)}</span></div>${body}</section>`;
}

function table(headers, rows) {
  if (!rows.length) return `<div class="empty">No records.</div>`;
  return `<div class="table-wrap"><table><thead><tr>${headers.map(value => `<th>${escapeHtml(value)}</th>`).join("")}</tr></thead><tbody>${rows.map(cells => `<tr>${cells.map(cell => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function detailFields(record) {
  const entries = Object.entries(object(record)).filter(([, value]) => value !== null && value !== undefined && value !== "" && (!Array.isArray(value) || value.length));
  if (!entries.length) return `<div class="detail-empty">No fields.</div>`;
  return `<dl class="detail-grid">${entries.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(formatValue(value))}</dd>`).join("")}</dl>`;
}

function bulletGroup(label, values) {
  const rows = array(values);
  if (!rows.length) return "";
  return `<div class="record-subtitle">${escapeHtml(label)}</div><ul class="bullet-list">${rows.map(value => `<li>${escapeHtml(value)}</li>`).join("")}</ul>`;
}

function filterRecords(records, keys) {
  const query = state.query.trim().toLowerCase();
  if (!query) return array(records);
  return array(records).filter(record => matchesText(record, keys, query));
}

function matchesText(record, keys, query) {
  return keys.some(key => formatValue(record?.[key]).toLowerCase().includes(query));
}

function bindSearch() {
  const input = document.getElementById("search-input");
  if (!input) return;
  input.addEventListener("input", event => {
    state.query = event.target.value;
    if (state.currentView === "files") {
      const target = document.getElementById("locator-results");
      if (target) target.innerHTML = `<div class="empty">Searching research index...</div>`;
      scheduleLocator(state.query.trim());
    } else {
      renderCurrentView();
      const next = document.getElementById("search-input");
      if (next) {
        next.focus();
        next.setSelectionRange(next.value.length, next.value.length);
      }
    }
  });
}

function badge(value) {
  const label = String(value ?? "unknown");
  return `<span class="badge ${tone(label)}">${escapeHtml(label)}</span>`;
}

function tone(value) {
  const normalized = String(value || "").toLowerCase();
  if (["completed", "supported", "pass", "current", "accepted", "normal_termination", "success", "resolved"].includes(normalized)) return "good";
  if (["failed", "fail", "error", "blocked", "contradicted", "blocking", "invalid"].includes(normalized)) return "bad";
  if (["inconclusive", "warning", "stopped", "historical", "stale", "accepted_risk", "submission_ambiguous"].includes(normalized)) return "warn";
  if (["review", "advisory"].includes(normalized)) return "review";
  return "info";
}

function icon(name) {
  return `<svg class="icon" aria-hidden="true"><use href="#icon-${escapeHtml(name)}"/></svg>`;
}

function mono(value) { return `<span class="mono">${escapeHtml(value ?? "")}</span>`; }
function array(value) { return Array.isArray(value) ? value : []; }
function object(value) { return value && typeof value === "object" && !Array.isArray(value) ? value : {}; }
function compact(values) { return array(values).filter(value => value !== null && value !== undefined && String(value).trim()).join(" | "); }
function formatValue(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try { return JSON.stringify(value); } catch (_error) { return String(value); }
}
function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString();
}
function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
}
function pathName(value) { return String(value || "File").split("/").filter(Boolean).pop() || "File"; }
function shortDigest(value) { const text = String(value || ""); return text.startsWith("sha256:") ? text.slice(7, 19) : text.slice(0, 12); }
function recordId(record) { return record.claim_id || record.node_id || record.observation_id || record.spec_id || record.result_id || record.finding_id || record.acceptance_id || record.activity_id || record.task_id || record.control_id || record.intent_id || "Record"; }
function labelForKind(kind) {
  return ({ node: "ResearchNode", claim: "Claim", observation: "Observation", "validation-spec": "GateSpec", "validation-result": "Validation Result", finding: "Finding", acceptance: "Acceptance", activity: "Deterministic Operation", agent: "Subagent Run", control: "Remote Control" })[kind] || "Details";
}
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}

function updateThemeControl() {
  const current = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  const next = current === "dark" ? "light" : "dark";
  themeIcon.querySelector("use").setAttribute("href", current === "dark" ? "#icon-sun" : "#icon-moon");
  themeButton.title = `Use ${next} theme`;
  themeButton.setAttribute("aria-label", `Use ${next} theme`);
}

function toggleTheme() {
  const current = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem(themeStorageKey, next); } catch (_error) {}
  updateThemeControl();
  if (state.currentView === "graphs") requestAnimationFrame(drawAllGraphs);
}

function showToast(message) {
  clearTimeout(state.toastTimer);
  toast.textContent = message;
  toast.classList.add("visible");
  state.toastTimer = setTimeout(() => toast.classList.remove("visible"), 2200);
}

function renderFatal(error) {
  content.innerHTML = `<div class="fatal">${escapeHtml(error.message || error)}</div>`;
  setHealth("invalid", "Unavailable");
}

document.getElementById("sidebar").addEventListener("click", event => {
  const button = event.target.closest("[data-view]");
  if (!button) return;
  state.currentView = button.dataset.view;
  state.query = "";
  state.locator = null;
  state.locatorQuery = null;
  renderCurrentView();
});

content.addEventListener("click", event => {
  const detail = event.target.closest("[data-detail]");
  if (detail) {
    openDetail(detail.dataset.detail, detail.dataset.id);
    return;
  }
  const file = event.target.closest("[data-file]");
  if (file) openFile(file.dataset.file);
});

inspectorBody.addEventListener("click", event => {
  const tab = event.target.closest("[data-node-tab]");
  if (tab && state.detailKind === "node") {
    state.nodeTab = tab.dataset.nodeTab;
    renderNodeDetail(state.detail);
    return;
  }
  const detail = event.target.closest("[data-detail]");
  if (detail) {
    openDetail(detail.dataset.detail, detail.dataset.id);
    return;
  }
  const file = event.target.closest("[data-file]");
  if (file) openFile(file.dataset.file);
});

workspaceSelect.addEventListener("change", async event => {
  clearTimeout(state.liveTimer);
  state.workspaceId = event.target.value;
  state.query = "";
  try {
    await loadWorkspace();
  } catch (error) {
    renderFatal(error);
  } finally {
    scheduleLiveRefresh();
  }
});
themeButton.addEventListener("click", toggleTheme);
refreshButton.addEventListener("click", refreshExplorer);
document.getElementById("close-inspector").addEventListener("click", closeInspector);
document.getElementById("inspector-backdrop").addEventListener("click", closeInspector);
document.addEventListener("keydown", event => { if (event.key === "Escape") closeInspector(); });
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    clearTimeout(state.liveTimer);
  } else {
    scheduleLiveRefresh(0);
  }
});
window.addEventListener("resize", () => { if (state.currentView === "graphs") requestAnimationFrame(drawAllGraphs); });
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", event => {
  let saved = null;
  try { saved = localStorage.getItem(themeStorageKey); } catch (_error) {}
  if (!saved) {
    document.documentElement.dataset.theme = event.matches ? "dark" : "light";
    updateThemeControl();
  }
});

boot();
