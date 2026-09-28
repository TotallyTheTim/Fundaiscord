// Pure functions behind the Funda Watch page: no DOM, no storage, so they can be unit-tested
// with `node --test` (see tests/js/logic.test.mjs).

export const TIERS = ["top", "good", "ok", "low", "pending"];
export const TIER_LABEL = { top: "Top", good: "Good", ok: "Okay", low: "Low", pending: "Pending" };
export const STATUS_KEYS = ["interested", "viewing", "skip"];
export const STATUS_LABEL = { interested: "Interested", viewing: "Viewing requested", skip: "Skipped" };

// A Discord reaction on the alert can set the status too, once the data carries `reactions`.
const REACTION_STATUS = { "❤": "interested", "\u{1F4C5}": "viewing", "❌": "skip" };

// Rijswijk's wijken are numbered by CBS, so give them a hint of what's in them.
const WIJK_HINTS = {
  "Wijk 01": "Cromvliet, Leeuwendaal",
  "Wijk 02": "Oud-Rijswijk e.o.",
  "Wijk 08": "Overvoorde e.o.",
  "Wijk 10": "Sion e.o.",
};

export const DAY_MS = 86_400_000;
// Monthly VvE above this (EUR) is flagged even when the reserve fund and maintenance plan are in order.
export const VVE_HIGH_MONTHLY = 400;

export function defaultFilters() {
  return {
    tab: "triage",
    tiers: ["top", "good", "ok", "pending"],
    q: "",
    maxPrice: "",
    minArea: "",
    minBalcony: "",
    minBeds: "0",
    maxVve: "",
    hideErfpacht: true,
    showGone: false,
    onlyNew: false,
    onlyDrops: false,
    wijkOff: [],
    sort: "score",
    group: "none",
    density: "detailed",
  };
}

export const tierOf = (l) => (l.score ? l.score.tier : "pending");

export function wijkLabel(wijk) {
  if (!wijk) return "Unknown wijk";
  return WIJK_HINTS[wijk] ? `${wijk} (${WIJK_HINTS[wijk]})` : wijk;
}

export function statusOf(l, statuses) {
  if (statuses && statuses[l.id]) return statuses[l.id];
  for (const emoji of l.reactions || []) {
    const mapped = REACTION_STATUS[String(emoji).replace(/️/g, "")];
    if (mapped) return mapped;
  }
  return null;
}

export function tabOf(l, statuses) {
  const status = statusOf(l, statuses);
  if (status === "skip") return "skipped";
  if (status === "interested" || status === "viewing") return "shortlist";
  return "triage";
}

export function daysSince(iso, now) {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return null;
  return Math.max(0, Math.floor((now - then) / DAY_MS));
}

export const pricePerM2 = (l) => (l.price && l.living_area ? Math.round(l.price / l.living_area) : null);
export const balconyM2 = (l) => (l.details && l.details.outdoor_m2) || 0;

// Whether this listing arrived after `lastVisit` (an ISO timestamp, or null on a first visit).
export function isNew(l, lastVisit) {
  return lastVisit !== null && lastVisit !== undefined && new Date(l.first_seen).getTime() > new Date(lastVisit).getTime();
}

// The latest asking-price cut, if the last change was downwards.
export function priceDrop(l) {
  const history = l.price_history || [];
  if (history.length < 2) return null;
  const [since, to] = history[history.length - 1];
  const [, from] = history[history.length - 2];
  if (!(to < from)) return null;
  return { from, to, amount: from - to, pct: Math.round(((from - to) / from) * 100), since };
}

