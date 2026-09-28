// Funda Watch UI. The decisions live in logic.js (unit-tested); this file only wires them to the DOM.
// Everything that comes from listings.json is inserted as text, never as HTML.
import {
  TIERS, TIER_LABEL, STATUS_KEYS, STATUS_LABEL, DAY_MS, defaultFilters, tierOf, wijkLabel, statusOf, daysSince,
  pricePerM2, balconyM2, isNew, priceDrop, criteria, wijkRanks, reasonBars, applyFilters, countTabs, inTab,
  sortListings, groupListings, euro, euroShort, activeFilters, removeFilter, photoUrl, describeFreshness,
} from "./logic.js";

const $ = (id) => document.getElementById(id);
const MAX_COMPARE = 4;
const CRIT_MARK = { good: "✓", neutral: "–", unclear: "?", bad: "✕" };
const TAB_LABEL = { triage: "To triage", shortlist: "Shortlist", skipped: "Skipped", all: "All" };

// Constant icon markup only; nothing from the data ever reaches innerHTML.
const SVG = {
  heart: '<svg viewBox="0 0 24 24"><path d="M12 21s-7-4.5-9.5-9A5.5 5.5 0 0 1 12 6.5 5.5 5.5 0 0 1 21.5 12C19 16.5 12 21 12 21z"/></svg>',
  calendar: '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
  x: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  chevron: '<svg viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>',
  house: '<svg viewBox="0 0 24 24"><path d="M3 11l9-8 9 8M5 10v10h14V10"/></svg>',
};
const STATUS_ICON = { interested: "heart", viewing: "calendar", skip: "x" };
const STATUS_SHORT = { interested: "Interested", viewing: "Viewing", skip: "Skip" };

// localStorage can be unavailable (private windows, blocked storage), so every access is guarded.
const store = {
  get(key, fallback) {
    try { const raw = localStorage.getItem(key); return raw === null ? fallback : JSON.parse(raw); } catch { return fallback; }
  },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* carry on without persistence */ } },
};

let listings = [];
let generated = null;
let ranks = new Map();
let statuses = store.get("fw:statuses", {});
let filters = loadFilters();
let lastVisit = store.get("fw:lastVisit", null);
let photosInList = store.get("fw:photos", true);
let lastCheck = null; // when the workflow last ran, if GitHub told us
let selectedId = null;
const openIds = new Set();
const compareIds = new Set();
let cache = null;
let map = null, markerLayer = null;
const markers = new Map();

const TIER_COLOURS = { top: "#22ab34", good: "#0071b3", ok: "#8a8a8a", low: "#c93328", pending: "#bdbdbd" };

function loadFilters() {
  const merged = { ...defaultFilters(), ...store.get("fw:filters:v2", {}) };
  if (!Array.isArray(merged.tiers)) merged.tiers = defaultFilters().tiers;
  if (!Array.isArray(merged.wijkOff)) merged.wijkOff = [];
  if (!["triage", "shortlist", "skipped", "all"].includes(merged.tab)) merged.tab = "triage";
  return merged;
}

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children) if (child !== null && child !== undefined && child !== false) node.append(child);
  return node;
}
const icon = (name) => { const s = el("span", { class: "ico", "aria-hidden": "true" }); s.innerHTML = SVG[name]; return s; };
const safeHttps = (url) => (typeof url === "string" && url.startsWith("https://") ? url : null);
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "");

function toast(message) {
  const node = el("div", { class: "toast", role: "status", text: message });
  document.body.append(node);
  setTimeout(() => node.remove(), 2600);
}

// ---------- computing what to show ----------

function compute() {
  const ctx = { statuses, lastVisit, now: Date.now() };
  const base = applyFilters(listings, { ...filters, onlyNew: false, onlyDrops: false }, ctx);
  const passing = applyFilters(listings, filters, ctx);
  const counts = countTabs(passing, statuses);
  const visible = sortListings(passing.filter((l) => inTab(l, filters.tab, statuses)), filters.sort);
  return {
    ctx, passing, counts, visible,
    groups: groupListings(visible, filters.group, statuses),
    newCount: base.filter((l) => isNew(l, lastVisit)).length,
    dropCount: base.filter((l) => priceDrop(l)).length,
  };
}

const visibleIds = () => (cache ? cache.visible.map((l) => l.id) : []);

// ---------- pieces of a listing ----------

function scoreBox(l) {
  const tier = tierOf(l);
  return el("div", { class: `score ${tier}`, title: `${TIER_LABEL[tier]}${l.score ? `, ${l.score.points} points` : ""}` },
    el("b", { text: l.score ? String(l.score.points) : "…" }), el("small", { text: TIER_LABEL[tier] }));
}

