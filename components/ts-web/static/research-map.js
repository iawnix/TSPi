"use strict";

(function attachResearchMap(global) {
  function mount(root, options = {}) {
    const projection = object(options.projection);
    const nodes = new Map(array(projection.nodes).map(row => [row.node_ref, row]));
    const highlights = options.highlightIds instanceof Set ? options.highlightIds : null;
    root.classList.add("research-map");
    root.innerHTML = array(projection.phases).length
      ? array(projection.phases).map(phase => renderPhase(phase, nodes, options, highlights)).join("")
      : `<div class="research-map-empty">${escapeHtml(tr("map.noPhases", "No research phases are recorded."))}</div>`;

    const handleClick = event => {
      const node = event.target.closest("[data-research-node]");
      if (node && typeof options.onSelectNode === "function") {
        options.onSelectNode(node.dataset.researchNode);
        return;
      }
      const claim = event.target.closest("[data-research-claim]");
      if (claim && typeof options.onSelectClaim === "function") {
        options.onSelectClaim(claim.dataset.researchClaim);
        return;
      }
      const relation = event.target.closest("[data-research-relation]");
      if (relation && typeof options.onSelectRelation === "function") {
        options.onSelectRelation(relation.dataset.researchRelation);
      }
    };
    root.addEventListener("click", handleClick);
    return {
      destroy() {
        root.removeEventListener("click", handleClick);
        root.replaceChildren();
        root.classList.remove("research-map");
      },
    };
  }

  function renderPhase(phase, nodes, options, highlights) {
    const lanes = array(phase.lanes);
    const sharedRefs = array(phase.shared_node_refs);
    return `<section class="research-map-phase">
      <header class="research-map-phase-header">
        <div class="research-map-phase-id">${escapeHtml(phase.phase_id || tr("map.phaseFallback", "Research Phase"))}</div>
        <div><h2>${escapeHtml(phase.title || phase.phase_id || tr("map.phaseFallback", "Research Phase"))}</h2><p>${escapeHtml(phase.objective || "")}</p></div>
        <div class="research-map-phase-meta">${sharedRefs.length} ${escapeHtml(tr("map.shared", "shared"))} · ${lanes.length} ${escapeHtml(tr("map.lanes", "lanes"))}</div>
      </header>
      ${renderRelations(phase.claim_relations)}
      ${sharedRefs.length ? `<section class="research-map-shared">
        <div class="research-map-section-heading"><div><h3>${escapeHtml(tr("map.sharedFoundation", "Shared foundation"))}</h3><p>${escapeHtml(tr("map.sharedDescription", "Inputs used by more than one hypothesis."))}</p></div><span>${sharedRefs.length} ${escapeHtml(sharedRefs.length === 1 ? tr("map.node", "node") : tr("map.nodes", "nodes"))}</span></div>
        ${renderConnectivity(phase.shared_connectivity_segments)}
        <div class="research-map-node-list">${sharedRefs.map(ref => renderNode(nodes.get(ref), options, highlights)).join("")}</div>
      </section>` : ""}
      <div class="research-map-lanes">${lanes.map(lane => renderLane(lane, nodes, options, highlights)).join("")}</div>
    </section>`;
  }

  function renderRelations(value) {
    const relations = array(value);
    if (!relations.length) return "";
    return `<div class="research-map-relations"><span>${escapeHtml(tr("map.hypothesisRelations", "Hypothesis relations"))}</span>${relations.map(row => {
      const label = `${row.source_claim_ref || tr("map.claim", "Claim")} ${humanize(row.relation_type)} ${row.target_claim_ref || tr("map.claim", "Claim")}`;
      return `<button type="button" data-research-relation="${escapeHtml(row.relation_ref)}" title="${escapeHtml(row.rationale || label)}">${escapeHtml(label)}</button>`;
    }).join("")}</div>`;
  }

  function renderLane(lane, nodes, options, highlights) {
    const nodeRefs = array(lane.node_refs);
    const isClaim = lane.lane_type === "claim" && lane.claim_ref;
    const claimGate = object(lane.claim_gate);
    const claimGateResult = object(claimGate.result);
    return `<section class="research-map-lane ${isClaim ? "claim" : "exploration"}">
      <header class="research-map-lane-header">
        <div class="research-map-lane-kicker">${escapeHtml(isClaim ? lane.claim_type || tr("map.hypothesis", "Hypothesis") : tr("map.exploration", "Exploration"))}</div>
        ${isClaim
          ? `<button type="button" data-research-claim="${escapeHtml(lane.claim_ref)}"><span>${escapeHtml(lane.claim_ref)}</span>${status(lane.status)}${gateStatus(claimGateResult, "claim")}</button>`
          : `<div class="research-map-lane-title"><span>${escapeHtml(tr("map.unassigned", "Unassigned research"))}</span>${status(lane.status)}</div>`}
        <p>${escapeHtml(lane.statement || "")}</p>
      </header>
      ${renderConnectivity(lane.connectivity_segments)}
      <div class="research-map-node-list">${nodeRefs.length
        ? nodeRefs.map(ref => renderNode(nodes.get(ref), options, highlights)).join("")
        : `<div class="research-map-empty">${escapeHtml(tr("map.noNodes", "No ResearchNodes assigned."))}</div>`}</div>
    </section>`;
  }

  function renderConnectivity(value) {
    const segments = array(value);
    if (!segments.length) return "";
    return `<section class="research-map-connectivity"><div class="research-map-connectivity-heading"><h4>${escapeHtml(tr("map.connectivity", "Connectivity evidence"))}</h4><span>${segments.length} ${escapeHtml(segments.length === 1 ? tr("map.segment", "segment") : tr("map.segments", "segments"))}</span></div>${segments.map(segment => {
      const directed = segment.direction !== "undirected";
      return `<div class="research-map-segment">
        <div class="research-map-endpoints"><span>${escapeHtml(segment.endpoint_a)}</span><i class="${directed ? "directed" : ""}" aria-label="${escapeHtml(directed ? tr("map.directed", "directed connection") : tr("map.undirected", "undirected connection"))}"></i><span>${escapeHtml(segment.endpoint_b)}</span></div>
        <div class="research-map-segment-meta"><span>${escapeHtml(segment.subject_ref || tr("map.reactionPath", "Reaction path"))}</span><code>${escapeHtml(array(segment.observation_refs).join(", "))}</code></div>
      </div>`;
    }).join("")}</section>`;
  }

  function renderNode(node, options, highlights) {
    if (!node) return "";
    const latest = object(node.latest_calculation);
    const nodeGate = object(object(node.node_gate).result);
    const selected = options.selectedId === node.node_ref;
    const focused = array(options.focusNodeRefs).includes(node.node_ref);
    const dimmed = highlights && !highlights.has(node.node_ref);
    const dependencies = array(node.upstream_dependencies);
    const attemptText = latest.intent_id
      ? `${node.attempt_count} ${tr(node.attempt_count === 1 ? "map.attempt" : "map.attempts", node.attempt_count === 1 ? "attempt" : "attempts")} · ${tr("map.latest", "latest")} ${latest.intent_id} · ${trStatus(latest.state || "unknown")}`
      : tr("map.noAttempts", "No calculation attempts");
    const upstream = dependencies.length
      ? dependencies.map(row => `${row.node_ref} · ${row.observation_count} ${tr("map.observations", "observations")}`).join("; ")
      : tr("map.entryDecision", "Entry research decision");
    const traceText = `${array(node.observation_refs).length} ${tr("map.observations", "observations")} · ${array(node.dependent_refs).length} ${tr("map.downstream", "downstream")}`;
    const outcome = object(node.outcome);
    return `<button class="research-map-node ${selected ? "selected" : ""} ${focused ? "focused" : ""} ${dimmed ? "dimmed" : ""}" type="button" data-research-node="${escapeHtml(node.node_ref)}">
      <span class="research-map-node-head"><code>${escapeHtml(node.node_ref)}</code>${status(node.status)}${gateStatus(nodeGate, "node")}</span>
      <strong>${escapeHtml(node.title || node.node_ref)}</strong>
      <span class="research-map-node-objective">${escapeHtml(node.objective || "")}</span>
      <span class="research-map-node-run">${escapeHtml(attemptText)}</span>
      <span class="research-map-node-run">${escapeHtml(traceText)}${outcome.outcome ? ` · ${escapeHtml(trStatus(outcome.outcome))}` : ""}</span>
      <span class="research-map-node-upstream"><b>${escapeHtml(tr("map.upstream", "Upstream"))}</b>${escapeHtml(upstream)}</span>
    </button>`;
  }

  function status(value) {
    const normalized = String(value || "unknown");
    const tone = ["completed", "supported"].includes(normalized)
      ? "good"
      : ["blocked", "failed", "contradicted"].includes(normalized)
        ? "bad"
        : ["inconclusive", "stopped"].includes(normalized)
          ? "warn"
          : "info";
    return `<span class="research-map-status ${tone}">${escapeHtml(trStatus(normalized))}</span>`;
  }

  function gateStatus(result, scope) {
    const verdict = String(result.verdict || "");
    if (!verdict) return "";
    const stale = result.stale === true;
    const tone = verdict === "pass" ? "good" : ["fail", "blocked"].includes(verdict) ? "bad" : "warn";
    const label = stale ? `${tr(`map.gate.${verdict}`, verdict)} · ${tr("map.gate.stale", "stale")}` : tr(`map.gate.${verdict}`, verdict);
    return `<span class="research-map-status ${tone}" title="${escapeHtml(tr(`map.${scope}Gate`, scope === "node" ? "Node Gate" : "Claim Gate"))}">${escapeHtml(label)}</span>`;
  }

  function tr(key, fallback = key, variables = null) {
    return global.TSExplorerI18n?.t(key, fallback, variables) || fallback;
  }

  function trStatus(value) {
    return global.TSExplorerI18n?.status(value) || String(value || "unknown");
  }

  function humanize(value) {
    return String(value || tr("claimMap.relation", "relation")).replace(/[_.-]+/g, " ");
  }

  function array(value) {
    return Array.isArray(value) ? value : [];
  }

  function object(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
    })[character]);
  }

  global.TSResearchMap = { mount };
})(window);
