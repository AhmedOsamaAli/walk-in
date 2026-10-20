/* Blank Space front end: a plain ES module, no build step. Leaflet is loaded globally first. */

const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const ENTITIES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ENTITIES[ch]);
const list = (value) =>
  (Array.isArray(value) ? value : value ? [value] : [])
    .filter((item) => item !== null && item !== undefined && String(item).trim() !== "")
    .map(String);
const price = (level) => "$".repeat(Math.max(1, Math.min(4, Number(level) || 2)));
const letter = (i) => String.fromCharCode(65 + i);
const fmtLat = (lat) => `${lat >= 0 ? "N" : "S"} ${Math.abs(lat).toFixed(4)}`;
const fmtLon = (lon) => `${lon >= 0 ? "E" : "W"} ${Math.abs(lon).toFixed(4)}`;
const coords = (lat, lon) => `${fmtLat(lat)} · ${fmtLon(lon)}`;
const safeUrl = (url) =>
  typeof url === "string" && (/^https:\/\//i.test(url) || /^data:image\/(png|jpeg|webp);base64,/i.test(url)) ? url : null;

const FOCUS_LABELS = { any: "Any business", food_drink: "Food & drink", retail: "Retail", leisure: "Leisure" };
const AGE_LABELS = {
  "24_and_younger": "Under 25", "25_to_29": "25–29", "30_to_34": "30–34",
  "35_to_44": "35–44", "45_to_54": "45–54", "55_and_older": "55+",
};
const WALK_M = 800;
const STEP_TOTAL = 6;

const state = {
  site: null,
  running: false,
  controller: null,
  runId: null,
  startedAt: 0,
  steps: new Map(),
  doneSteps: 0,
  demand: null,
  gaps: [],
  concepts: [],
  openGap: null,
  designs: new Map(),
  grids: new Map(),
};

const sectionObserver = new IntersectionObserver(
  (entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      $$(".bar-nav a").forEach((link) => link.classList.toggle("current", link.dataset.nav === entry.target.id));
    }
  },
  { rootMargin: "-45% 0px -50% 0px" },
);

/* ---------- Map ---------- */

const map = L.map("map", { zoomControl: false, worldCopyJump: true }).setView([40.735, -73.975], 12);
L.control.zoom({ position: "topright" }).addTo(map);
L.control.scale({ position: "bottomright", imperial: false, maxWidth: 120 }).addTo(map);
for (const [name, zIndex] of [["grid", 350], ["labels", 360], ["radar", 380]]) {
  const pane = map.createPane(name);
  pane.style.zIndex = String(zIndex);
  pane.style.pointerEvents = "none";
}
map.getPane("grid").classList.add("grid-pane");

const ATTRIBUTION =
  'Tiles &copy; <a href="https://www.esri.com">Esri</a> &mdash; Esri, HERE, Garmin, &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas";
L.tileLayer(`${ESRI}/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}`, {
  maxNativeZoom: 16, maxZoom: 19, attribution: ATTRIBUTION,
}).addTo(map);
L.tileLayer(`${ESRI}/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}`, {
  maxNativeZoom: 16, maxZoom: 19, pane: "labels",
}).addTo(map);

const gridRenderer = L.canvas({ padding: 0.5, pane: "grid" });
const layers = {
  grid: L.layerGroup().addTo(map),
  ring: L.layerGroup().addTo(map),
  block: L.layerGroup().addTo(map),
  gap: L.layerGroup().addTo(map),
  site: L.layerGroup().addTo(map),
};
const TIP = { className: "tip", direction: "top", offset: [0, -6], opacity: 1 };
let radar = null;
let moveToken = 0;

const readout = $("#readout");
let pointerOnMap = false;
const showCenter = () => {
  if (!pointerOnMap) {
    const center = map.getCenter();
    readout.textContent = coords(center.lat, center.lng);
  }
};
map.on("mouseover", () => {
  pointerOnMap = true;
});
map.on("mouseout", () => {
  pointerOnMap = false;
  showCenter();
});
map.on("move", showCenter);
map.on("mousemove", (event) => {
  readout.textContent = coords(event.latlng.lat, event.latlng.lng);
});
map.on("click", (event) => {
  if (state.running || $("#s-brief").hidden) return;
  const { lat, lng } = event.latlng.wrap();
  selectSite({ lat, lon: lng, label: "Dropped pin" }, { zoom: Math.max(map.getZoom(), 15) });
});

function selectSite(site, { zoom = 15, reveal = false } = {}) {
  state.site = { id: site.id || null, label: site.label || "Dropped pin", lat: Number(site.lat), lon: Number(site.lon) };
  $("#chosen").hidden = false;
  $("#chosen-label").textContent = state.site.label;
  $("#chosen-coords").textContent = coords(state.site.lat, state.site.lon);
  $("#go").disabled = false;
  $("#map-hint").hidden = true;
  $$(".site-btn").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.id === state.site.id)));
  clearMapRun();
  drawSite();
  map.flyTo([state.site.lat, state.site.lon], zoom, { duration: reduced ? 0 : 1.4 });
  if (reveal) $("#go").scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
}

