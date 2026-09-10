"use strict";

(function attachClaimMap(global) {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const NODE_WIDTH = 256;
  const NODE_HEIGHT = 128;
  const COLUMN_GAP = 112;
  const ROW_GAP = 28;
  const LAYOUT_PADDING = 42;
  const EDGE_LANE_GAP = 28;
  const EDGE_LANE_OFFSET = 30;
  const MIN_ZOOM = 0.28;
  const MAX_ZOOM = 1.8;

  function mount(root, options = {}) {
    if (!(root instanceof Element)) throw new TypeError("Claim Map root must be an Element");
    const allNodes = records(options.nodes).filter(node => identifier(node));
    const nodeById = new Map(allNodes.map(node => [identifier(node), node]));
    const allEdges = records(options.edges).filter(edge => nodeById.has(edge.source) && nodeById.has(edge.target));
    const focusIds = new Set(records(options.focusClaimRefs).filter(claimId => nodeById.has(claimId)));
    const highlightIds = options.highlightIds instanceof Set ? options.highlightIds : null;
    let selectedId = nodeById.has(options.selectedId) ? options.selectedId : null;
    let selectedRelationId = allEdges.some(edge => edge.id === options.selectedRelationId)
      ? options.selectedRelationId
      : null;
    let filters = normalizeFilters(options.filters);
    const restoreInitialViewport = validViewport(options.viewport);
    let viewport = restoreInitialViewport ? { ...options.viewport } : { x: 0, y: 0, zoom: 1 };
    let currentNodes = [];
    let currentEdges = [];
    let layout = emptyLayout();
    let canvas = null;
    let frame = null;
    let dragging = null;
    let resizeObserver = null;
    const nodeElements = new Map();
    const outlineElements = new Map();
    const relationElements = new Map();
    root.replaceChildren();
    root.classList.add("claim-map");
    if (!allNodes.length) {
      root.append(element("div", "empty", tr("claimMap.noClaims", "No scientific Claims are recorded.")));
      return emptyController();
    }

    const toolbar = element("div", "claim-map-toolbar");
    const filterGroup = element("div", "claim-map-filters");
    const statusSelect = filterSelect(
      tr("claimMap.filterStatus", "Filter Claim status"),
      [["", tr("claimMap.allStatuses", "All statuses")], ...uniqueValues(allNodes, "status").map(value => [value, trStatus(value)])],
      filters.status,
    );
    const typeSelect = filterSelect(
      tr("claimMap.filterType", "Filter Claim type"),
      [["", tr("claimMap.allTypes", "All Claim types")], ...uniqueValues(allNodes, "claim_type").map(value => [value, value])],
      filters.claimType,
    );
    const acceptanceSelect = filterSelect(
      tr("claimMap.filterAcceptance", "Filter acceptance state"),
      [["", tr("claimMap.allAcceptance", "All acceptance")], ["current", tr("claimMap.currentAcceptance", "Current acceptance")], ["historical", tr("claimMap.historicalAcceptance", "Historical acceptance")], ["none", tr("claimMap.notAccepted", "Not accepted")]],
      filters.acceptance,
    );
    filters = {
      status: statusSelect.value,
      claimType: typeSelect.value,
      acceptance: acceptanceSelect.value,
    };
    filterGroup.append(statusSelect, typeSelect, acceptanceSelect);

    const actions = element("div", "claim-map-actions");
    const stats = element("div", "claim-map-stats");
    const focusButton = iconButton("focus", tr("claimMap.focus", "Focus current Claims"));
    focusButton.disabled = focusIds.size === 0;
    if (focusButton.disabled) {
      const reason = tr("claimMap.noFocus", "No focused Claims are recorded");
      focusButton.title = reason;
      focusButton.setAttribute("aria-label", reason);
    }
    const zoomOutButton = iconButton("zoom-out", tr("tree.zoomOut", "Zoom out"));
    const zoomInButton = iconButton("zoom-in", tr("tree.zoomIn", "Zoom in"));
    const fitButton = iconButton("fit", tr("claimMap.fit", "Fit Claim Map"));
    actions.append(stats, focusButton, zoomOutButton, zoomInButton, fitButton);
    toolbar.append(filterGroup, actions);

    const stage = element("div", "claim-map-stage");
    stage.tabIndex = 0;
    stage.setAttribute("role", "application");
    stage.setAttribute("aria-label", tr("claimMap.aria", "Scientific Claim relation map"));
    const outline = element("div", "claim-map-outline");
    outline.setAttribute("aria-label", tr("claimMap.outlineAria", "Scientific Claim relation outline"));
    root.append(toolbar, stage, outline);

    function renderVisualization({ restoreViewport = false } = {}) {
      if (frame !== null) global.cancelAnimationFrame(frame);
      frame = null;
      nodeElements.clear();
      outlineElements.clear();
      relationElements.clear();
      stage.replaceChildren();
      outline.replaceChildren();

      currentNodes = filterNodes(allNodes, filters, highlightIds);
      const visibleIds = new Set(currentNodes.map(identifier));
      currentEdges = allEdges.filter(edge => visibleIds.has(edge.source) && visibleIds.has(edge.target));
      layout = computeLayout(currentNodes, currentEdges);
      stats.textContent = `${currentNodes.length} ${tr("claimMap.claims", "claims")} | ${currentEdges.length} ${tr("claimMap.relations", "relations")}`;

      if (!currentNodes.length) {
        canvas = null;
        stage.append(element("div", "claim-map-empty", tr("claimMap.noMatch", "No Claims match the current filters.")));
        outline.append(element("div", "claim-map-empty", tr("claimMap.noMatch", "No Claims match the current filters.")));
        return;
      }

      canvas = element("div", "claim-map-canvas");
      canvas.style.width = `${layout.width}px`;
      canvas.style.height = `${layout.height}px`;
      const edgeSvg = svgElement("svg", "claim-map-edges");
      edgeSvg.setAttribute("width", String(layout.width));
      edgeSvg.setAttribute("height", String(layout.height));
      edgeSvg.setAttribute("viewBox", `0 0 ${layout.width} ${layout.height}`);

      const nodeLayer = element("div", "claim-map-nodes");
      let longEdgeIndex = 0;
      for (const edge of currentEdges) {
        const source = layout.positions[edge.source];
        const target = layout.positions[edge.target];
        if (!source || !target) continue;
        const laneIndex = Math.abs(target.depth - source.depth) > 1 ? longEdgeIndex++ : 0;
        const edgeElement = buildEdge(edge, source, target, laneIndex);
        edgeElement.addEventListener("click", event => {
          event.stopPropagation();
          selectRelation(edge.id);
        });
        edgeElement.addEventListener("keydown", event => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          selectRelation(edge.id);
        });
        edgeSvg.append(edgeElement);
        rememberRelationElement(edge.id, edgeElement);
      }
      for (const node of currentNodes) {
        const claimId = identifier(node);
        const position = layout.positions[claimId];
        const card = buildNodeCard(node, position);
        card.addEventListener("click", () => selectClaim(claimId));
        nodeLayer.append(card);
        nodeElements.set(claimId, card);
      }
      canvas.append(edgeSvg, nodeLayer);
      stage.append(canvas);
      renderOutline();
      applyHighlights();

      frame = global.requestAnimationFrame(() => {
        if (restoreViewport && validViewport(viewport)) applyTransform({ notify: false });
        else fitAll();
      });
    }

    function renderOutline() {
      const incoming = new Map(currentNodes.map(node => [identifier(node), []]));
      for (const edge of currentEdges) incoming.get(edge.target)?.push(edge);
      const orderedNodes = [...currentNodes].sort((left, right) => {
        const a = layout.positions[identifier(left)];
        const b = layout.positions[identifier(right)];
        return a.depth - b.depth || a.y - b.y || naturalCompare(identifier(left), identifier(right));
      });
      for (const node of orderedNodes) {
        const claimId = identifier(node);
        const position = layout.positions[claimId];
        const entry = buildOutlineNode(node, incoming.get(claimId), position.depth);
        entry.claimButton.addEventListener("click", () => selectClaim(claimId));
        for (const item of entry.relationButtons) {
          item.button.addEventListener("click", () => selectRelation(item.relationId));
          rememberRelationElement(item.relationId, item.button);
        }
        outline.append(entry.root);
        outlineElements.set(claimId, entry.claimButton);
      }
    }

    function rememberRelationElement(relationId, target) {
      if (!relationElements.has(relationId)) relationElements.set(relationId, []);
      relationElements.get(relationId).push(target);
    }

    function selectClaim(claimId) {
      selectedId = claimId;
      selectedRelationId = null;
      applyHighlights();
      if (typeof options.onSelectClaim === "function") options.onSelectClaim(claimId);
    }

    function selectRelation(relationId) {
      selectedRelationId = relationId;
      selectedId = null;
      applyHighlights();
      if (typeof options.onSelectRelation === "function") options.onSelectRelation(relationId);
    }

    function setSelected(claimId) {
      selectedId = nodeById.has(claimId) ? claimId : null;
      selectedRelationId = null;
      applyHighlights();
    }

    function setSelectedRelation(relationId) {
      selectedRelationId = allEdges.some(edge => edge.id === relationId) ? relationId : null;
      selectedId = null;
      applyHighlights();
    }

    function applyHighlights() {
      const lineage = computeLineage(currentNodes, currentEdges, selectedId);
      const selectedRelation = currentEdges.find(edge => edge.id === selectedRelationId);
      const relationNodeIds = selectedRelation ? new Set([selectedRelation.source, selectedRelation.target]) : null;
      for (const [claimId, target] of [...nodeElements, ...outlineElements]) {
        const inLineage = !lineage || lineage.nodeIds.has(claimId);
        const inRelation = !relationNodeIds || relationNodeIds.has(claimId);
        target.classList.toggle("selected", claimId === selectedId);
        target.classList.toggle("focused", focusIds.has(claimId));
        target.classList.toggle("lineage", Boolean(lineage && inLineage));
        target.classList.toggle("relation-endpoint", Boolean(relationNodeIds && inRelation));
        target.classList.toggle("dimmed", Boolean((lineage && !inLineage) || (relationNodeIds && !inRelation)));
      }
      for (const edge of currentEdges) {
        const inLineage = !lineage || (lineage.nodeIds.has(edge.source) && lineage.nodeIds.has(edge.target));
        const isSelected = edge.id === selectedRelationId;
        for (const target of relationElements.get(edge.id) || []) {
          target.classList.toggle("selected", isSelected);
          target.classList.toggle("lineage", Boolean(lineage && inLineage));
          target.classList.toggle("dimmed", Boolean((lineage && !inLineage) || (selectedRelation && !isSelected)));
        }
      }
    }

    function applyTransform({ notify = true } = {}) {
      if (!canvas) return;
      canvas.style.transform = `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})`;
      if (notify && typeof options.onViewportChange === "function") options.onViewportChange({ ...viewport });
    }

    function fitNodeIds(ids, maxZoom = 1) {
      if (!canvas || !stage.clientWidth || !stage.clientHeight) return;
      const positions = ids.map(id => layout.positions[id]).filter(Boolean);
      if (!positions.length) return;
      const minX = Math.min(...positions.map(position => position.x));
      const minY = Math.min(...positions.map(position => position.y));
      const maxX = Math.max(...positions.map(position => position.x + NODE_WIDTH));
      const maxY = Math.max(...positions.map(position => position.y + NODE_HEIGHT));
      const width = Math.max(maxX - minX, 1);
      const height = Math.max(maxY - minY, 1);
      const padding = 72;
      viewport.zoom = clamp(
        Math.min((stage.clientWidth - padding) / width, (stage.clientHeight - padding) / height, maxZoom),
        MIN_ZOOM,
        MAX_ZOOM,
      );
      viewport.x = (stage.clientWidth - width * viewport.zoom) / 2 - minX * viewport.zoom;
      viewport.y = (stage.clientHeight - height * viewport.zoom) / 2 - minY * viewport.zoom;
      applyTransform();
    }

    function fitAll() {
      fitNodeIds(currentNodes.map(identifier));
    }

    function zoomBy(factor, clientX = null, clientY = null) {
      if (!canvas) return;
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

    function updateFilters() {
      filters = {
        status: statusSelect.value,
        claimType: typeSelect.value,
        acceptance: acceptanceSelect.value,
      };
      if (typeof options.onFiltersChange === "function") options.onFiltersChange({ ...filters });
      renderVisualization();
    }

    statusSelect.addEventListener("change", updateFilters);
    typeSelect.addEventListener("change", updateFilters);
    acceptanceSelect.addEventListener("change", updateFilters);
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
      if (event.button !== 0 || event.target.closest("button, [data-claim-interactive]")) return;
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

    renderVisualization({ restoreViewport: restoreInitialViewport });
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
      getFilters: () => ({ ...filters }),
      getViewport: () => ({ ...viewport }),
      setSelected,
      setSelectedRelation,
    });
  }

  function computeLayout(nodes, edges) {
    if (!nodes.length) return emptyLayout();
    const ids = new Set(nodes.map(identifier));
    const incoming = new Map([...ids].map(id => [id, []]));
    for (const edge of edges) {
      if (ids.has(edge.source) && ids.has(edge.target)) incoming.get(edge.target).push(edge.source);
    }
    const depth = new Map();
    function visit(claimId, stack = new Set()) {
      if (depth.has(claimId)) return depth.get(claimId);
      if (stack.has(claimId)) return 0;
      const parents = incoming.get(claimId) || [];
      const nextStack = new Set(stack).add(claimId);
      const value = parents.length ? 1 + Math.max(...parents.map(parent => visit(parent, nextStack))) : 0;
      depth.set(claimId, value);
      return value;
    }
    for (const node of nodes) visit(identifier(node));

    const columns = new Map();
    for (const node of nodes) {
      const value = depth.get(identifier(node)) || 0;
      if (!columns.has(value)) columns.set(value, []);
      columns.get(value).push(node);
    }
    const rowOrder = new Map();
    for (const column of [...columns.keys()].sort((left, right) => left - right)) {
      columns.get(column).sort((left, right) => {
        const leftCenter = average((incoming.get(identifier(left)) || []).map(parent => rowOrder.get(parent)).filter(Number.isFinite));
        const rightCenter = average((incoming.get(identifier(right)) || []).map(parent => rowOrder.get(parent)).filter(Number.isFinite));
        return leftCenter - rightCenter || naturalCompare(identifier(left), identifier(right));
      });
      columns.get(column).forEach((node, index) => rowOrder.set(identifier(node), index));
    }

    const maxDepth = Math.max(...columns.keys(), 0);
    const longEdgeCount = edges.filter(edge => {
      const sourceDepth = depth.get(edge.source);
      const targetDepth = depth.get(edge.target);
      return Number.isFinite(sourceDepth) && Number.isFinite(targetDepth) && Math.abs(targetDepth - sourceDepth) > 1;
    }).length;
    const verticalPadding = LAYOUT_PADDING + Math.ceil(longEdgeCount / 2) * EDGE_LANE_GAP;
    const maxRows = Math.max(...[...columns.values()].map(rows => rows.length), 1);
    const width = LAYOUT_PADDING * 2 + (maxDepth + 1) * NODE_WIDTH + maxDepth * COLUMN_GAP;
    const height = verticalPadding * 2 + maxRows * NODE_HEIGHT + Math.max(maxRows - 1, 0) * ROW_GAP;
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

  function filterNodes(nodes, filters = {}, highlightIds = null) {
    const normalized = normalizeFilters(filters);
    return records(nodes).filter(node => {
      const claimId = identifier(node);
      if (highlightIds instanceof Set && !highlightIds.has(claimId)) return false;
      if (normalized.status && String(node.status || "") !== normalized.status) return false;
      if (normalized.claimType && String(node.claim_type || "") !== normalized.claimType) return false;
      if (normalized.acceptance && String(node.acceptance_state || "none") !== normalized.acceptance) return false;
      return true;
    });
  }

  function buildEdge(edge, source, target, laneIndex) {
    const group = svgElement("g", `claim-map-edge-group ${relationTone(edge.kind)}`);
    group.dataset.claimInteractive = "relation";
    group.dataset.relationId = String(edge.id || "");
    group.setAttribute("tabindex", "0");
    group.setAttribute("role", "button");
    group.setAttribute("aria-label", tr("claimMap.edgeAria", "{{source}} {{relation}} {{target}}", { source: edge.source, relation: edge.kind || tr("claimMap.relation", "relation"), target: edge.target }));
    const route = computeEdgeRoute(source, target, laneIndex);
    const hit = svgElement("path", "claim-map-edge-hit");
    hit.setAttribute("d", route.pathData);
    const path = svgElement("path", "claim-map-edge");
    path.setAttribute("d", route.pathData);
    const arrow = svgElement("path", "claim-map-arrow");
    arrow.setAttribute("d", `M ${route.x2} ${route.y2} L ${route.x2 - 9} ${route.y2 - 5} L ${route.x2 - 9} ${route.y2 + 5} Z`);
    const kind = String(edge.kind || "relation");
    const labelLines = wrapRelationLabel(kind, route.long ? 22 : 12);
    const labelWidth = Math.max(54, 18 + Math.max(...labelLines.map(line => line.length)) * 6.2);
    const labelHeight = 10 + labelLines.length * 11;
    const labelGroup = svgElement("g", "claim-map-edge-label");
    const background = svgElement("rect");
    background.setAttribute("x", String(route.labelX - labelWidth / 2));
    background.setAttribute("y", String(route.labelY - labelHeight / 2));
    background.setAttribute("width", String(labelWidth));
    background.setAttribute("height", String(labelHeight));
    background.setAttribute("rx", "4");
    const text = svgElement("text");
    text.setAttribute("text-anchor", "middle");
    labelLines.forEach((line, index) => {
      const row = svgElement("tspan");
      row.setAttribute("x", String(route.labelX));
      row.setAttribute("y", String(route.labelY - ((labelLines.length - 1) * 11) / 2 + index * 11 + 3.5));
      row.textContent = line;
      text.append(row);
    });
    labelGroup.append(background, text);
    const title = svgElement("title");
    title.textContent = [kind, edge.rationale].filter(Boolean).join(": ");
    group.append(hit, path, arrow, labelGroup, title);
    return group;
  }

  function computeEdgeRoute(source, target, laneIndex = 0) {
    const x1 = source.x + NODE_WIDTH + 5;
    const y1 = source.y + NODE_HEIGHT / 2;
    const x2 = target.x - 9;
    const y2 = target.y + NODE_HEIGHT / 2;
    const long = Math.abs((target.depth || 0) - (source.depth || 0)) > 1;
    if (!long) {
      const handle = Math.min(118, Math.max(34, Math.abs(x2 - x1) * 0.45));
      return {
        long,
        x2,
        y2,
        labelX: (x1 + x2) / 2,
        labelY: (y1 + y2) / 2,
        pathData: `M ${x1} ${y1} C ${x1 + handle} ${y1}, ${x2 - handle} ${y2}, ${x2} ${y2}`,
      };
    }
    const level = Math.floor(Math.max(0, laneIndex) / 2);
    const offset = EDGE_LANE_OFFSET + level * EDGE_LANE_GAP;
    const laneY = laneIndex % 2 === 0
      ? Math.min(source.y, target.y) - offset
      : Math.max(source.y + NODE_HEIGHT, target.y + NODE_HEIGHT) + offset;
    const bend = Math.min(72, Math.max(34, Math.abs(x2 - x1) * 0.12));
    return {
      long,
      x2,
      y2,
      labelX: (x1 + x2) / 2,
      labelY: laneY,
      pathData: `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x1 + bend} ${laneY}, ${x1 + bend * 2} ${laneY} L ${x2 - bend * 2} ${laneY} C ${x2 - bend} ${laneY}, ${x2 - bend} ${y2}, ${x2} ${y2}`,
    };
  }

  function wrapRelationLabel(value, maxCharacters = 12) {
    const text = String(value || "relation");
    const lines = [];
    let remaining = text;
    while (remaining.length > maxCharacters) {
      const separator = remaining.lastIndexOf("_", maxCharacters - 1);
      const splitAt = separator >= Math.floor(maxCharacters / 2) ? separator + 1 : maxCharacters;
      lines.push(remaining.slice(0, splitAt));
      remaining = remaining.slice(splitAt);
    }
    if (remaining) lines.push(remaining);
    return lines;
  }

  function buildNodeCard(node, position) {
    const button = element("button", `claim-map-node ${statusTone(node.status)}`);
    button.type = "button";
    button.dataset.claimInteractive = "claim";
    button.dataset.claimId = identifier(node);
    button.style.left = `${position.x}px`;
    button.style.top = `${position.y}px`;
    const heading = element("div", "claim-map-node-heading");
    heading.append(
      element("span", "claim-map-node-id", identifier(node)),
      statusLabel(node.status),
    );
    const statement = element("div", "claim-map-node-statement", String(node.statement || tr("claimMap.noStatement", "No statement recorded.")));
    const meta = element("div", "claim-map-node-meta");
    meta.append(element("span", "claim-map-node-type", String(node.claim_type || "claim")));
    if (String(node.acceptance_state || "none") !== "none") {
      meta.append(element("span", `claim-map-acceptance ${node.acceptance_state}`, trStatus(node.acceptance_state)));
    }
    const counts = element(
      "div",
      "claim-map-node-counts",
      tr("claimMap.counts", "{{observations}} observations · {{checks}} checks · {{reviews}} reviews", { observations: Number(node.observation_count) || 0, checks: Number(node.validation_result_count) || 0, reviews: Number(node.review_run_count) || 0 }),
    );
    button.append(heading, statement, meta, counts);
    button.title = String(node.statement || identifier(node));
    return button;
  }

  function buildOutlineNode(node, incomingEdges, depth) {
    const root = element("div", "claim-map-outline-entry");
    root.style.setProperty("--claim-indent", `${Math.min(depth, 4) * 18}px`);
    const button = element("button", `claim-map-outline-node ${statusTone(node.status)}`);
    button.type = "button";
    button.dataset.claimInteractive = "claim";
    button.dataset.claimId = identifier(node);
    const heading = element("div", "claim-map-outline-heading");
    heading.append(element("span", "claim-map-node-id", identifier(node)), statusLabel(node.status));
    const statement = element("div", "claim-map-outline-statement", String(node.statement || tr("claimMap.noStatement", "No statement recorded.")));
    const meta = element("div", "claim-map-outline-meta", `${node.claim_type || tr("map.claim", "claim")} | ${node.acceptance_state ? trStatus(node.acceptance_state) : tr("claimMap.notAccepted", "not accepted")}`);
    button.append(heading, statement, meta);
    root.append(button);
    const relationButtons = [];
    if (records(incomingEdges).length) {
      const relations = element("div", "claim-map-outline-relations");
      for (const edge of records(incomingEdges)) {
        const relation = element("button", `claim-map-outline-relation ${relationTone(edge.kind)}`, `${edge.kind || tr("claimMap.relation", "relation")} ${tr("claimMap.relationFrom", "from")} ${edge.source}`);
        relation.type = "button";
        relation.dataset.claimInteractive = "relation";
        relation.dataset.relationId = String(edge.id || "");
        relation.title = String(edge.rationale || relation.textContent);
        relations.append(relation);
        relationButtons.push({ relationId: edge.id, button: relation });
      }
      root.append(relations);
    } else {
      root.append(element("div", "claim-map-outline-root", tr("claimMap.rootClaim", "Root Claim")));
    }
    return { root, claimButton: button, relationButtons };
  }

  function statusLabel(value) {
    const target = element("span", "claim-map-node-status");
    target.append(element("span", "claim-map-status-dot"), document.createTextNode(trStatus(value || "unknown")));
    return target;
  }

  function filterSelect(label, choices, value) {
    const select = document.createElement("select");
    select.className = "claim-map-filter";
    select.setAttribute("aria-label", label);
    for (const [optionValue, optionLabel] of choices) select.append(new Option(optionLabel, optionValue));
    select.value = choices.some(([optionValue]) => optionValue === value) ? value : "";
    return select;
  }

  function tr(key, fallback = key, variables = null) {
    return global.TSExplorerI18n?.t(key, fallback, variables) || fallback;
  }

  function trStatus(value) {
    return global.TSExplorerI18n?.status(value) || String(value || "unknown");
  }

  function iconButton(iconName, label) {
    const button = element("button", "icon-button claim-map-action");
    button.type = "button";
    button.title = label;
    button.setAttribute("aria-label", label);
    const svg = svgElement("svg", "icon");
    svg.setAttribute("aria-hidden", "true");
    const use = svgElement("use");
    use.setAttribute("href", `#icon-${iconName}`);
    svg.append(use);
    button.append(svg);
    return button;
  }

  function relationTone(value) {
    const normalized = String(value || "").toLowerCase();
    if (normalized.includes("conflict") || normalized.includes("contradict")) return "conflict";
    if (normalized.includes("alternative")) return "alternative";
    if (normalized.includes("refine")) return "refinement";
    if (normalized.includes("depend") || normalized.includes("support")) return "dependency";
    return "neutral";
  }

  function statusTone(value) {
    const normalized = String(value || "").toLowerCase();
    if (["completed", "supported", "pass", "current", "accepted", "success", "resolved"].includes(normalized)) return "good";
    if (["failed", "fail", "error", "blocked", "contradicted", "blocking", "invalid", "refuted"].includes(normalized)) return "bad";
    if (["inconclusive", "warning", "stopped", "historical", "stale"].includes(normalized)) return "warn";
    return "info";
  }

  function uniqueValues(nodes, key) {
    return [...new Set(nodes.map(node => String(node[key] || "")).filter(Boolean))]
      .sort(naturalCompare);
  }

  function normalizeFilters(value) {
    const source = object(value);
    return {
      status: String(source.status || ""),
      claimType: String(source.claimType || ""),
      acceptance: String(source.acceptance || ""),
    };
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

  function identifier(node) {
    return String(node?.claim_id || node?.id || "");
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

  function emptyLayout() {
    return { width: 0, height: 0, positions: {}, maxDepth: 0 };
  }

  function emptyController() {
    return Object.freeze({
      destroy() {},
      fit() {},
      getFilters: () => normalizeFilters(),
      getViewport: () => null,
      setSelected() {},
      setSelectedRelation() {},
    });
  }

  global.TSClaimMap = Object.freeze({
    mount,
    computeLayout,
    computeLineage,
    computeEdgeRoute,
    filterNodes,
    wrapRelationLabel,
  });
})(window);
