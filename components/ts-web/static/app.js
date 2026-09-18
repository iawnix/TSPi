"use strict";

// TS Web is intentionally a thin renderer. The ResearchMap returned by the
// provider is the state; this file only chooses a view and formats records.
const state = { workspaceId: null, workspaces: [], map: null, view: "roadmap", query: "", authToken: "", authPrompt: null, refreshTimer: null };
const $ = (id) => document.getElementById(id);
const content = $("content");
const workspaceSelect = $("workspace-select");
const health = $("health");
const healthLabel = $("health-label");
const refreshButton = $("refresh-button");
const refreshStatus = $("refresh-status");
const themeButton = $("theme-button");
const themeIcon = $("theme-icon");
const languageButton = $("language-button");
const inspector = $("inspector");
const inspectorKicker = $("inspector-kicker");
const inspectorTitle = $("inspector-title");
const inspectorBody = $("inspector-body");
const authDialog = $("auth-dialog");
const authForm = $("auth-form");
const authTokenInput = $("auth-token");
const authReveal = $("auth-reveal");
const authError = $("auth-error");
const authWarning = $("auth-warning");
const authSubmit = $("auth-submit");
const toast = $("toast");
const i18n = window.TSExplorerI18n;

function tr(key, fallback = key, variables = null) {
  if (i18n) return i18n.t(key, fallback, variables);
  return typeof fallback === "string" && variables ? fallback.replace(/\{\{(\w+)\}\}/g, (_m, name) => String(variables[name] ?? "")) : fallback;
}
function array(value) { return Array.isArray(value) ? value : []; }
function esc(value) { return String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char])); }
function json(value) { return esc(JSON.stringify(value, null, 2)); }
function label(value) { return String(value || "").replaceAll("_", " "); }

async function api(path) {
  const target = new URL(path, window.location.href);
  if (target.origin !== window.location.origin || !target.pathname.startsWith("/api/")) throw new Error("unsafe API target");
  while (true) {
    const headers = { Accept: "application/json" };
    if (state.authToken) headers.Authorization = `Bearer ${state.authToken}`;
    const submitted = Boolean(state.authToken);
    let response;
    try { response = await fetch(target.href, { cache: "no-store", headers }); } catch (error) { throw new Error(error.message || "network request failed"); }
    const text = await response.text();
    if (response.status === 401) { await requestAccessToken({ rejected: submitted }); continue; }
    let payload;
    try { payload = JSON.parse(text); } catch (_error) { throw new Error("invalid JSON response"); }
    if (!response.ok) throw new Error(payload.error || `${response.status} ${response.statusText}`);
    return payload;
  }
}

function requestAccessToken({ rejected = false } = {}) {
  state.authToken = "";
  authError.hidden = !rejected;
  authWarning.hidden = window.location.protocol === "https:" || ["localhost", "127.0.0.1", "::1"].includes(window.location.hostname);
  authSubmit.disabled = false;
  if (!authDialog.open) authDialog.showModal();
  requestAnimationFrame(() => { authTokenInput.focus(); if (rejected) authTokenInput.select(); });
  if (!state.authPrompt) state.authPrompt = new Promise(resolve => { state.resolveAuthPrompt = resolve; });
  return state.authPrompt;
}

function setHealth(kind, text) { health.className = `health ${kind}`; healthLabel.textContent = text; }
function showToast(text) { toast.textContent = text; toast.classList.add("visible"); setTimeout(() => toast.classList.remove("visible"), 2400); }
function setCount(name, value) { const target = document.querySelector(`[data-count="${name}"]`); if (target) target.textContent = String(value); }

async function boot() {
  i18n?.setLocale(i18n.getLocale());
  document.documentElement.lang = i18n?.getLocale() || "en";
  updateTheme();
  try { await loadCatalog(); await loadMap(); scheduleRefresh(); } catch (error) { renderError(error); }
}

async function loadCatalog() {
  const payload = await api("/api/workspaces");
  state.workspaces = array(payload.workspaces);
  if (!state.workspaces.length) throw new Error("No ResearchMap workspace is registered.");
  let saved = state.workspaceId;
  try { saved ||= localStorage.getItem("research-map-workspace"); } catch (_error) {}
  state.workspaceId = state.workspaces.some(row => row.workspace_id === saved) ? saved : (payload.default_workspace || state.workspaces[0].workspace_id);
  workspaceSelect.innerHTML = state.workspaces.map(row => `<option value="${esc(row.workspace_id)}">${esc(row.label || row.workspace_id)}</option>`).join("");
  workspaceSelect.value = state.workspaceId;
}