// The five at-a-glance judgements shown as chips. state: good | neutral | unclear | bad
export function criteria(l) {
  const d = l.details;
  if (!d) return [{ key: "pending", state: "unclear", label: "Details pending" }];
  const out = [];

  // 1. Outdoor space
  if (d.balcony) {
    const m2 = d.outdoor_m2;
    out.push({ key: "outdoor", state: m2 === null || m2 < 5 ? "neutral" : "good", label: m2 ? `Balcony ${m2} m²` : "Balcony" });
  } else if (d.garden) {
    out.push({ key: "outdoor", state: "neutral", label: "Garden" });
  } else {
    out.push({ key: "outdoor", state: "neutral", label: "No outdoor space" });
  }

  // 2. Ownership
  if (d.erfpacht) {
    out.push({ key: "ownership", state: "bad", label: d.erfpacht_perpetual ? "Erfpacht, bought off" : "Erfpacht" });
  } else if (d.ownership) {
    out.push({ key: "ownership", state: "good", label: "Freehold" });
  } else {
    out.push({ key: "ownership", state: "unclear", label: "Ownership unclear" });
  }

  // 3. VvE
  if (!d.is_apartment) {
    out.push({ key: "vve", state: "good", label: "House, no VvE" });
  } else {
    const cost = d.vve_monthly ? ` · €${Math.round(d.vve_monthly)}` : "";
    const weak = [];
    if (d.vve_reserve_fund === false) weak.push("no reserve fund");
    if (d.vve_maintenance_plan === false) weak.push("no plan");
    if (d.vve_registered === false) weak.push("not registered");
    if (weak.length) out.push({ key: "vve", state: "bad", label: `VvE ${weak.join(", ")}${cost}` });
    else if (d.vve_reserve_fund === true && d.vve_maintenance_plan === true) {
      // A tidy checklist doesn't make a very high monthly fee fine, so don't tick it.
      const high = d.vve_monthly && d.vve_monthly > VVE_HIGH_MONTHLY;
      out.push(high ? { key: "vve", state: "unclear", label: `VvE high${cost}` } : { key: "vve", state: "good", label: `VvE healthy${cost}` });
    } else out.push({ key: "vve", state: "unclear", label: `VvE unclear${cost}` });
  }

  // 4. Rooms (a second bedroom can be the office, a third is a bonus)
  if (l.bedrooms === null || l.bedrooms === undefined) out.push({ key: "rooms", state: "unclear", label: "Bedrooms unknown" });
  else out.push({ key: "rooms", state: l.bedrooms >= 3 ? "good" : "neutral", label: `${l.bedrooms} bedrooms` });

  // 5. Condition and character
  const prewar = d.year_built && d.year_built < 1940;
  if (d.needs_work) out.push({ key: "condition", state: "bad", label: "Needs work" });
  else if (prewar) out.push({ key: "condition", state: "good", label: `Pre-war ${d.year_built}${d.move_in_ready ? " · ready" : ""}` });
  else if (d.move_in_ready) out.push({ key: "condition", state: "good", label: "Move-in ready" });
  else out.push({ key: "condition", state: "neutral", label: d.year_built ? `Built ${d.year_built}` : "Condition unknown" });

  return out;
}

// Rank of each active, scored listing within its wijk (1 = best). Ties share a rank.
export function wijkRanks(listings) {
  const byWijk = new Map();
  for (const l of listings) {
    if (!l.active || !l.score) continue;
    const key = l.wijk || "";
    if (!byWijk.has(key)) byWijk.set(key, []);
    byWijk.get(key).push(l);
  }
  const ranks = new Map();
  for (const items of byWijk.values()) {
    const sorted = [...items].sort((a, b) => b.score.points - a.score.points);
    sorted.forEach((l, i) => {
      const rank = i > 0 && sorted[i - 1].score.points === l.score.points ? ranks.get(sorted[i - 1].id).rank : i + 1;
      ranks.set(l.id, { rank, of: sorted.length });
    });
  }
  return ranks;
}

// Bars for the "Why N points" panel: width is proportional to the biggest reason.
export function reasonBars(score) {
  if (!score) return [];
  const biggest = Math.max(1, ...score.reasons.map((r) => Math.abs(r.points)));
  return score.reasons.map((r) => ({ text: r.text, points: r.points, width: Math.max(6, Math.round((Math.abs(r.points) / biggest) * 100)) }));
}

// Everything except the tab: the tab counts need to know how many pass the other filters.
export function applyFilters(listings, f, ctx) {
  const query = f.q.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return listings.filter((l) => {
    const d = l.details;
    if (!l.active && !f.showGone) return false;
    if (!f.tiers.includes(tierOf(l))) return false;
    if (f.hideErfpacht && d && d.erfpacht) return false;
    if (f.wijkOff.includes(l.wijk || "")) return false;
    if (f.onlyNew && !isNew(l, ctx.lastVisit)) return false;
    if (f.onlyDrops && !priceDrop(l)) return false;
    if (f.maxPrice !== "" && l.price && l.price > Number(f.maxPrice)) return false;
    if (f.minArea !== "" && (l.living_area || 0) < Number(f.minArea)) return false;
    if (f.minBalcony !== "" && balconyM2(l) < Number(f.minBalcony)) return false;
    if (Number(f.minBeds) && (l.bedrooms || 0) < Number(f.minBeds)) return false;
    if (f.maxVve !== "" && d && d.vve_monthly && d.vve_monthly > Number(f.maxVve)) return false;
    if (query.length) {
      const hay = [l.title, l.wijk, l.neighbourhood, l.city].join(" ").toLowerCase();
      if (!query.every((word) => hay.includes(word))) return false;
    }
    return true;
  });
}

export function countTabs(passing, statuses) {
  const counts = { triage: 0, shortlist: 0, skipped: 0, all: passing.length };
  for (const l of passing) counts[tabOf(l, statuses)] += 1;
  return counts;
}

export function inTab(l, tab, statuses) {
  return tab === "all" || tabOf(l, statuses) === tab;
}

