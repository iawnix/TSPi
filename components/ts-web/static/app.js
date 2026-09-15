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
  attemptView: { family: "all", kind: "all", state: "all", page: 1 },
  refreshing: false,
  liveTimer: null,
  liveStale: false,
  toastTimer: null,
  researchTree: null,
  researchTreeViewport: null,
  researchMap: null,
  roadmapMode: "map",
  claimMap: null,
  claimMapViewport: null,
  claimMapFilters: null,
  conclusionsMode: "table",
  snapshotReceivedAt: null,
  authToken: "",
  authPrompt: null,
  resolveAuthPrompt: null,
  authChecking: false,
};

const content = document.getElementById("content");
const workspaceMain = document.getElementById("workspace-main");
const workspaceSelect = document.getElementById("workspace-select");
const health = document.getElementById("health");
const healthLabel = document.getElementById("health-label");
const themeButton = document.getElementById("theme-button");
const themeIcon = document.getElementById("theme-icon");
const languageButton = document.getElementById("language-button");
const refreshButton = document.getElementById("refresh-button");
const refreshStatus = document.getElementById("refresh-status");
const inspector = document.getElementById("inspector");
const inspectorKicker = document.getElementById("inspector-kicker");
const inspectorTitle = document.getElementById("inspector-title");
const inspectorBody = document.getElementById("inspector-body");
const authDialog = document.getElementById("auth-dialog");
const authForm = document.getElementById("auth-form");
const authTokenInput = document.getElementById("auth-token");
const authReveal = document.getElementById("auth-reveal");
const authError = document.getElementById("auth-error");
const authWarning = document.getElementById("auth-warning");
const authSubmit = document.getElementById("auth-submit");
const toast = document.getElementById("toast");
const themeStorageKey = "ts-explorer-theme";
const workspaceStorageKey = "ts-explorer-workspace";
const liveRefreshIntervalMs = 5000;
const i18n = window.TSExplorerI18n;

function tr(key, fallback = key, variables = null) {
  if (i18n) return i18n.t(key, fallback, variables);
  if (!variables || typeof fallback !== "string") return fallback;
  return fallback.replace(/\{\{(\w+)\}\}/g, (_match, name) => String(variables[name] ?? ""));
}

function trStatus(value) {
  return i18n ? i18n.status(value) : String(value || "None");
}

function trAttemptKind(value) {
  const normalized = String(value || "primary").toLowerCase();
  return ["primary", "retry", "recalculation"].includes(normalized)
    ? tr(`attempt.kind.${normalized}`, value || "Primary")
    : String(value || tr("attempt.kind.primary", "Primary"));
}

async function api(path) {
  const target = new URL(path, window.location.href);
  if (target.origin !== window.location.origin || !target.pathname.startsWith("/api/")) {
    throw new Error(tr("error.unsafeApiTarget", "Refusing an API request outside this TS Web server."));
  }
  while (true) {
    const headers = { Accept: "application/json" };
    if (state.authToken) headers.Authorization = `Bearer ${state.authToken}`;
    const submittedToken = Boolean(state.authToken);
    let response;
    try {
      response = await fetch(target.href, { cache: "no-store", headers });
    } catch (error) {
      completeAuthentication();
      throw error;
    }
    const text = await response.text();
    if (response.status === 401) {
      await requestAccessToken({ rejected: submittedToken });
      continue;
    }
    completeAuthentication();
    let payload;
    try {
      payload = JSON.parse(text);
    } catch (_error) {
      throw new Error(tr("error.invalidJson", "Invalid JSON from {{path}}.", { path }));
    }
    if (!response.ok) throw new Error(payload.error || `${response.status} ${response.statusText}`);
    return payload;
  }
}

function requestAccessToken({ rejected = false } = {}) {
  state.authToken = "";
  state.authChecking = false;
  authError.hidden = !rejected;
  authWarning.hidden = isEncryptedOrLoopback();
  authSubmit.disabled = false;
  authSubmit.textContent = tr("auth.connect", "Connect");
  setHealth("invalid", tr("health.authRequired", "Authentication required"));
  if (!authDialog.open) authDialog.showModal();
  requestAnimationFrame(() => {
    authTokenInput.focus();
    if (rejected) authTokenInput.select();
  });
  if (!state.authPrompt) {
    state.authPrompt = new Promise(resolve => {
      state.resolveAuthPrompt = resolve;
    });
  }
  return state.authPrompt;
}

function completeAuthentication() {
  if (!state.authChecking) return;
  state.authChecking = false;
  authTokenInput.value = "";
  authReveal.checked = false;
  authTokenInput.type = "password";
  if (authDialog.open) authDialog.close();
}

function isEncryptedOrLoopback() {
  if (window.location.protocol === "https:") return true;
  const hostname = window.location.hostname.toLowerCase();
  return hostname === "localhost" || hostname === "::1" || hostname.startsWith("127.");
}

async function boot() {
  i18n?.setLocale(i18n.getLocale());
  document.documentElement.lang = i18n?.getLocale() || "en";
  setHealth("loading", tr("health.loading", "Loading"));
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
  if (!state.workspaces.length) throw new Error(tr("error.noWorkspace", "No workspace is registered."));
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
  if (!preserveInteraction) {
    state.researchTreeViewport = null;
    state.claimMapViewport = null;
    state.claimMapFilters = null;
  }
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
    throw new Error(tr("error.initialSnapshot", "Initial workspace snapshot is incomplete."));
  }
  state.liveStale = false;
  await applyWorkspaceSnapshot(payload, { preserveInteraction });
  try { localStorage.setItem(workspaceStorageKey, state.workspaceId); } catch (_error) {}
}

async function applyWorkspaceSnapshot(payload, { preserveInteraction = false } = {}) {
  const interaction = preserveInteraction ? captureInteraction() : null;
  state.snapshotReceivedAt = new Date().toISOString();
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
  refreshStatus.textContent = tr("action.refreshing", "Refreshing workspace");
  const previousWorkspaceId = state.workspaceId;
  try {
    await loadWorkspaceCatalog();
    await loadWorkspace({ preserveInteraction: previousWorkspaceId === state.workspaceId });
    refreshStatus.textContent = tr("action.refreshed", "Workspace refreshed");
    showToast(tr("action.refreshed", "Workspace refreshed"));
  } catch (error) {
    refreshStatus.textContent = tr("action.refreshFailed", "Refresh failed");
    showToast(`${tr("action.refreshFailed", "Refresh failed")}: ${error.message || error}`);
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
      if (!payload.view || !payload.graph) throw new Error(tr("error.changedSnapshot", "Changed workspace snapshot is incomplete."));
      await applyWorkspaceSnapshot(payload, { preserveInteraction: true });
      refreshStatus.textContent = tr("action.updated", "Workspace updated automatically");
    } else if (wasStale) {
      updateChrome();
      refreshStatus.textContent = tr("action.restored", "Live refresh restored");
    }
  } catch (error) {
    if (workspaceId === state.workspaceId && state.view) {
      state.liveStale = true;
      updateChrome();
      refreshStatus.textContent = tr("action.stale", "Live refresh unavailable; showing the last valid snapshot");
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
    openAttemptIds: [...inspectorBody.querySelectorAll("details[data-attempt-id][open]")]
      .map(row => row.dataset.attemptId)
      .filter(Boolean),
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
    restoreOpenAttempts(interaction.openAttemptIds);
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
    `<option value="${escapeHtml(row.workspace_id)}">${escapeHtml(row.label || row.workspace_id)}${row.available === false ? ` (${escapeHtml(tr("workspace.incompatibleSuffix", "incompatible"))})` : ""}</option>`
  ).join("");
  workspaceSelect.value = state.workspaceId;
}

function renderUnavailableWorkspace(row) {
  teardownVisualizations();
  setHealth("invalid", tr("health.incompatible", "Incompatible"));
  for (const name of ["phases", "claims", "validation", "findings", "activity"]) setCount(name, 0);
  document.getElementById("sidebar-meta").textContent = "ts-research-kernel/6 required";
  content.innerHTML = [
    renderHeader("unavailable", tr("view.unavailable.subtitle", "Registered workspace cannot be read by this release."), false, "", tr("view.unavailable.title", "Unavailable workspace")),
    `<div class="fatal"><strong>${escapeHtml(tr("view.unavailable.incompatible", "Incompatible workspace"))}</strong><br>${escapeHtml(row.load_error || tr("view.unavailable.message", "The workspace is unavailable."))}</div>`,
  ].join("");
}

function updateChrome() {
  const view = state.view;
  if (state.liveStale) {
    setHealth("stale", tr("health.stale", "Stale"));
  } else {
    setHealth(view.valid ? "valid" : "invalid", view.valid ? tr("health.valid", "Valid") : tr("health.invalid", "Invalid"));
  }
  setCount("phases", view.research_phases.length);
  setCount("claims", view.claims.length);
  setCount("validation", view.validation_results.length);
  setCount("findings", view.findings.length);
  setCount("activity", view.deterministic_activities.length + view.agent_runs.length);
  document.getElementById("sidebar-meta").textContent = view.workspace.kernel_protocol || tr("workspace.fallback", "Research workspace");
  updateSnapshotMeta();
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
  teardownVisualizations();
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
  };
  (renderers[state.currentView] || renderRoadmap)();
  if (resetScroll) workspaceMain.scrollTop = 0;
}

function teardownResearchTree() {
  state.researchTree?.destroy();
  state.researchTree = null;
}

function teardownResearchMap() {
  state.researchMap?.destroy();
  state.researchMap = null;
}

function teardownClaimMap() {
  state.claimMap?.destroy();
  state.claimMap = null;
}

function teardownVisualizations() {
  teardownResearchMap();
  teardownResearchTree();
  teardownClaimMap();
}