async function loadMap() {
  const payload = await api(`/api/workspace/${encodeURIComponent(state.workspaceId)}/snapshot`);
  if (!payload.map) throw new Error("Provider did not return a ResearchMap.");
  state.map = payload.map;
  try { localStorage.setItem("research-map-workspace", state.workspaceId); } catch (_error) {}
  updateChrome();
  render();
}

function scheduleRefresh() {
  clearTimeout(state.refreshTimer);
  if (!document.hidden) state.refreshTimer = setTimeout(async () => { try { await loadMap(); } catch (_error) { setHealth("stale", "Stale"); } scheduleRefresh(); }, 5000);
}

function updateChrome() {
  const map = state.map || {};
  const progress = map.progress || {};
  setHealth("valid", "ResearchMap");
  setCount("phases", array(map.phases).length);
  setCount("claims", array(map.claims).length);
  setCount("validation", array(map.gates).length);
  setCount("findings", array(map.findings).length);
  setCount("activity", array(map.nodes).length);
  $("sidebar-meta").textContent = `${map.schema_version || "research-map/1"} · revision ${map.revision ?? 0}`;
  refreshStatus.textContent = `${progress.closed_node_count || 0}/${progress.node_count || 0} nodes closed`;
}

function render() {
  document.querySelectorAll("[data-view]").forEach(button => button.classList.toggle("active", button.dataset.view === state.view));
  const views = { roadmap: renderRoadmap, conclusions: renderClaims, findings: renderFindings, validation: renderGates, activity: renderNodes, files: renderFiles };
  (views[state.view] || renderRoadmap)();
}

function header(title, subtitle = "") {
  return `<div class="view-header"><div class="view-heading"><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div><div class="view-tools"><svg class="icon"><use href="#icon-search"/></svg><input class="search-input" id="search-input" type="search" value="${esc(state.query)}" placeholder="Search this ResearchMap"></div></div>`;
}
function summary() {
  const p = state.map.progress || {};
  const items = [["phase_count","Phases"],["claim_count","Claims"],["node_count","Nodes"],["finding_count","Findings"],["gate_count","Gates"],["closed_node_count","Closed nodes"]];
  return `<div class="summary-strip">${items.map(([key, name]) => `<div class="summary-item"><div class="summary-value">${Number(p[key] || 0)}</div><div class="summary-label">${name}</div></div>`).join("")}</div>`;
}
function matches(row) { return !state.query || JSON.stringify(row).toLowerCase().includes(state.query.toLowerCase()); }