function drawSite() {
  layers.site.clearLayers();
  layers.ring.clearLayers();
  const { lat, lon } = state.site;
  const icon = L.divIcon({
    className: "site-icon",
    iconSize: [0, 0],
    html: '<div class="site-pin"><span class="sq"></span><span class="tagl">Site</span></div>',
  });
  L.marker([lat, lon], { icon, interactive: false, keyboard: false }).addTo(layers.site);
  const ring = L.circle([lat, lon], {
    radius: 1, color: "#0000ff", weight: 1.25, dashArray: "3 6",
    fillColor: "#0000ff", fillOpacity: 0.035, interactive: false,
  }).addTo(layers.ring);
  growCircle(ring, WALK_M, reduced ? 0 : 1200);
}

function growCircle(circle, radius, ms) {
  if (!ms) {
    circle.setRadius(radius);
    return;
  }
  const start = performance.now();
  const frame = (now) => {
    const t = Math.min(1, (now - start) / ms);
    circle.setRadius(Math.max(1, radius * (1 - Math.pow(1 - t, 4))));
    if (t < 1) requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

function radarIcon() {
  const center = L.latLng(state.site.lat, state.site.lon);
  const a = map.latLngToLayerPoint(center);
  const b = map.latLngToLayerPoint(L.latLng(center.lat + WALK_M / 111320, center.lng));
  const r = Math.max(12, Math.round(Math.abs(a.y - b.y)));
  return L.divIcon({ className: "radar-icon", iconSize: [r * 2, r * 2], iconAnchor: [r, r], html: '<div class="radar"></div>' });
}

function startRadar() {
  stopRadar();
  if (!state.site || reduced) return;
  radar = L.marker([state.site.lat, state.site.lon], {
    icon: radarIcon(), pane: "radar", interactive: false, keyboard: false,
  }).addTo(map);
  map.on("zoomend", resizeRadar);
}

function resizeRadar() {
  if (radar) radar.setIcon(radarIcon());
}

function stopRadar() {
  if (radar) {
    radar.remove();
    radar = null;
  }
  map.off("zoomend", resizeRadar);
}

function clearMapRun() {
  layers.block.clearLayers();
  layers.gap.clearLayers();
  layers.grid.clearLayers();
  map.getPane("grid").classList.remove("in");
  stopRadar();
  state.openGap = null;
}

function afterMove(fn) {
  const token = ++moveToken;
  let ran = false;
  const run = () => {
    if (ran || token !== moveToken) return;
    ran = true;
    fn();
  };
  map.once("moveend", run);
  setTimeout(run, reduced ? 50 : 1500);
}

/* ---------- API ---------- */

async function api(path, options = {}) {
  const headers = { Accept: "application/json" };
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) throw new Error(await errorText(response));
  return response.json();
}

async function errorText(response) {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    /* not JSON */
  }
  return response.status === 429 ? "Too many requests. Try again in a while." : `Request failed (${response.status}).`;
}

/* ---------- Presets and search ---------- */

async function loadPresets() {
  try {
    const presets = await api("/api/presets");
    $("#presets").innerHTML = presets
      .map(
        (preset, i) => `
        <li><button class="site-btn" type="button" data-id="${esc(preset.id)}" aria-pressed="false">
          <span class="letter">${letter(i)}</span>
          <span><span class="name">${esc(preset.label)}</span><span class="blurb">${esc(preset.blurb)}</span></span>
          <span class="coords mono">${esc(fmtLat(preset.lat))}<br>${esc(fmtLon(preset.lon))}</span>
          <span class="arrow" aria-hidden="true">→</span>
        </button></li>`,
      )
      .join("");
    $$(".site-btn").forEach((button, i) => button.addEventListener("click", () => selectSite(presets[i], { reveal: true })));
  } catch (error) {
    $("#presets").innerHTML = `<li class="muted">${esc(error.message)}</li>`;
  }
}

const searchInput = $("#search");
const resultsBox = $("#search-results");
let searchTimer = 0;
let searchSeq = 0;
let searchQuery = "";
let searchResults = [];
let activeResult = -1;

searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const query = searchInput.value.trim();
  if (query.length < 3) {
    hideResults();
    return;
  }
  searchTimer = setTimeout(() => runSearch(query), 450);
});

searchInput.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    hideResults();
    return;
  }
  if (resultsBox.hidden || !searchResults.length) return;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const step = event.key === "ArrowDown" ? 1 : -1;
    activeResult = (activeResult + step + searchResults.length) % searchResults.length;
    $$("button", resultsBox).forEach((button, i) => button.setAttribute("aria-selected", String(i === activeResult)));
  }
});

$("#search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = searchInput.value.trim();
  if (query.length < 3) return;
  clearTimeout(searchTimer);
  if (activeResult >= 0 && searchQuery === query) {
    pickResult(activeResult);
    return;
  }
  if (searchQuery !== query) await runSearch(query);
  if (searchResults.length) pickResult(0);
});

document.addEventListener("click", (event) => {
  if (!event.target.closest("#search-form")) hideResults();
});