function renderHeader(titleKey, subtitleKey, searchable = false, placeholderKey = "", titleFallback = titleKey) {
  const title = tr(`view.${titleKey}.title`, titleFallback);
  const subtitle = tr(`view.${titleKey}.subtitle`, subtitleKey);
  const placeholder = placeholderKey ? tr(`view.${titleKey}.search`, placeholderKey) : "";
  return `<div class="view-header">
    <div class="view-heading"><h1>${escapeHtml(title)}</h1><p>${escapeHtml(subtitle)}</p></div>
    ${searchable ? `<div class="view-tools">${icon("search")}<input class="search-input" id="search-input" type="search" value="${escapeHtml(state.query)}" placeholder="${escapeHtml(placeholder)}" aria-label="${escapeHtml(placeholder)}" aria-keyshortcuts="/ Control+K Meta+K" title="${escapeHtml(tr("search.shortcut", "Press / or Ctrl+K to search"))}"></div>` : ""}
    <div class="snapshot-meta" id="snapshot-meta" aria-label="${escapeHtml(tr("snapshot.lastUpdated", "Last snapshot"))}">${renderSnapshotMeta()}</div>
  </div>`;
}

function renderSnapshotMeta() {
  const view = state.view;
  if (!view) return `<span class="snapshot-state">${escapeHtml(tr("snapshot.awaiting", "Awaiting snapshot"))}</span>`;
  const updated = state.snapshotReceivedAt ? formatTime(state.snapshotReceivedAt) : tr("snapshot.awaiting", "Awaiting snapshot");
  const workspaceRevision = shortRevision(view.workspace_revision);
  const operationalRevision = shortRevision(view.operational_revision);
  const liveLabel = state.liveStale ? tr("snapshot.stale", "Live refresh stale") : tr("snapshot.live", "Live refresh on");
  return `<span class="snapshot-state ${state.liveStale ? "stale" : "live"}">${escapeHtml(liveLabel)}</span><span>${escapeHtml(tr("snapshot.lastUpdated", "Last snapshot"))}: ${escapeHtml(updated)}</span><span>${escapeHtml(tr("snapshot.workspaceRevision", "Workspace revision"))}: <code>${escapeHtml(workspaceRevision)}</code></span><span>${escapeHtml(tr("snapshot.operationalRevision", "Operational revision"))}: <code>${escapeHtml(operationalRevision)}</code></span>`;
}

function updateSnapshotMeta() {
  const target = document.getElementById("snapshot-meta");
  if (target) {
    target.innerHTML = renderSnapshotMeta();
    target.setAttribute("aria-label", tr("snapshot.lastUpdated", "Last snapshot"));
  }
}

function shortRevision(value) {
  const text = String(value || "");
  if (!text) return "—";
  return text.startsWith("sha256:") ? text.slice(7, 19) : text.slice(0, 12);
}

function renderRoadmap() {
  const view = state.view;
  const summary = state.graph.semantic_summary;
  const phases = array(view.research_phases);
  const nodes = array(view.research_nodes);
  const query = state.query.trim().toLowerCase();
  const claimById = new Map(view.claims.map(claim => [claim.claim_id, claim]));
  const phaseById = new Map(phases.map(phase => [phase.phase_id, phase]));
  const matchedNodeIds = new Set(nodes
    .filter(node => matchesNode(node, phaseById.get(node.phase_ref) || {}, claimById, query))
    .map(node => node.node_id));
  const mode = state.roadmapMode === "dag" ? "dag" : "map";
  content.innerHTML = [
    renderHeader("roadmap", "Phases, shared foundations, hypothesis branches, and recorded connectivity.", true, "Filter phases, nodes, claims, or calculations", view.label),
    renderNotices(),
    `<div class="summary-strip">
      ${summaryItem(summary.phase_count, tr("summary.phases", "Research Phases"))}
      ${summaryItem(summary.node_count, tr("summary.nodes", "Research Nodes"))}
      ${summaryItem(summary.claim_count, tr("summary.claims", "Claims"))}
      ${summaryItem(summary.observation_count, tr("summary.observations", "Observations"))}
      ${summaryItem(summary.open_finding_count, tr("summary.findings", "Open Findings"))}
      ${summaryItem(summary.current_acceptance_count, tr("summary.acceptances", "Current Acceptances"))}
    </div>`,
    renderFrontier(view),
    renderStatusLegend(),
    renderRoadmapMode(mode),
    mode === "map"
      ? `<section class="research-map-section"><div id="research-map"></div></section>`
      : `<section class="research-tree-section"><div id="research-tree"></div></section>`,
  ].join("");
  if (mode === "map") {
    const root = document.getElementById("research-map");
    if (!window.TSResearchMap) throw new Error(tr("error.rendererUnavailable", "{{name}} renderer is unavailable.", { name: tr("mode.map", "Research Map") }));
    state.researchMap = window.TSResearchMap.mount(root, {
      projection: state.graph.research_map,
      focusNodeRefs: view.focus.node_refs,
      highlightIds: query ? matchedNodeIds : null,
      selectedId: state.detailKind === "node" ? state.detailId : null,
      onSelectNode: nodeId => openDetail("node", nodeId),
      onSelectClaim: claimId => openDetail("claim", claimId),
      onSelectRelation: relationId => openDetail("relation", relationId),
    });
  } else {
    const root = document.getElementById("research-tree");
    if (!window.TSResearchTree) throw new Error(tr("error.rendererUnavailable", "{{name}} renderer is unavailable.", { name: tr("mode.dag", "Dependency DAG") }));
    state.researchTree = window.TSResearchTree.mount(root, {
      nodes,
      edges: state.graph.research_node_dag.edges,
      phases,
      focusNodeRefs: view.focus.node_refs,
      highlightIds: query ? matchedNodeIds : null,
      selectedId: state.detailKind === "node" ? state.detailId : null,
      viewport: state.researchTreeViewport,
      onViewportChange: viewport => { state.researchTreeViewport = viewport; },
      onSelect: nodeId => openDetail("node", nodeId),
    });
  }
  bindSearch();
}

function renderRoadmapMode(mode) {
  return `<div class="view-mode-bar"><div class="segmented-control" role="tablist" aria-label="${escapeHtml(tr("mode.roadmapAria", "Research Map view"))}">
    <button class="mode-button ${mode === "map" ? "active" : ""}" type="button" role="tab" data-roadmap-mode="map" aria-selected="${mode === "map"}">${icon("roadmap")}<span>${tr("mode.map", "Research Map")}</span></button>
    <button class="mode-button ${mode === "dag" ? "active" : ""}" type="button" role="tab" data-roadmap-mode="dag" aria-selected="${mode === "dag"}">${icon("branch")}<span>${tr("mode.dag", "Dependency DAG")}</span></button>
  </div></div>`;
}

function renderFrontier(view) {
  const nodes = array(view.research_nodes);
  const focused = new Set(array(view.focus?.node_refs));
  const frontier = nodes.find(node => focused.has(node.node_id))
    || nodes.find(node => String(node.status || "").toLowerCase() === "open");
  if (!frontier) {
    return `<section class="frontier-card empty-frontier"><div><span class="frontier-kicker">${tr("frontier.title", "Research frontier")}</span><strong>${tr("frontier.empty", "No focused ResearchNode is recorded.")}</strong></div></section>`;
  }
  const claims = array(frontier.related_claim_refs || frontier.claim_refs);
  return `<section class="frontier-card">
    <div class="frontier-main"><span class="frontier-kicker">${tr("frontier.title", "Research frontier")}</span><h2>${escapeHtml(frontier.title || frontier.node_id)}</h2><p>${escapeHtml(frontier.objective || frontier.deliverable || "")}</p></div>
    <div class="frontier-meta"><span class="frontier-status ${tone(frontier.status)}">${escapeHtml(trStatus(frontier.status))}</span>${claims.length ? `<span class="frontier-claim-label">${tr("frontier.claim", "Claim scope")}</span><div class="frontier-claims">${claims.slice(0, 3).map(ref => detailButton("claim", ref, ref)).join("")}</div>` : ""}<span class="frontier-next">${tr("frontier.next", "Follow the linked node for evidence and decisions.")}</span></div>
    <button class="frontier-open" type="button" data-detail="node" data-id="${escapeHtml(frontier.node_id)}" aria-label="${escapeHtml(frontier.node_id)}">${icon("chevron")}</button>
  </section>`;
}

function renderStatusLegend() {
  return `<div class="status-legend" aria-label="${tr("legend.title", "Status key")}"><span class="status-legend-title">${tr("legend.title", "Status key")}</span><span class="legend-item good"><i></i>${tr("legend.supported", "Supported")}</span><span class="legend-item info"><i></i>${tr("legend.proposed", "Proposed")}</span><span class="legend-item open"><i></i>${tr("legend.open", "Open")}</span><span class="legend-item warn"><i></i>${tr("legend.warning", "Warning")}</span><span class="legend-item bad"><i></i>${tr("legend.blocking", "Blocking")}</span></div>`;
}

