import assert from "node:assert/strict";
import { test } from "node:test";
import * as L from "../../docs/logic.js";

const NOW = new Date("2026-09-28T12:00:00Z").getTime();

function details(over = {}) {
  return {
    ownership: "Volle eigendom", erfpacht: false, erfpacht_perpetual: false, is_apartment: true, floor: 2,
    floor_label: "2e woonlaag", year_built: 1965, balcony: false, outdoor_m2: null, garden: false, lift: false,
    vve_monthly: null, vve_reserve_fund: null, vve_maintenance_plan: null, vve_registered: null, busy_road: false,
    monument: false, needs_work: false, move_in_ready: false, top_floor_hint: false, latitude: 52.06, longitude: 4.27,
    ...over,
  };
}

let counter = 0;
function listing(over = {}, det = undefined, score = undefined) {
  counter += 1;
  return {
    id: String(counter), title: `Straat ${counter}`, city: "Den Haag", wijk: "Leyenburg", neighbourhood: "Leyenburg",
    url: "https://www.funda.nl/x", price: 300000, living_area: 80, bedrooms: 2, energy_label: "B",
    published: "2026-09-20T00:00:00+02:00", first_seen: "2026-09-27T10:00:00+00:00", last_seen: "2026-09-28",
    active: true, inactive_since: null, price_history: [["2026-09-27", 300000]], photo_url: null, search_name: "Den Haag",
    details: det === undefined ? details() : det,
    score: score === undefined ? { points: 60, tier: "good", reasons: [{ points: 10, text: "a" }] } : score,
    ...over,
  };
}
const ctx = (over = {}) => ({ statuses: {}, lastVisit: null, now: NOW, ...over });

test("tierOf treats a listing without a score as pending", () => {
  assert.equal(L.tierOf(listing({}, undefined, null)), "pending");
  assert.equal(L.tierOf(listing({}, undefined, { points: 80, tier: "top", reasons: [] })), "top");
});

test("statusOf prefers the local status and falls back to Discord reactions", () => {
  const l = listing({ reactions: ["❤️"] });
  assert.equal(L.statusOf(l, {}), "interested");
  assert.equal(L.statusOf(l, { [l.id]: "skip" }), "skip");
  assert.equal(L.statusOf(listing({ reactions: ["\u{1F4C5}"] }), {}), "viewing");
  assert.equal(L.statusOf(listing({ reactions: ["❌"] }), {}), "skip");
  assert.equal(L.statusOf(listing({ reactions: ["🎉"] }), {}), null);
  assert.equal(L.statusOf(listing(), {}), null);
});

test("the variation selector on a reaction emoji is ignored", () => {
  assert.equal(L.statusOf(listing({ reactions: ["❤️"] }), {}), "interested");
  assert.equal(L.statusOf(listing({ reactions: ["❤"] }), {}), "interested");
});

test("tabOf puts skipped and shortlisted listings where they belong", () => {
  const a = listing(), b = listing(), c = listing();
  const statuses = { [b.id]: "interested", [c.id]: "skip" };
  assert.deepEqual([a, b, c].map((l) => L.tabOf(l, statuses)), ["triage", "shortlist", "skipped"]);
  assert.equal(L.tabOf(listing(), { x: "viewing" }), "triage");
  const v = listing();
  assert.equal(L.tabOf(v, { [v.id]: "viewing" }), "shortlist");
});

test("daysSince counts whole days and handles bad input", () => {
  assert.equal(L.daysSince("2026-09-25T12:00:00Z", NOW), 3);
  assert.equal(L.daysSince("2026-09-28T11:00:00Z", NOW), 0);
  assert.equal(L.daysSince("2027-01-01T00:00:00Z", NOW), 0);
  assert.equal(L.daysSince(null, NOW), null);
  assert.equal(L.daysSince("nonsense", NOW), null);
});

test("pricePerM2 needs both a price and an area", () => {
  assert.equal(L.pricePerM2(listing({ price: 300000, living_area: 80 })), 3750);
  assert.equal(L.pricePerM2(listing({ price: null })), null);
  assert.equal(L.pricePerM2(listing({ living_area: 0 })), null);
});