async function runSearch(query) {
  const seq = ++searchSeq;
  try {
    const items = await api(`/api/geocode?q=${encodeURIComponent(query)}`);
    if (seq !== searchSeq) return;
    searchQuery = query;
    searchResults = items;
    activeResult = -1;
    resultsBox.innerHTML = items.length
      ? items
          .map((item, i) => `<li><button type="button" role="option" aria-selected="false" data-i="${i}">${esc(item.label)}</button></li>`)
          .join("")
      : '<li class="empty">No matches. Try a street or neighborhood name.</li>';
    $$("button", resultsBox).forEach((button) => button.addEventListener("click", () => pickResult(Number(button.dataset.i))));
    resultsBox.hidden = false;
  } catch (error) {
    if (seq !== searchSeq) return;
    searchQuery = "";
    searchResults = [];
    resultsBox.innerHTML = `<li class="empty">${esc(error.message)}</li>`;
    resultsBox.hidden = false;
  }
}

function pickResult(index) {
  const result = searchResults[index];
  if (!result) return;
  const label = shortLabel(result.label);
  hideResults();
  searchInput.value = label;
  selectSite({ lat: result.lat, lon: result.lon, label }, { zoom: 16, reveal: true });
}

function shortLabel(label) {
  return String(label || "").split(",").map((part) => part.trim()).filter(Boolean).slice(0, 2).join(", ") || "Selected site";
}

function hideResults() {
  resultsBox.hidden = true;
  activeResult = -1;
}

/* ---------- Survey run ---------- */

$("#go").addEventListener("click", startSurvey);
$("#new-survey").addEventListener("click", resetToBrief);

async function startSurvey() {
  if (!state.site || state.running) return;
  const focus = $('input[name="focus"]:checked')?.value || "any";
  const notes = $("#notes").value.trim();
  const site = state.site;
  resetResults();
  swapView(() => {
    $("#s-brief").hidden = true;
    $("#site-title").textContent = site.label;
    $("#site-coords").textContent = [coords(site.lat, site.lon), FOCUS_LABELS[focus], notes ? "Owner constraints set" : ""]
      .filter(Boolean)
      .join(" · ");
    $("#s-site").hidden = false;
    show("#s-log");
  });
  window.scrollTo({ top: 0, behavior: reduced ? "auto" : "smooth" });
  state.running = true;
  state.startedAt = performance.now();
  setProgress(0.06);
  $("#legend").hidden = false;
  map.flyTo([site.lat, site.lon], 15, { duration: reduced ? 0 : 1.2 });
  startRadar();

  const params = new URLSearchParams({ lat: site.lat.toFixed(6), lon: site.lon.toFixed(6), label: site.label, focus, notes });
  const controller = new AbortController();
  state.controller = controller;
  try {
    const response = await fetch(`/api/run?${params}`, {
      signal: controller.signal,
      headers: { Accept: "text/event-stream" },
    });
    if (!response.ok) throw new Error(await errorText(response));
    for await (const { event, data } of readEvents(response.body)) handle(event, data);
  } catch (error) {
    if (error.name !== "AbortError") logLine(error.message, "err");
  } finally {
    if (state.controller === controller) {
      state.running = false;
      state.controller = null;
      stopRadar();
    }
  }
}

function resetResults() {
  state.steps.clear();
  state.doneSteps = 0;
  state.runId = null;
  state.demand = null;
  state.gaps = [];
  state.concepts = [];
  state.designs.clear();
  $("#log").innerHTML = "";
  $("#log-meta").textContent = "";
  for (const id of ["s-log", "s-block", "s-gaps", "s-concepts", "s-taste"]) $(`#${id}`).hidden = true;
  $("#without").hidden = true;
  $("#without").innerHTML = "";
  $$(".bar-nav a").forEach((link) => link.classList.remove("ready", "current"));
  clearMapRun();
  if (state.site) drawSite();
}

function resetToBrief() {
  state.controller?.abort();
  state.controller = null;
  state.running = false;
  swapView(() => {
    resetResults();
    $("#s-site").hidden = true;
    $("#s-brief").hidden = false;
  });
  $("#legend").hidden = true;
  setProgress(0.42);
  window.scrollTo({ top: 0, behavior: reduced ? "auto" : "smooth" });
}

function swapView(update) {
  if (reduced || !document.startViewTransition) {
    update();
    return;
  }
  const transition = document.startViewTransition(update);
  // A skipped or timed-out transition still applies the update; don't surface it as an error.
  for (const promise of [transition.ready, transition.finished, transition.updateCallbackDone]) promise.catch(() => {});
}

function show(selector) {
  const section = $(selector);
  if (section.hidden) {
    section.hidden = false;
    if (!reduced) {
      section.classList.remove("reveal");
      void section.offsetWidth;
      section.classList.add("reveal");
    }
    $(`.bar-nav a[data-nav="${section.id}"]`)?.classList.add("ready");
    sectionObserver.observe(section);
  }
  return section;
}

async function* readEvents(stream) {
  const reader = stream.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      buffer += value.replace(/\r\n/g, "\n");
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const parsed = parseEvent(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        if (parsed) yield parsed;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function parseEvent(chunk) {
  let event = "message";
  const data = [];
  for (const line of chunk.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (!data.length) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) };
  } catch {
    return null;
  }
}