function renderNotices() {
  const rows = [];
  if (!state.view.valid) {
    rows.push(notice("error", "findings", tr("notice.validationFindings", "{{count}} workspace validation finding(s)", { count: state.view.validation_findings.length }), tr("detail.workspaceInvalid", "Workspace invalid")));
  }
  if (state.view.unresolved_controls.length) {
    rows.push(notice("error", "activity", tr("notice.unresolvedControls", "{{count}} unresolved remote control effect(s)", { count: state.view.unresolved_controls.length }), tr("detail.reconcileReplay", "Reconcile before replay")));
  }
  if (state.view.retryable_controls.length) {
    const count = state.view.retryable_controls.length;
    const intentIds = [...new Set(state.view.retryable_controls
      .map(row => row.intent_id)
      .filter(Boolean))];
    const subject = count === 1 && intentIds.length === 1
      ? `${intentIds[0]} ${tr("detail.remoteSubmissionDidNotStart", "remote submission did not start")}`
      : `${count} ${tr("detail.remoteSubmissionsDidNotStart", "remote submissions did not start")}`;
    rows.push(notice("warning", "activity", subject, tr("detail.retryRemote", "Fix remote configuration, then retry")));
  }
  if (array(state.view.calculation_attempt_integrity_findings).length) {
    rows.push(notice(
      "error",
      "activity",
      tr("notice.attemptIntegrity", "{{count}} calculation Attempt integrity finding(s)", { count: array(state.view.calculation_attempt_integrity_findings).length }),
      tr("detail.inspectNode", "Inspect the affected Node before continuing"),
    ));
  }
  if (state.view.pending_review_dispositions.length) {
    rows.push(notice("info", "conclusions", tr("notice.pendingReviews", "{{count}} Review response(s) pending Root disposition", { count: state.view.pending_review_dispositions.length }), tr("detail.advisoryOnly", "Advisory only")));
  }
  if (state.view.acceptance_summary.stale_refs.length) {
    rows.push(notice("warning", "validation", tr("notice.staleAcceptances", "{{count}} historical acceptance record(s) are stale", { count: state.view.acceptance_summary.stale_refs.length }), tr("detail.reassessAcceptance", "Reassess before acceptance")));
  }
  return rows.length ? `<div class="notice-stack">${rows.join("")}</div>` : "";
}

function notice(kind, iconName, message, tail) {
  return `<div class="notice ${kind}">${icon(iconName)}<span>${escapeHtml(message)}</span><code>${escapeHtml(tail)}</code></div>`;
}

function summaryItem(value, label) {
  return `<div class="summary-item"><div class="summary-value">${escapeHtml(value)}</div><div class="summary-label">${escapeHtml(label)}</div></div>`;
}

function matchesNode(node, phase, claimById, query) {
  if (!query) return true;
  const claims = array(node.related_claim_refs).map(ref => claimById.get(ref)).filter(Boolean);
  return matchesText(node, ["node_id", "title", "objective", "deliverable", "status", "tags", "opening_decision", "result"], query)
    || matchesText(node, ["attempts"], query)
    || matchesText(phase, ["phase_id", "title", "objective"], query)
    || claims.some(claim => matchesText(claim, ["claim_id", "statement", "claim_type", "status"], query));
}

function renderConclusions() {
  const graphClaims = new Map(state.graph.claim_graph.nodes.map(row => [row.claim_id, row]));
  const rows = filterRecords(state.view.claims, ["claim_id", "claim_type", "statement", "status", "assumptions", "falsifiers", "tags"]);
  const mode = state.conclusionsMode === "map" ? "map" : "table";
  const matchedClaimIds = new Set(rows.map(claim => claim.claim_id));
  const body = mode === "table"
    ? section(tr("section.claims", "Claims"), `${rows.length}`, table(
      [tr("table.claim", "Claim"), "Statement", "Type", "Status", tr("table.acceptance", "Acceptance")],
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
    ))
    : `<section class="claim-map-section"><div id="claim-map"></div></section>`;
  content.innerHTML = renderHeader("conclusions", "Claims remain separate from execution nodes and carry assumptions, falsifiers, validation, and acceptance.", true, "Filter claims")
    + renderNotices()
    + renderStatusLegend()
    + renderConclusionsMode(mode)
    + body;
  if (mode === "map") {
    const root = document.getElementById("claim-map");
    if (!window.TSClaimMap) throw new Error(tr("error.rendererUnavailable", "{{name}} renderer is unavailable.", { name: tr("mode.claimMap", "Claim Map") }));
    state.claimMap = window.TSClaimMap.mount(root, {
      nodes: state.graph.claim_graph.nodes,
      edges: state.graph.claim_graph.edges,
      focusClaimRefs: state.view.focus.claim_refs,
      highlightIds: state.query.trim() ? matchedClaimIds : null,
      selectedId: state.detailKind === "claim" ? state.detailId : null,
      selectedRelationId: state.detailKind === "relation" ? state.detailId : null,
      filters: state.claimMapFilters,
      viewport: state.claimMapViewport,
      onFiltersChange: filters => { state.claimMapFilters = filters; },
      onViewportChange: viewport => { state.claimMapViewport = viewport; },
      onSelectClaim: claimId => openDetail("claim", claimId),
      onSelectRelation: relationId => openDetail("relation", relationId),
    });
  }
  bindSearch();
}

function renderConclusionsMode(mode) {
  return `<div class="view-mode-bar"><div class="segmented-control" role="tablist" aria-label="${escapeHtml(tr("mode.conclusionsAria", "Scientific Conclusions view"))}">
    <button class="mode-button ${mode === "table" ? "active" : ""}" type="button" role="tab" data-conclusions-mode="table" aria-selected="${mode === "table"}">${icon("conclusions")}<span>${tr("mode.table", "Table")}</span></button>
    <button class="mode-button ${mode === "map" ? "active" : ""}" type="button" role="tab" data-conclusions-mode="map" aria-selected="${mode === "map"}">${icon("graphs")}<span>${tr("mode.claimMap", "Map")}</span></button>
  </div></div>`;
}

function renderValidation() {
  const specs = filterRecords(state.view.proof_specs, ["proof_id", "title", "dimension", "target_claim_ref", "template_ref"]);
  const results = filterRecords(state.view.validation_results, ["result_id", "dimension", "verdict", "target_claim_ref", "proof_ref"]);
  const acceptances = filterRecords(state.view.acceptances, ["acceptance_id", "claim_ref", "profile_id", "current", "stale_reasons"]);
  content.innerHTML = renderHeader("validation", "Frozen ProofSpecs, deterministic results, and revision-bound acceptance records.", true, "Filter validation records")
    + renderNotices()
    + section(tr("section.proofSpecs", "ProofSpecs"), `${specs.length}`, table(["ProofSpec", "Title", "Dimension", "Target Claim"], specs.map(row => [detailButton("validation-spec", row.proof_id, row.proof_id), escapeHtml(row.title), mono(row.dimension), detailButton("claim", row.target_claim_ref, row.target_claim_ref)])))
    + section(tr("section.validationResults", "Validation Results"), `${results.length}`, table(["Result", "Dimension", "Verdict", "Target Claim", "ProofSpec"], results.map(row => [detailButton("validation-result", row.result_id, row.result_id), mono(row.dimension), badge(row.verdict), detailButton("claim", row.target_claim_ref, row.target_claim_ref), mono(row.proof_ref)])))
    + section(tr("section.acceptances", "Acceptance Records"), `${acceptances.length}`, table(["Acceptance", "Claim", "Profile", "State"], acceptances.map(row => [detailButton("acceptance", row.acceptance_id, row.acceptance_id), detailButton("claim", row.claim_ref, row.claim_ref), mono(row.profile_id || tr("table.profile", "Profile")), badge(row.current ? "current" : "historical")])))
    ;
  bindSearch();
}

function renderFindings() {
  const rows = filterRecords(state.view.findings, ["finding_id", "finding_type", "severity", "status", "statement", "claim_refs", "node_refs"]);
  content.innerHTML = renderHeader("findings", "Explicit anomalies, limitations, conflicts, and unresolved questions.", true, "Filter findings")
    + renderNotices()
    + section(tr("section.scientificFindings", "Scientific Findings"), `${rows.length}`, table(["Finding", "Statement", "Severity", "Status", "Scope"], rows.map(row => [
      detailButton("finding", row.finding_id, row.finding_id),
      `<div class="statement">${escapeHtml(row.statement)}</div>`,
      badge(row.severity),
      badge(row.status),
      `<div class="mono">${escapeHtml([...array(row.claim_refs), ...array(row.node_refs)].join(", ") || tr("detail.none", "none"))}</div>`,
    ])));
  bindSearch();
}

function renderActivity() {
  const activities = filterRecords(state.view.deterministic_activities, ["activity_id", "kind", "operation", "status", "summary", "node_refs"]);
  const runs = filterRecords(state.view.agent_runs, ["task_id", "role", "operation", "status", "summary", "claim_refs", "node_refs"]);
  const attemptFindings = filterRecords(state.view.calculation_attempt_integrity_findings, ["scope", "path", "message", "node_refs", "intent_id"]);
  content.innerHTML = renderHeader("activity", "Deterministic host operations and isolated Compute or Review runs.", true, "Filter operations and runs")
    + renderNotices()
    + section(tr("section.operations", "Deterministic Operations"), `${activities.length}`, recordList(activities.map(row => ({
      kind: "activity",
      id: row.activity_id,
      title: compact([row.kind, row.operation]) || tr("detail.deterministicOperations", "Deterministic operation"),
      subtitle: row.summary || array(row.node_refs).join(", "),
      status: row.status,
    }))))
    + section(tr("section.runs", "Subagent Runs"), `${runs.length}`, recordList(runs.map(row => ({
      kind: "agent",
      id: row.task_id,
      title: compact([row.role, row.operation]) || tr("detail.subagentRuns", "Subagent run"),
      subtitle: row.summary || compact([...array(row.claim_refs), ...array(row.node_refs)]),
      status: row.status,
    }))))
    + section(tr("section.integrity", "Attempt Integrity"), `${attemptFindings.length}`, recordList(attemptFindings.map(row => ({
      kind: "finding",
      id: row.path,
      title: compact([row.scope, row.intent_id]) || tr("detail.attemptPath", "Attempt path"),
      subtitle: compact([row.path, ...array(row.node_refs), row.message]),
      status: "invalid",
    }))));
  bindSearch();
}

function renderResearchFiles() {
  const query = state.query.trim();
  content.innerHTML = renderHeader("files", "Locate canonical records, ResearchNodes, calculation attempts, and artifact-bound files.", true, "Search claim_1, node_2, calc_3, concept, or path")
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
  if (state.locatorQuery !== query || !state.locator) return `<div class="empty">${escapeHtml(tr("detail.loadingIndex", "Loading research index..."))}</div>`;
  const locator = state.locator;
  const summary = `<div class="locator-summary"><span>${array(locator.matches).length} ${escapeHtml(tr("locator.matches", "matches"))}</span><span>${escapeHtml(locator.query_mode || "index")}</span><span>${escapeHtml(locator.query || tr("locator.index", "workspace index"))}</span></div>`;
  if (!array(locator.matches).length) return summary + `<div class="empty">${escapeHtml(tr("detail.noMatchingArtifacts", "No matching research records or artifacts."))}</div>`;
  return summary + locator.matches.map(renderLocatorMatch).join("");
}