function badges(l) {
  const out = [];
  if (isNew(l, lastVisit)) out.push(el("span", { class: "badge new", text: "New" }));
  const drop = priceDrop(l);
  if (drop) out.push(el("span", { class: "badge drop", title: `Was ${euro(drop.from)}`, text: `▼ ${euro(drop.amount)}` }));
  const status = statusOf(l, statuses);
  if (status) out.push(el("span", { class: "badge status", text: STATUS_LABEL[status] }));
  if (!l.active) out.push(el("span", { class: "badge gone", text: "No longer matches" }));
  return out;
}

function titleLine(l) {
  const link = el("a", { href: safeHttps(l.url) || "#", target: "_blank", rel: "noopener noreferrer", text: l.title });
  return el("div", { class: "title-line" }, el("h3", { class: "title" }, link), ...badges(l));
}

function placeText(l) {
  return [l.neighbourhood && l.neighbourhood !== l.wijk ? l.neighbourhood : null, l.wijk ? wijkLabel(l.wijk) : null, l.city].filter(Boolean).join(" · ");
}

function factsLine(l) {
  const parts = [el("span", { class: "price", text: l.price ? euro(l.price) : "Price unknown" })];
  const add = (text, cls) => { if (text) parts.push(el("span", { class: cls || "", text })); };
  add(l.living_area ? `${l.living_area} m²` : "");
  add(l.bedrooms !== null && l.bedrooms !== undefined ? `${l.bedrooms} bed` : "");
  const per = pricePerM2(l);
  add(per ? `${euro(per)}/m²` : "", "dim");
  if (l.details) add(l.details.is_apartment ? "Apartment" : "House", "dim");
  add(l.energy_label ? `label ${l.energy_label}` : "", "dim");
  const days = daysSince(l.published, Date.now());
  add(days !== null ? `${days} d on Funda` : "", "dim");
  return el("div", { class: "facts" }, ...parts);
}

function critChips(l) {
  return el("div", { class: "crits" }, ...criteria(l).map((c) =>
    el("span", { class: `crit ${c.state}` }, el("i", { text: CRIT_MARK[c.state] }), c.label)));
}

function miniCrits(l) {
  const list = criteria(l);
  const shown = list.length === 1 ? Array.from({ length: 5 }, () => ({ state: "unclear", label: "Details pending" })) : list;
  return el("div", { class: "mini", "aria-hidden": "true" }, ...shown.map((c) => el("span", { class: c.state, title: c.label, text: CRIT_MARK[c.state] })));
}

function topReasons(l) {
  if (!l.score) return null;
  return el("ul", { class: "reasons" }, ...l.score.reasons.slice(0, 3).map((r) =>
    el("li", { class: r.points > 0 ? "pos" : "neg" }, el("b", { text: `${r.points > 0 ? "+" : ""}${r.points}` }), ` ${r.text}`)));
}

function statusButton(l, key, withLabel) {
  const on = statuses[l.id] === key;
  return el("button", {
    class: `btn small${on ? " on" : ""}`, type: "button", title: STATUS_LABEL[key], "aria-label": STATUS_LABEL[key], "aria-pressed": String(on),
    onclick: (e) => { e.stopPropagation(); act(l.id, key); },
  }, icon(STATUS_ICON[key]), withLabel ? STATUS_SHORT[key] : null);
}

function compareBox(l) {
  const box = el("input", { type: "checkbox", "aria-label": `Compare ${l.title}` });
  box.checked = compareIds.has(l.id);
  box.addEventListener("click", (e) => e.stopPropagation());
  box.addEventListener("change", () => toggleCompare(l.id, box));
  return el("label", { onclick: (e) => e.stopPropagation() }, box, "Compare");
}

// ---------- the expanded panel ----------

function kv(rows) {
  const dl = el("dl", { class: "kv" });
  for (const [k, v] of rows) if (v !== null && v !== undefined && v !== "") dl.append(el("dt", { text: k }), el("dd", { text: String(v) }));
  return dl;
}
const yn = (v) => (v === true ? "yes" : v === false ? "no" : "unknown");