function handle(event, data) {
  switch (event) {
    case "run":
      state.runId = data.run_id;
      logLine(`Survey ${data.run_id} started · ${data.llm ? "LLM agent with Qloo tools" : "evidence rules (no LLM key set)"}`);
      break;
    case "status":
      onStatus(data);
      break;
    case "agent":
      logLine(agentText(data), "agent");
      break;
    case "block":
      renderBlock(data);
      break;
    case "demand":
      state.demand = data;
      break;
    case "gaps":
      renderGaps(data.rows || []);
      break;
    case "taste":
      renderTaste(data);
      break;
    case "concepts":
      renderConcepts(data);
      break;
    case "baseline":
      renderBaseline(data.concepts || []);
      break;
    case "notice":
      logLine(data.message, "warn");
      break;
    case "error":
      logLine(data.message, "err");
      break;
    case "done":
      onDone(data);
      break;
    default:
      break;
  }
}

/* ---------- 01 Log ---------- */

function elapsed() {
  return `${((performance.now() - state.startedAt) / 1000).toFixed(1)}s`;
}

function logLine(text, kind = "", status = "") {
  const item = document.createElement("li");
  if (kind) item.className = kind;
  item.innerHTML = `<span class="t">${elapsed()}</span><span class="msg">${esc(text)}</span><span class="state">${esc(status)}</span>`;
  $("#log").append(item);
  return item;
}

function onStatus({ step, state: phase, label }) {
  let item = state.steps.get(step);
  if (!item) {
    item = logLine(label, "running", "Run");
    state.steps.set(step, item);
  }
  if (phase === "done" && !item.classList.contains("done")) {
    item.classList.remove("running");
    item.classList.add("done");
    item.querySelector(".state").textContent = `✓ ${elapsed()}`;
    state.doneSteps += 1;
    setProgress(state.doneSteps / STEP_TOTAL);
  }
}

function agentText({ tool, args }) {
  if (tool === "inspect_gap") return `Agent inspects the ${args?.genre || "unknown"} gap: competitors, favorites, design DNA`;
  if (tool === "local_taste") return "Agent reads local brands, artists and the crowd";
  return `Agent calls ${tool}`;
}

function onDone(data) {
  setProgress(1);
  logLine("Survey complete", "done", "✓");
  $("#log-meta").textContent = `${data.seconds}s · ${data.qloo_calls} Qloo calls · ${data.cache_hits} served from cache`;
}

function setProgress(fraction) {
  $("#mark-fill").style.setProperty("--p", String(Math.max(0.04, Math.min(1, fraction))));
}

/* ---------- 02 Block ---------- */

function renderBlock({ summary = {}, places = [] }) {
  show("#s-block");
  const prices = Object.entries(summary.price_levels || {}).sort((a, b) => b[1] - a[1]);
  const typical = prices.length ? Number(prices[0][0]) : null;
  $("#block-stats").innerHTML = [
    numberStat(summary.place_count ?? places.length, "Places within 800 m"),
    summary.avg_rating ? numberStat(summary.avg_rating, "Average rating", 2) : textStat("—", "Average rating"),
    textStat(typical ? price(typical) : "—", "Most common price"),
    numberStat((summary.rising || []).length, "Places rising"),
  ].join("");
  $$("[data-count]", $("#block-stats")).forEach(countUp);
  $("#block-genres").innerHTML =
    (summary.top_genres || []).map(([name, count]) => `<span class="tag">${esc(name)} <small>${esc(count)}</small></span>`).join("") ||
    '<span class="muted">No genre data.</span>';
  $("#praise").innerHTML = keyRows(summary.praise, 7) || '<li class="muted">No review keywords nearby.</li>';
  $("#complaints").innerHTML = keyRows(summary.complaints, 7) || '<li class="muted">No recurring complaints.</li>';
  $("#momentum").innerHTML =
    momentumList("Rising", summary.rising, "up", "▲") + momentumList("Fading", summary.fading, "down", "▼");
  plotBlock(places);
}

function numberStat(value, label, decimals = 0) {
  return `<div class="stat"><b data-count="${Number(value) || 0}" data-dec="${decimals}">0</b><span class="mono">${esc(label)}</span></div>`;
}

function textStat(text, label) {
  return `<div class="stat"><b>${esc(text)}</b><span class="mono">${esc(label)}</span></div>`;
}

function keyRows(rows, limit) {
  return (rows || [])
    .slice(0, limit)
    .map(([key, count]) => `<li><span>${esc(key)}</span><small>${esc(count)}</small></li>`)
    .join("");
}

function momentumList(title, rows, cls, arrow) {
  const items = (rows || [])
    .slice(0, 5)
    .map(([name, value]) => `<li><span>${esc(name)}</span><span class="${cls} mono">${arrow} ${Math.abs(Number(value) || 0).toFixed(2)}</span></li>`)
    .join("");
  return `<div><h3 class="label mono">${title}</h3><ul class="mo">${items || '<li class="muted">None detected.</li>'}</ul></div>`;
}