function renderLocatorMatch(match) {
  const refs = [
    ...array(match.claim_refs).map(ref => `<span class="ref-chip">${escapeHtml(tr("locator.claim", "Claim"))} ${escapeHtml(ref)}</span>`),
    ...array(match.node_refs).map(ref => `<span class="ref-chip">${escapeHtml(tr("locator.node", "Node"))} ${escapeHtml(ref)}</span>`),
    ...array(match.observation_refs).map(ref => `<span class="ref-chip">${escapeHtml(tr("locator.observation", "Observation"))} ${escapeHtml(ref)}</span>`),
  ].join("");
  const directories = array(match.directories).map(row => pathRow(row.path, row.label || tr("locator.directory", "directory"), null)).join("");
  const attempts = array(match.attempts).map(row => `<div class="record-row"><div><div class="record-title mono">${escapeHtml(row.intent_id || row.ref)}</div><div class="record-subtitle">${escapeHtml(compact([capabilityLabel(row), row.state]))}</div></div>${row.state ? badge(row.state) : ""}</div>`).join("");
  const artifacts = array(match.artifacts).map(row => pathRow(row.path, compact([row.artifact_id, row.relation, row.sha256 && shortDigest(row.sha256)]), row.preview)).join("");
  const files = array(match.files).map(row => pathRow(row.path, formatBytes(row.size || row.size_bytes || 0), row.preview)).join("");
  return `<section class="locator-match">
    <div class="locator-head"><div><strong>${escapeHtml(match.ref || match.label || tr("detail.resultRecord", "Result"))}</strong><div class="record-subtitle">${escapeHtml(match.kind || tr("detail.record", "record"))}</div></div>${refs ? `<div class="ref-chips">${refs}</div>` : ""}</div>
    <div class="locator-groups">
      ${directories ? `<div class="locator-group"><h3>${escapeHtml(tr("detail.directories", "Directories"))}</h3>${directories}</div>` : ""}
      ${attempts ? `<div class="locator-group"><h3>${escapeHtml(tr("detail.calculationAttempts", "Calculation Attempts"))}</h3>${attempts}</div>` : ""}
      ${artifacts ? `<div class="locator-group wide"><h3>${escapeHtml(tr("detail.artifactsBindings", "Artifacts and Semantic Bindings"))}</h3>${artifacts}</div>` : ""}
      ${files ? `<div class="locator-group wide"><h3>${escapeHtml(tr("detail.files", "Files"))}</h3>${files}</div>` : ""}
    </div>
  </section>`;
}