test("isNew compares first_seen with the last visit and never flags a first visit", () => {
  const l = listing({ first_seen: "2026-09-28T10:00:00+00:00" });
  assert.equal(L.isNew(l, null), false);
  assert.equal(L.isNew(l, "2026-09-28T09:00:00Z"), true);
  assert.equal(L.isNew(l, "2026-09-28T11:00:00Z"), false);
});

test("priceDrop reports only a downward last change", () => {
  const drop = listing({ price_history: [["2026-09-01", 360000], ["2026-09-20", 350000]] });
  assert.deepEqual(L.priceDrop(drop), { from: 360000, to: 350000, amount: 10000, pct: 3, since: "2026-09-20" });
  assert.equal(L.priceDrop(listing({ price_history: [["2026-09-01", 350000], ["2026-09-20", 360000]] })), null);
  assert.equal(L.priceDrop(listing({ price_history: [["2026-09-01", 350000]] })), null);
  assert.equal(L.priceDrop(listing({ price_history: [] })), null);
  assert.equal(L.priceDrop(listing({ price_history: undefined })), null);
});

test("priceDrop looks at the last change only, so a rise after a drop is not a drop", () => {
  const l = listing({ price_history: [["a", 360000], ["b", 350000], ["c", 355000]] });
  assert.equal(L.priceDrop(l), null);
});

test("criteria for a listing without details is one pending chip", () => {
  assert.deepEqual(L.criteria(listing({}, null, null)), [{ key: "pending", state: "unclear", label: "Details pending" }]);
});

test("criteria: outdoor space states", () => {
  const outdoor = (d) => L.criteria(listing({}, details(d)))[0];
  assert.deepEqual(outdoor({ balcony: true, outdoor_m2: 12 }), { key: "outdoor", state: "good", label: "Balcony 12 m²" });
  assert.equal(outdoor({ balcony: true, outdoor_m2: 3 }).state, "neutral");
  assert.equal(outdoor({ balcony: true, outdoor_m2: null }).label, "Balcony");
  assert.equal(outdoor({ garden: true }).label, "Garden");
  assert.equal(outdoor({}).label, "No outdoor space");
});

test("criteria: ownership states", () => {
  const own = (d) => L.criteria(listing({}, details(d)))[1];
  assert.deepEqual(own({}), { key: "ownership", state: "good", label: "Freehold" });
  assert.deepEqual(own({ erfpacht: true }), { key: "ownership", state: "bad", label: "Erfpacht" });
  assert.equal(own({ erfpacht: true, erfpacht_perpetual: true }).label, "Erfpacht, bought off");
  assert.equal(own({ ownership: null }).state, "unclear");
});

test("criteria: a house has no VvE, an apartment is judged on its checklist", () => {
  const vve = (d) => L.criteria(listing({}, details(d)))[2];
  assert.deepEqual(vve({ is_apartment: false }), { key: "vve", state: "good", label: "House, no VvE" });
  assert.deepEqual(vve({ vve_reserve_fund: true, vve_maintenance_plan: true, vve_monthly: 200 }), { key: "vve", state: "good", label: "VvE healthy · €200" });
  assert.deepEqual(vve({ vve_reserve_fund: true, vve_maintenance_plan: null, vve_monthly: 137 }), { key: "vve", state: "unclear", label: "VvE unclear · €137" });
  assert.deepEqual(vve({ vve_reserve_fund: false, vve_maintenance_plan: false, vve_monthly: 90 }), { key: "vve", state: "bad", label: "VvE no reserve fund, no plan · €90" });
  assert.equal(vve({ vve_registered: false }).label, "VvE not registered");
  assert.equal(vve({ vve_reserve_fund: true, vve_maintenance_plan: true }).label, "VvE healthy");
});

