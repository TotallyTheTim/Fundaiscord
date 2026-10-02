import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from factories import NOW, make_candidate, make_details

from scoring import Assessment, Score, ScoringConfig, Weights
from store import KEEP_INACTIVE_DAYS, ListingStore


def new_store(tmp_path: Path) -> ListingStore:
    return ListingStore.load(tmp_path / "docs" / "listings.json")


def assessment(points: int = 60, tier: str = "good", **detail_overrides: object) -> Assessment:
    return Assessment(make_details(**detail_overrides), Score(points, tier, ()))


def test_a_missing_file_gives_an_empty_store(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    assert len(store) == 0 and store.all() == []


def test_upsert_creates_a_record_from_the_candidate(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    store.upsert(make_candidate(id="7", price=350_000), "Leyenburg", NOW)

    r = store.get("7")
    assert r.title == "Teststraat 1" and r.wijk == "Leyenburg" and r.price == 350_000
    assert r.active and r.details is None and r.score is None
    assert r.first_seen == NOW.isoformat(timespec="seconds")
    assert r.last_seen == NOW.date().isoformat()
    assert r.price_history == [[NOW.date().isoformat(), 350_000]]


def test_upserting_again_keeps_first_seen_and_details(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    store.upsert(make_candidate(id="7"), None, NOW)
    store.set_assessment("7", assessment(80, "top"))
    store.upsert(make_candidate(id="7", title="Renamed"), "Leyenburg", NOW + timedelta(days=2))

    r = store.get("7")
    assert r.first_seen == NOW.isoformat(timespec="seconds")
    assert r.last_seen == (NOW + timedelta(days=2)).date().isoformat()
    assert r.title == "Renamed" and r.wijk == "Leyenburg"
    assert r.details is not None and r.score is not None and r.score.points == 80


def test_a_price_change_is_added_to_the_history_once(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    store.upsert(make_candidate(id="7", price=360_000), None, NOW)
    store.upsert(make_candidate(id="7", price=350_000), None, NOW + timedelta(days=1))
    store.upsert(make_candidate(id="7", price=350_000), None, NOW + timedelta(days=2))

    assert [p for _, p in store.get("7").price_history] == [360_000, 350_000]
    assert store.get("7").price == 350_000


def test_a_listing_that_returns_becomes_active_again(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    store.upsert(make_candidate(id="7"), None, NOW)
    store.deactivate_missing(set(), NOW + timedelta(days=1))
    assert not store.get("7").active

    store.upsert(make_candidate(id="7"), None, NOW + timedelta(days=3))
    r = store.get("7")
    assert r.active and r.inactive_since is None


def test_deactivate_missing_only_touches_listings_not_seen(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    for listing_id in ("a", "b", "c"):
        store.upsert(make_candidate(id=listing_id), None, NOW)
    count = store.deactivate_missing({"a", "c"}, NOW + timedelta(days=1))

    assert count == 1
    assert store.get("a").active and store.get("c").active and not store.get("b").active
    assert store.get("b").inactive_since == (NOW + timedelta(days=1)).date().isoformat()


def test_needing_details_lists_active_unenriched_listings_newest_first(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    store.upsert(make_candidate(id="old", published=NOW - timedelta(days=9)), None, NOW)
    store.upsert(make_candidate(id="new", published=NOW - timedelta(hours=2)), None, NOW)
    store.upsert(make_candidate(id="done", published=NOW), None, NOW)
    store.upsert(make_candidate(id="gone", published=NOW), None, NOW)
    store.set_assessment("done", assessment())
    store.deactivate_missing({"old", "new", "done"}, NOW)

    assert store.needing_details(10) == ["new", "old"]
    assert store.needing_details(1) == ["new"]


def test_candidate_of_rebuilds_the_candidate(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    original = make_candidate(id="7", price=345_000, bedrooms=3, energy_label="A")
    store.upsert(original, "Leyenburg", NOW)

    assert store.candidate_of("7") == original


def test_rescore_uses_stored_details_and_the_current_weights(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    # price pinned at the scoring default's price/m² reference, so it contributes no bonus/penalty
    store.upsert(make_candidate(id="7", bedrooms=2, energy_label="C", price=4157 * 80), None, NOW)
    store.set_assessment("7", assessment(50, "ok", garden=True))
    store.upsert(make_candidate(id="8"), None, NOW)  # no details yet

    store.rescore(ScoringConfig(weights=Weights(garden=30)))

    rescored = store.get("7").score
    assert rescored is not None and rescored.points == 80
    assert store.get("8").score is None


def test_prune_drops_long_gone_listings_but_keeps_recent_and_active_ones(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    for listing_id in ("active", "recent", "ancient"):
        store.upsert(make_candidate(id=listing_id), None, NOW)
    store.deactivate_missing({"active"}, NOW - timedelta(days=KEEP_INACTIVE_DAYS + 5))
    store.get("recent").inactive_since = (NOW - timedelta(days=10)).date().isoformat()
    store.prune(NOW)

    assert "active" in store and "recent" in store and "ancient" not in store


def test_save_and_reload_round_trip_including_details_and_score(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    store.upsert(make_candidate(id="7"), "Leyenburg", NOW)
    store.set_assessment("7", assessment(84, "top", balcony=True, outdoor_m2=10, erfpacht=False))
    assert store.save(NOW)

    reloaded = new_store(tmp_path)
    r = reloaded.get("7")
    assert r.wijk == "Leyenburg"
    assert r.details == make_details(balcony=True, outdoor_m2=10)
    assert r.score is not None and r.score.points == 84 and r.score.tier == "top"


def test_save_writes_nothing_when_nothing_changed(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    store.upsert(make_candidate(id="7"), None, NOW)
    assert store.save(NOW)
    path = tmp_path / "docs" / "listings.json"
    first = path.read_text(encoding="utf-8")

    reloaded = new_store(tmp_path)
    assert not reloaded.save(NOW + timedelta(hours=5))
    assert path.read_text(encoding="utf-8") == first  # not even the timestamp moved


def test_an_empty_store_never_creates_a_file(tmp_path: Path) -> None:
    assert not new_store(tmp_path).save(NOW)
    assert not (tmp_path / "docs" / "listings.json").exists()


def test_saving_the_same_content_again_after_a_change_writes_again_only_once(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    store.upsert(make_candidate(id="7", price=360_000), None, NOW)
    assert store.save(NOW)
    store.upsert(make_candidate(id="7", price=350_000), None, NOW)
    assert store.save(NOW)
    assert not store.save(NOW)


def test_the_file_is_sorted_by_id_for_stable_diffs(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    for listing_id in ("9", "10", "2"):
        store.upsert(make_candidate(id=listing_id), None, NOW)
    store.save(NOW)

    written = json.loads((tmp_path / "docs" / "listings.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in written["listings"]] == ["10", "2", "9"]
    assert written["generated"] == NOW.isoformat(timespec="seconds")


def test_a_record_with_an_unreadable_details_shape_is_reloaded_without_details(tmp_path: Path) -> None:
    path = tmp_path / "docs" / "listings.json"
    path.parent.mkdir(parents=True)
    store = new_store(tmp_path)
    store.upsert(make_candidate(id="7"), None, NOW)
    store.set_assessment("7", assessment())
    store.save(NOW)

    data = json.loads(path.read_text(encoding="utf-8"))
    del data["listings"][0]["details"]["erfpacht"]  # a field the current code requires
    path.write_text(json.dumps(data), encoding="utf-8")

    r = new_store(tmp_path).get("7")
    assert r.details is None and r.score is None  # dropped so the backfill fetches it again


def test_unknown_extra_fields_in_the_file_are_ignored(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    store.upsert(make_candidate(id="7"), None, NOW)
    store.set_assessment("7", assessment())
    store.save(NOW)

    path = tmp_path / "docs" / "listings.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["listings"][0]["from_the_future"] = 1
    data["listings"][0]["details"]["also_new"] = 2
    path.write_text(json.dumps(data), encoding="utf-8")

    assert new_store(tmp_path).get("7").details is not None


def test_naive_and_aware_published_timestamps_survive_a_round_trip(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    published = datetime(2026, 9, 19, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    store.upsert(make_candidate(id="7", published=published), None, NOW)
    store.save(NOW)

    assert new_store(tmp_path).candidate_of("7").published == published


def test_a_listing_whose_details_keep_failing_is_eventually_left_alone(tmp_path: Path) -> None:
    from store import MAX_DETAIL_ATTEMPTS

    store = new_store(tmp_path)
    store.upsert(make_candidate(id="broken", published=NOW), None, NOW)
    store.upsert(make_candidate(id="fine", published=NOW - timedelta(days=3)), None, NOW)

    for _ in range(MAX_DETAIL_ATTEMPTS):
        store.record_details_failure("broken")

    assert store.needing_details(10) == ["fine"]


def test_failed_listings_wait_behind_ones_that_have_not_failed(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    store.upsert(make_candidate(id="failed_once", published=NOW), None, NOW)
    store.upsert(make_candidate(id="untried", published=NOW - timedelta(days=5)), None, NOW)
    store.record_details_failure("failed_once")

    assert store.needing_details(10) == ["untried", "failed_once"]


def test_a_successful_fetch_clears_the_failure_count(tmp_path: Path) -> None:
    store = new_store(tmp_path)
    store.upsert(make_candidate(id="7"), None, NOW)
    store.record_details_failure("7")
    store.set_assessment("7", assessment())

    assert store.get("7").details_failures == 0