async function openDetail(kind, id, { preserveNodeTab = false } = {}) {
  const workspaceId = state.workspaceId;
  state.detail = null;
  state.detailKind = kind;
  state.detailId = id;
  state.filePath = null;
  if (!preserveNodeTab || kind !== "node") {
    state.nodeTab = "overview";
    resetAttemptView();
  }
  inspectorKicker.textContent = labelForKind(kind);
  inspectorTitle.textContent = id;
  inspectorBody.innerHTML = `<div class="empty">${escapeHtml(tr("detail.loading", "Loading details..."))}</div>`;
  document.body.classList.add("inspector-open");
  inspector.setAttribute("aria-hidden", "false");
  try {
    let payload;
    if (kind === "node" || kind === "claim") {
      payload = await api(`/api/workspace/${encodeURIComponent(state.workspaceId)}/${kind}/${encodeURIComponent(id)}`);
    } else {
      payload = localRecord(kind, id);
    }
    if (workspaceId !== state.workspaceId || state.detailKind !== kind || state.detailId !== id) return false;
    state.detail = payload;
    renderInspector();
    return true;
  } catch (error) {
    if (workspaceId !== state.workspaceId || state.detailKind !== kind || state.detailId !== id) return false;
    inspectorBody.innerHTML = `<div class="fatal">${escapeHtml(error.message || error)}</div>`;
    return false;
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
  if (state.detailKind === "relation") {
    renderRelationDetail(state.detail);
    return;
  }
  if (state.detailKind === "file") {
    renderFileDetail(state.detail);
    return;
  }
  const record = state.detail || {};
  inspectorKicker.textContent = labelForKind(state.detailKind);
  inspectorTitle.textContent = recordId(record);
  inspectorBody.innerHTML = `<section class="detail-section">${detailFields(record)}</section>`;
}

function renderNodeDetail(payload) {
  const node = payload.research_node;
  inspectorKicker.textContent = `${payload.phase.phase_id} | ${node.node_id}`;
  inspectorTitle.textContent = node.title;
  const tabs = ["overview", "conclusions", "evidence", "runs", "files", "history"];
  const tabLabels = Object.fromEntries(tabs.map(tab => [tab, tr(`tab.${tab}`, tab)]));
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
  return `<section class="detail-section"><h3>${escapeHtml(tr("detail.researchDecision", "Research Decision"))}</h3><div class="detail-callout info"><div class="detail-meta"><span class="mono">${escapeHtml(opening.decision_id || node.created_by_decision)}</span><span>${escapeHtml(formatTime(opening.created_at || node.created_at))}</span></div><p class="detail-copy">${escapeHtml(opening.rationale || node.objective)}</p></div></section>
    <section class="detail-section"><h3>${escapeHtml(tr("detail.researchContract", "Research Contract"))}</h3><dl class="detail-grid"><dt>${escapeHtml(tr("detail.phase", "Phase"))}</dt><dd><span class="mono">${escapeHtml(payload.phase.phase_id)}</span> ${escapeHtml(payload.phase.title)}</dd><dt>${escapeHtml(tr("detail.question", "Question"))}</dt><dd>${escapeHtml(node.objective)}</dd><dt>${escapeHtml(tr("detail.principalDeliverable", "Principal deliverable"))}</dt><dd>${escapeHtml(node.deliverable)}</dd><dt>${escapeHtml(tr("detail.primaryClaim", "Primary Claim"))}</dt><dd>${node.primary_claim_ref ? detailButton("claim", node.primary_claim_ref, node.primary_claim_ref) : escapeHtml(tr("detail.none", "none"))}</dd></dl></section>
    ${renderAttemptOverview(node)}
    ${renderNodeDispatch(payload)}
    <section class="detail-section"><h3>${escapeHtml(tr("detail.outcome", "Outcome"))}</h3>${result.outcome ? `<div class="detail-callout ${tone(result.outcome)}"><div class="detail-meta">${badge(result.outcome)}<span>${escapeHtml(formatTime(result.completed_at))}</span></div><p class="detail-copy">${escapeHtml(result.summary)}</p>${bulletGroup(tr("detail.openQuestions", "Open Questions"), result.open_questions)}</div>` : `<div class="detail-empty">${escapeHtml(tr("detail.noTerminalResult", "No terminal result has been recorded."))}</div>`}</section>
    <section class="detail-section"><h3>${escapeHtml(tr("detail.lineage", "Lineage"))}</h3>${linkedNodeGroup(tr("detail.dependsOn", "Depends on"), payload.dependencies)}${linkedNodeGroup(tr("detail.continuedBy", "Continued by"), payload.dependents)}</section>
    <section class="detail-section"><h3>${escapeHtml(tr("detail.relatedClaims", "Related Claims"))}</h3>${linkedClaimRows(payload.claims)}</section>`;
}

function renderNodeConclusions(payload) {
  const node = payload.research_node;
  const result = object(node.result);
  return `<section class="detail-section"><h3>${escapeHtml(tr("detail.nodeOutcome", "Node Outcome"))}</h3>${result.summary ? `<div class="detail-callout ${tone(result.outcome)}"><p class="detail-copy">${escapeHtml(result.summary)}</p></div>` : `<div class="detail-empty">${escapeHtml(tr("detail.noConclusion", "This Node has no terminal conclusion."))}</div>`}</section>
    <section class="detail-section"><h3>${escapeHtml(tr("section.claims", "Claims"))}</h3>${linkedClaimRows(payload.claims)}</section>
    <section class="detail-section"><h3>${escapeHtml(tr("section.scientificFindings", "Findings"))}</h3>${detailRecordRows(payload.findings, "finding", "finding_id", "statement", "status")}</section>`;
}

function renderNodeEvidence(payload) {
  return `<section class="detail-section"><h3>${escapeHtml(tr("detail.observations", "Observations"))}</h3>${detailRecordRows(payload.observations, "observation", "observation_id", "summary", "concept_id")}</section>
    <section class="detail-section"><h3>${escapeHtml(tr("detail.frozenProofSpecs", "Frozen ProofSpecs"))}</h3>${detailRecordRows(payload.proof_specs, "validation-spec", "proof_id", "title", "dimension")}</section>
    <section class="detail-section"><h3>${escapeHtml(tr("detail.validationResults", "Validation Results"))}</h3>${detailRecordRows(payload.validation_results, "validation-result", "result_id", "dimension", "verdict")}</section>
    ${renderScientificAnalyses(payload)}`;
}

function renderNodeDispatch(payload) {
  const record = array(payload.node_dispatch).at(-1);
  if (!record) return "";
  const label = record.paused === true ? tr("detail.dispatchPaused", "Further dispatch paused") : record.paused === false ? tr("detail.dispatchResumed", "Further dispatch enabled") : tr("detail.dispatchUnknown", "Dispatch state needs inspection");
  return `<section class="detail-section"><h3>${escapeHtml(label)}</h3><p>${escapeHtml(record.rationale || record.integrity_error || "")}</p><p class="muted">${escapeHtml(tr("detail.dispatchIndependent", "Existing jobs remain independently inspectable and cancellable. Scientific status is unchanged."))}</p></section>`;
}

function renderScientificAnalyses(payload) {
  const analyses = array(payload.scientific_analyses?.analyses);
  if (!analyses.length) return "";
  return `<section class="detail-section"><h3>${escapeHtml(tr("detail.scientificAnalyses", "Scientific analyses"))}</h3>${analyses.map(row => `<div class="detail-callout"><div class="detail-meta"><span>${escapeHtml(row.capability)}@${escapeHtml(row.version)}</span>${badge(row.verdict)}</div>${pathRow(row.path, row.artifact_id, {available: true})}${bulletGroup(tr("detail.limitations", "Limitations"), row.limitations)}</div>`).join("")}</section>`;
}

function renderAttemptOverview(node) {
  const attempts = array(node.attempts);
  const summary = object(node.attempt_summary);
  const latest = attempts.at(-1);
  if (!attempts.length) {
    return `<section class="detail-section"><h3>${escapeHtml(tr("detail.calculationRuns", "Calculation Runs"))}</h3><div class="detail-empty">${escapeHtml(tr("map.noAttempts", "No calculation attempts"))}</div></section>`;
  }
  const states = Object.entries(object(summary.states));
  return `<section class="detail-section"><div class="detail-section-heading"><h3>${escapeHtml(tr("detail.calculationRuns", "Calculation Runs"))}</h3><button class="record-button" type="button" data-node-tab="runs">${escapeHtml(tr("detail.openRuns", "Open Runs"))}</button></div>
    <dl class="attempt-overview"><div><dt>${escapeHtml(tr("detail.attempts", "Attempts"))}</dt><dd>${Number(summary.attempt_count) || attempts.length}</dd></div><div><dt>${escapeHtml(tr("detail.families", "Families"))}</dt><dd>${Number(summary.family_count) || 1}</dd></div><div><dt>${escapeHtml(tr("detail.latest", "Latest"))}</dt><dd><span class="mono">${escapeHtml(latest.intent_id)}</span> ${badge(attemptDisplayState(latest))}</dd></div></dl>
    ${states.length ? `<div class="attempt-state-summary">${states.map(([name, count]) => `${badge(name)}<span>${Number(count) || 0}</span>`).join("")}</div>` : ""}
  </section>`;
}

function renderNodeRuns(payload) {
  const node = payload.research_node;
  return `${renderAttemptTimeline(node.attempts)}
    ${renderAttemptIntegrityFindings(payload.calculation_attempt_integrity_findings)}
    <section class="detail-section"><h3>${escapeHtml(tr("detail.deterministicOperations", "Deterministic Operations"))}</h3>${detailRecordRows(node.activities, "activity", "activity_id", "operation", "status")}</section>
    <section class="detail-section"><h3>${escapeHtml(tr("detail.subagentRuns", "Subagent Runs"))}</h3>${detailRecordRows(payload.agent_runs, "agent", "task_id", "operation", "status")}</section>
    <section class="detail-section"><h3>${escapeHtml(tr("detail.unresolvedControls", "Unresolved Controls"))}</h3>${detailRecordRows(node.unresolved_controls, "control", "control_id", "operation", "state")}</section>
    <section class="detail-section"><h3>${escapeHtml(tr("detail.retryableControls", "Retryable Controls"))}</h3>${detailRecordRows(node.retryable_controls, "control", "control_id", "operation", "error_class")}</section>`;
}

function renderAttemptIntegrityFindings(value) {
  const findings = array(value);
  if (!findings.length) return "";
  const message = findings.length === 1
    ? tr("detail.oneAttemptInspection", "One Attempt path requires inspection.")
    : `${findings.length} ${tr("detail.attemptPathsInspection", "Attempt paths require inspection.")}`;
  return `<section class="detail-section"><h3>${escapeHtml(tr("detail.attemptIntegrity", "Attempt Integrity"))}</h3><div class="detail-callout error"><div class="detail-copy">${escapeHtml(message)}</div>${findings.map(row => `<div class="record-row"><div><div class="record-title mono">${escapeHtml(row.path || tr("detail.attemptParent", "Attempt parent"))}</div><div class="record-subtitle">${escapeHtml(row.message || tr("detail.integrityCheckFailed", "Integrity check failed"))}</div></div>${badge("invalid")}</div>`).join("")}</div></section>`;
}

function renderAttemptTimeline(value) {
  const attempts = array(value);
  if (!attempts.length) {
    return `<section class="detail-section"><h3>${escapeHtml(tr("detail.attemptFamilies", "Attempt Families"))}</h3><div class="detail-empty">${escapeHtml(tr("map.noAttempts", "No calculation attempts"))}</div></section>`;
  }
  const view = window.TSAttemptTimeline.project(attempts, state.attemptView);
  state.attemptView = { ...view.filters, page: view.page };
  const familyOptions = view.choices.families.map(id => {
    const attempt = attempts.find(row => row.family_root_id === id || row.intent_id === id);
    return { value: id, label: `${tr("detail.family", "Family")} ${attempt?.family_index || "?"} · ${id}` };
  });
  return `<section class="detail-section attempt-timeline-section">
    <div class="detail-section-heading"><h3>${escapeHtml(tr("detail.attemptFamilies", "Attempt Families"))}</h3><span>${escapeHtml(tr("detail.countStatus", "{{shown}} of {{total}}", { shown: view.total, total: attempts.length }))}</span></div>
    <div class="attempt-toolbar">${icon("filter")}${attemptFilter("family", tr("detail.family", "Family"), familyOptions, view.filters.family)}${attemptFilter("kind", tr("detail.kind", "Kind"), view.choices.kinds.map(value => ({ value, label: trAttemptKind(value) })), view.filters.kind)}${attemptFilter("state", tr("detail.state", "State"), view.choices.states.map(value => ({ value, label: trStatus(value) })), view.filters.state)}</div>
    ${view.rows.length ? renderAttemptGroups(view.rows) : `<div class="detail-empty">${escapeHtml(tr("detail.noAttemptMatch", "No Attempts match these filters."))}</div>`}
    ${renderAttemptPagination(view)}
  </section>`;
}

function attemptFilter(name, label, options, selected) {
  const filterLabel = `${tr("detail.filterAttempts", "Filter Attempts by")} ${label}`;
  return `<label class="attempt-filter"><span class="sr-only">${escapeHtml(label)}</span><select data-attempt-filter="${escapeHtml(name)}" aria-label="${escapeHtml(filterLabel)}"><option value="all">${escapeHtml(tr("detail.all", "All"))} ${escapeHtml(label)}</option>${options.map(option => `<option value="${escapeHtml(option.value)}" ${option.value === selected ? "selected" : ""}>${escapeHtml(option.label)}</option>`).join("")}</select></label>`;
}

function renderAttemptGroups(rows) {
  const groups = [];
  for (const attempt of rows) {
    const familyId = attempt.family_root_id || attempt.intent_id;
    let group = groups.find(row => row.id === familyId);
    if (!group) {
      group = { id: familyId, index: attempt.family_index, attempts: [] };
      groups.push(group);
    }
    group.attempts.push(attempt);
  }
  return `<div class="attempt-family-list">${groups.map(group => `<section class="attempt-family"><div class="attempt-family-heading"><span>${icon("branch")} ${escapeHtml(tr("detail.family", "Family"))} ${escapeHtml(group.index || "?")}</span><span class="mono">${escapeHtml(group.id)}</span></div><div class="attempt-list">${group.attempts.map(renderAttempt).join("")}</div></section>`).join("")}</div>`;
}

function renderAttemptPagination(view) {
  if (view.pageCount <= 1) return "";
  const previous = tr("detail.previousPage", "Previous Attempt page");
  const next = tr("detail.nextPage", "Next Attempt page");
  return `<nav class="attempt-pagination" aria-label="${escapeHtml(tr("detail.attemptPages", "Attempt pages"))}"><button class="icon-button" type="button" data-attempt-page="${view.page - 1}" title="${escapeHtml(previous)}" aria-label="${escapeHtml(previous)}" ${view.page <= 1 ? "disabled" : ""}>${icon("arrow-left")}</button><span>${escapeHtml(tr("detail.pageStatus", "Page {{page}} of {{pages}}", { page: view.page, pages: view.pageCount }))}</span><button class="icon-button" type="button" data-attempt-page="${view.page + 1}" title="${escapeHtml(next)}" aria-label="${escapeHtml(next)}" ${view.page >= view.pageCount ? "disabled" : ""}>${icon("arrow-right")}</button></nav>`;
}

function renderAttempt(attempt) {
  const lineage = object(attempt.lineage);
  const parameters = object(attempt.parameters);
  const executor = object(attempt.executor);
  const execution = object(attempt.execution_target);
  const resources = object(execution.resources);
  const stateLabel = attemptDisplayState(attempt);
  const purpose = attempt.purpose || capabilityLabel(attempt) || tr("detail.calculationAttempts", "Calculation attempt");
  const source = lineage.source_intent_id;
  const sourceNode = lineage.source_node;
  const sourceLabel = [sourceNode, source].filter(Boolean).join(" / ");
  const sourceField = source && sourceNode
    ? `<button class="attempt-source" type="button" data-attempt-node="${escapeHtml(sourceNode)}" data-attempt-open="${escapeHtml(source)}">${escapeHtml(sourceLabel)}</button>`
    : escapeHtml(sourceLabel || tr("detail.none", "none"));
  const error = attempt.error_class ? `<span class="attempt-error">${badge(attempt.error_class)}</span>` : "";
  const inputRefs = array(attempt.input_bindings).map(binding => compact([binding.input_role, binding.artifact_id]));
  const changedFields = array(lineage.changed_fields);
  const runs = array(attempt.runs);
  return `<details class="attempt-disclosure ${tone(stateLabel)}" data-attempt-id="${escapeHtml(attempt.intent_id)}">
    <summary>
      <span class="attempt-icon">${icon("flask")}</span>
      <span class="attempt-summary-copy"><span class="attempt-summary-title"><span class="mono">${escapeHtml(attempt.intent_id)}</span><span>${escapeHtml(trAttemptKind(attempt.attempt_kind || "primary"))}</span></span><span class="attempt-summary-purpose">${escapeHtml(purpose)}</span></span>
      <span class="attempt-summary-state">${badge(stateLabel)}${error}</span>
      <span class="attempt-chevron">${icon("chevron")}</span>
    </summary>
    <div class="attempt-body">
      <dl class="detail-grid attempt-grid">
        <dt>${escapeHtml(tr("detail.capability", "Capability"))}</dt><dd>${escapeHtml(capabilityLabel(attempt) || tr("detail.unknown", "unknown"))}</dd>
        <dt>${escapeHtml(tr("detail.executor", "Executor"))}</dt><dd>${escapeHtml(compact([executor.backend, executor.task_type]) || tr("detail.notShown", "not shown"))}</dd>
        <dt>${escapeHtml(tr("detail.method", "Method"))}</dt><dd>${escapeHtml(compact([attempt.method, attempt.basis]) || tr("detail.notRecorded", "not recorded"))}</dd>
        <dt>${escapeHtml(tr("detail.expectedOutputs", "Expected outputs"))}</dt><dd>${escapeHtml(array(attempt.expected_output_roles).join(", ") || tr("detail.notRecorded", "not recorded"))}</dd>
        <dt>${escapeHtml(tr("detail.family", "Family"))}</dt><dd>${escapeHtml(tr("detail.family", "Family"))} ${escapeHtml(attempt.family_index || "?")} · <span class="mono">${escapeHtml(attempt.family_root_id || attempt.intent_id)}</span></dd>
        <dt>${escapeHtml(tr("detail.lineage", "Lineage"))}</dt><dd>${escapeHtml(trAttemptKind(lineage.relation || attempt.attempt_kind || "primary"))} · ${sourceField}</dd>
        <dt>${escapeHtml(tr("detail.reason", "Reason"))}</dt><dd>${escapeHtml(lineage.reason || (attempt.attempt_kind === "primary" ? tr("detail.primaryAttempt", "Primary Attempt") : tr("detail.notRecorded", "not recorded")))}</dd>
        <dt>${escapeHtml(tr("detail.programState", "Program state"))}</dt><dd>${escapeHtml(trStatus(attempt.program_status || "unknown"))}</dd>
        <dt>${escapeHtml(tr("detail.execution", "Execution"))}</dt><dd>${escapeHtml(compact([execution.kind, execution.profile]) || tr("detail.notRecorded", "not recorded"))}</dd>
        <dt>${escapeHtml(tr("detail.job", "Job"))}</dt><dd>${escapeHtml(attempt.job_id || tr("detail.notRecorded", "not recorded"))}</dd>
        <dt>${escapeHtml(tr("detail.duration", "Duration"))}</dt><dd>${escapeHtml(formatDuration(attempt.duration_seconds))}</dd>
        <dt>${escapeHtml(tr("detail.observed", "Observed"))}</dt><dd>${escapeHtml(formatTime(attempt.finished_at || attempt.observed_at) || tr("detail.notRecorded", "not recorded"))}</dd>
        <dt>${escapeHtml(tr("detail.subagentRuns", "Subagent runs"))}</dt><dd>${runs.length}</dd>
      </dl>
      ${renderAttemptRefs(tr("detail.scientificChanges", "Scientific changes"), changedFields)}
      ${renderAttemptRefs(tr("detail.inputArtifacts", "Input artifacts"), inputRefs)}
      ${renderAttemptRefs(tr("detail.expectedArtifacts", "Expected artifacts"), attempt.expected_artifacts)}
      ${renderObservationCandidates(attempt.observation_candidates)}
      ${attempt.scientific_intent_digest ? `<div class="attempt-digest"><span>${escapeHtml(tr("detail.scientificIntent", "Scientific intent"))}</span><code>${escapeHtml(shortDigest(attempt.scientific_intent_digest))}</code></div>` : ""}
      ${Object.keys(parameters).length ? `<details class="attempt-technical"><summary>${escapeHtml(tr("detail.capabilityParameters", "Capability parameters"))}</summary>${detailFields(parameters)}</details>` : ""}
      ${Object.keys(resources).length ? `<details class="attempt-technical"><summary>${escapeHtml(tr("detail.remoteResources", "Remote resources"))}</summary>${detailFields(resources)}</details>` : ""}
      ${runs.length ? `<div class="attempt-runs"><div class="record-subtitle">${escapeHtml(tr("detail.subagentRuns", "Subagent runs"))}</div>${detailRecordRows(runs, "agent", "task_id", "operation", "status")}</div>` : ""}
    </div>
  </details>`;
}

function renderObservationCandidates(projection) {
  if (!projection || typeof projection !== "object") return "";
  const status = String(projection.status || "invalid");
  const candidates = array(projection.candidates);
  const pending = Boolean(projection.pending_interpretation);
  const subtitle = pending
    ? tr("detail.parserPending", "Parser output · pending Root interpretation")
    : status === "interpreted"
      ? tr("detail.parserPromoted", "Parser output · promoted to canonical Observations")
      : status === "empty"
        ? tr("detail.parserEmpty", "Parser output · no semantic candidates")
        : tr("detail.parserDiagnosis", "Parser output · requires diagnosis");
  const error = projection.error
    ? `<div class="observation-candidate-error">${escapeHtml(projection.error)}</div>`
    : "";
  const rows = candidates.map(candidate => {
    const stateLabel = String(candidate.state || "pending_interpretation");
    const value = formatValue(candidate.value);
    const unit = candidate.unit ? ` ${candidate.unit}` : "";
    const promoted = array(candidate.observation_refs);
    return `<article class="observation-candidate ${tone(stateLabel)}">
      <div class="observation-candidate-head"><span class="mono">${escapeHtml(candidate.candidate_id || tr("detail.candidate", "candidate"))}</span><span class="observation-candidate-concept">${escapeHtml(candidate.concept_id || tr("detail.unknownConcept", "unknown concept"))}</span>${badge(stateLabel)}</div>
      <div class="observation-candidate-value"><code>${escapeHtml(value)}${escapeHtml(unit)}</code></div>
      ${candidate.summary ? `<div class="observation-candidate-summary">${escapeHtml(candidate.summary)}</div>` : ""}
      ${promoted.length ? `<div class="observation-candidate-promotion">${escapeHtml(tr("locator.observation", "Observation"))} ${escapeHtml(promoted.join(", "))}</div>` : ""}
    </article>`;
  }).join("");
  const diagnostics = array(projection.diagnostics);
  const count = Number(projection.candidate_count) || candidates.length;
  const shown = candidates.length;
  const countLabel = shown < count ? tr("detail.countStatus", "{{shown}} of {{total}}", { shown, total: count }) : `${count}`;
  return `<section class="observation-candidates ${tone(status)}">
    <div class="observation-candidates-heading"><div><h4>${escapeHtml(tr("detail.observationCandidates", "Observation Candidates"))}</h4><p>${escapeHtml(subtitle)}</p></div><div class="observation-candidates-meta">${badge(status)}<span>${escapeHtml(countLabel)}</span></div></div>
    ${error}
    ${rows ? `<div class="observation-candidate-list">${rows}</div>` : ""}
    ${diagnostics.length ? `<div class="observation-candidate-diagnostics"><span>${escapeHtml(tr("detail.parserDiagnostics", "Parser diagnostics"))}</span>${diagnostics.map(item => `<div>${escapeHtml(item)}</div>`).join("")}</div>` : ""}
    ${projection.ref ? `<div class="observation-candidate-ref mono">${escapeHtml(projection.ref)}</div>` : ""}
  </section>`;
}

function renderAttemptRefs(label, values) {
  const rows = array(values).filter(Boolean);
  if (!rows.length) return "";
  return `<div class="attempt-refs"><div class="record-subtitle">${escapeHtml(label)}</div><div class="ref-chips">${rows.map(value => `<span class="ref-chip">${escapeHtml(value)}</span>`).join("")}</div></div>`;
}

function attemptDisplayState(attempt) {
  if (attempt.display_state) return attempt.display_state;
  const programStatus = String(attempt.program_status || "").toLowerCase();
  if (["completed", "normal_termination", "failed", "running"].includes(programStatus)) return programStatus;
  return attempt.state || attempt.program_status || "unknown";
}

function renderNodeFiles(payload) {
  const files = array(payload.files?.files);
  return `<section class="detail-section"><h3>${escapeHtml(tr("detail.nodeFiles", "Node Files"))}</h3>${files.length ? files.map(row => pathRow(row.path, compact([formatBytes(row.size), formatTime(row.modified * 1000)]), row.preview)).join("") : `<div class="detail-empty">${escapeHtml(tr("detail.noCurrentFiles", "No current files are present for this Node."))}</div>`}</section>`;
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
    proof_spec_refs: node.proof_spec_refs,
    validation_result_refs: node.validation_result_refs,
  };
  const decisions = array(payload.history).map(row => `<div class="record-row"><div><div class="record-title mono">${escapeHtml(row.decision_id || tr("detail.decision", "Decision"))}</div><div class="record-subtitle">${escapeHtml(row.rationale || tr("detail.canonicalMutation", "Canonical mutation"))}</div></div><div class="record-meta"><span>${escapeHtml(formatTime(row.created_at))}</span></div></div>`).join("");
  return `<section class="detail-section"><h3>${escapeHtml(tr("detail.decisionHistory", "Decision History"))}</h3>${decisions || `<div class="detail-empty">${escapeHtml(tr("detail.noMatchingDecisions", "No matching decisions were projected."))}</div>`}</section><section class="detail-section"><h3>${escapeHtml(tr("detail.auditReferences", "Audit References"))}</h3>${detailFields(audit)}</section>`;
}