function countUp(el) {
  const target = Number(el.dataset.count) || 0;
  const decimals = Number(el.dataset.dec) || 0;
  if (reduced) {
    el.textContent = target.toFixed(decimals);
    return;
  }
  const start = performance.now();
  const frame = (now) => {
    const t = Math.min(1, (now - start) / 1100);
    el.textContent = (target * (1 - Math.pow(1 - t, 3))).toFixed(decimals);
    if (t < 1) requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

function plotBlock(places) {
  layers.block.clearLayers();
  for (const place of places) {
    if (place.lat == null || place.lon == null) continue;
    const dot = L.circleMarker([place.lat, place.lon], {
      radius: 3.4, stroke: false, fillColor: "#000", fillOpacity: 0.85, className: "pdot",
    })
      .bindTooltip(tipHtml(place), TIP)
      .addTo(layers.block);
    const el = dot.getElement();
    if (el) el.style.animationDelay = reduced ? "0ms" : `${Math.round(((place.distance_m ?? 400) / WALK_M) * 1100)}ms`;
  }
}

function tipHtml(place) {
  const meta = [
    place.genres?.[0],
    place.rating ? `★ ${Number(place.rating).toFixed(1)}` : "",
    place.price_level ? price(place.price_level) : "",
    place.distance_m != null ? `${place.distance_m} m` : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const said = place.complaints?.length
    ? `<span class="bad">${esc(place.complaints[0])}</span>`
    : esc((place.praise || []).slice(0, 2).join(", "));
  return `<b>${esc(place.name)}</b>${meta ? `<span class="m">${esc(meta)}</span>` : ""}${said ? `<span class="s">${said}</span>` : ""}`;
}

/* ---------- 03 Gaps ---------- */

function renderGaps(rows) {
  state.gaps = rows;
  show("#s-gaps");
  const box = $("#gaps");
  if (!rows.length) {
    box.innerHTML = '<li class="gap-empty serif">Not enough Qloo data around this site to rank what is missing. Try a busier block.</li>';
    return;
  }
  box.innerHTML = rows.map(gapHtml).join("");
  $$(".gap-row", box).forEach((button) => button.addEventListener("click", () => toggleGap(Number(button.dataset.i))));
  $$("[data-count]", box).forEach(countUp);
  toggleGap(0);
}

function gapHtml(gap, i) {
  const supply = Math.min(gap.nearby_count, 24);
  const pips = "<i></i>".repeat(supply) + (gap.nearby_count > 24 || gap.nearby_capped ? '<i class="more">+</i>' : "");
  const dots = Array.from({ length: gap.favorites_total || 0 }, (_, k) => `<i class="${k < gap.favorites_far ? "on" : ""}"></i>`).join("");
  const competitors =
    (gap.competitors || []).slice(0, 6).map(competitorHtml).join("") ||
    '<li class="muted">No direct competitor within walking distance.</li>';
  const favorites = (gap.favorites || []).slice(0, 6).map(favoriteHtml).join("") || '<li class="muted">No favorites found.</li>';
  const median = gap.median_favorite_km != null ? ` · median ${gap.median_favorite_km} km` : "";
  return `
    <li class="gap${i === 0 ? " first" : ""}" style="--i:${i}">
      <button class="gap-row" type="button" data-i="${i}" aria-expanded="false">
        <span class="gap-score" data-count="${Number(gap.gap_score) || 0}">0</span>
        <span>
          <span class="gap-name">${esc(gap.genre)}<small class="mono muted">locals' #${esc(gap.demand_rank)}</small></span>
          <span class="gap-bars">
            <span class="meter"><span class="mono">Within walk · ${esc(gap.nearby_count)}${gap.nearby_capped ? "+" : ""}</span><span class="pips">${pips || '<span class="mono muted">none</span>'}</span></span>
            <span class="meter"><span class="mono">Favorites beyond · ${esc(gap.favorites_far)}/${esc(gap.favorites_total)}</span><span class="dots">${dots}</span></span>
          </span>
        </span>
        <span class="gap-toggle" aria-hidden="true">+</span>
      </button>
      <div class="gap-detail-wrap"><div class="gap-detail"><div class="gap-detail-inner">
        <div><h4 class="label mono">Competitors within walk</h4><ul class="mini">${competitors}</ul></div>
        <div><h4 class="label mono">Where locals go instead${median}</h4><ul class="mini">${favorites}</ul></div>
      </div></div></div>
    </li>`;
}

function competitorHtml(place) {
  const said = place.complaints?.length
    ? `<span class="bad">${esc(place.complaints.join(", "))}</span>`
    : esc((place.praise || []).slice(0, 2).join(", "));
  const details = [place.rating ? `★ ${Number(place.rating).toFixed(1)}` : "", said].filter(Boolean).join(" · ");
  return `<li><span class="n">${esc(place.name)}</span>${details ? `<span class="s">${details}</span>` : ""}</li>`;
}

function favoriteHtml(place) {
  const km = place.distance_m != null ? `${(place.distance_m / 1000).toFixed(1)} km away` : "";
  return `<li><span class="n">${esc(place.name)}</span><span class="km">${km}</span></li>`;
}

function toggleGap(index) {
  const opening = state.openGap !== index;
  state.openGap = opening ? index : null;
  $$("#gaps .gap").forEach((item, k) => {
    const open = opening && k === index;
    item.classList.toggle("open", open);
    item.querySelector(".gap-row").setAttribute("aria-expanded", String(open));
  });
  if (opening) drawGap(state.gaps[index]);
  else clearGap();
}

function clearGap() {
  moveToken += 1;
  layers.gap.clearLayers();
  layers.grid.clearLayers();
  map.getPane("grid").classList.remove("in");
  $("#legend-grid").textContent = "Taste grid";
}

function drawGap(gap) {
  clearGap();
  if (!gap || !state.site) return;
  const site = L.latLng(state.site.lat, state.site.lon);
  const points = [site];
  for (const place of gap.competitors || []) {
    if (place.lat == null) continue;
    L.circleMarker([place.lat, place.lon], {
      radius: 5, color: "#000", weight: 1.5, fillColor: "#fff", fillOpacity: 1, className: "pdot",
    })
      .bindTooltip(tipHtml(place), TIP)
      .addTo(layers.gap);
  }
  const favorites = (gap.favorites || []).filter((place) => place.lat != null && place.lon != null);
  for (const place of favorites) {
    points.push(L.latLng(place.lat, place.lon));
    L.circleMarker([place.lat, place.lon], {
      radius: 5.5, color: "#fff", weight: 1.5, fillColor: "#0000ff", fillOpacity: 1, className: "pdot",
    })
      .bindTooltip(tipHtml(place), TIP)
      .addTo(layers.gap);
  }
  $("#legend-grid").textContent = `Taste grid · ${gap.genre}`;
  if (points.length > 1) {
    afterMove(() =>
      favorites.forEach((place, k) => {
        const line = L.polyline(arc(site, L.latLng(place.lat, place.lon)), {
          color: "#0000ff", weight: 1.3, opacity: 0.8, interactive: false, className: "leak",
        }).addTo(layers.gap);
        drawLine(line, k * 80);
      }),
    );
    map.flyToBounds(L.latLngBounds(points), { padding: [80, 80], maxZoom: 15, duration: reduced ? 0 : 1.2 });
  }
  drawGrid(gap);
}

function arc(from, to) {
  const points = [];
  const dx = to.lng - from.lng;
  const dy = to.lat - from.lat;
  const cx = (from.lng + to.lng) / 2 - dy * 0.2;
  const cy = (from.lat + to.lat) / 2 + dx * 0.2;
  for (let i = 0; i <= 40; i++) {
    const t = i / 40;
    const u = 1 - t;
    points.push([u * u * from.lat + 2 * u * t * cy + t * t * to.lat, u * u * from.lng + 2 * u * t * cx + t * t * to.lng]);
  }
  return points;
}

function drawLine(line, delay) {
  const el = line.getElement();
  if (!el || reduced) return;
  const length = el.getTotalLength();
  el.style.transition = "none";
  el.style.strokeDasharray = `${length}`;
  el.style.strokeDashoffset = `${length}`;
  el.getBoundingClientRect();
  el.style.transition = "";
  el.addEventListener(
    "transitionend",
    () => {
      el.style.strokeDasharray = "";
      el.style.strokeDashoffset = "";
    },
    { once: true },
  );
  setTimeout(() => {
    el.style.strokeDashoffset = "0";
  }, 40 + delay);
}

async function drawGrid(gap) {
  const site = state.site;
  const key = `${site.lat.toFixed(5)},${site.lon.toFixed(5)}|${gap.genre_id}`;
  let cells = state.grids.get(key);
  if (!cells) {
    try {
      const data = await api(`/api/heatmap?lat=${site.lat}&lon=${site.lon}&tag=${encodeURIComponent(gap.genre_id)}`);
      cells = data.cells || [];
      state.grids.set(key, cells);
    } catch {
      cells = [];
    }
  }
  if (state.gaps[state.openGap] !== gap) return;
  layers.grid.clearLayers();
  for (const cell of cells) {
    if (cell.affinity < 0.45) continue;
    const [dLat, dLon] = cellSpan(cell.geohash);
    const strength = (cell.affinity - 0.45) / 0.55;
    L.rectangle(
      [[cell.lat - dLat / 2, cell.lon - dLon / 2], [cell.lat + dLat / 2, cell.lon + dLon / 2]],
      { renderer: gridRenderer, stroke: false, fillColor: "#0000ff", fillOpacity: 0.04 + 0.32 * strength ** 1.8, interactive: false },
    ).addTo(layers.grid);
  }
  const pane = map.getPane("grid");
  pane.classList.remove("in");
  requestAnimationFrame(() => requestAnimationFrame(() => pane.classList.add("in")));
}

function cellSpan(geohash) {
  const bits = 5 * ((geohash || "").length || 7);
  return [180 / 2 ** Math.floor(bits / 2), 360 / 2 ** Math.ceil(bits / 2)];
}

/* ---------- 04 Concepts ---------- */

function renderConcepts({ concepts = [], mode, note }) {
  state.concepts = concepts;
  show("#s-concepts");
  $("#concepts-note").textContent =
    mode === "agent"
      ? "Designed by the agent from the gaps above. Every claim traces back to Qloo evidence."
      : mode === "rules"
        ? "Built from the evidence by deterministic rules. Add an LLM key for agent-written concepts and interiors."
        : note || "";
  const box = $("#posters");
  if (!concepts.length) {
    box.innerHTML = `<p class="serif">${esc(note || "No concepts for this site.")}</p>`;
    return;
  }
  box.innerHTML = concepts.map(posterHtml).join("");
  $$(".poster", box).forEach((card) => card.addEventListener("click", () => openDesign(Number(card.dataset.i))));
  $$("[data-count]", box).forEach(countUp);
}

function posterHtml(concept, i) {
  const why = list(concept.why_here).slice(0, 3).map((line) => `<li>${esc(line)}</li>`).join("");
  const signature = list(concept.signature).slice(0, 4).map((item) => `<span>${esc(item)}</span>`).join("");
  const inspired = list(concept.inspired_by).slice(0, 3).join(" · ");
  return `
    <article class="poster p${i}" data-i="${i}" style="--i:${i}">
      <div class="poster-top mono"><span>Concept ${letter(i)} · ${esc(concept.genre)}</span><span>${price(concept.price_level)}</span></div>
      <div class="poster-score"><span data-count="${Number(concept.gap_score) || 0}">0</span><small>gap</small></div>
      <h3 class="poster-name">${esc(concept.name)}</h3>
      <p class="poster-line">${esc(concept.one_liner)}</p>
      ${why ? `<ol class="poster-why">${why}</ol>` : ""}
      ${signature ? `<div class="poster-sig">${signature}</div>` : ""}
      ${inspired ? `<p class="poster-insp mono">Inspired by ${esc(inspired)}</p>` : ""}
      <button class="poster-open mono" type="button"><span>Open design sheet</span><span aria-hidden="true">→</span></button>
    </article>`;
}

function renderBaseline(items) {
  if (!items.length) return;
  const box = $("#without");
  const rows = items
    .map((item) => `<li><s>${esc(item.name || item.genre)}</s>${item.genre ? `<span class="mono">${esc(item.genre)}</span>` : ""}</li>`)
    .join("");
  box.innerHTML = `
    <h3 class="label mono">A language model with no data suggested</h3>
    <ul>${rows}</ul>
    <p>Plausible, and it would say much the same for almost any block. It has no evidence about who lives within a ten-minute walk.</p>`;
  box.hidden = false;
}

/* ---------- 05 Taste ---------- */

function renderTaste(taste) {
  show("#s-taste");
  const brands = taste.distinctive_brands?.length ? taste.distinctive_brands : taste.brands || [];
  const artists = taste.distinctive_artists?.length ? taste.distinctive_artists : taste.artists || [];
  let words = [...brands.slice(0, 6), ...artists.slice(0, 6)].map((entity) => entity.name).filter(Boolean);
  const track = $("#marquee");
  if (words.length) {
    while (words.length < 10) words = words.concat(words);
    const run = words.map((word) => `<span>${esc(word)}</span><i></i>`).join("");
    track.innerHTML = run + run;
    track.parentElement.hidden = false;
  } else {
    track.parentElement.hidden = true;
  }
  $("#brands").innerHTML = brands.slice(0, 8).map(nameHtml).join("") || '<li class="muted">No brand data.</li>';
  $("#artists").innerHTML = artists.slice(0, 8).map(nameHtml).join("") || '<li class="muted">No artist data.</li>';
  $$("#brands img, #artists img").forEach((img) =>
    img.addEventListener("error", () => img.replaceWith(Object.assign(document.createElement("span"), { className: "ph" })), { once: true }),
  );
  renderCrowd(taste.demographics, taste.crowd);
  $("#cues").innerHTML =
    (state.demand?.cues || []).map((cue) => `<span class="tag blue">${esc(cue)}</span>`).join("") ||
    '<span class="muted">None detected.</span>';
}

function nameHtml(entity) {
  const image = safeUrl(entity.image);
  const media = image
    ? `<img src="${esc(image)}" alt="" loading="lazy" referrerpolicy="no-referrer" />`
    : '<span class="ph"></span>';
  return `<li>${media}<span class="nm">${esc(entity.name)}</span></li>`;
}

function renderCrowd(demographics, text) {
  $("#crowd-note").textContent = text ? `· ${text}` : "";
  const box = $("#crowd");
  if (!demographics?.age) {
    box.innerHTML = '<p class="muted">No crowd data for this site.</p>';
    return;
  }
  const rows = Object.entries(AGE_LABELS)
    .filter(([key]) => key in demographics.age)
    .map(([key, label]) => ({ label, value: Number(demographics.age[key]) || 0 }));
  if (demographics.gender?.female != null) rows.push({ label: "Women", value: Number(demographics.gender.female) || 0 });
  const max = Math.max(0.25, ...rows.map((row) => Math.abs(row.value)));
  box.innerHTML = rows
    .map(({ label, value }) => {
      const bar = `<i style="--w:${((Math.abs(value) / max) * 100).toFixed(1)}%"></i>`;
      return `<div class="crow"><span class="lab">${esc(label)}</span><span class="neg">${value < 0 ? bar : ""}</span><span class="pos">${value > 0 ? bar : ""}</span><span class="val">${value > 0 ? "+" : ""}${value.toFixed(2)}</span></div>`;
    })
    .join("");
}

/* ---------- Design sheet ---------- */

const dialog = $("#design");
let designToken = 0;
$("#design-close").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (event) => {
  if (event.target === dialog) dialog.close();
});

async function openDesign(index) {
  const concept = state.concepts[index];
  if (!concept || !state.runId) return;
  const token = ++designToken;
  $("#design-body").innerHTML = designSkeleton(concept, index);
  if (!dialog.open) dialog.showModal();
  const key = `${state.runId}:${index}`;
  try {
    let design = state.designs.get(key);
    if (!design) {
      design = await api("/api/design", { method: "POST", body: JSON.stringify({ run_id: state.runId, index }) });
      state.designs.set(key, design);
    }
    if (token === designToken && dialog.open) $("#design-body").innerHTML = designHtml(concept, design, index);
  } catch (error) {
    if (token === designToken && dialog.open) {
      $("#design-body").innerHTML = `
        <div class="d-main">
          <p class="d-eyebrow mono">Design sheet</p>
          <h2 class="d-title" id="design-title">${esc(concept.name)}</h2>
          <p class="d-p">${esc(error.message)}</p>
        </div>`;
    }
  }
}

function designSkeleton(concept, index) {
  return `
    <div class="d-main">
      <p class="d-eyebrow mono">Design sheet · Concept ${letter(index)} · drafting</p>
      <h2 class="d-title" id="design-title">${esc(concept.name)}</h2>
      <div class="sk" style="height:20px;width:72%"></div>
      <div class="sk" style="height:20px;width:54%;margin-top:10px"></div>
      <div class="sk" style="height:240px;margin-top:34px"></div>
    </div>
    <aside class="d-side"><div class="d-side-inner">
      <div class="sk" style="height:190px;border-radius:24px"></div>
      <div class="sk" style="height:132px;border-radius:24px"></div>
      <div class="sk" style="height:132px;border-radius:24px"></div>
    </div></aside>`;
}

function designHtml(concept, design, index) {
  const interior = design.interior || {};
  const spec = [
    ["Mood", interior.mood],
    ["Decor & materials", list(interior.materials).join(", ")],
    ["Lighting", interior.lighting],
    ["Layout", interior.layout],
    ["Seating", interior.seating],
    ["Price", price(design.price_level || concept.price_level)],
    ["Hours", design.hours],
  ].filter(([, value]) => value);
  const offer = list(design.offer);
  const music = design.music || {};
  const artists = list(music.artists);
  const partners = (design.partners || []).filter((partner) => partner && partner.name);
  const image = safeUrl(design.image);
  const name = design.name || concept.name;
  const inspired = list(concept.inspired_by);
  const sound = artists.length || music.direction
    ? `<h3 class="d-h">Sound</h3>${music.direction ? `<p class="d-p">${esc(music.direction)}</p>` : ""}
       <div class="tags" style="margin-top:12px">${artists.map((artist) => `<span class="tag blue">${esc(artist)}</span>`).join("")}</div>`
    : "";
  return `
    <div class="d-main">
      <p class="d-eyebrow mono">Design sheet · Concept ${letter(index)} · ${esc(concept.genre)} · ${design.mode === "agent" ? "agent" : "evidence rules"}</p>
      <h2 class="d-title" id="design-title">${esc(name)}</h2>
      <p class="d-tagline">${esc(design.tagline || concept.one_liner)}</p>
      ${design.concept_statement ? `<p class="d-statement serif">${esc(design.concept_statement)}</p>` : ""}
      <h3 class="d-h">Interior</h3>
      <dl class="spec">${spec.map(([key, value]) => `<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`).join("")}</dl>
      ${offer.length ? `<h3 class="d-h">The offer</h3><ol class="offer">${offer.map((item) => `<li>${esc(item)}</li>`).join("")}</ol>` : ""}
      ${sound}
      ${partners.length ? `<h3 class="d-h">Partners</h3><ul class="partners">${partners.map((partner) => `<li><b>${esc(partner.name)}</b><span>${esc(partner.why || "")}</span></li>`).join("")}</ul>` : ""}
      ${design.launch ? `<h3 class="d-h">Launch</h3><p class="d-p">${esc(design.launch)}</p>` : ""}
      ${concept.risk ? `<h3 class="d-h">Risk</h3><p class="d-p">${esc(concept.risk)}</p>` : ""}
    </div>
    <aside class="d-side"><div class="d-side-inner">
      ${image ? `<figure class="d-image"><img src="${esc(image)}" alt="Generated interior concept for ${esc(name)}" /></figure>` : plateHtml(design.dna || {})}
      <p class="d-source mono">Design DNA read from the locals' favorite ${esc(concept.genre)} places${inspired.length ? `: ${esc(inspired.join(", "))}` : ""}.</p>
    </div></aside>`;
}

function plateHtml(dna) {
  const pick = (key, count) => list(dna[key]).slice(0, count);
  const menu = pick("menu", 2).length ? pick("menu", 2) : pick("offerings", 2);
  const tiles = [
    ["pl-a", "Ambience", pick("ambience", 3).join(" / ") || "Warm, welcoming", "big"],
    ["pl-b", "Decor", pick("decor", 2).join(", ") || "Open", "ser"],
    ["pl-c", "Setting", pick("setting", 2).join(", ") || "Street level", "ser"],
    ["pl-d", "On the menu", menu.join(", ") || "House specials", "ser"],
    ["pl-e", "Amenities", pick("amenities", 3).join(", ") || "Seating", "ser"],
  ];
  return `<div class="plate">${tiles
    .map(([cls, title, text, style]) => `<div class="${cls}"><span class="mono">${title}</span><span class="${style}">${esc(text)}</span></div>`)
    .join("")}</div>`;
}

/* ---------- Start ---------- */

setProgress(0.42);
loadPresets();