function panelFor(l) {
  const d = l.details;
  const why = el("div", { class: "why" });
  if (l.score) {
    for (const b of reasonBars(l.score)) {
      why.append(el("div", { class: `row ${b.points > 0 ? "pos" : "neg"}` }, el("b", { text: `${b.points > 0 ? "+" : ""}${b.points}` }),
        el("div", {}, el("span", { text: b.text }), el("div", { class: "bar", style: `width:${b.width}%` }))));
    }
  } else {
    why.append(el("p", { class: "place", text: "Details pending: this listing hasn't been read yet, so it has no score." }));
  }

  const rank = ranks.get(l.id);
  const facts = d ? kv([
    ["Ownership", d.ownership],
    ["Type", d.is_apartment ? "Apartment" : "House"],
    ["Floor", d.is_apartment ? `${d.floor_label || (d.floor === 0 ? "Ground floor" : "")}${d.lift ? " · lift" : " · no lift"}` : null],
    ["Built", d.year_built],
    ["Outdoor", d.balcony ? `Balcony/terrace${d.outdoor_m2 ? ` ${d.outdoor_m2} m²` : ""}` : d.garden ? "Garden" : "None"],
    ["VvE", d.is_apartment ? (d.vve_monthly ? `${euro(d.vve_monthly)} / month` : "unknown") : "No VvE (house)"],
    ["Reserve fund", d.is_apartment ? yn(d.vve_reserve_fund) : null],
    ["Maintenance plan", d.is_apartment ? yn(d.vve_maintenance_plan) : null],
    ["Registered (KvK)", d.is_apartment ? yn(d.vve_registered) : null],
    ["Busy road", d.busy_road ? "yes" : "no"],
    ["Condition (guess)", d.needs_work ? "needs work" : d.move_in_ready ? "move-in ready" : "no signal"],
    ["Energy label", l.energy_label],
    ["Rank", rank ? `#${rank.rank} of ${rank.of} in ${l.wijk}` : null],
  ]) : el("p", { class: "place", text: "Not read yet." });

  const days = daysSince(l.published, Date.now());
  const history = (l.price_history || []).slice().reverse();
  const timeline = el("div", {}, kv([
    ["On Funda since", l.published ? `${fmtDate(l.published)}${days !== null ? ` · ${days} days` : ""}` : null],
    ["First seen here", fmtDate(l.first_seen)],
    ["Found by", l.search_name],
    ["Last seen", l.last_seen ? fmtDate(l.last_seen) : null],
  ]));
  const hist = el("div", { class: "pricehist" });
  history.forEach(([date, price], i) => {
    const older = history[i + 1];
    const cls = older ? (price < older[1] ? "down" : price > older[1] ? "up" : "") : "";
    hist.append(el("div", { class: cls, text: `${date}  ${euro(price)}${cls === "down" ? "  ▼" : cls === "up" ? "  ▲" : ""}` }));
  });
  timeline.append(hist);
  const links = el("div", { class: "links" });
  const funda = safeHttps(l.url);
  if (funda) links.append(el("a", { href: funda, target: "_blank", rel: "noopener noreferrer", text: "Open on Funda ↗" }));
  if (d && d.latitude !== null && d.latitude !== undefined) {
    links.append(el("a", { href: `https://www.google.com/maps?q=${d.latitude},${d.longitude}`, target: "_blank", rel: "noopener noreferrer", text: "Google Maps ↗" }));
    links.append(el("a", { href: `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${d.latitude},${d.longitude}`, target: "_blank", rel: "noopener noreferrer", text: "Street View ↗" }));
  } else {
    links.append(el("a", { href: `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${l.title} ${l.city}`)}`, target: "_blank", rel: "noopener noreferrer", text: "Search on Google Maps ↗" }));
  }
  timeline.append(links);

  const photo = photoUrl(l.photo_url, 800);
  return el("div", { class: "panel" },
    photo ? el("img", { class: "banner", src: photo, alt: `Photo of ${l.title}`, loading: "lazy", referrerpolicy: "no-referrer" }) : null,
    el("div", { class: "cols" },
      el("section", {}, el("h4", { text: `Why ${l.score ? l.score.points : "no"} points` }), why),
      el("section", {}, el("h4", { text: "Facts" }), facts),
      el("section", {}, el("h4", { text: "Timeline & price" }), timeline)));
}

// ---------- list items ----------

// The listing's photo at thumbnail size (about 30 KB instead of the 580 KB original), or a house
// icon when there's no photo, photos are switched off, or the image fails to load.
function thumbFor(l) {
  const src = photosInList ? photoUrl(l.photo_url, 400) : null;
  if (!src) return el("div", { class: "thumb placeholder", "aria-hidden": "true" }, icon("house"));
  const img = el("img", { src, alt: `Photo of ${l.title}`, loading: "lazy", decoding: "async", referrerpolicy: "no-referrer" });
  const box = el("div", { class: "thumb" }, img);
  img.addEventListener("error", () => { box.className = "thumb placeholder"; box.replaceChildren(icon("house")); });
  return box;
}

function buildCard(l) {
  const open = openIds.has(l.id);
  const thumb = thumbFor(l);
  const actions = el("div", { class: "actions" }, ...STATUS_KEYS.map((k) => statusButton(l, k, true)),
    el("button", { class: "more-link", type: "button", "aria-expanded": String(open), onclick: (e) => { e.stopPropagation(); toggleOpen(l.id); }, text: open ? "Details ▴" : "Details ▾" }));
  const body = el("div", { class: "body" }, scoreBox(l),
    el("div", { class: "main" }, titleLine(l), el("div", { class: "place", text: placeText(l) }), factsLine(l), critChips(l), topReasons(l), actions));
  const card = el("article", { class: `card${l.id === selectedId ? " selected" : ""}${l.active ? "" : " gone"}`, "data-id": l.id, tabindex: "0" },
    thumb, body, el("div", { class: "side" }, compareBox(l)), open ? panelFor(l) : null);
  card.addEventListener("click", () => select(l.id, { pan: true }));
  return card;
}

function buildRow(l) {
  const open = openIds.has(l.id);
  const link = el("a", { href: safeHttps(l.url) || "#", target: "_blank", rel: "noopener noreferrer", text: l.title, onclick: (e) => e.stopPropagation() });
  const line2 = el("div", { class: "line2" }, el("b", { text: `${euroShort(l.price)}${l.living_area ? ` · ${l.living_area} m²` : ""}` }), ` · ${placeText(l)}`);
  const row = el("div", { class: "row-compact" }, scoreBox(l),
    el("div", { style: "min-width:0" }, el("div", { class: "line1" }, link, ...badges(l)), line2),
    miniCrits(l),
    el("div", { class: "icon-actions" }, ...STATUS_KEYS.map((k) => statusButton(l, k, false))),
    el("button", { class: "chev", type: "button", "aria-label": "Details", "aria-expanded": String(open), onclick: (e) => { e.stopPropagation(); toggleOpen(l.id); } }, icon("chevron")));
  const wrap = el("div", { class: `row-wrap${l.id === selectedId ? " selected" : ""}${l.active ? "" : " gone"}`, "data-id": l.id, tabindex: "0" }, row, open ? panelFor(l) : null);
  wrap.addEventListener("click", () => select(l.id, { pan: true }));
  return wrap;
}

function emptyState() {
  const msg = {
    triage: ["Nothing left to triage", "Everything that matches has a status, or the filters hide it."],
    shortlist: ["Nothing shortlisted yet", "Use Interested or Viewing on a listing to add it here."],
    skipped: ["No skipped listings", "Listings you skip end up here, in case you change your mind."],
    all: ["Nothing matches", "Try loosening the filters."],
  }[filters.tab];
  if (!listings.length) return el("div", { class: "empty" }, el("strong", { text: "No listings yet" }), "The first workflow run creates this list.");
  return el("div", { class: "empty" }, el("strong", { text: msg[0] }), msg[1], " ", el("a", { href: "#", text: "Reset filters", onclick: (e) => { e.preventDefault(); resetFilters(); } }));
}

function renderList() {
  const list = $("list");
  list.replaceChildren();
  if (!cache.visible.length) { list.append(emptyState()); return; }
  const build = filters.density === "compact" ? buildRow : buildCard;
  for (const group of cache.groups) {
    if (group.label) list.append(el("div", { class: "group-head" }, group.label, el("span", { class: "n", text: `${group.items.length}` })));
    for (const l of group.items) list.append(build(l));
  }
}

// ---------- toolbar, tabs, chips ----------

function renderTabs() {
  const nav = $("tabs");
  nav.replaceChildren(...Object.keys(TAB_LABEL).map((key) => el("button", {
    class: "tab", role: "tab", type: "button", "aria-selected": String(filters.tab === key),
    onclick: () => { filters.tab = key; changed(); },
  }, TAB_LABEL[key], el("span", { class: "n", text: String(cache.counts[key]) }))));
}

function renderToolbar() {
  const q = $("q");
  if (document.activeElement !== q) q.value = filters.q;
  $("sort").value = filters.sort;
  $("group").value = filters.group;
  $("densityDetailed").setAttribute("aria-pressed", String(filters.density !== "compact"));
  $("densityCompact").setAttribute("aria-pressed", String(filters.density === "compact"));
  $("newBtn").setAttribute("aria-pressed", String(filters.onlyNew));
  $("newBtn").classList.toggle("on", filters.onlyNew);
  $("newCount").textContent = String(cache.newCount);
  $("dropsBtn").setAttribute("aria-pressed", String(filters.onlyDrops));
  $("dropsBtn").classList.toggle("on", filters.onlyDrops);
  $("dropsCount").textContent = String(cache.dropCount);
  const active = activeFilters(filters).length;
  $("filtersCount").hidden = active === 0;
  $("filtersCount").textContent = String(active);
  $("photosToggle").checked = photosInList;
  const shown = $("split").dataset.view === "map";
  $("viewToggle").textContent = shown ? "List" : "Map";
}

function renderChips() {
  const box = $("activeFilters");
  const chips = activeFilters(filters);
  box.replaceChildren();
  if (!chips.length) return;
  box.append(el("span", { text: "Filtered:" }));
  for (const chip of chips) {
    box.append(el("span", { class: "fchip" }, chip.label,
      el("button", { type: "button", "aria-label": `Remove filter: ${chip.label}`, text: "×", onclick: () => { filters = removeFilter(filters, chip.id); changed(); } })));
  }
}

function renderSummary() {
  const active = listings.filter((l) => l.active);
  const pending = active.filter((l) => !l.score).length;
  const box = $("summary");
  box.replaceChildren();
  if (!generated) { box.textContent = listings.length ? "" : "No data yet. The first workflow run creates it."; return; }
  const parts = [`${active.length} matching`];
  if (pending) parts.push(`${pending} awaiting details`);
  const fresh = describeFreshness(generated, lastCheck, Date.now());
  box.textContent = fresh ? `${parts.join(" · ")} · ${fresh}` : parts.join(" · ");
}

function renderCompareBar() {
  const bar = $("compareBar");
  bar.hidden = compareIds.size === 0;
  $("compareText").textContent = `${compareIds.size} selected (max ${MAX_COMPARE})`;
  $("compareOpen").disabled = compareIds.size < 2;
}

// ---------- rendering everything ----------

function render(opts = {}) {
  cache = compute();
  renderSummary();
  renderTabs();
  renderToolbar();
  renderChips();
  renderList();
  updateMap(cache.visible, opts.fit === true);
  renderCompareBar();
  if (filterDialogOpen()) updateFilterButton();
}

function changed() {
  store.set("fw:filters:v2", filters);
  render({ fit: true });
}

function resetFilters() {
  filters = { ...defaultFilters(), density: filters.density };
  changed();
  syncFilterDialog();
}

// ---------- actions ----------

function toggleOpen(id) {
  if (openIds.has(id)) openIds.delete(id); else openIds.add(id);
  render();
  selectedId = id;
  markSelected();
}

function act(id, status) {
  const before = visibleIds();
  const at = before.indexOf(id);
  if (statuses[id] === status) delete statuses[id]; else statuses[id] = status;
  store.set("fw:statuses", statuses);
  render();
  const after = visibleIds();
  if (id === selectedId && !after.includes(id)) {
    // The listing left this tab, so move on to its neighbour like a triage queue.
    const next = before.slice(at + 1).find((x) => after.includes(x)) || before.slice(0, at).reverse().find((x) => after.includes(x));
    if (next) select(next, { scroll: true, pan: true }); else selectedId = null;
  }
}

function toggleCompare(id, box) {
  if (compareIds.has(id)) compareIds.delete(id);
  else if (compareIds.size >= MAX_COMPARE) { if (box) box.checked = false; toast(`You can compare up to ${MAX_COMPARE} listings.`); return; }
  else compareIds.add(id);
  renderCompareBar();
}

function markSelected() {
  for (const node of document.querySelectorAll("#list [data-id]")) node.classList.toggle("selected", node.dataset.id === selectedId);
  for (const [id, marker] of markers) marker.setStyle({ radius: id === selectedId ? 13 : 9, weight: id === selectedId ? 3 : 2 });
}

function select(id, opts = {}) {
  selectedId = id;
  markSelected();
  const l = listings.find((x) => x.id === id);
  if (!l) return;
  const marker = markers.get(id);
  if (map && marker && l.details && opts.pan) map.flyTo([l.details.latitude, l.details.longitude], Math.max(map.getZoom(), 15), { duration: 0.5 });
  if (map && marker && opts.pan) marker.openPopup();
  if (opts.scroll) {
    const node = document.querySelector(`#list [data-id="${CSS.escape(id)}"]`);
    if (node && node.scrollIntoView) node.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

// ---------- map ----------

function initMap() {
  if (typeof L === "undefined") {
    $("map").style.display = "none";
    const note = $("mapnote");
    note.style.display = "block";
    note.textContent = "The map library couldn't be loaded, so the map is unavailable.";
    return;
  }
  map = L.map("map").setView([52.06, 4.3], 12);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap contributors" }).addTo(map);
  markerLayer = L.layerGroup().addTo(map);
}

function popupFor(l) {
  const box = el("div", {}, el("strong", { text: l.title }), el("br"),
    el("span", { text: `${l.price ? euro(l.price) : ""} · ${l.living_area || "?"} m²` }), el("br"),
    el("span", { text: l.score ? `${l.score.points}/100 · ${TIER_LABEL[tierOf(l)]}` : "Details pending" }), el("br"),
    el("a", { href: safeHttps(l.url) || "#", target: "_blank", rel: "noopener noreferrer", text: "Open on Funda ↗" }));
  return box;
}

function updateMapNote(visible) {
  const note = $("mapnote");
  const missing = visible.filter((l) => !(l.details && l.details.latitude !== null && l.details.latitude !== undefined)).length;
  note.style.display = missing ? "block" : "none";
  note.textContent = missing ? `${missing} listing${missing === 1 ? "" : "s"} in this view ${missing === 1 ? "isn't" : "aren't"} on the map yet, because their details haven't been read.` : "";
}

function updateMap(visible, fit) {
  if (!map) return;
  updateMapNote(visible);
  markerLayer.clearLayers();
  const points = [];
  for (const l of visible) {
    const d = l.details;
    if (!d || d.latitude === null || d.latitude === undefined) continue;
    let marker = markers.get(l.id);
    if (!marker) {
      marker = L.circleMarker([d.latitude, d.longitude], { radius: 9, weight: 2, color: "#fff", fillOpacity: 0.92 });
      marker.on("click", () => select(l.id, { scroll: true }));
      markers.set(l.id, marker);
    }
    marker.setStyle({ fillColor: TIER_COLOURS[tierOf(l)], radius: l.id === selectedId ? 13 : 9, weight: l.id === selectedId ? 3 : 2 });
    marker.bindPopup(() => popupFor(l));
    markerLayer.addLayer(marker);
    points.push([d.latitude, d.longitude]);
  }
  if (fit && points.length) map.fitBounds(points, { padding: [30, 30], maxZoom: 15 });
}

// ---------- filter dialog ----------

const filterDialog = () => $("filterDialog");
const filterDialogOpen = () => filterDialog().hasAttribute("open");
function openDialog(dlg) { if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", ""); }
function closeDialog(dlg) { if (typeof dlg.close === "function") dlg.close(); else dlg.removeAttribute("open"); }

function buildFilterDialog() {
  const body = $("filterBody");
  body.replaceChildren();
  const tierRow = el("div", { class: "tierchips" });
  for (const t of TIERS) {
    tierRow.append(el("button", { class: "btn", type: "button", "data-tier": t, "aria-pressed": "false", text: TIER_LABEL[t],
      onclick: () => { filters.tiers = filters.tiers.includes(t) ? filters.tiers.filter((x) => x !== t) : [...filters.tiers, t]; changed(); syncFilterDialog(); } }));
  }
  const num = (key, label, step) => el("label", { class: "field" }, label,
    el("input", { type: "number", min: "0", step, "data-key": key, oninput: (e) => { filters[key] = e.target.value; changed(); } }));
  const beds = el("label", { class: "field" }, "Min bedrooms",
    el("select", { "data-key": "minBeds", onchange: (e) => { filters.minBeds = e.target.value; changed(); } },
      ...[["0", "Any"], ["2", "2+"], ["3", "3+"], ["4", "4+"]].map(([v, t]) => el("option", { value: v, text: t }))));
  const check = (key, label) => el("label", { class: "check" }, el("input", { type: "checkbox", "data-key": key, onchange: (e) => { filters[key] = e.target.checked; changed(); } }), label);
  const counts = new Map();
  for (const l of listings) if (l.active) counts.set(l.wijk || "", (counts.get(l.wijk || "") || 0) + 1);
  const wijken = el("div", { class: "wijklist" });
  for (const [name, n] of [...counts].sort((a, b) => wijkLabel(a[0]).localeCompare(wijkLabel(b[0])))) {
    wijken.append(el("label", { class: "check" },
      el("input", { type: "checkbox", "data-wijk": name, onchange: (e) => { filters.wijkOff = e.target.checked ? filters.wijkOff.filter((w) => w !== name) : [...filters.wijkOff, name]; changed(); } }),
      `${wijkLabel(name)} (${n})`));
  }
  body.append(
    el("div", { class: "fsection" }, el("h3", { text: "Tiers" }), tierRow),
    el("div", { class: "fsection" }, el("h3", { text: "Limits" }), el("div", { class: "fgrid" },
      num("maxPrice", "Max price (€)", "5000"), num("minArea", "Min living area (m²)", "5"), num("minBalcony", "Min balcony (m²)", "1"),
      beds, num("maxVve", "Max VvE (€ per month)", "25"))),
    el("div", { class: "checks" }, check("hideErfpacht", "Hide erfpacht"), check("showGone", "Include listings that no longer match")),
    el("div", { class: "fsection" }, el("h3", { text: "Wijken" }), wijken));
  syncFilterDialog();
}

function syncFilterDialog() {
  const body = $("filterBody");
  for (const b of body.querySelectorAll("[data-tier]")) b.setAttribute("aria-pressed", String(filters.tiers.includes(b.dataset.tier))), b.classList.toggle("on", filters.tiers.includes(b.dataset.tier));
  for (const i of body.querySelectorAll("input[data-key], select[data-key]")) {
    const value = filters[i.dataset.key];
    if (i.type === "checkbox") i.checked = Boolean(value); else if (document.activeElement !== i) i.value = value;
  }
  for (const i of body.querySelectorAll("input[data-wijk]")) i.checked = !filters.wijkOff.includes(i.dataset.wijk);
  updateFilterButton();
}

function updateFilterButton() {
  const n = cache ? cache.visible.length : 0;
  $("filterShow").textContent = `Show ${n} result${n === 1 ? "" : "s"}`;
}

// ---------- compare ----------

function compareRows(items) {
  const num = (fn, pick) => ({ fn, pick });
  const days = (l) => daysSince(l.published, Date.now());
  const rows = [
    ["Price", (l) => (l.price ? euro(l.price) : "–"), num((l) => l.price, "min")],
    ["Living area", (l) => (l.living_area ? `${l.living_area} m²` : "–"), num((l) => l.living_area, "max")],
    ["Price per m²", (l) => (pricePerM2(l) ? euro(pricePerM2(l)) : "–"), num(pricePerM2, "min")],
    ["Bedrooms", (l) => l.bedrooms ?? "–", num((l) => l.bedrooms, "max")],
    ["Type", (l) => (l.details ? (l.details.is_apartment ? "Apartment" : "House") : "–")],
    ["Floor", (l) => (l.details && l.details.is_apartment ? `${l.details.floor_label || "–"}${l.details.lift ? " · lift" : ""}` : "–")],
    ["Outdoor", (l) => (l.details ? (l.details.balcony ? `Balcony ${l.details.outdoor_m2 || "?"} m²` : l.details.garden ? "Garden" : "None") : "–"), num(balconyM2, "max")],
    ["Ownership", (l) => (l.details ? (l.details.erfpacht ? "Erfpacht" : "Freehold") : "–")],
    ["VvE per month", (l) => (l.details ? (l.details.is_apartment ? (l.details.vve_monthly ? euro(l.details.vve_monthly) : "unknown") : "none (house)") : "–"),
      num((l) => (l.details && l.details.is_apartment ? l.details.vve_monthly : null), "min")],
    ["VvE health", (l) => (l.details && l.details.is_apartment ? `reserve ${yn(l.details.vve_reserve_fund)}, plan ${yn(l.details.vve_maintenance_plan)}` : "–")],
    ["Built", (l) => (l.details && l.details.year_built) || "–"],
    ["Energy label", (l) => l.energy_label || "–"],
    ["Score", (l) => (l.score ? `${l.score.points} · ${TIER_LABEL[tierOf(l)]}` : "pending"), num((l) => (l.score ? l.score.points : null), "max")],
    ["Rank in wijk", (l) => (ranks.get(l.id) ? `#${ranks.get(l.id).rank} of ${ranks.get(l.id).of}` : "–")],
    ["On Funda", (l) => (days(l) !== null ? `${days(l)} days` : "–")],
    ["First seen here", (l) => fmtDate(l.first_seen)],
  ];
  return rows.map(([label, value, best]) => {
    let winner = null;
    if (best) {
      const nums = items.map((l) => best.fn(l)).filter((v) => typeof v === "number" && v > 0);
      if (nums.length > 1 && new Set(nums).size > 1) winner = best.pick === "min" ? Math.min(...nums) : Math.max(...nums);
    }
    return { label, cells: items.map((l) => ({ text: String(value(l)), best: winner !== null && best.fn(l) === winner })) };
  });
}

function openCompare() {
  const items = [...compareIds].map((id) => listings.find((l) => l.id === id)).filter(Boolean);
  if (items.length < 2) { toast("Pick at least two listings to compare."); return; }
  const table = el("table", { class: "cmp" });
  table.append(el("thead", {}, el("tr", {}, el("th", {}), ...items.map((l) =>
    el("th", {}, el("a", { href: safeHttps(l.url) || "#", target: "_blank", rel: "noopener noreferrer", text: l.title }), el("div", { class: "place", text: placeText(l) }))))));
  const tbody = el("tbody");
  for (const row of compareRows(items)) tbody.append(el("tr", {}, el("th", { text: row.label }), ...row.cells.map((c) => el("td", { class: c.best ? "best" : "", text: c.text }))));
  table.append(tbody);
  $("compareBody").replaceChildren(el("div", { style: "overflow:auto" }, table));
  openDialog($("compareDialog"));
}

// ---------- export, import, keyboard ----------

async function exportStatuses() {
  const text = JSON.stringify(statuses);
  try { await navigator.clipboard.writeText(text); toast("Statuses copied. Paste them into Import on your other device."); }
  catch { prompt("Copy these statuses:", text); }
}

function importStatuses() {
  const text = prompt("Paste exported statuses:");
  if (!text) return;
  try {
    const incoming = JSON.parse(text);
    if (!incoming || typeof incoming !== "object" || Array.isArray(incoming)) throw new Error("not an object");
    let added = 0;
    for (const [id, s] of Object.entries(incoming)) if (STATUS_KEYS.includes(s)) { statuses[id] = s; added += 1; }
    store.set("fw:statuses", statuses);
    render();
    toast(`Imported ${added} status${added === 1 ? "" : "es"}.`);
  } catch { toast("That doesn't look like exported statuses."); }
}

function onKey(e) {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const tag = (e.target && e.target.tagName) || "";
  if (["INPUT", "SELECT", "TEXTAREA"].includes(tag) || document.querySelector("dialog[open]")) return;
  const ids = visibleIds();
  const at = ids.indexOf(selectedId);
  const go = (i) => { if (ids[i] !== undefined) select(ids[i], { scroll: true, pan: true }); };
  if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); go(at + 1 >= ids.length ? ids.length - 1 : at + 1); }
  else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); go(Math.max(0, at - 1)); }
  else if (selectedId && e.key === "i") act(selectedId, "interested");
  else if (selectedId && e.key === "v") act(selectedId, "viewing");
  else if (selectedId && e.key === "s") act(selectedId, "skip");
  else if (selectedId && (e.key === "Enter" || e.key === "o")) toggleOpen(selectedId);
  else if (selectedId && e.key === "c") { toggleCompare(selectedId); render(); }
}