function renderClaimDetail(payload) {
  const claim = payload.claim;
  inspectorKicker.textContent = `${claim.claim_type} | ${claim.claim_id}`;
  inspectorTitle.textContent = claim.statement;
  inspectorBody.innerHTML = `<div class="detail-summary"><div class="detail-meta">${badge(claim.status)}<span>${escapeHtml(claim.claim_id)}</span></div><p>${escapeHtml(claim.statement)}</p></div>
    <section class="detail-section"><h3>${escapeHtml(tr("detail.scientificContract", "Scientific Contract"))}</h3>${bulletGroup(tr("detail.assumptions", "Assumptions"), claim.assumptions)}${bulletGroup(tr("detail.falsifiers", "Falsifiers"), claim.falsifiers)}</section>
    <section class="detail-section"><h3>${escapeHtml(tr("detail.researchNodes", "ResearchNodes"))}</h3>${linkedNodeGroup(tr("detail.relatedNodes", "Related Nodes"), payload.research_nodes)}</section>
    <section class="detail-section"><h3>${escapeHtml(tr("detail.observations", "Observations"))}</h3>${detailRecordRows(payload.observations, "observation", "observation_id", "summary", "concept_id")}</section>
    <section class="detail-section"><h3>${escapeHtml(tr("detail.validation", "Validation"))}</h3>${detailRecordRows(payload.validation_results, "validation-result", "result_id", "dimension", "verdict")}</section>
    <section class="detail-section"><h3>${escapeHtml(tr("section.scientificFindings", "Findings"))}</h3>${detailRecordRows(payload.findings, "finding", "finding_id", "statement", "status")}</section>
    <section class="detail-section"><h3>${escapeHtml(tr("detail.acceptance", "Acceptance"))}</h3>${detailRecordRows(payload.acceptances, "acceptance", "acceptance_id", "profile_id", "current")}</section>
    <section class="detail-section"><h3>${escapeHtml(tr("detail.reviewRuns", "Review Runs"))}</h3>${detailRecordRows(payload.review_runs, "agent", "task_id", "summary", "status")}</section>`;
}