test("criteria: a healthy checklist with a very high monthly fee is flagged, not ticked", () => {
  const vve = (d) => L.criteria(listing({}, details(d)))[2];
  const ok = { vve_reserve_fund: true, vve_maintenance_plan: true };
  assert.deepEqual(vve({ ...ok, vve_monthly: 631 }), { key: "vve", state: "unclear", label: "VvE high · €631" });
  assert.equal(vve({ ...ok, vve_monthly: L.VVE_HIGH_MONTHLY }).state, "good");
  assert.equal(vve({ ...ok, vve_monthly: L.VVE_HIGH_MONTHLY + 1 }).state, "unclear");
  // a weak checklist stays "bad" whatever the fee
  assert.equal(vve({ vve_reserve_fund: false, vve_maintenance_plan: true, vve_monthly: 631 }).state, "bad");
});

test("criteria: bedrooms", () => {
  const rooms = (b) => L.criteria(listing({ bedrooms: b }))[3];
  assert.deepEqual(rooms(3), { key: "rooms", state: "good", label: "3 bedrooms" });
  assert.equal(rooms(2).state, "neutral");
  assert.equal(rooms(null).state, "unclear");
});

test("criteria: condition and character", () => {
  const cond = (d) => L.criteria(listing({}, details(d)))[4];
  assert.deepEqual(cond({ needs_work: true, year_built: 1920 }), { key: "condition", state: "bad", label: "Needs work" });
  assert.deepEqual(cond({ year_built: 1898, move_in_ready: true }), { key: "condition", state: "good", label: "Pre-war 1898 · ready" });
  assert.equal(cond({ year_built: 1923 }).label, "Pre-war 1923");
  assert.equal(cond({ move_in_ready: true }).label, "Move-in ready");
  assert.deepEqual(cond({ year_built: 2003 }), { key: "condition", state: "neutral", label: "Built 2003" });
  assert.equal(cond({ year_built: null }).label, "Condition unknown");
});

test("criteria always yields the five chips for a listing with details", () => {
  assert.deepEqual(L.criteria(listing()).map((c) => c.key), ["outdoor", "ownership", "vve", "rooms", "condition"]);
});

test("wijkRanks ranks within a wijk, shares ties, and skips inactive or unscored listings", () => {
  const a = listing({ wijk: "X" }, undefined, { points: 80, tier: "top", reasons: [] });
  const b = listing({ wijk: "X" }, undefined, { points: 70, tier: "top", reasons: [] });
  const c = listing({ wijk: "X" }, undefined, { points: 70, tier: "top", reasons: [] });
  const d = listing({ wijk: "X" }, undefined, { points: 50, tier: "ok", reasons: [] });
  const gone = listing({ wijk: "X", active: false }, undefined, { points: 99, tier: "top", reasons: [] });
  const unscored = listing({ wijk: "X" }, null, null);
  const other = listing({ wijk: "Y" }, undefined, { points: 10, tier: "low", reasons: [] });
  const ranks = L.wijkRanks([a, b, c, d, gone, unscored, other]);
  assert.deepEqual(ranks.get(a.id), { rank: 1, of: 4 });
  assert.deepEqual(ranks.get(b.id), { rank: 2, of: 4 });
  assert.deepEqual(ranks.get(c.id), { rank: 2, of: 4 });
  assert.deepEqual(ranks.get(d.id), { rank: 4, of: 4 });
  assert.equal(ranks.has(gone.id), false);
  assert.equal(ranks.has(unscored.id), false);
  assert.deepEqual(ranks.get(other.id), { rank: 1, of: 1 });
});

test("reasonBars scales to the biggest reason and keeps tiny ones visible", () => {
  const bars = L.reasonBars({ points: 60, tier: "good", reasons: [{ points: 15, text: "a" }, { points: -6, text: "b" }, { points: 1, text: "c" }] });
  assert.deepEqual(bars.map((b) => b.width), [100, 40, 7]);
  assert.deepEqual(L.reasonBars(null), []);
  assert.deepEqual(L.reasonBars({ points: 50, tier: "ok", reasons: [] }), []);
});

test("applyFilters hides gone listings unless asked", () => {
  const live = listing(), gone = listing({ active: false });
  assert.deepEqual(L.applyFilters([live, gone], L.defaultFilters(), ctx()), [live]);
  assert.equal(L.applyFilters([live, gone], { ...L.defaultFilters(), showGone: true }, ctx()).length, 2);
});