const points = (l) => (l.score ? l.score.points : -1);
const byScore = (a, b) => points(b) - points(a) || (a.price ?? Infinity) - (b.price ?? Infinity) || b.first_seen.localeCompare(a.first_seen);

export const SORTS = {
  score: byScore,
  new: (a, b) => b.first_seen.localeCompare(a.first_seen) || byScore(a, b),
  published: (a, b) => (b.published || "").localeCompare(a.published || "") || byScore(a, b),
  price: (a, b) => (a.price ?? Infinity) - (b.price ?? Infinity) || byScore(a, b),
  ppm2: (a, b) => (pricePerM2(a) ?? Infinity) - (pricePerM2(b) ?? Infinity) || byScore(a, b),
  balcony: (a, b) => balconyM2(b) - balconyM2(a) || byScore(a, b),
  drop: (a, b) => ((priceDrop(b) || { pct: 0 }).pct - (priceDrop(a) || { pct: 0 }).pct) || byScore(a, b),
};

export function sortListings(list, key) {
  return [...list].sort(SORTS[key] || SORTS.score);
}

// Sections for the "group by" option. Each has a key, a label and its items in order.
export function groupListings(list, key, statuses) {
  if (key === "none") return [{ key: "all", label: "", items: list }];
  const groups = new Map();
  const add = (k, label, l) => {
    if (!groups.has(k)) groups.set(k, { key: k, label, items: [] });
    groups.get(k).items.push(l);
  };
  for (const l of list) {
    if (key === "wijk") add(l.wijk || "", wijkLabel(l.wijk), l);
    else if (key === "city") add(l.city || "", l.city || "Unknown city", l);
    else if (key === "tier") add(tierOf(l), `${TIER_LABEL[tierOf(l)]} matches`, l);
    else if (key === "status") {
      const s = statusOf(l, statuses);
      add(s || "none", s ? STATUS_LABEL[s] : "No status yet", l);
    }
  }
  const result = [...groups.values()];
  if (key === "tier") result.sort((a, b) => TIERS.indexOf(a.key) - TIERS.indexOf(b.key));
  else if (key === "wijk" || key === "city") result.sort((a, b) => Math.max(...b.items.map(points)) - Math.max(...a.items.map(points)));
  return result;
}

export function euro(value) {
  return value === null || value === undefined ? "" : `€${Math.round(value).toLocaleString("nl-NL")}`;
}

export function euroShort(value) {
  if (value === null || value === undefined) return "";
  return value >= 1000 ? `€${Math.round(value / 1000)}k` : euro(value);
}

// The removable chips under the toolbar, one per filter that differs from its default.
export function activeFilters(f) {
  const base = defaultFilters();
  const chips = [];
  if (f.hideErfpacht) chips.push({ id: "hideErfpacht", label: "Erfpacht hidden" });
  for (const t of TIERS) if (base.tiers.includes(t) && !f.tiers.includes(t)) chips.push({ id: `tier:${t}`, label: `${TIER_LABEL[t]} hidden` });
  for (const t of TIERS) if (!base.tiers.includes(t) && f.tiers.includes(t)) chips.push({ id: `tier:${t}`, label: `${TIER_LABEL[t]} shown` });
  if (f.q.trim()) chips.push({ id: "q", label: `“${f.q.trim()}”` });
  if (f.maxPrice !== "") chips.push({ id: "maxPrice", label: `Max ${euro(Number(f.maxPrice))}` });
  if (f.minArea !== "") chips.push({ id: "minArea", label: `Min ${f.minArea} m²` });
  if (f.minBalcony !== "") chips.push({ id: "minBalcony", label: `Balcony ≥ ${f.minBalcony} m²` });
  if (Number(f.minBeds)) chips.push({ id: "minBeds", label: `${f.minBeds}+ bedrooms` });
  if (f.maxVve !== "") chips.push({ id: "maxVve", label: `VvE ≤ ${euro(Number(f.maxVve))}` });
  if (f.showGone) chips.push({ id: "showGone", label: "Including no longer matching" });
  if (f.wijkOff.length) chips.push({ id: "wijkOff", label: `${f.wijkOff.length} wijk${f.wijkOff.length === 1 ? "" : "en"} hidden` });
  return chips;
}

// The filters with one chip's condition undone.
export function removeFilter(f, id) {
  const base = defaultFilters();
  const next = { ...f };
  if (id === "hideErfpacht") next.hideErfpacht = false;
  else if (id.startsWith("tier:")) {
    const tier = id.slice(5);
    next.tiers = f.tiers.includes(tier) ? f.tiers.filter((t) => t !== tier) : [...f.tiers, tier];
  } else if (id === "wijkOff") next.wijkOff = [];
  else if (id === "showGone") next.showGone = false;
  else if (id in base) next[id] = base[id];
  return next;
}