function renderRelationDetail(relation) {
  inspectorKicker.textContent = `${relation.relation_type} | ${relation.relation_id}`;
  inspectorTitle.textContent = `${relation.source_claim_ref} ${tr("tree.edgeTo", "to")} ${relation.target_claim_ref}`;
  inspectorBody.innerHTML = `<div class="detail-summary"><div class="detail-meta"><span class="mono">${escapeHtml(relation.relation_id)}</span><span>${escapeHtml(relation.relation_type)}</span></div><p>${escapeHtml(relation.rationale)}</p></div>
    <section class="detail-section"><h3>${escapeHtml(tr("detail.claimRelation", "Claim Relation"))}</h3><dl class="detail-grid"><dt>${escapeHtml(tr("detail.source", "Source"))}</dt><dd>${detailButton("claim", relation.source_claim_ref, relation.source_claim_ref)}</dd><dt>${escapeHtml(tr("detail.target", "Target"))}</dt><dd>${detailButton("claim", relation.target_claim_ref, relation.target_claim_ref)}</dd><dt>${escapeHtml(tr("detail.relation", "Relation"))}</dt><dd><span class="mono">${escapeHtml(relation.relation_type)}</span></dd></dl></section>
    <section class="detail-section"><h3>${escapeHtml(tr("detail.audit", "Audit"))}</h3><dl class="detail-grid"><dt>${escapeHtml(tr("detail.decision", "Decision"))}</dt><dd><span class="mono">${escapeHtml(relation.created_by_decision)}</span></dd><dt>${escapeHtml(tr("detail.created", "Created"))}</dt><dd>${escapeHtml(formatTime(relation.created_at))}</dd></dl></section>`;
}

async function openFile(path) {
  const workspaceId = state.workspaceId;
  state.detail = null;
  state.detailKind = "file";
  state.detailId = path;
  state.filePath = path;
  inspectorKicker.textContent = tr("detail.researchFile", "Research File");
  inspectorTitle.textContent = pathName(path);
  inspectorBody.innerHTML = `<div class="empty">${escapeHtml(tr("detail.loadingFile", "Loading file..."))}</div>`;
  document.body.classList.add("inspector-open");
  inspector.setAttribute("aria-hidden", "false");
  try {
    const payload = await api(`/api/workspace/${encodeURIComponent(state.workspaceId)}/file?path=${encodeURIComponent(path)}`);
    if (workspaceId !== state.workspaceId || state.filePath !== path) return;
    state.detail = payload;
    renderFileDetail(payload);
  } catch (error) {
    if (workspaceId !== state.workspaceId || state.filePath !== path) return;
    inspectorBody.innerHTML = `<div class="fatal">${escapeHtml(error.message || error)}</div>`;
  }
}

function renderFileDetail(payload) {
  inspectorKicker.textContent = tr("detail.researchFile", "Research File");
  inspectorTitle.textContent = pathName(payload.path || state.filePath);
  inspectorBody.innerHTML = `<section class="detail-section"><dl class="detail-grid"><dt>${escapeHtml(tr("detail.path", "Path"))}</dt><dd class="mono">${escapeHtml(payload.path)}</dd><dt>${escapeHtml(tr("detail.size", "Size"))}</dt><dd>${escapeHtml(formatBytes(payload.size))}</dd></dl><pre class="file-preview">${escapeHtml(payload.text)}</pre></section>`;
}

function closeInspector() {
  document.body.classList.remove("inspector-open");
  inspector.setAttribute("aria-hidden", "true");
}

function restoreOpenAttempts(attemptIds) {
  const wanted = new Set(array(attemptIds));
  inspectorBody.querySelectorAll("details[data-attempt-id]").forEach(row => {
    row.open = wanted.has(row.dataset.attemptId);
  });
}

function revealAttempt(attemptId) {
  const row = [...inspectorBody.querySelectorAll("details[data-attempt-id]")]
    .find(candidate => candidate.dataset.attemptId === attemptId);
  if (!row) return false;
  row.open = true;
  row.scrollIntoView({ block: "nearest", behavior: "smooth" });
  row.querySelector("summary")?.focus({ preventScroll: true });
  return true;
}

async function openAttemptSource(sourceNodeId, attemptId) {
  if (!sourceNodeId || !attemptId) {
    showToast(tr("detail.calculationSourceUnavailable", "Calculation source is unavailable"));
    return;
  }
  if (state.detailKind !== "node" || state.detailId !== sourceNodeId) {
    const opened = await openDetail("node", sourceNodeId);
    if (!opened) return;
  }
  state.nodeTab = "runs";
  resetAttemptView();
  state.attemptView.page = window.TSAttemptTimeline.pageForAttempt(
    state.detail.research_node.attempts,
    state.attemptView,
    attemptId,
  ) || 1;
  renderNodeDetail(state.detail);
  if (!revealAttempt(attemptId)) {
    showToast(tr("detail.calculationUnavailable", "Calculation {{id}} is not available in {{node}}", { id: attemptId, node: sourceNodeId }));
  }
}

function clearInspectorState() {
  state.detail = null;
  state.detailKind = null;
  state.detailId = null;
  state.filePath = null;
  state.nodeTab = "overview";
  resetAttemptView();
  closeInspector();
}

function resetAttemptView() {
  state.attemptView = { family: "all", kind: "all", state: "all", page: 1 };
}

function localRecord(kind, id) {
  const sources = {
    observation: [state.view.observations, "observation_id"],
    "validation-spec": [state.view.proof_specs, "proof_id"],
    "validation-result": [state.view.validation_results, "result_id"],
    finding: [state.view.findings, "finding_id"],
    acceptance: [state.view.acceptances, "acceptance_id"],
    relation: [state.view.claim_relations, "relation_id"],
    activity: [state.view.deterministic_activities, "activity_id"],
    agent: [state.view.agent_runs, "task_id"],
    control: [[...array(state.view.unresolved_controls), ...array(state.view.retryable_controls)], "control_id"],
  };
  const [records, key] = sources[kind] || [[], "id"];
  const record = array(records).find(row => String(row[key]) === String(id));
  if (!record) throw new Error(tr("error.unknownRecord", "Unknown {{kind}}: {{id}}", { kind: labelForKind(kind), id }));
  return record;
}

function linkedNodeGroup(label, records) {
  const rows = array(records);
  if (!rows.length) return `<div class="detail-empty">${escapeHtml(label)}: ${escapeHtml(tr("detail.none", "none"))}.</div>`;
  return `<div class="record-subtitle">${escapeHtml(label)}</div>${recordList(rows.map(row => ({ kind: "node", id: row.node_id, title: row.title, subtitle: row.objective, status: row.status })))}`;
}

function linkedClaimRows(records) {
  const rows = array(records);
  if (!rows.length) return `<div class="detail-empty">${escapeHtml(tr("detail.noLinkedClaims", "No Claims are linked."))}</div>`;
  return recordList(rows.map(row => ({ kind: "claim", id: row.claim_id, title: row.statement, subtitle: compact([row.claim_id, row.claim_type]), status: row.status })));
}

function detailRecordRows(records, kind, idKey, titleKey, statusKey) {
  const rows = array(records);
  if (!rows.length) return `<div class="detail-empty">${escapeHtml(tr("detail.noRecords", "No records."))}</div>`;
  return recordList(rows.map(row => ({
    kind,
    id: row[idKey],
    title: formatValue(row[titleKey]) || row[idKey],
    subtitle: row[idKey],
    status: formatValue(row[statusKey]),
  })));
}

function recordList(rows) {
  if (!rows.length) return `<div class="empty">${escapeHtml(tr("detail.noRecords", "No records."))}</div>`;
  return `<div class="record-list">${rows.map(row => `<button class="record-row" type="button" data-detail="${escapeHtml(row.kind)}" data-id="${escapeHtml(row.id)}"><div><div class="record-title">${escapeHtml(row.title || row.id)}</div><div class="record-subtitle mono">${escapeHtml(row.subtitle || row.id || "")}</div></div><div class="record-meta">${row.status ? badge(row.status) : ""}${icon("chevron")}</div></button>`).join("")}</div>`;
}

