const graph = __GRAPH_DATA__;
const workspace = document.getElementById("workspace");
const svg = d3.select("#graph");
const element = svg.node();
const nodes = graph.nodes.map((node) => ({ ...node }));
const allLinks = graph.links.map((link) => ({ ...link }));
const nodeById = new Map(nodes.map((node) => [node.id, node]));
const motionReduced = matchMedia("(prefers-reduced-motion: reduce)");

svg.select("#static-graph").remove();

const wrap = element.parentElement;
const zoomRoot = svg.append("g");
const linkLayer = zoomRoot.append("g");
const nodeLayer = zoomRoot.append("g");
const endpointId = (value) => typeof value === "object" ? value.id : value;
const degree = new Map(nodes.map((node) => [node.id, 0]));

allLinks.forEach((link) => {
  degree.set(endpointId(link.source), (degree.get(endpointId(link.source)) || 0) + 1);
  degree.set(endpointId(link.target), (degree.get(endpointId(link.target)) || 0) + 1);
});

const prominentList = [...nodes]
  .filter((node) => node.kind === "document" && !node.is_session)
  .sort((left, right) => (degree.get(right.id) || 0) - (degree.get(left.id) || 0))
  .slice(0, 5);
const prominent = new Set(prominentList.map((node) => node.id));
const labelLeft = new Set(prominentList.filter((_, index) => index % 2).map((node) => node.id));
const colorMap = {
  pattern: "var(--pattern)",
  concept: "var(--concept)",
  decision: "var(--decision)",
  session: "var(--session)",
  source: "var(--source)",
  tag: "var(--tag)",
};

let visibleNodes = [...nodes];
let visibleIds = new Set(nodes.map((node) => node.id));
let activeLinks = [];
let activeCollection = "all";
let activeCategory = "all";
let selectedNode = null;
let selectionHistory = [];
let activeSearchIndex = -1;
let resizeFrame = 0;
let initialFitPending = true;
let linkSelection;

function compactGraph() { return wrap.clientWidth < 600; }
function chargeStrength(node) { return compactGraph() ? (node.kind === "tag" ? -48 : -88) : (node.kind === "tag" ? -72 : -155); }
function collisionRadius(node) { return compactGraph() ? (node.kind === "tag" ? 20 : 27) : (node.kind === "tag" ? 30 : 40); }
function linkDistance(link) { return compactGraph() ? (link.kind === "tag" ? 62 : link.kind === "semantic" ? 92 : 78) : (link.kind === "tag" ? 96 : link.kind === "semantic" ? 142 : 116); }

const simulation = d3.forceSimulation(nodes)
  .randomSource(d3.randomLcg(.417))
  .alphaDecay(.038)
  .velocityDecay(.42)
  .force("charge", d3.forceManyBody().strength(chargeStrength))
  .force("center", d3.forceCenter())
  .force("x", d3.forceX().strength(.035))
  .force("y", d3.forceY().strength(.035))
  .force("collision", d3.forceCollide().radius(collisionRadius));

function fillFor(node) { return colorMap[node.is_session ? "session" : node.category] || colorMap.source; }
function placeLabels() {
  const transform = d3.zoomTransform(element);
  const offset = 14 / transform.k;
  nodeSelection.select("text")
    .attr("y", 4 / transform.k)
    .style("font-size", `${12 / transform.k}px`)
    .style("stroke-width", `${5 / transform.k}px`)
    .each(function placeLabel(node) {
      const screenX = Number.isFinite(node.x) ? transform.applyX(node.x) : wrap.clientWidth / 2;
      const textWidth = this.getComputedTextLength() * transform.k;
      const leftSpace = screenX - 18;
      const rightSpace = wrap.clientWidth - screenX - 18;
      const useLeft = leftSpace >= textWidth && rightSpace < textWidth
        ? true
        : rightSpace >= textWidth && leftSpace < textWidth
          ? false
          : leftSpace === rightSpace
            ? labelLeft.has(node.id)
            : leftSpace > rightSpace;
      d3.select(this)
        .attr("x", useLeft ? -offset : offset)
        .attr("text-anchor", useLeft ? "end" : "start");
    });
}
function symbol(node) {
  const base = node.kind === "tag" ? 90 : 170;
  const weight = Math.min(180, (degree.get(node.id) || 0) * 18);
  const type = node.kind === "tag" ? d3.symbolDiamond : node.is_session ? d3.symbolSquare : d3.symbolCircle;
  return d3.symbol().type(type).size(base + weight)();
}