// ---------- start ----------

function bind() {
  $("q").addEventListener("input", (e) => { filters.q = e.target.value; changed(); });
  $("sort").addEventListener("change", (e) => { filters.sort = e.target.value; changed(); });
  $("group").addEventListener("change", (e) => { filters.group = e.target.value; changed(); });
  $("densityDetailed").addEventListener("click", () => { filters.density = "detailed"; changed(); });
  $("densityCompact").addEventListener("click", () => { filters.density = "compact"; changed(); });
  $("newBtn").addEventListener("click", () => { filters.onlyNew = !filters.onlyNew; changed(); });
  $("dropsBtn").addEventListener("click", () => { filters.onlyDrops = !filters.onlyDrops; changed(); });
  $("filtersBtn").addEventListener("click", () => { syncFilterDialog(); openDialog(filterDialog()); });
  $("filterClose").addEventListener("click", () => closeDialog(filterDialog()));
  $("filterShow").addEventListener("click", () => closeDialog(filterDialog()));
  $("filterReset").addEventListener("click", resetFilters);
  $("compareOpen").addEventListener("click", openCompare);
  $("compareClose").addEventListener("click", () => closeDialog($("compareDialog")));
  $("compareClear").addEventListener("click", () => { compareIds.clear(); render(); });
  $("markSeen").addEventListener("click", () => { lastVisit = new Date().toISOString(); store.set("fw:lastVisit", lastVisit); render(); toast("Marked everything as seen."); });
  $("exportBtn").addEventListener("click", () => { $("menu").removeAttribute("open"); exportStatuses(); });
  $("importBtn").addEventListener("click", () => { $("menu").removeAttribute("open"); importStatuses(); });
  $("resetBtn").addEventListener("click", () => { $("menu").removeAttribute("open"); resetFilters(); });
  $("photosToggle").addEventListener("change", (e) => { photosInList = e.target.checked; store.set("fw:photos", photosInList); render(); });
  $("viewToggle").addEventListener("click", () => {
    const split = $("split");
    split.dataset.view = split.dataset.view === "map" ? "list" : "map";
    renderToolbar();
    // The map was sized (and fitted) while hidden, so measure it again and frame every marker now it shows.
    if (split.dataset.view === "map" && map) setTimeout(() => { map.invalidateSize(); updateMap(cache.visible, true); }, 50);
  });
  document.addEventListener("keydown", onKey);
  document.addEventListener("click", (e) => { const menu = $("menu"); if (menu.open && !menu.contains(e.target)) menu.removeAttribute("open"); });
  // Remember when you last looked, so the next visit can flag what arrived in between.
  window.addEventListener("pagehide", () => store.set("fw:lastVisit", new Date().toISOString()));
}

async function load() {
  try {
    const response = await fetch("listings.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    listings = Array.isArray(data.listings) ? data.listings : [];
    generated = data.generated || null;
  } catch {
    listings = [];
  }
  ranks = wijkRanks(listings);
  buildFilterDialog();
  render({ fit: true });
  fetchLastCheck().then((when) => { if (when) { lastCheck = when; renderSummary(); } });
}

// listings.json only changes when something does, so ask GitHub when the watcher last ran. The site lives
// at <owner>.github.io/<repo>/, which is also where its Actions runs are. Any failure just means no "Checked" text.
async function fetchLastCheck() {
  try {
    const owner = location.hostname.endsWith(".github.io") ? location.hostname.split(".")[0] : null;
    const repo = location.pathname.split("/").filter(Boolean)[0];
    if (!owner || !repo) return null;
    const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/funda-watch.yml/runs?per_page=1&status=completed`;
    const response = await fetch(url, { headers: { Accept: "application/vnd.github+json" } });
    if (!response.ok) return null;
    const data = await response.json();
    return (data.workflow_runs && data.workflow_runs[0] && data.workflow_runs[0].updated_at) || null;
  } catch {
    return null;
  }
}

function init() {
  bind();
  initMap();
  render();
  load();
}

init();