function renderRoadmap() {
  const map = state.map;
  const phases = array(map.phases).filter(matches);
  const phaseIds = new Set(phases.map(phase => phase.id));
  const ungrouped = array(map.nodes).filter(node => !node.phase_id || !phaseIds.has(node.phase_id)).filter(matches);
  const phaseMarkup = phases.map(phase => {
    const nodes = array(map.nodes).filter(node => node.phase_id === phase.id && matches(node));
    return `<section class="section-block"><div class="section-heading"><h2>${esc(phase.title)}</h2><span class="muted">${nodes.length} node${nodes.length === 1 ? "" : "s"}</span></div><p class="muted">${esc(phase.objective || "")}</p><div class="record-grid">${nodes.map(nodeCard).join("") || `<div class="empty">No ResearchNodes in this phase.</div>`}</div></section>`;
  }).join("");
  const ungroupedMarkup = ungrouped.length ? `<section class="section-block"><div class="section-heading"><h2>Ungrouped ResearchNodes</h2><span class="muted">${ungrouped.length}</span></div><div class="record-grid">${ungrouped.map(nodeCard).join("")}</div></section>` : "";
  content.innerHTML = header(map.title, `Canonical ResearchMap · revision ${map.revision}`) + summary() + `<div class="research-map-list">${phaseMarkup || ungroupedMarkup || `<div class="empty">No ResearchMap records match the current search.</div>`}${phaseMarkup ? ungroupedMarkup : ""}</div>`;
  bindSearch();
}
function nodeCard(node) {
  const findings = array(state.map.findings).filter(item => item.node_id === node.id);
  return `<button class="record-card" data-open-kind="node" data-open-id="${esc(node.id)}"><div class="record-card-top"><strong>${esc(node.title)}</strong><span class="badge ${esc(node.state)}">${esc(label(node.state))}</span></div><p>${esc(node.objective)}</p><div class="record-card-meta">${findings.length} finding${findings.length === 1 ? "" : "s"} · ${node.claim_ids?.length || 0} claim${node.claim_ids?.length === 1 ? "" : "s"}</div></button>`;
}
function renderClaims() { const rows = array(state.map.claims).filter(matches); content.innerHTML = header("Research Claims", "Claims are hypotheses tracked by the ResearchMap.") + summary() + tableView(rows, ["statement","status","predictions","falsifiers"], "claim"); bindSearch(); }
function renderFindings() { const rows = array(state.map.findings).filter(matches); content.innerHTML = header("Findings", "FactFinding and IssueFinding share one Finding structure.") + summary() + tableView(rows, ["kind","statement","status","node_id","claim_ids"], "finding"); bindSearch(); }
function renderGates() { const rows = array(state.map.gates).filter(matches); content.innerHTML = header("Research Gates", "NodeGate and ClaimGate are specialized Gate objects.") + summary() + tableView(rows, ["scope","target_id","criteria","evaluations"], "gate"); bindSearch(); }
function renderNodes() { const rows = array(state.map.nodes).filter(matches); content.innerHTML = header("ResearchNodes", "Node state is part of the canonical map and readiness is derived.") + summary() + tableView(rows, ["title","state","outcome","phase_id","dependency_ids"], "node"); bindSearch(); }
function renderFiles() { content.innerHTML = header("Research Files", "Execution artifacts remain under their ResearchNode directories.") + summary() + `<div class="empty">Select a ResearchNode from the Research Map to inspect its recorded references.</div>`; bindSearch(); }
function tableView(rows, fields, kind) {
  if (!rows.length) return `<div class="empty">No records match the current search.</div>`;
  return `<div class="table-wrap"><table><thead><tr><th>Record</th>${fields.map(field => `<th>${esc(label(field))}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr><td><button class="record-button" data-open-kind="${kind}" data-open-id="${esc(row.id)}">${esc(row.id)}</button></td>${fields.map(field => `<td>${formatCell(row[field])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function formatCell(value) { if (Array.isArray(value)) return esc(value.join(", ") || "-"); if (value && typeof value === "object") return `<code>${json(value)}</code>`; return esc(value ?? "-"); }
function bindSearch() { const input = $("search-input"); input?.addEventListener("input", event => { state.query = event.target.value; render(); const next = $("search-input"); next?.focus(); next?.setSelectionRange(state.query.length, state.query.length); }); }

async function openDetail(kind, id) {
  try {
    const payload = await api(`/api/workspace/${encodeURIComponent(state.workspaceId)}/${kind}/${encodeURIComponent(id)}`);
    const object = payload.object;
    inspectorKicker.textContent = label(kind);
    inspectorTitle.textContent = object.title || object.statement || object.id;
    inspectorBody.innerHTML = `<pre class="json-view">${json(object)}</pre>`;
    inspector.setAttribute("aria-hidden", "false");
    document.body.classList.add("inspector-open");
  } catch (error) { showToast(error.message || "Unable to load record"); }
}
function closeInspector() { inspector.setAttribute("aria-hidden", "true"); document.body.classList.remove("inspector-open"); }
function renderError(error) { setHealth("invalid", "Unavailable"); content.innerHTML = `<div class="fatal"><strong>ResearchMap unavailable</strong><br>${esc(error.message || error)}</div>`; }
function updateTheme() { const dark = document.documentElement.dataset.theme === "dark"; themeIcon?.querySelector("use")?.setAttribute("href", dark ? "#icon-sun" : "#icon-moon"); }

document.querySelectorAll("[data-view]").forEach(button => button.addEventListener("click", () => { state.view = button.dataset.view; render(); }));
workspaceSelect?.addEventListener("change", async event => { state.workspaceId = event.target.value; try { await loadMap(); } catch (error) { renderError(error); } });
refreshButton?.addEventListener("click", async () => { try { await loadMap(); showToast("ResearchMap refreshed"); } catch (error) { showToast(error.message); } scheduleRefresh(); });
$("close-inspector")?.addEventListener("click", closeInspector);
$("inspector-backdrop")?.addEventListener("click", closeInspector);
content?.addEventListener("click", event => { const target = event.target.closest("[data-open-kind]"); if (target) openDetail(target.dataset.openKind, target.dataset.openId); });
themeButton?.addEventListener("click", () => { document.documentElement.dataset.theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; updateTheme(); });
languageButton?.addEventListener("click", () => { i18n?.setLocale(i18n.getLocale() === "zh-CN" ? "en" : "zh-CN"); location.reload(); });
authReveal?.addEventListener("change", () => { authTokenInput.type = authReveal.checked ? "text" : "password"; });
authForm?.addEventListener("submit", event => { event.preventDefault(); state.authToken = authTokenInput.value.trim(); if (state.authPrompt) state.resolveAuthPrompt?.(); state.authPrompt = null; authDialog.close(); });
document.addEventListener("visibilitychange", scheduleRefresh);
boot();