const nodeSelection = nodeLayer.selectAll("g")
  .data(nodes, (node) => node.id)
  .join("g")
  .attr("class", (node) => `node ${node.kind} ${node.category} ${prominent.has(node.id) ? "prominent" : ""}`)
  .attr("role", "button")
  .attr("tabindex", 0)
  .attr("aria-label", (node) => `${node.title}, ${node.category}`)
  .call(d3.drag().on("start", dragStart).on("drag", dragged).on("end", dragEnd));

nodeSelection.append("circle").attr("class", "hit-area").attr("r", 24);
nodeSelection.append("path").attr("d", symbol).attr("fill", fillFor);
nodeSelection.append("text")
  .attr("x", (node) => labelLeft.has(node.id) ? -14 : 14)
  .attr("y", 4)
  .attr("text-anchor", (node) => labelLeft.has(node.id) ? "end" : "start")
  .text((node) => node.label);

nodeSelection
  .on("click", (event, node) => {
    if (!event.defaultPrevented) selectNode(node, false);
  })
  .on("keydown", (event, node) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectNode(node, false);
    }
  })
  .on("dblclick", (_, node) => { if (node.url) location.href = node.url; })
  .on("pointerenter", showTooltip)
  .on("pointermove", moveTooltip)
  .on("pointerleave", hideTooltip);

simulation
  .on("tick", () => {
    linkSelection?.attr("x1", (link) => link.source.x).attr("y1", (link) => link.source.y).attr("x2", (link) => link.target.x).attr("y2", (link) => link.target.y);
    nodeSelection.attr("transform", (node) => `translate(${node.x},${node.y})`);
    placeLabels();
  })
  .on("end", () => {
    if (initialFitPending && !selectedNode) {
      initialFitPending = false;
      fit();
    }
  });

const zoom = d3.zoom().scaleExtent([.18, 4]).on("zoom", (event) => {
  zoomRoot.attr("transform", event.transform);
  placeLabels();
});
svg.call(zoom);

function size() {
  const width = wrap.clientWidth;
  const height = element.clientHeight;
  svg.attr("viewBox", [0, 0, width, height]);
  simulation.force("center", d3.forceCenter(width / 2, height / 2));
  simulation.force("x").x(width / 2);
  simulation.force("y").y(height / 2);
  simulation.force("charge").strength(chargeStrength);
  simulation.force("collision").radius(collisionRadius);
  const force = simulation.force("link");
  if (force) force.distance(linkDistance);
}

function enabled(kind) { return document.getElementById(`layer-${kind}`).checked; }
function edgeVisible(link) { return visibleIds.has(endpointId(link.source)) && visibleIds.has(endpointId(link.target)); }
function updateCounts() {
  const documents = visibleNodes.filter((node) => node.kind === "document").length;
  const tags = visibleNodes.filter((node) => node.kind === "tag").length;
  document.getElementById("counts").textContent = `${documents} documents · ${tags} tags · ${activeLinks.length} visible edges`;
}

function updateLinks() {
  activeLinks = allLinks.filter((link) => enabled(link.kind) && edgeVisible(link));
  linkSelection = linkLayer.selectAll("line")
    .data(activeLinks, (link) => `${endpointId(link.source)}|${endpointId(link.target)}|${link.kind}`)
    .join("line")
    .attr("class", (link) => `edge ${link.kind}`)
    .attr("aria-label", (link) => link.kind === "semantic" ? `Semantic similarity ${Math.round((link.score || 0) * 100)} percent` : link.kind);
  simulation.force("link", d3.forceLink(activeLinks).id((node) => node.id).distance(linkDistance).strength((link) => link.kind === "semantic" ? .1 : .24));
  simulation.alpha(.72).restart();
  updateCounts();
  applySelectionHighlight();
}