test("applyFilters hides erfpacht by default but not listings without details", () => {
  const erf = listing({}, details({ erfpacht: true })), pending = listing({}, null, null), fine = listing();
  const shown = L.applyFilters([erf, pending, fine], L.defaultFilters(), ctx());
  assert.deepEqual(shown.map((l) => l.id), [pending.id, fine.id]);
  const all = L.applyFilters([erf, fine], { ...L.defaultFilters(), hideErfpacht: false }, ctx());
  assert.equal(all.length, 2);
});

test("applyFilters applies the tier chips (low is hidden by default)", () => {
  const low = listing({}, undefined, { points: 20, tier: "low", reasons: [] });
  const top = listing({}, undefined, { points: 90, tier: "top", reasons: [] });
  assert.deepEqual(L.applyFilters([low, top], L.defaultFilters(), ctx()), [top]);
  assert.equal(L.applyFilters([low, top], { ...L.defaultFilters(), tiers: [...L.TIERS] }, ctx()).length, 2);
});

test("applyFilters: numeric limits", () => {
  const f = (over) => ({ ...L.defaultFilters(), ...over });
  const a = listing({ price: 250000, living_area: 90, bedrooms: 3 }, details({ balcony: true, outdoor_m2: 10, vve_monthly: 150 }));
  const b = listing({ price: 390000, living_area: 76, bedrooms: 2 }, details({ vve_monthly: 320 }));
  const ids = (over) => L.applyFilters([a, b], f(over), ctx()).map((l) => l.id);
  assert.deepEqual(ids({ maxPrice: "300000" }), [a.id]);
  assert.deepEqual(ids({ minArea: "80" }), [a.id]);
  assert.deepEqual(ids({ minBalcony: "5" }), [a.id]);
  assert.deepEqual(ids({ minBeds: "3" }), [a.id]);
  assert.deepEqual(ids({ maxVve: "200" }), [a.id]);
  assert.deepEqual(ids({}), [a.id, b.id]);
});

test("applyFilters: a VvE limit does not exclude houses or unknown costs", () => {
  const house = listing({}, details({ is_apartment: false, vve_monthly: null }));
  const pending = listing({}, null, null);
  assert.equal(L.applyFilters([house, pending], { ...L.defaultFilters(), maxVve: "100" }, ctx()).length, 2);
});

test("applyFilters: text search matches every word across title, wijk, buurt and city", () => {
  const a = listing({ title: "Regentesselaan 38", wijk: "Regentessekwartier", neighbourhood: "Rond de Energiecentrale" });
  const b = listing({ title: "Hugo de Grootstraat 229", city: "Delft", wijk: "Hof van Delft" });
  const f = (q) => L.applyFilters([a, b], { ...L.defaultFilters(), q }, ctx()).map((l) => l.id);
  assert.deepEqual(f("regentes"), [a.id]);
  assert.deepEqual(f("delft hugo"), [b.id]);
  assert.deepEqual(f("energie den haag"), [a.id]);
  assert.deepEqual(f("nothing like this"), []);
  assert.deepEqual(f("   "), [a.id, b.id]);
});

test("applyFilters: only new and only price drops", () => {
  const fresh = listing({ first_seen: "2026-09-28T10:00:00+00:00" });
  const old = listing({ first_seen: "2026-09-01T10:00:00+00:00" });
  const dropped = listing({ price_history: [["a", 360000], ["b", 350000]] });
  const f = (over, c) => L.applyFilters([fresh, old, dropped], { ...L.defaultFilters(), ...over }, ctx(c)).map((l) => l.id);
  // `dropped` keeps listing()'s default first_seen of 2026-09-27, which is also after the last visit.
  assert.deepEqual(f({ onlyNew: true }, { lastVisit: "2026-09-20T00:00:00Z" }), [fresh.id, dropped.id]);
  assert.deepEqual(f({ onlyDrops: true }), [dropped.id]);
});

test("applyFilters: hidden wijken", () => {
  const a = listing({ wijk: "A" }), b = listing({ wijk: "B" }), none = listing({ wijk: null });
  const shown = L.applyFilters([a, b, none], { ...L.defaultFilters(), wijkOff: ["B", ""] }, ctx());
  assert.deepEqual(shown.map((l) => l.id), [a.id]);
});

