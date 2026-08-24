"use strict";

(function attachResearchTree(global) {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const NODE_WIDTH = 278;
  const NODE_HEIGHT = 158;
  const COLUMN_GAP = 96;
  const ROW_GAP = 30;
  const LAYOUT_PADDING = 42;
  const MIN_ZOOM = 0.24;
  const MAX_ZOOM = 1.8;
  const PHASE_COLORS = ["--cyan", "--green", "--amber", "--violet", "--blue"];

  function mount(root, options = {}) {
    if (!(root instanceof Element)) throw new TypeError("Research Tree root must be an Element");
    const nodes = records(options.nodes).filter(node => identifier(node));
    const nodeById = new Map(nodes.map(node => [identifier(node), node]));
    const edges = records(options.edges).filter(edge => nodeById.has(edge.source) && nodeById.has(edge.target));
    const phases = records(options.phases);
    const phaseById = new Map(phases.map(phase => [String(phase.phase_id || ""), phase]));
    const phaseOrder = new Map(phases.map((phase, index) => [String(phase.phase_id || ""), index]));
    const layout = computeLayout(nodes, edges, phaseOrder);
    const highlightIds = options.highlightIds instanceof Set ? options.highlightIds : null;
    const focusIds = new Set(records(options.focusNodeRefs).filter(nodeId => nodeById.has(nodeId)));
    let selectedId = nodeById.has(options.selectedId) ? options.selectedId : null;
    let activePhase = "";
    let viewport = validViewport(options.viewport) ? { ...options.viewport } : { x: 0, y: 0, zoom: 1 };
    let frame = null;
    let dragging = null;
    let resizeObserver = null;

    root.replaceChildren();
    root.classList.toggle("compact", nodes.length <= 2);
    if (!nodes.length) {
      root.append(element("div", "empty", "No ResearchNodes are recorded."));
      return emptyController();
    }

    const toolbar = element("div", "research-tree-toolbar");
    const phaseControl = element("div", "research-tree-phase-control");
    const phaseLabel = element("label", "sr-only", "Research Phase");
    const phaseSelect = document.createElement("select");
    phaseSelect.className = "research-tree-phase-select";
    phaseSelect.setAttribute("aria-label", "Focus Research Phase");
    phaseSelect.append(new Option("All phases", ""));
    for (const phase of phases) {
      const phaseId = String(phase.phase_id || "");
      phaseSelect.append(new Option([phaseId, phase.title].filter(Boolean).join(" | "), phaseId));
    }
    phaseControl.append(phaseLabel, phaseSelect);

    const matches = highlightIds ? highlightIds.size : nodes.length;
    const stats = element(
      "div",
      "research-tree-stats",
      highlightIds ? `${matches} matches | ${nodes.length} nodes | ${edges.length} links` : `${nodes.length} nodes | ${edges.length} links`,
    );
    const actions = element("div", "research-tree-actions");
    const focusButton = iconButton("focus", "Focus current ResearchNode");
    focusButton.disabled = focusIds.size === 0;
    const zoomOutButton = iconButton("zoom-out", "Zoom out");
    const zoomInButton = iconButton("zoom-in", "Zoom in");
    const fitButton = iconButton("fit", "Fit Research Tree");
    actions.append(stats, focusButton, zoomOutButton, zoomInButton, fitButton);
    toolbar.append(phaseControl, actions);

    const stage = element("div", "research-tree-stage");
    stage.tabIndex = 0;
    stage.setAttribute("role", "application");
    stage.setAttribute("aria-label", "ResearchNode dependency tree");
    const canvas = element("div", "research-tree-canvas");
    canvas.style.width = `${layout.width}px`;
    canvas.style.height = `${layout.height}px`;
    const edgeSvg = svgElement("svg", "research-tree-edges");
    edgeSvg.setAttribute("width", String(layout.width));
    edgeSvg.setAttribute("height", String(layout.height));
    edgeSvg.setAttribute("viewBox", `0 0 ${layout.width} ${layout.height}`);
    edgeSvg.setAttribute("aria-hidden", "true");
    const nodeLayer = element("div", "research-tree-nodes");
    const nodeElements = new Map();
    const outlineElements = new Map();
    const edgeElements = [];

    const incomingCounts = countsBy(edges, "target");
    const outgoingCounts = countsBy(edges, "source");
    for (const edge of edges) {
      const source = layout.positions[edge.source];
      const target = layout.positions[edge.target];
      if (!source || !target) continue;
      const edgeElement = buildEdge(edge, source, target, {
        branch: (outgoingCounts.get(edge.source) || 0) > 1,
        merge: (incomingCounts.get(edge.target) || 0) > 1,
      });
      edgeSvg.append(edgeElement);
      edgeElements.push({ edge, element: edgeElement });
    }

    for (const node of nodes) {
      const nodeId = identifier(node);
      const position = layout.positions[nodeId];
      const phaseIndex = phaseOrder.get(String(node.phase_ref || "")) || 0;
      const card = buildNodeCard(node, phaseById.get(String(node.phase_ref || "")), phaseIndex, position);
      card.addEventListener("click", () => selectNode(nodeId));
      nodeLayer.append(card);
      nodeElements.set(nodeId, card);
    }
    canvas.append(edgeSvg, nodeLayer);
    stage.append(canvas);

    const minimap = element("div", "research-tree-minimap");
    const minimapSvg = svgElement("svg", "");
    minimapSvg.setAttribute("viewBox", `0 0 ${layout.width} ${layout.height}`);
    minimapSvg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    for (const node of nodes) {
      const nodeId = identifier(node);
      const position = layout.positions[nodeId];
      const phaseIndex = phaseOrder.get(String(node.phase_ref || "")) || 0;
      const marker = svgElement("rect", "research-tree-minimap-node");
      marker.setAttribute("x", String(position.x));
      marker.setAttribute("y", String(position.y));
      marker.setAttribute("width", String(NODE_WIDTH));
      marker.setAttribute("height", String(NODE_HEIGHT));
      marker.setAttribute("rx", "5");
      marker.style.setProperty("--phase-color", phaseColor(phaseIndex));
      minimapSvg.append(marker);
    }
    const minimapViewport = svgElement("rect", "research-tree-minimap-viewport");
    minimapSvg.append(minimapViewport);
    minimap.append(minimapSvg);
    stage.append(minimap);

    const outline = element("div", "research-tree-outline");
    outline.setAttribute("aria-label", "ResearchNode dependency outline");
    const orderedNodes = [...nodes].sort((left, right) => {
      const a = layout.positions[identifier(left)];
      const b = layout.positions[identifier(right)];
      return a.depth - b.depth || a.y - b.y || naturalCompare(identifier(left), identifier(right));
    });
    for (const node of orderedNodes) {
      const nodeId = identifier(node);
      const position = layout.positions[nodeId];
      const phase = phaseById.get(String(node.phase_ref || ""));
      const phaseIndex = phaseOrder.get(String(node.phase_ref || "")) || 0;
      const row = buildOutlineNode(node, phase, phaseIndex, position.depth);
      row.addEventListener("click", () => selectNode(nodeId));
      outline.append(row);
      outlineElements.set(nodeId, row);
    }

    root.append(toolbar, stage, outline);

    function selectNode(nodeId) {
      selectedId = nodeId;
      applyHighlights();
      if (typeof options.onSelect === "function") options.onSelect(nodeId);
    }

    function setSelected(nodeId) {
      selectedId = nodeById.has(nodeId) ? nodeId : null;
      applyHighlights();
    }

    function applyHighlights() {
      const lineage = computeLineage(nodes, edges, selectedId);
      for (const [nodeId, card] of nodeElements) applyNodeClasses(card, nodeById.get(nodeId), nodeId, lineage);
      for (const [nodeId, row] of outlineElements) applyNodeClasses(row, nodeById.get(nodeId), nodeId, lineage);
      for (const item of edgeElements) {
        const inLineage = !lineage || (lineage.nodeIds.has(item.edge.source) && lineage.nodeIds.has(item.edge.target));
        const searchMatch = !highlightIds || highlightIds.has(item.edge.source) || highlightIds.has(item.edge.target);
        const phaseMatch = !activePhase
          || String(nodeById.get(item.edge.source)?.phase_ref || "") === activePhase
          || String(nodeById.get(item.edge.target)?.phase_ref || "") === activePhase;
        item.element.classList.toggle("lineage", Boolean(lineage && inLineage));
        item.element.classList.toggle("dimmed", Boolean((lineage && !inLineage) || !searchMatch || !phaseMatch));
      }
    }

    function applyNodeClasses(target, node, nodeId, lineage) {
      const inLineage = !lineage || lineage.nodeIds.has(nodeId);
      const searchMatch = !highlightIds || highlightIds.has(nodeId);
      const phaseMatch = !activePhase || String(node?.phase_ref || "") === activePhase;
      target.classList.toggle("selected", nodeId === selectedId);
      target.classList.toggle("focused", focusIds.has(nodeId));
      target.classList.toggle("lineage", Boolean(lineage && inLineage));
      target.classList.toggle("search-match", Boolean(highlightIds && searchMatch));
      target.classList.toggle("dimmed", Boolean((lineage && !inLineage) || !searchMatch || !phaseMatch));
    }

    function applyTransform({ notify = true } = {}) {
      canvas.style.transform = `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})`;
      updateMinimap();
      if (notify && typeof options.onViewportChange === "function") options.onViewportChange({ ...viewport });
    }

    function updateMinimap() {
      const width = Math.max(stage.clientWidth, 1) / viewport.zoom;
      const height = Math.max(stage.clientHeight, 1) / viewport.zoom;
      minimapViewport.setAttribute("x", String(-viewport.x / viewport.zoom));
      minimapViewport.setAttribute("y", String(-viewport.y / viewport.zoom));
      minimapViewport.setAttribute("width", String(width));
      minimapViewport.setAttribute("height", String(height));
    }

    function fitNodeIds(ids, maxZoom = 1) {
      const positions = ids.map(id => layout.positions[id]).filter(Boolean);
      if (!positions.length || !stage.clientWidth || !stage.clientHeight) return;
      const minX = Math.min(...positions.map(position => position.x));
      const minY = Math.min(...positions.map(position => position.y));
      const maxX = Math.max(...positions.map(position => position.x + NODE_WIDTH));
      const maxY = Math.max(...positions.map(position => position.y + NODE_HEIGHT));
      const boundsWidth = maxX - minX;
      const boundsHeight = maxY - minY;
      const padding = 72;
      viewport.zoom = clamp(
        Math.min((stage.clientWidth - padding) / boundsWidth, (stage.clientHeight - padding) / boundsHeight, maxZoom),
        MIN_ZOOM,
        MAX_ZOOM,
      );
      viewport.x = (stage.clientWidth - boundsWidth * viewport.zoom) / 2 - minX * viewport.zoom;
      viewport.y = (stage.clientHeight - boundsHeight * viewport.zoom) / 2 - minY * viewport.zoom;
      applyTransform();
    }

    function fitAll() {
      activePhase = "";
      phaseSelect.value = "";
      applyHighlights();
      fitNodeIds(nodes.map(identifier));
    }

    function zoomBy(factor, clientX = null, clientY = null) {
      const previous = viewport.zoom;
      const next = clamp(previous * factor, MIN_ZOOM, MAX_ZOOM);
      if (next === previous) return;
      const bounds = stage.getBoundingClientRect();
      const pointX = clientX === null ? bounds.width / 2 : clientX - bounds.left;
      const pointY = clientY === null ? bounds.height / 2 : clientY - bounds.top;
      viewport.x = pointX - ((pointX - viewport.x) * next) / previous;
      viewport.y = pointY - ((pointY - viewport.y) * next) / previous;
      viewport.zoom = next;
      applyTransform();
    }

    phaseSelect.addEventListener("change", () => {
      activePhase = phaseSelect.value;
      applyHighlights();
      if (!activePhase) {
        fitNodeIds(nodes.map(identifier));
        return;
      }
      const phaseIds = nodes.filter(node => String(node.phase_ref || "") === activePhase).map(identifier);
      fitNodeIds(phaseIds, 1.1);
      outlineElements.get(phaseIds[0])?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
    focusButton.addEventListener("click", () => fitNodeIds([...focusIds], 1.15));
    zoomOutButton.addEventListener("click", () => zoomBy(0.82));
    zoomInButton.addEventListener("click", () => zoomBy(1.22));
    fitButton.addEventListener("click", fitAll);

    function pointerMove(event) {
      if (!dragging || event.pointerId !== dragging.pointerId) return;
      viewport.x = dragging.originX + event.clientX - dragging.clientX;
      viewport.y = dragging.originY + event.clientY - dragging.clientY;
      stage.classList.add("dragging");
      applyTransform();
    }

    function pointerEnd(event) {
      if (!dragging || event.pointerId !== dragging.pointerId) return;
      dragging = null;
      stage.classList.remove("dragging");
      if (stage.hasPointerCapture(event.pointerId)) stage.releasePointerCapture(event.pointerId);
    }

    stage.addEventListener("pointerdown", event => {
      if (event.button !== 0 || event.target.closest("button")) return;
      dragging = {
        pointerId: event.pointerId,
        clientX: event.clientX,
        clientY: event.clientY,
        originX: viewport.x,
        originY: viewport.y,
      };
      stage.setPointerCapture(event.pointerId);
    });
    stage.addEventListener("pointermove", pointerMove);
    stage.addEventListener("pointerup", pointerEnd);
    stage.addEventListener("pointercancel", pointerEnd);
    stage.addEventListener("wheel", event => {
      event.preventDefault();
      zoomBy(event.deltaY < 0 ? 1.1 : 0.9, event.clientX, event.clientY);
    }, { passive: false });
    stage.addEventListener("keydown", event => {
      if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        zoomBy(1.16);
      } else if (event.key === "-") {
        event.preventDefault();
        zoomBy(0.86);
      } else if (event.key === "0") {
        event.preventDefault();
        fitAll();
      }
    });

    applyHighlights();
    frame = global.requestAnimationFrame(() => {
      if (validViewport(options.viewport)) applyTransform({ notify: false });
      else fitNodeIds(nodes.map(identifier));
    });
    if (typeof global.ResizeObserver === "function") {
      resizeObserver = new global.ResizeObserver(() => applyTransform({ notify: false }));
      resizeObserver.observe(stage);
    }

    return Object.freeze({
      destroy() {
        if (frame !== null) global.cancelAnimationFrame(frame);
        resizeObserver?.disconnect();
      },
      fit: fitAll,
      getViewport: () => ({ ...viewport }),
      setSelected,
    });
  }

  function computeLayout(nodes, edges, phaseOrder = new Map()) {
    const ids = new Set(nodes.map(identifier));
    const incoming = new Map([...ids].map(id => [id, []]));
    for (const edge of edges) {
      if (ids.has(edge.source) && ids.has(edge.target)) incoming.get(edge.target).push(edge.source);
    }
    const depth = new Map();
    function visit(nodeId, stack = new Set()) {
      if (depth.has(nodeId)) return depth.get(nodeId);
      if (stack.has(nodeId)) return 0;
      const nextStack = new Set(stack).add(nodeId);
      const parents = incoming.get(nodeId) || [];
      const value = parents.length ? 1 + Math.max(...parents.map(parent => visit(parent, nextStack))) : 0;
      depth.set(nodeId, value);
      return value;
    }
    for (const node of nodes) visit(identifier(node));

    const columns = new Map();
    for (const node of nodes) {
      const value = depth.get(identifier(node)) || 0;
      if (!columns.has(value)) columns.set(value, []);
      columns.get(value).push(node);
    }
    const stableCompare = (left, right) => {
      const phaseDifference = (phaseOrder.get(String(left.phase_ref || "")) ?? Number.MAX_SAFE_INTEGER)
        - (phaseOrder.get(String(right.phase_ref || "")) ?? Number.MAX_SAFE_INTEGER);
      return phaseDifference || naturalCompare(identifier(left), identifier(right));
    };
    const rowOrder = new Map();
    for (const column of [...columns.keys()].sort((left, right) => left - right)) {
      columns.get(column).sort((left, right) => {
        const leftParents = incoming.get(identifier(left)) || [];
        const rightParents = incoming.get(identifier(right)) || [];
        const leftCenter = average(leftParents.map(parent => rowOrder.get(parent)).filter(Number.isFinite));
        const rightCenter = average(rightParents.map(parent => rowOrder.get(parent)).filter(Number.isFinite));
        return leftCenter - rightCenter || stableCompare(left, right);
      });
      columns.get(column).forEach((node, index) => rowOrder.set(identifier(node), index));
    }

    const maxDepth = Math.max(...columns.keys(), 0);
    const maxRows = Math.max(...[...columns.values()].map(rows => rows.length), 1);
    const width = LAYOUT_PADDING * 2 + (maxDepth + 1) * NODE_WIDTH + maxDepth * COLUMN_GAP;
    const height = LAYOUT_PADDING * 2 + maxRows * NODE_HEIGHT + Math.max(maxRows - 1, 0) * ROW_GAP;
    const positions = {};
    for (const [column, rows] of columns) {
      const columnHeight = rows.length * NODE_HEIGHT + Math.max(rows.length - 1, 0) * ROW_GAP;
      const top = (height - columnHeight) / 2;
      rows.forEach((node, index) => {
        positions[identifier(node)] = {
          x: LAYOUT_PADDING + column * (NODE_WIDTH + COLUMN_GAP),
          y: top + index * (NODE_HEIGHT + ROW_GAP),
          depth: column,
          row: index,
        };
      });
    }
    return { width, height, positions, maxDepth };
  }

  function computeLineage(nodes, edges, selectedId) {
    const ids = new Set(nodes.map(identifier));
    if (!selectedId || !ids.has(selectedId)) return null;
    const parents = new Map([...ids].map(id => [id, []]));
    const children = new Map([...ids].map(id => [id, []]));
    for (const edge of edges) {
      if (!ids.has(edge.source) || !ids.has(edge.target)) continue;
      parents.get(edge.target).push(edge.source);
      children.get(edge.source).push(edge.target);
    }
    const ancestors = traverse(parents, selectedId);
    const descendants = traverse(children, selectedId);
    return {
      selectedId,
      ancestors,
      descendants,
      nodeIds: new Set([selectedId, ...ancestors, ...descendants]),
    };
  }

  function buildEdge(edge, source, target, shape) {
    const group = svgElement("g", "research-tree-edge-group");
    if (shape.branch) group.classList.add("branch");
    if (shape.merge) group.classList.add("merge");
    group.dataset.source = edge.source;
    group.dataset.target = edge.target;
    const x1 = source.x + NODE_WIDTH + 5;
    const y1 = source.y + NODE_HEIGHT / 2;
    const x2 = target.x - 5;
    const y2 = target.y + NODE_HEIGHT / 2;
    const handle = Math.min(110, Math.max(32, Math.abs(x2 - x1) * 0.45));
    const path = svgElement("path", "research-tree-edge");
    path.setAttribute("d", `M ${x1} ${y1} C ${x1 + handle} ${y1}, ${x2 - handle} ${y2}, ${x2} ${y2}`);
    const sourceDot = svgElement("circle", "research-tree-edge-dot source");
    sourceDot.setAttribute("cx", String(x1));
    sourceDot.setAttribute("cy", String(y1));
    sourceDot.setAttribute("r", "3.4");
    const targetDot = svgElement("circle", "research-tree-edge-dot target");
    targetDot.setAttribute("cx", String(x2));
    targetDot.setAttribute("cy", String(y2));
    targetDot.setAttribute("r", "3.4");
    const title = svgElement("title", "");
    title.textContent = `${edge.source} to ${edge.target}`;
    group.append(path, sourceDot, targetDot, title);
    return group;
  }

  function buildNodeCard(node, phase, phaseIndex, position) {
    const button = element("button", `research-tree-node ${statusTone(node.status)}`);
    button.type = "button";
    button.dataset.nodeId = identifier(node);
    button.style.left = `${position.x}px`;
    button.style.top = `${position.y}px`;
    button.style.setProperty("--phase-color", phaseColor(phaseIndex));
    const heading = element("div", "research-tree-node-heading");
    const identity = element("div", "research-tree-node-identity");
    identity.append(
      element("span", "research-tree-phase", String(phase?.phase_id || node.phase_ref || "phase")),
      element("span", "research-tree-node-id", identifier(node)),
    );
    const status = element("span", "research-tree-node-status");
    status.append(element("span", "research-tree-status-dot"), document.createTextNode(String(node.status || "unknown")));
    heading.append(identity, status);
    const title = element("div", "research-tree-node-title", String(node.title || node.objective || identifier(node)));
    const opening = object(node.opening_decision);
    const decision = element("div", "research-tree-node-copy");
    decision.append(element("span", "research-tree-node-label", "Decision"), element("span", "research-tree-node-text", String(opening.rationale || node.objective || "No rationale recorded.")));
    const result = object(node.result);
    const outcome = element("div", "research-tree-node-copy outcome");
    outcome.append(element("span", "research-tree-node-label", "Outcome"), element("span", "research-tree-node-text", String(result.summary || "Pending")));
    const attemptCount = records(node.attempts).length;
    const meta = element("div", "research-tree-node-meta", `${attemptCount} attempts | ${Number(node.compute_run_count || 0)} runs${node.primary_claim_ref ? ` | ${node.primary_claim_ref}` : ""}`);
    button.append(heading, title, decision, outcome, meta);
    button.title = [node.title, opening.rationale, result.summary].filter(Boolean).join("\n");
    return button;
  }

  function buildOutlineNode(node, phase, phaseIndex, depth) {
    const button = element("button", `research-tree-outline-node ${statusTone(node.status)}`);
    button.type = "button";
    button.dataset.nodeId = identifier(node);
    button.style.setProperty("--tree-indent", `${Math.min(depth, 4) * 18}px`);
    button.style.setProperty("--phase-color", phaseColor(phaseIndex));
    const head = element("div", "research-tree-outline-head");
    head.append(
      element("span", "research-tree-phase", String(phase?.phase_id || node.phase_ref || "phase")),
      element("span", "research-tree-node-id", identifier(node)),
      element("span", "research-tree-outline-status", String(node.status || "unknown")),
    );
    const title = element("div", "research-tree-outline-title", String(node.title || node.objective || identifier(node)));
    const dependencies = records(node.dependency_refs);
    const lineage = element("div", "research-tree-outline-lineage", dependencies.length ? `from ${dependencies.join(", ")}` : "entry decision");
    button.append(head, title, lineage);
    return button;
  }

  function iconButton(iconName, label) {
    const button = element("button", "icon-button research-tree-action");
    button.type = "button";
    button.title = label;
    button.setAttribute("aria-label", label);
    const svg = svgElement("svg", "icon");
    svg.setAttribute("aria-hidden", "true");
    const use = svgElement("use", "");
    use.setAttribute("href", `#icon-${iconName}`);
    svg.append(use);
    button.append(svg);
    return button;
  }

  function phaseColor(index) {
    return `var(${PHASE_COLORS[index % PHASE_COLORS.length]})`;
  }

  function statusTone(value) {
    const normalized = String(value || "").toLowerCase();
    if (["completed", "supported", "pass", "current", "accepted", "success", "resolved"].includes(normalized)) return "good";
    if (["failed", "fail", "error", "blocked", "contradicted", "blocking", "invalid"].includes(normalized)) return "bad";
    if (["inconclusive", "warning", "stopped", "historical", "stale", "submission_ambiguous"].includes(normalized)) return "warn";
    return "info";
  }

  function traverse(adjacency, start) {
    const seen = new Set();
    const stack = [...(adjacency.get(start) || [])];
    while (stack.length) {
      const current = stack.pop();
      if (seen.has(current)) continue;
      seen.add(current);
      stack.push(...(adjacency.get(current) || []));
    }
    return seen;
  }

  function countsBy(edges, key) {
    const result = new Map();
    for (const edge of edges) result.set(edge[key], (result.get(edge[key]) || 0) + 1);
    return result;
  }

  function identifier(node) {
    return String(node?.node_id || node?.id || "");
  }

  function naturalCompare(left, right) {
    return String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: "base" });
  }

  function average(values) {
    return values.length ? values.reduce((total, value) => total + value, 0) / values.length : Number.MAX_SAFE_INTEGER;
  }

  function records(value) {
    return Array.isArray(value) ? value : [];
  }

  function object(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function element(tagName, className = "", text = null) {
    const target = document.createElement(tagName);
    if (className) target.className = className;
    if (text !== null) target.textContent = text;
    return target;
  }

  function svgElement(tagName, className = "") {
    const target = document.createElementNS(SVG_NS, tagName);
    if (className) target.setAttribute("class", className);
    return target;
  }

  function clamp(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, value));
  }

  function validViewport(value) {
    return value && [value.x, value.y, value.zoom].every(Number.isFinite) && value.zoom >= MIN_ZOOM && value.zoom <= MAX_ZOOM;
  }

  function emptyController() {
    return Object.freeze({ destroy() {}, fit() {}, getViewport: () => null, setSelected() {} });
  }

  global.TSResearchTree = Object.freeze({ mount, computeLayout, computeLineage });
})(window);