function applyView(shouldFit = true) {
  const documents = nodes.filter((node) => node.kind === "document"
    && (activeCollection === "all" || node.collection === activeCollection)
    && (activeCategory === "all" || node.category === activeCategory));
  const ids = new Set(documents.map((node) => node.id));
  allLinks.filter((link) => link.kind === "tag" && (ids.has(endpointId(link.source)) || ids.has(endpointId(link.target)))).forEach((link) => {
    ids.add(endpointId(link.source));
    ids.add(endpointId(link.target));
  });
  visibleNodes = nodes.filter((node) => ids.has(node.id));
  visibleIds = new Set(visibleNodes.map((node) => node.id));
  nodeSelection.classed("filtered", (node) => !visibleIds.has(node.id));
  simulation.nodes(visibleNodes);
  document.querySelectorAll("[data-collection]").forEach((button) => {
    const active = activeCategory === "all" && button.dataset.collection === activeCollection;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  document.querySelectorAll("[data-category]").forEach((button) => {
    const active = button.dataset.category === activeCategory;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  if (selectedNode && !visibleIds.has(selectedNode.id)) clearSelection();
  updateLinks();
  if (shouldFit) setTimeout(fit, 360);
  if (innerWidth <= 820) openPanel(null);
}

function setCollection(name, shouldFit = true) {
  activeCollection = name;
  activeCategory = "all";
  applyView(shouldFit);
}

function setCategory(category, shouldFit = true) {
  activeCollection = "all";
  activeCategory = category;
  applyView(shouldFit);
}

function fit() {
  const positioned = visibleNodes.filter((node) => Number.isFinite(node.x) && Number.isFinite(node.y));
  const width = wrap.clientWidth;
  const height = element.clientHeight;
  if (!positioned.length || !width || !height) return;
  const xs = positioned.map((node) => node.x);
  const ys = positioned.map((node) => node.y);
  const padding = compactGraph() ? 24 : 44;
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const boundsWidth = Math.max(1, maxX - minX + padding * 2);
  const boundsHeight = Math.max(1, maxY - minY + padding * 2);
  const scale = Math.min(compactGraph() ? 2.6 : 1.9, .84 / Math.max(boundsWidth / width, boundsHeight / height));
  const transform = d3.zoomIdentity.translate(width / 2, height / 2).scale(scale).translate(-(minX + maxX) / 2, -(minY + maxY) / 2);
  if (motionReduced.matches) svg.call(zoom.transform, transform);
  else svg.transition().duration(320).ease(d3.easeCubicOut).call(zoom.transform, transform);
}

function focusNode(node) {
  if (!Number.isFinite(node.x) || !Number.isFinite(node.y)) return;
  const current = d3.zoomTransform(element);
  const scale = Math.max(1.15, Math.min(2, current.k));
  const transform = d3.zoomIdentity.translate(wrap.clientWidth / 2, element.clientHeight / 2).scale(scale).translate(-node.x, -node.y);
  if (motionReduced.matches) svg.call(zoom.transform, transform);
  else svg.transition().duration(300).ease(d3.easeCubicOut).call(zoom.transform, transform);
}

function zoomBy(factor) {
  svg.interrupt();
  if (motionReduced.matches) svg.call(zoom.scaleBy, factor);
  else svg.transition().duration(180).ease(d3.easeCubicOut).call(zoom.scaleBy, factor);
}

function moveTooltip(event) {
  const tooltip = document.getElementById("node-tooltip");
  const bounds = wrap.getBoundingClientRect();
  const width = tooltip.offsetWidth || 220;
  const height = tooltip.offsetHeight || 54;
  const left = Math.max(10, Math.min(bounds.width - width - 10, event.clientX - bounds.left + 14));
  const top = Math.max(10, Math.min(bounds.height - height - 10, event.clientY - bounds.top + 14));
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

function showTooltip(event, node) {
  const tooltip = document.getElementById("node-tooltip");
  document.getElementById("tooltip-title").textContent = node.title;
  document.getElementById("tooltip-meta").textContent = `${node.is_session ? "Codex session" : node.category} · Click to inspect`;
  tooltip.hidden = false;
  moveTooltip(event);
}

function hideTooltip() {
  document.getElementById("node-tooltip").hidden = true;
}

function applySelectionHighlight() {
  if (!selectedNode) {
    nodeSelection.classed("connected", false).classed("unrelated", false);
    linkSelection?.classed("connected", false).classed("unrelated", false);
    return;
  }
  const relatedIds = new Set([selectedNode.id]);
  activeLinks.forEach((link) => {
    const source = endpointId(link.source);
    const target = endpointId(link.target);
    if (source === selectedNode.id) relatedIds.add(target);
    if (target === selectedNode.id) relatedIds.add(source);
  });
  nodeSelection
    .classed("connected", (node) => relatedIds.has(node.id))
    .classed("unrelated", (node) => visibleIds.has(node.id) && !relatedIds.has(node.id));
  linkSelection
    ?.classed("connected", (link) => endpointId(link.source) === selectedNode.id || endpointId(link.target) === selectedNode.id)
    .classed("unrelated", (link) => endpointId(link.source) !== selectedNode.id && endpointId(link.target) !== selectedNode.id);
}

function relationNodes(node) {
  const related = new Map();
  const precedence = { link: 3, tag: 2, semantic: 1 };
  for (const link of allLinks) {
    const source = endpointId(link.source);
    const target = endpointId(link.target);
    if (source !== node.id && target !== node.id) continue;
    const other = nodeById.get(source === node.id ? target : source);
    if (!other) continue;
    const current = related.get(other.id) || { node: other, kinds: new Set(), score: 0, priority: 0 };
    current.kinds.add(link.kind);
    current.score = Math.max(current.score, link.score || 0);
    current.priority = Math.max(current.priority, precedence[link.kind] || 0);
    related.set(other.id, current);
  }
  return [...related.values()]
    .map((item) => ({ ...item, kind: [...item.kinds].sort((left, right) => (precedence[right] || 0) - (precedence[left] || 0)).join(" · ") }))
    .sort((left, right) => (right.priority - left.priority) || (right.score - left.score) || left.node.title.localeCompare(right.node.title));
}

function groupLabel(node) {
  if (node.is_session) return "Sessions";
  if (node.kind === "tag") return "Tags";
  return { pattern: "Patterns", concept: "Concepts", decision: "Decisions", lesson: "Lessons", snippet: "Snippets", source: "Sources", infra: "Infrastructure" }[node.category] || "Related knowledge";
}

function renderRelations(node) {
  const container = document.getElementById("relations");
  const relations = relationNodes(node);
  document.getElementById("relations-heading").textContent = `Linked knowledge · ${relations.length}`;
  container.replaceChildren();
  if (!relations.length) {
    const empty = document.createElement("p");
    empty.className = "relations-empty";
    empty.textContent = "No indexed relationships for this node yet.";
    container.append(empty);
    return;
  }
  const groups = new Map();
  const order = ["Patterns", "Concepts", "Decisions", "Lessons", "Sessions", "Snippets", "Sources", "Infrastructure", "Related knowledge", "Tags"];
  relations.forEach((item) => {
    const key = groupLabel(item.node);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  });
  const sorted = [...groups].sort((left, right) => (order.indexOf(left[0]) < 0 ? 99 : order.indexOf(left[0])) - (order.indexOf(right[0]) < 0 ? 99 : order.indexOf(right[0])));
  for (const [label, items] of sorted) {
    const group = document.createElement("div");
    group.className = "relation-group";
    const heading = document.createElement("h4");
    heading.textContent = `${label} · ${items.length}`;
    group.append(heading);
    for (const item of items.slice(0, 8)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "relation-row";
      button.setAttribute("aria-label", `Focus ${item.node.title}, connected by ${item.kind}`);
      const dot = document.createElement("i");
      dot.className = `relation-dot ${item.node.is_session ? "session" : item.node.category}`;
      const title = document.createElement("span");
      title.textContent = item.node.title;
      const kind = document.createElement("small");
      kind.textContent = item.kind;
      button.append(dot, title, kind);
      button.addEventListener("click", () => {
        if (!visibleIds.has(item.node.id)) setCollection("all", false);
        selectNode(item.node, true);
      });
      group.append(button);
    }
    container.append(group);
  }
}

function selectNode(node, focus) {
  if (selectedNode && selectedNode.id !== node.id) selectionHistory.push(selectedNode.id);
  selectedNode = node;
  hideTooltip();
  nodeSelection.classed("selected", (item) => item.id === node.id);
  applySelectionHighlight();
  document.getElementById("inspector-empty").hidden = true;
  document.getElementById("detail-content").classList.add("is-visible");
  document.getElementById("clear-selection").hidden = false;
  document.getElementById("back-selection").hidden = selectionHistory.length === 0;
  const relationCount = relationNodes(node).length;
  document.getElementById("inspector-subtitle").textContent = `${relationCount} indexed connection${relationCount === 1 ? "" : "s"}`;
  placeLabels();
  document.getElementById("detail-kind").textContent = node.is_session ? "Codex session" : node.category;
  document.getElementById("detail-title").textContent = node.title;
  document.getElementById("detail-description").textContent = node.description || `${node.category} node`;
  document.getElementById("detail-path").textContent = node.path || "";
  const values = [...(node.tags || [])];
  if (node.project) values.unshift(node.project);
  if (node.date) values.unshift(node.date.slice(0, 16).replace("T", " · "));
  document.getElementById("detail-tags").replaceChildren(...values.map((value) => {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = value;
    return badge;
  }));
  const open = document.getElementById("detail-open");
  open.hidden = !node.url;
  if (node.url) open.href = node.url;
  renderRelations(node);
  document.querySelector(".inspector-scroll").scrollTo({ top: 0, behavior: motionReduced.matches ? "auto" : "smooth" });
  if (focus) focusNode(node);
  if (innerWidth <= 820) openPanel("inspector");
}

function clearSelection() {
  selectedNode = null;
  selectionHistory = [];
  nodeSelection.classed("selected", false);
  applySelectionHighlight();
  document.getElementById("inspector-empty").hidden = false;
  document.getElementById("detail-content").classList.remove("is-visible");
  document.getElementById("clear-selection").hidden = true;
  document.getElementById("back-selection").hidden = true;
  document.getElementById("inspector-subtitle").textContent = "Selection and relationships";
}

function goBackSelection() {
  const previousId = selectionHistory.pop();
  const previous = nodeById.get(previousId);
  if (!previous) return;
  const remainingHistory = [...selectionHistory];
  selectedNode = null;
  selectionHistory = remainingHistory;
  selectNode(previous, true);
  selectionHistory = remainingHistory;
  document.getElementById("back-selection").hidden = selectionHistory.length === 0;
}

function dragStart(event, node) {
  hideTooltip();
  d3.select(event.sourceEvent?.currentTarget || null).classed("dragging", true);
  if (!event.active) simulation.alphaTarget(.18).restart();
  node.fx = node.x;
  node.fy = node.y;
}
function dragged(event, node) { node.fx = event.x; node.fy = event.y; }
function dragEnd(event, node) {
  if (!event.active) simulation.alphaTarget(0);
  node.fx = null;
  node.fy = null;
  nodeSelection.classed("dragging", false);
}

function nodeMatches(node, normalized) {
  return `${node.title} ${node.description || ""} ${node.path || ""} ${node.project || ""} ${(node.tags || []).join(" ")}`.toLowerCase().includes(normalized);
}

function closeSearchResults() {
  const input = document.getElementById("search");
  document.getElementById("search-results").hidden = true;
  input.setAttribute("aria-expanded", "false");
  input.removeAttribute("aria-activedescendant");
  activeSearchIndex = -1;
}

function activateSearchResult(index) {
  const results = [...document.querySelectorAll(".search-result")];
  if (!results.length) return;
  activeSearchIndex = Math.max(0, Math.min(results.length - 1, index));
  results.forEach((button, position) => {
    const active = position === activeSearchIndex;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
  const active = results[activeSearchIndex];
  document.getElementById("search").setAttribute("aria-activedescendant", active.id);
  active.scrollIntoView({ block: "nearest" });
}

function chooseSearchResult(node) {
  if (!visibleIds.has(node.id)) setCollection("all", false);
  closeSearchResults();
  selectNode(node, true);
}

function renderSearchResults(normalized, matches) {
  const panel = document.getElementById("search-results");
  const list = document.getElementById("search-result-list");
  const input = document.getElementById("search");
  activeSearchIndex = -1;
  input.removeAttribute("aria-activedescendant");
  list.replaceChildren();
  if (!normalized) {
    closeSearchResults();
    return;
  }
  panel.hidden = false;
  input.setAttribute("aria-expanded", "true");
  document.getElementById("search-summary").textContent = matches.length
    ? `${matches.length} result${matches.length === 1 ? "" : "s"} · Enter to open`
    : "No matches";
  if (!matches.length) {
    const empty = document.createElement("p");
    empty.className = "search-empty";
    empty.textContent = "Try a title, tag, project, or knowledge type.";
    list.append(empty);
    return;
  }
  matches.slice(0, 8).forEach((node, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.id = `search-result-${index}`;
    button.className = "search-result";
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", "false");
    const dot = document.createElement("i");
    dot.className = `category-dot ${node.is_session ? "session" : node.category}`;
    const main = document.createElement("span");
    main.className = "search-result-main";
    const title = document.createElement("strong");
    title.textContent = node.title;
    const context = document.createElement("small");
    context.textContent = node.description || node.path || "No description";
    main.append(title, context);
    const kind = document.createElement("span");
    kind.className = "search-result-kind";
    kind.textContent = node.is_session ? "session" : node.category;
    button.append(dot, main, kind);
    button.addEventListener("pointerenter", () => activateSearchResult(index));
    button.addEventListener("click", () => chooseSearchResult(node));
    list.append(button);
  });
}

function search(query) {
  const normalized = query.trim().toLowerCase();
  const matches = normalized
    ? nodes.filter((node) => nodeMatches(node, normalized)).sort((left, right) => {
      const leftTitle = left.title.toLowerCase();
      const rightTitle = right.title.toLowerCase();
      return Number(rightTitle.startsWith(normalized)) - Number(leftTitle.startsWith(normalized)) || left.title.localeCompare(right.title);
    })
    : [];
  nodeSelection.classed("dimmed", (node) => normalized && !nodeMatches(node, normalized)).classed("match", (node) => normalized && nodeMatches(node, normalized));
  document.querySelectorAll(".session-row").forEach((button) => button.classList.toggle("search-hidden", Boolean(normalized) && !nodeMatches(nodeById.get(button.dataset.nodeId), normalized)));
  document.getElementById("search-clear").hidden = !normalized;
  renderSearchResults(normalized, matches);
}

function openPanel(panel) {
  workspace.classList.remove("library-open", "inspector-open");
  if (panel) workspace.classList.add(`${panel}-open`);
  document.getElementById("details-toggle").setAttribute("aria-expanded", String(panel === "inspector"));
}

document.querySelectorAll('input[id^="layer-"]').forEach((input) => input.addEventListener("change", updateLinks));
document.querySelectorAll("[data-collection]").forEach((button) => button.addEventListener("click", () => setCollection(button.dataset.collection)));
document.querySelectorAll("[data-category]").forEach((button) => button.addEventListener("click", () => setCategory(button.dataset.category)));
document.querySelectorAll("[data-node-id]").forEach((button) => button.addEventListener("click", () => {
  setCollection("all", false);
  const node = nodeById.get(button.dataset.nodeId);
  if (node) selectNode(node, true);
}));
document.getElementById("fit").addEventListener("click", fit);
document.getElementById("zoom-in").addEventListener("click", () => zoomBy(1.28));
document.getElementById("zoom-out").addEventListener("click", () => zoomBy(.78));
document.getElementById("clear-selection").addEventListener("click", () => {
  clearSelection();
  if (innerWidth <= 820) openPanel(null);
});
document.getElementById("back-selection").addEventListener("click", goBackSelection);
document.getElementById("library-toggle").addEventListener("click", () => {
  if (innerWidth <= 820) {
    openPanel(workspace.classList.contains("library-open") ? null : "library");
    return;
  }
  workspace.classList.toggle("library-collapsed");
  document.getElementById("library-toggle").setAttribute("aria-expanded", String(!workspace.classList.contains("library-collapsed")));
});
document.getElementById("details-toggle").addEventListener("click", () => openPanel(workspace.classList.contains("inspector-open") ? null : "inspector"));
document.getElementById("sidebar-scrim").addEventListener("click", () => openPanel(null));
document.getElementById("search").addEventListener("input", (event) => search(event.target.value));
document.getElementById("search").addEventListener("focus", (event) => {
  if (event.target.value.trim()) search(event.target.value);
});
document.getElementById("search").addEventListener("keydown", (event) => {
  const results = [...document.querySelectorAll(".search-result")];
  if (event.key === "ArrowDown" && results.length) {
    event.preventDefault();
    activateSearchResult(activeSearchIndex + 1);
  } else if (event.key === "ArrowUp" && results.length) {
    event.preventDefault();
    activateSearchResult(activeSearchIndex <= 0 ? results.length - 1 : activeSearchIndex - 1);
  } else if (event.key === "Enter" && activeSearchIndex >= 0) {
    event.preventDefault();
    results[activeSearchIndex].click();
  } else if (event.key === "Escape") {
    event.stopPropagation();
    closeSearchResults();
  }
});
document.getElementById("search-clear").addEventListener("click", () => {
  const input = document.getElementById("search");
  input.value = "";
  search("");
  input.focus();
});
document.addEventListener("pointerdown", (event) => {
  document.querySelectorAll("details.menu[open]").forEach((menu) => {
    if (!menu.contains(event.target)) menu.open = false;
  });
  const searchWrap = document.querySelector(".search-wrap");
  if (!searchWrap.contains(event.target)) closeSearchResults();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    const openMenu = document.querySelector("details.menu[open]");
    if (openMenu) {
      openMenu.open = false;
      return;
    }
    if (workspace.classList.contains("library-open") || workspace.classList.contains("inspector-open")) {
      openPanel(null);
      return;
    }
    if (selectedNode) clearSelection();
  }
});

document.getElementById("scope-label").textContent = `${graph.meta.scope} · ${(graph.meta.collections || []).join(", ")}`;
if (graph.meta.generatedAt) document.getElementById("counts").title = `Indexed ${new Date(graph.meta.generatedAt).toLocaleString()}`;
if (graph.meta.liveReload) {
  const initialVersion = graph.meta.liveReload.version;
  const pollForChanges = async () => {
    try {
      const response = await fetch(graph.meta.liveReload.url, { cache: "no-store" });
      const state = await response.json();
      if (state.version !== initialVersion) {
        location.reload();
        return;
      }
    } catch (_) {
      // The local server may be restarting; retry without disrupting the UI.
    }
    setTimeout(pollForChanges, 750);
  };
  setTimeout(pollForChanges, 750);
}
new ResizeObserver(() => {
  cancelAnimationFrame(resizeFrame);
  resizeFrame = requestAnimationFrame(() => {
    size();
    simulation.alpha(.16).restart();
  });
}).observe(wrap);
size();
applyView(false);
setTimeout(fit, 850);