test("countTabs counts the listings that pass the filters per tab", () => {
  const a = listing(), b = listing(), c = listing(), d = listing();
  const counts = L.countTabs([a, b, c, d], { [b.id]: "interested", [c.id]: "viewing", [d.id]: "skip" });
  assert.deepEqual(counts, { triage: 1, shortlist: 2, skipped: 1, all: 4 });
});

test("inTab", () => {
  const a = listing();
  assert.equal(L.inTab(a, "all", { [a.id]: "skip" }), true);
  assert.equal(L.inTab(a, "triage", { [a.id]: "skip" }), false);
  assert.equal(L.inTab(a, "skipped", { [a.id]: "skip" }), true);
});

test("sortListings: score (ties broken by cheaper price) and it does not mutate the input", () => {
  const a = listing({ price: 300000 }, undefined, { points: 70, tier: "top", reasons: [] });
  const b = listing({ price: 250000 }, undefined, { points: 70, tier: "top", reasons: [] });
  const c = listing({}, undefined, { points: 90, tier: "top", reasons: [] });
  const pending = listing({}, null, null);
  const input = [pending, a, b, c];
  const sorted = L.sortListings(input, "score");
  assert.deepEqual(sorted.map((l) => l.id), [c.id, b.id, a.id, pending.id]);
  assert.deepEqual(input.map((l) => l.id), [pending.id, a.id, b.id, c.id]);
});

test("sortListings: price, price per m2, balcony, newest and price drop", () => {
  const cheap = listing({ price: 200000, living_area: 100, first_seen: "2026-09-01T00:00:00+00:00" });
  const dear = listing({ price: 400000, living_area: 100, first_seen: "2026-09-28T00:00:00+00:00", price_history: [["a", 420000], ["b", 400000]] }, details({ balcony: true, outdoor_m2: 12 }));
  const noPrice = listing({ price: null });
  const ids = (key) => L.sortListings([dear, noPrice, cheap], key).map((l) => l.id);
  assert.deepEqual(ids("price"), [cheap.id, dear.id, noPrice.id]);
  assert.deepEqual(ids("ppm2"), [cheap.id, dear.id, noPrice.id]);
  assert.equal(ids("balcony")[0], dear.id);
  assert.equal(ids("new")[0], dear.id);
  assert.equal(ids("drop")[0], dear.id);
  assert.equal(L.sortListings([dear, cheap], "unknown-key").length, 2);
});

test("groupListings: none gives one unlabeled group", () => {
  const list = [listing(), listing()];
  const groups = L.groupListings(list, "none", {});
  assert.equal(groups.length, 1);
  assert.equal(groups[0].label, "");
  assert.equal(groups[0].items.length, 2);
});

test("groupListings: by tier follows the tier order, by wijk puts the best group first", () => {
  const top = listing({ wijk: "A" }, undefined, { points: 90, tier: "top", reasons: [] });
  const ok = listing({ wijk: "B" }, undefined, { points: 45, tier: "ok", reasons: [] });
  const good = listing({ wijk: "B" }, undefined, { points: 60, tier: "good", reasons: [] });
  assert.deepEqual(L.groupListings([ok, top, good], "tier", {}).map((g) => g.key), ["top", "good", "ok"]);
  const byWijk = L.groupListings([ok, top, good], "wijk", {});
  assert.deepEqual(byWijk.map((g) => g.key), ["A", "B"]);
  assert.equal(byWijk[1].items.length, 2);
});

test("groupListings: by status and city", () => {
  const a = listing({ city: "Delft" }), b = listing({ city: "Den Haag" });
  const byStatus = L.groupListings([a, b], "status", { [a.id]: "interested" });
  assert.deepEqual(byStatus.map((g) => g.label).sort(), ["Interested", "No status yet"]);
  assert.equal(L.groupListings([a, b], "city", {}).length, 2);
});

test("wijkLabel adds a hint to Rijswijk's numbered wijken and leaves names alone", () => {
  assert.equal(L.wijkLabel("Wijk 02"), "Wijk 02 (Oud-Rijswijk e.o.)");
  assert.equal(L.wijkLabel("Leyenburg"), "Leyenburg");
  assert.equal(L.wijkLabel(null), "Unknown wijk");
});