function detailButton(kind, id, label) {
  if (!id) return `<span class="muted">${escapeHtml(tr("detail.none", "none"))}</span>`;
  return `<button class="record-button mono" type="button" data-detail="${escapeHtml(kind)}" data-id="${escapeHtml(id)}">${escapeHtml(label || id)}</button>`;
}

function pathRow(path, meta, preview) {
  if (!path) return "";
  const label = `<span class="path-name mono">${escapeHtml(path)}</span>${meta ? `<span class="path-meta">${escapeHtml(meta)}</span>` : ""}`;
  if (preview?.available) {
    return `<div class="path-row"><button class="path-button" type="button" data-file="${escapeHtml(path)}" title="${escapeHtml(tr("detail.preview", "Preview {{path}}", { path }))}"><span class="path-copy">${label}</span>${icon("eye")}</button></div>`;
  }
  const reason = preview ? `<div class="path-preview-state">${escapeHtml(preview.reason || tr("detail.previewUnavailable", "Preview unavailable"))}</div>` : "";
  return `<div class="path-row"><div class="path-copy">${label}${reason}</div></div>`;
}

function section(title, meta, body) {
  return `<section class="section"><div class="section-header"><h2>${escapeHtml(title)}</h2><span class="section-meta">${escapeHtml(meta)}</span></div>${body}</section>`;
}

function table(headers, rows) {
  if (!rows.length) return `<div class="empty">${escapeHtml(tr("detail.noRecords", "No records."))}</div>`;
  return `<div class="table-wrap"><table><thead><tr>${headers.map(value => `<th>${escapeHtml(tableHeader(value))}</th>`).join("")}</tr></thead><tbody>${rows.map(cells => `<tr>${cells.map(cell => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function tableHeader(value) {
  const keys = {
    Statement: "table.statement", Type: "table.type", Status: "table.status", Title: "table.title",
    Dimension: "table.dimension", "Target Claim": "table.targetClaim", Result: "table.result",
    ProofSpec: "table.proofSpec", Finding: "table.finding", Severity: "table.severity", Scope: "table.scope",
    Acceptance: "table.acceptance", Claim: "table.claim", Profile: "table.profile", State: "table.state", Verdict: "table.verdict",
  };
  return keys[value] ? tr(keys[value], value) : value;
}

function detailFields(record) {
  const entries = Object.entries(object(record)).filter(([, value]) => value !== null && value !== undefined && value !== "" && (!Array.isArray(value) || value.length));
  if (!entries.length) return `<div class="detail-empty">${escapeHtml(tr("detail.noFields", "No fields."))}</div>`;
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
      if (target) target.innerHTML = `<div class="empty">${escapeHtml(tr("detail.searchingIndex", "Searching research index..."))}</div>`;
      scheduleLocator(state.query.trim());
    } else {
      if (state.currentView === "conclusions" && state.conclusionsMode === "map") state.claimMapViewport = null;
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
  return `<span class="badge ${tone(label)}">${escapeHtml(trStatus(label))}</span>`;
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
function capabilityLabel(record) {
  const capability = String(record?.capability || "");
  if (!capability) return "";
  const version = record?.capability_version ? `@${record.capability_version}` : "";
  return `${capability}${version}`;
}
function formatValue(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try { return JSON.stringify(value); } catch (_error) { return String(value); }
}
function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  const locale = i18n?.getLocale() === "zh" ? "zh-CN" : "en-US";
  return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString(locale);
}
function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
}
function formatDuration(value) {
  if (value === null || value === undefined || value === "") return tr("detail.notRecorded", "not recorded");
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 0) return tr("detail.notRecorded", "not recorded");
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}
function pathName(value) { return String(value || tr("detail.files", "File")).split("/").filter(Boolean).pop() || tr("detail.files", "File"); }
function shortDigest(value) { const text = String(value || ""); return text.startsWith("sha256:") ? text.slice(7, 19) : text.slice(0, 12); }
function recordId(record) { return record.claim_id || record.node_id || record.relation_id || record.observation_id || record.proof_id || record.result_id || record.finding_id || record.acceptance_id || record.activity_id || record.task_id || record.control_id || record.intent_id || tr("detail.record", "Record"); }
function labelForKind(kind) {
  const labels = { node: "ResearchNode", claim: "Claim", relation: "Claim Relation", observation: "Observation", "validation-spec": "ProofSpec", "validation-result": "Validation Result", finding: "Finding", acceptance: "Acceptance", activity: "Deterministic Operation", agent: "Subagent Run", control: "Remote Control" };
  const keys = { node: "detail.node", claim: "detail.claim", relation: "detail.claimRelation", observation: "detail.observation", "validation-spec": "detail.validationSpec", "validation-result": "detail.validationResult", finding: "detail.finding", acceptance: "detail.acceptanceRecord", activity: "detail.deterministicOperation", agent: "detail.subagentRun", control: "detail.remoteControl" };
  return keys[kind] ? tr(keys[kind], labels[kind]) : labels[kind] || tr("detail.details", "Details");
}
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}

function updateThemeControl() {
  const current = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  const next = current === "dark" ? "light" : "dark";
  themeIcon.querySelector("use").setAttribute("href", current === "dark" ? "#icon-sun" : "#icon-moon");
  const key = next === "dark" ? "controls.theme.dark" : "controls.theme.light";
  themeButton.title = tr(key, `Use ${next} theme`);
  themeButton.setAttribute("aria-label", tr(key, `Use ${next} theme`));
}

function toggleTheme() {
  const current = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem(themeStorageKey, next); } catch (_error) {}
  updateThemeControl();
}

function toggleLanguage() {
  if (!i18n) return;
  i18n.setLocale(i18n.getLocale() === "zh" ? "en" : "zh");
  document.documentElement.lang = i18n.getLocale();
  renderCurrentView({ resetScroll: false });
  if (state.detail) renderInspector();
  if (state.view) updateChrome();
  updateThemeControl();
  languageButton.title = tr("controls.language", "Switch language");
  languageButton.setAttribute("aria-label", tr("controls.language", "Switch language"));
}

function showToast(message) {
  clearTimeout(state.toastTimer);
  toast.textContent = message;
  toast.classList.add("visible");
  state.toastTimer = setTimeout(() => toast.classList.remove("visible"), 2200);
}

function renderFatal(error) {
  teardownVisualizations();
  content.innerHTML = `<div class="fatal">${escapeHtml(error.message || error)}</div>`;
  setHealth("invalid", tr("health.unavailable", "Unavailable"));
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
  const roadmapMode = event.target.closest("[data-roadmap-mode]");
  if (roadmapMode) {
    state.roadmapMode = roadmapMode.dataset.roadmapMode === "dag" ? "dag" : "map";
    renderCurrentView({ resetScroll: false });
    return;
  }
  const mode = event.target.closest("[data-conclusions-mode]");
  if (mode) {
    state.conclusionsMode = mode.dataset.conclusionsMode === "map" ? "map" : "table";
    renderCurrentView({ resetScroll: false });
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

inspectorBody.addEventListener("click", async event => {
  const tab = event.target.closest("[data-node-tab]");
  if (tab && state.detailKind === "node") {
    state.nodeTab = tab.dataset.nodeTab;
    renderNodeDetail(state.detail);
    return;
  }
  const page = event.target.closest("[data-attempt-page]");
  if (page && state.detailKind === "node") {
    state.attemptView.page = Number(page.dataset.attemptPage) || 1;
    renderNodeDetail(state.detail);
    return;
  }
  const attempt = event.target.closest("[data-attempt-open]");
  if (attempt && state.detailKind === "node") {
    await openAttemptSource(attempt.dataset.attemptNode, attempt.dataset.attemptOpen);
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

inspectorBody.addEventListener("change", event => {
  const filter = event.target.closest("[data-attempt-filter]");
  if (!filter || state.detailKind !== "node") return;
  const name = filter.dataset.attemptFilter;
  if (!["family", "kind", "state"].includes(name)) return;
  state.attemptView[name] = filter.value || "all";
  state.attemptView.page = 1;
  renderNodeDetail(state.detail);
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
languageButton.addEventListener("click", toggleLanguage);
refreshButton.addEventListener("click", refreshExplorer);
authForm.addEventListener("submit", event => {
  event.preventDefault();
  const token = authTokenInput.value.trim();
  if (!token || !state.resolveAuthPrompt) return;
  state.authToken = token;
  state.authChecking = true;
  authError.hidden = true;
  authSubmit.disabled = true;
  authSubmit.textContent = tr("auth.checking", "Checking...");
  const resolve = state.resolveAuthPrompt;
  state.authPrompt = null;
  state.resolveAuthPrompt = null;
  resolve();
});
authReveal.addEventListener("change", () => {
  authTokenInput.type = authReveal.checked ? "text" : "password";
  authTokenInput.focus();
});
authDialog.addEventListener("cancel", event => event.preventDefault());
document.getElementById("close-inspector").addEventListener("click", closeInspector);
document.getElementById("inspector-backdrop").addEventListener("click", closeInspector);
document.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    closeInspector();
    return;
  }
  if ((event.key === "/" && !isTypingTarget(event.target)) || ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k")) {
    const input = document.getElementById("search-input");
    if (!input) return;
    event.preventDefault();
    input.focus();
    input.select();
  }
});

function isTypingTarget(target) {
  const tag = String(target?.tagName || "").toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || Boolean(target?.isContentEditable);
}
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    clearTimeout(state.liveTimer);
  } else {
    scheduleLiveRefresh(0);
  }
});
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", event => {
  let saved = null;
  try { saved = localStorage.getItem(themeStorageKey); } catch (_error) {}
  if (!saved) {
    document.documentElement.dataset.theme = event.matches ? "dark" : "light";
    updateThemeControl();
  }
});

boot();