test("photoUrl asks Funda's CDN for a resized copy and keeps other hosts untouched", () => {
  assert.equal(L.photoUrl("https://cloud.funda.nl/valentina_media/220/365/221.jpg", 400), "https://cloud.funda.nl/valentina_media/220/365/221.jpg?options=width=400");
  assert.equal(L.photoUrl("https://cloud.funda.nl/tiara-media/a/b", 800), "https://cloud.funda.nl/tiara-media/a/b?options=width=800");
  assert.equal(L.photoUrl("https://cloud.funda.nl/tiara-media/a/b?options=width=999", 400), "https://cloud.funda.nl/tiara-media/a/b?options=width=400", "an existing query is replaced, not stacked");
  assert.equal(L.photoUrl("https://example.com/x.jpg", 400), "https://example.com/x.jpg");
});

test("photoUrl refuses anything that isn't an https URL", () => {
  for (const bad of [null, undefined, "", "http://cloud.funda.nl/x", "javascript:alert(1)", 42]) assert.equal(L.photoUrl(bad, 400), null, String(bad));
});

test("timeAgo", () => {
  const ago = (ms) => L.timeAgo(new Date(NOW - ms).toISOString(), NOW);
  assert.equal(ago(30_000), "just now");
  assert.equal(ago(10 * 60_000), "10 min ago");
  assert.equal(ago(3 * 3_600_000), "3 h ago");
  assert.equal(ago(3 * 86_400_000), "3 days ago");
  assert.equal(L.timeAgo("nonsense", NOW), null);
  assert.equal(L.timeAgo(new Date(NOW + 5 * 60_000).toISOString(), NOW), "just now", "a clock a little ahead is not a negative age");
});

test("describeFreshness separates the last check from the last change", () => {
  const iso = (ms) => new Date(NOW - ms).toISOString();
  assert.equal(L.describeFreshness(iso(3 * 3_600_000), iso(12 * 60_000), NOW), "Checked 12 min ago · list changed 3 h ago");
  assert.equal(L.describeFreshness(iso(3 * 3_600_000), null, NOW), "List changed 3 h ago");
  assert.equal(L.describeFreshness(null, iso(60_000), NOW), "Checked just now");
  assert.equal(L.describeFreshness(null, null, NOW), "");
});

test("euro formatting", () => {
  assert.equal(L.euroShort(401000), "€401k");
  assert.equal(L.euroShort(950), "€950");
  assert.equal(L.euroShort(null), "");
  assert.match(L.euro(376500), /^€376[., ]?500$/);
  assert.equal(L.euro(undefined), "");
});

test("activeFilters lists what differs from the defaults, and removing a chip undoes it", () => {
  assert.deepEqual(L.activeFilters(L.defaultFilters()).map((c) => c.id), ["hideErfpacht"]);
  const f = { ...L.defaultFilters(), q: "delft", maxPrice: "300000", minBeds: "3", tiers: ["top", "good", "low"], wijkOff: ["A"], showGone: true };
  const ids = L.activeFilters(f).map((c) => c.id);
  for (const id of ["hideErfpacht", "q", "maxPrice", "minBeds", "tier:ok", "tier:pending", "tier:low", "wijkOff", "showGone"]) assert.ok(ids.includes(id), id);
  let g = f;
  for (const id of ids) g = L.removeFilter(g, id);
  assert.equal(g.q, ""); assert.equal(g.maxPrice, ""); assert.equal(g.minBeds, "0");
  assert.equal(g.hideErfpacht, false); assert.deepEqual(g.wijkOff, []); assert.equal(g.showGone, false);
  assert.deepEqual([...g.tiers].sort(), [...L.defaultFilters().tiers].sort());
});

test("removeFilter on a hidden tier shows it again, and on a shown tier hides it", () => {
  const hidden = L.removeFilter({ ...L.defaultFilters(), tiers: ["top"] }, "tier:good");
  assert.ok(hidden.tiers.includes("good"));
  const shown = L.removeFilter(L.defaultFilters(), "tier:top");
  assert.ok(!shown.tiers.includes("top"));
});
