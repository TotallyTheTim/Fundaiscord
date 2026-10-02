from datetime import timedelta
from pathlib import Path

import pytest
from factories import FILTERS, NOW, make_candidate, make_details

from config import Config, SearchConfig
from discord import DiscordError
from funda_client import SearchResult
from main import MAX_NOTIFICATIONS_PER_RUN, Fetcher, Match, Notifier, RunResult, run
from models import Candidate
from scoring import Assessment, Score
from state import SeenState
from store import ListingStore
from wijken import WijkMap

WIJKEN = WijkMap({"den-haag": {"Leyenburg": ["Leyenburg"], "Centrum": ["Centrum"]}})
OLD = NOW - timedelta(days=10)


def config_with(*searches: SearchConfig, notify_existing: bool = True) -> Config:
    return Config(
        notify_existing=notify_existing,
        old_listing_after_days=3,
        full_sweep_every_hours=12,
        filters=FILTERS,
        searches=searches,
    )


def search(name: str = "Den Haag", wijken: frozenset[str] = frozenset({"Leyenburg"})) -> SearchConfig:
    return SearchConfig(name=name, location="den-haag", wijken=wijken)


def baselined_state(tmp_path: Path, sweep_age_hours: int = 1) -> SeenState:
    """A state past its first run and recently swept, i.e. an ordinary quick run."""
    state = SeenState.load(tmp_path / "s.json")
    state.mark_baselined()
    state.mark_full_sweep(NOW - timedelta(hours=sweep_age_hours))
    return state


class Recorder:
    def __init__(self) -> None:
        self.sent: list[Match] = []

    def __call__(self, match: Match) -> None:
        self.sent.append(match)

    @property
    def ids(self) -> list[str]:
        return [m.candidate.id for m in self.sent]


class FakeFunda:
    """Returns fixed listings and remembers whether each call was a full sweep."""

    def __init__(self, *candidates: Candidate, complete: bool = True) -> None:
        self._result = SearchResult(
            list(candidates), complete=complete, error=None if complete else "page 3: timed out"
        )
        self.full_flags: list[bool] = []

    def __call__(self, search: SearchConfig, full: bool) -> SearchResult:
        self.full_flags.append(full)
        return self._result


def go(
    state: SeenState,
    fetch: Fetcher,
    notify: Notifier,
    *searches: SearchConfig,
    notify_existing: bool = True,
    force_full: bool = False,
) -> RunResult:
    config = config_with(*(searches or (search(),)), notify_existing=notify_existing)
    return run(config, WIJKEN, state, fetch, notify, NOW, force_full)


def test_new_match_is_notified_and_marked_seen(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path), Recorder()
    result = go(state, FakeFunda(make_candidate()), notify)

    assert notify.ids == ["1"]
    assert "1" in state
    assert result.notified == 1 and result.ok


def test_seen_listing_is_not_notified_again(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path), Recorder()
    state.add("1", NOW)
    go(state, FakeFunda(make_candidate()), notify)

    assert notify.sent == []


def test_listing_found_by_two_searches_notifies_once(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path), Recorder()
    go(state, FakeFunda(make_candidate()), notify, search("A"), search("B"))

    assert len(notify.sent) == 1


def test_rejected_listing_is_neither_notified_nor_marked(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path), Recorder()
    go(state, FakeFunda(make_candidate(price=500_000)), notify)

    assert notify.sent == []
    assert "1" not in state


def test_wijk_is_resolved_from_the_buurt(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path), Recorder()
    go(state, FakeFunda(make_candidate(neighbourhood="Centrum")), notify)

    assert notify.sent == []


def test_recent_listing_is_a_normal_alert(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path), Recorder()
    go(state, FakeFunda(make_candidate(published=NOW - timedelta(days=2))), notify)

    assert not notify.sent[0].old_listing


def test_old_listing_that_now_matches_gets_the_old_listing_alert(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path), Recorder()
    go(state, FakeFunda(make_candidate(published=OLD)), notify)

    assert notify.sent[0].old_listing
    assert notify.sent[0].age_days == 10


def test_unknown_publication_date_is_not_treated_as_old(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path), Recorder()
    go(state, FakeFunda(make_candidate(published=None)), notify)

    assert not notify.sent[0].old_listing
    assert notify.sent[0].age_days is None


def test_old_listing_alerts_only_once(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path), Recorder()
    fetch = FakeFunda(make_candidate(published=OLD))
    go(state, fetch, notify)
    go(state, fetch, notify)

    assert len(notify.sent) == 1


def test_baseline_run_records_old_listings_without_alerting(tmp_path: Path) -> None:
    state, notify = SeenState.load(tmp_path / "s.json"), Recorder()
    old, fresh = make_candidate(id="old", published=OLD), make_candidate(id="fresh")
    result = go(state, FakeFunda(old, fresh), notify)

    assert notify.ids == ["fresh"]
    assert "old" in state
    assert result.silently_marked == 1
    assert state.baselined


def test_baseline_run_can_be_fully_silent(tmp_path: Path) -> None:
    state, notify = SeenState.load(tmp_path / "s.json"), Recorder()
    go(state, FakeFunda(make_candidate()), notify, notify_existing=False)

    assert notify.sent == []
    assert "1" in state


def test_baseline_silent_marks_are_not_capped(tmp_path: Path) -> None:
    state, notify = SeenState.load(tmp_path / "s.json"), Recorder()
    old = [make_candidate(id=str(i), published=OLD) for i in range(MAX_NOTIFICATIONS_PER_RUN + 20)]
    result = go(state, FakeFunda(*old), notify)

    assert result.silently_marked == len(old)
    assert all(c.id in state for c in old)


def test_after_the_baseline_old_listings_do_alert(tmp_path: Path) -> None:
    state, notify = SeenState.load(tmp_path / "s.json"), Recorder()
    go(state, FakeFunda(), notify)  # baseline
    go(state, FakeFunda(make_candidate(published=OLD)), notify)

    assert notify.sent[0].old_listing


def test_baseline_is_not_completed_when_a_search_failed(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "s.json")

    def fetch(s: SearchConfig, full: bool) -> SearchResult:
        if s.name == "Broken":
            raise RuntimeError("blocked")
        return SearchResult([])

    go(state, fetch, Recorder(), search("Broken"), search("Fine"))

    assert not state.baselined
    assert state.last_full_sweep is None


def test_first_run_is_a_full_sweep(tmp_path: Path) -> None:
    fetch = FakeFunda()
    go(SeenState.load(tmp_path / "s.json"), fetch, Recorder())

    assert fetch.full_flags == [True]


def test_recently_swept_state_runs_a_quick_pass(tmp_path: Path) -> None:
    state, fetch = baselined_state(tmp_path, sweep_age_hours=1), FakeFunda()
    result = go(state, fetch, Recorder())

    assert fetch.full_flags == [False]
    assert not result.full_sweep
    assert state.last_full_sweep == NOW - timedelta(hours=1)


def test_a_due_sweep_runs_in_full_and_is_recorded(tmp_path: Path) -> None:
    state, fetch = baselined_state(tmp_path, sweep_age_hours=13), FakeFunda()
    go(state, fetch, Recorder())

    assert fetch.full_flags == [True]
    assert state.last_full_sweep == NOW


def test_force_full_overrides_the_schedule(tmp_path: Path) -> None:
    state, fetch = baselined_state(tmp_path, sweep_age_hours=1), FakeFunda()
    go(state, fetch, Recorder(), force_full=True)

    assert fetch.full_flags == [True]


def test_a_failed_full_sweep_stays_due(tmp_path: Path) -> None:
    state = baselined_state(tmp_path, sweep_age_hours=13)

    def fetch(s: SearchConfig, full: bool) -> SearchResult:
        raise RuntimeError("blocked")

    go(state, fetch, Recorder())
    assert state.full_sweep_due(NOW, every_hours=12)


def test_a_partial_full_sweep_still_processes_what_loaded_and_stays_due(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path, sweep_age_hours=13), Recorder()
    result = go(state, FakeFunda(make_candidate(), complete=False), notify)

    assert notify.ids == ["1"]
    assert "1" in state
    assert state.full_sweep_due(NOW, every_hours=12)
    assert result.incomplete_searches == 1


def test_a_partial_search_is_a_warning_not_a_failed_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    state = baselined_state(tmp_path)
    result = go(state, FakeFunda(complete=False), Recorder())

    assert result.ok
    assert "::warning::" in capsys.readouterr().out


def test_baseline_is_not_completed_when_a_search_was_partial(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "s.json")
    go(state, FakeFunda(complete=False), Recorder())

    assert not state.baselined
    assert state.last_full_sweep is None


def test_a_partial_baseline_still_records_old_listings_silently(tmp_path: Path) -> None:
    state, notify = SeenState.load(tmp_path / "s.json"), Recorder()
    go(state, FakeFunda(make_candidate(published=OLD), complete=False), notify)

    assert notify.sent == []
    assert "1" in state


def test_seen_listings_that_reappear_are_kept_alive(tmp_path: Path) -> None:
    state = baselined_state(tmp_path)
    state.add("1", NOW - timedelta(days=29))
    go(state, FakeFunda(make_candidate()), Recorder())  # touches the stale entry

    state.prune(NOW + timedelta(days=25), keep_days=30)
    assert "1" in state


def test_failed_search_does_not_stop_the_others(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path), Recorder()

    def fetch(s: SearchConfig, full: bool) -> SearchResult:
        if s.name == "Broken":
            raise RuntimeError("blocked")
        return SearchResult([make_candidate()])

    result = go(state, fetch, notify, search("Broken"), search("Fine"))

    assert len(notify.sent) == 1
    assert result.failed_searches == 1 and not result.ok


def test_failed_send_leaves_the_listing_unseen_for_the_next_run(tmp_path: Path) -> None:
    state = baselined_state(tmp_path)

    def notify(match: Match) -> None:
        raise DiscordError("HTTP 500")

    result = go(state, FakeFunda(make_candidate()), notify)

    assert "1" not in state
    assert result.failed_sends == 1 and not result.ok


def test_notifications_are_capped_per_run_and_oldest_go_first(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path), Recorder()
    total = MAX_NOTIFICATIONS_PER_RUN + 3
    listings = [
        make_candidate(id=str(i), published=NOW - timedelta(minutes=i)) for i in range(total)
    ]
    result = go(state, FakeFunda(*listings), notify)

    assert len(notify.sent) == MAX_NOTIFICATIONS_PER_RUN
    assert result.deferred == 3
    # oldest first: the highest ids have the earliest timestamps
    assert notify.sent[0].candidate.id == str(total - 1)
    assert "0" not in state


def test_a_search_notice_is_logged_as_a_warning_and_the_run_stays_green(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def fetch(s: SearchConfig, full: bool) -> SearchResult:
        return SearchResult([make_candidate()], notice="searched all of den-haag")

    notify = Recorder()
    result = go(baselined_state(tmp_path), fetch, notify)

    assert "::warning::[Den Haag] searched all of den-haag" in capsys.readouterr().out
    assert result.ok and notify.ids == ["1"]


class FakeEnrich:
    """Scores listings by id; an id missing from `scores` behaves like a failed detail fetch."""

    def __init__(self, scores: dict[str, int]) -> None:
        self._scores = scores
        self.asked: list[str] = []

    def __call__(self, candidate: Candidate) -> Assessment | None:
        self.asked.append(candidate.id)
        points = self._scores.get(candidate.id)
        if points is None:
            return None
        return Assessment(make_details(), Score(points, "ok", ()))


def go_enriched(
    state: SeenState, fetch: Fetcher, notify: Notifier, enrich: FakeEnrich, notify_existing: bool = True
) -> RunResult:
    config = config_with(search(), notify_existing=notify_existing)
    return run(config, WIJKEN, state, fetch, notify, NOW, enrich=enrich)


def test_alerts_are_sent_worst_first_so_the_best_arrives_last(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path), Recorder()
    listings = FakeFunda(make_candidate(id="a"), make_candidate(id="b"), make_candidate(id="c"))
    go_enriched(state, listings, notify, FakeEnrich({"a": 60, "b": 90, "c": 30}))

    assert notify.ids == ["c", "a", "b"]


def test_equal_scores_keep_oldest_first(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path), Recorder()
    older = make_candidate(id="older", published=NOW - timedelta(hours=5))
    newer = make_candidate(id="newer", published=NOW - timedelta(hours=1))
    go_enriched(state, FakeFunda(newer, older), notify, FakeEnrich({"older": 70, "newer": 70}))

    assert notify.ids == ["older", "newer"]


def test_a_listing_whose_details_failed_is_still_alerted_and_goes_first(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path), Recorder()
    listings = FakeFunda(make_candidate(id="ok"), make_candidate(id="broken"))
    result = go_enriched(state, listings, notify, FakeEnrich({"ok": 80}))

    assert notify.ids == ["broken", "ok"]
    assert notify.sent[0].assessment is None and notify.sent[1].assessment is not None
    assert "broken" in state and result.notified == 2


def test_the_assessment_is_attached_to_the_match(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path), Recorder()
    go_enriched(state, FakeFunda(make_candidate(id="a")), notify, FakeEnrich({"a": 77}))

    assessment = notify.sent[0].assessment
    assert assessment is not None and assessment.score.points == 77


def test_details_are_not_fetched_for_listings_that_are_only_recorded_silently(tmp_path: Path) -> None:
    state, notify = SeenState.load(tmp_path / "s.json"), Recorder()
    enrich = FakeEnrich({})
    go_enriched(state, FakeFunda(make_candidate(published=OLD)), notify, enrich)

    assert enrich.asked == []  # baseline run: old listing is recorded, never alerted


def test_details_are_only_fetched_for_listings_that_will_be_alerted(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path), Recorder()
    state.add("seen", NOW)
    enrich = FakeEnrich({"new": 50})
    listings = FakeFunda(make_candidate(id="seen"), make_candidate(id="new"), make_candidate(id="dear", price=900_000))
    go_enriched(state, listings, notify, enrich)

    assert enrich.asked == ["new"]


def test_without_an_enricher_alerts_still_work_and_carry_no_assessment(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path), Recorder()
    go(state, FakeFunda(make_candidate()), notify)

    assert notify.sent[0].assessment is None


def go_stored(
    state: SeenState,
    store: ListingStore,
    fetch: Fetcher,
    notify: Notifier,
    enrich: FakeEnrich | None = None,
    force_full: bool = False,
) -> RunResult:
    return run(config_with(search()), WIJKEN, state, fetch, notify, NOW, force_full, enrich, store)


def new_store(tmp_path: Path) -> ListingStore:
    return ListingStore.load(tmp_path / "docs" / "listings.json")


def test_every_matching_listing_is_stored_including_ones_already_alerted(tmp_path: Path) -> None:
    state, store = baselined_state(tmp_path), new_store(tmp_path)
    state.add("seen", NOW)
    listings = FakeFunda(make_candidate(id="seen"), make_candidate(id="new"), make_candidate(id="dear", price=900_000))
    go_stored(state, store, listings, Recorder())

    assert "seen" in store and "new" in store
    assert "dear" not in store  # doesn't pass the filters


def test_the_stored_record_gets_the_wijk_of_its_buurt(tmp_path: Path) -> None:
    state, store = baselined_state(tmp_path), new_store(tmp_path)
    go_stored(state, store, FakeFunda(make_candidate(id="1", neighbourhood="Leyenburg")), Recorder())

    assert store.get("1").wijk == "Leyenburg"


def test_a_notified_listing_gets_its_details_stored(tmp_path: Path) -> None:
    state, store = baselined_state(tmp_path), new_store(tmp_path)
    # price pinned at the scoring default's price/m² reference, so it contributes no bonus/penalty
    candidate = make_candidate(id="a", price=4157 * 80)
    go_stored(state, store, FakeFunda(candidate), Recorder(), FakeEnrich({"a": 77}))

    record = store.get("a")
    assert record.details == make_details()
    # The stored score is recomputed from the details with the current weights at the end
    # of the run (3 bedrooms +8, label B +5 on the base of 50), not the fake's placeholder 77.
    assert record.score is not None and record.score.points == 63


def test_listings_without_details_are_backfilled_with_a_budget(tmp_path: Path) -> None:
    state, store = baselined_state(tmp_path), new_store(tmp_path)
    for i in range(3):
        state.add(str(i), NOW)  # already alerted, so only the backfill can enrich them
    listings = FakeFunda(*[make_candidate(id=str(i), published=NOW - timedelta(hours=i)) for i in range(3)])
    enrich = FakeEnrich({"0": 60, "1": 61, "2": 62})
    result = go_stored(state, store, listings, Recorder(), enrich)

    assert result.backfilled == 3
    assert all(store.get(str(i)).details is not None for i in range(3))


def test_the_backfill_stops_at_the_per_run_budget(tmp_path: Path) -> None:
    from main import MAX_BACKFILL_PER_RUN

    state, store = baselined_state(tmp_path), new_store(tmp_path)
    total = MAX_BACKFILL_PER_RUN + 5
    for i in range(total):
        state.add(str(i), NOW)
    listings = FakeFunda(*[make_candidate(id=str(i), published=NOW - timedelta(minutes=i)) for i in range(total)])
    enrich = FakeEnrich({str(i): 50 for i in range(total)})
    result = go_stored(state, store, listings, Recorder(), enrich)

    assert result.backfilled == MAX_BACKFILL_PER_RUN
    assert len(store.needing_details(100)) == 5


def test_a_full_sweep_gets_a_bigger_backfill_budget(tmp_path: Path) -> None:
    from main import MAX_BACKFILL_PER_FULL_SWEEP, MAX_BACKFILL_PER_RUN

    assert MAX_BACKFILL_PER_FULL_SWEEP > MAX_BACKFILL_PER_RUN


def test_a_failed_backfill_is_counted_against_the_listing(tmp_path: Path) -> None:
    state, store = baselined_state(tmp_path), new_store(tmp_path)
    state.add("broken", NOW)
    result = go_stored(state, store, FakeFunda(make_candidate(id="broken")), Recorder(), FakeEnrich({}))

    assert result.backfilled == 0
    assert store.get("broken").details_failures == 1


def test_without_an_enricher_nothing_is_backfilled(tmp_path: Path) -> None:
    state, store = baselined_state(tmp_path), new_store(tmp_path)
    state.add("1", NOW)
    result = go_stored(state, store, FakeFunda(make_candidate(id="1")), Recorder())

    assert result.backfilled == 0 and store.get("1").details is None


def test_a_complete_full_sweep_deactivates_listings_it_no_longer_sees(tmp_path: Path) -> None:
    state, store = baselined_state(tmp_path, sweep_age_hours=13), new_store(tmp_path)
    store.upsert(make_candidate(id="gone"), None, NOW - timedelta(days=1))
    go_stored(state, store, FakeFunda(make_candidate(id="here")), Recorder())

    assert store.get("here").active and not store.get("gone").active


def test_a_quick_pass_never_deactivates_anything(tmp_path: Path) -> None:
    state, store = baselined_state(tmp_path, sweep_age_hours=1), new_store(tmp_path)
    store.upsert(make_candidate(id="older"), None, NOW - timedelta(days=1))
    go_stored(state, store, FakeFunda(make_candidate(id="here")), Recorder())

    assert store.get("older").active


def test_a_partial_full_sweep_does_not_deactivate_anything(tmp_path: Path) -> None:
    state, store = baselined_state(tmp_path, sweep_age_hours=13), new_store(tmp_path)
    store.upsert(make_candidate(id="maybe_still_there"), None, NOW - timedelta(days=1))
    go_stored(state, store, FakeFunda(make_candidate(id="here"), complete=False), Recorder())

    assert store.get("maybe_still_there").active


def test_a_failed_search_during_a_full_sweep_does_not_deactivate_anything(tmp_path: Path) -> None:
    state, store = baselined_state(tmp_path, sweep_age_hours=13), new_store(tmp_path)
    store.upsert(make_candidate(id="other_search"), None, NOW - timedelta(days=1))

    def fetch(s: SearchConfig, full: bool) -> SearchResult:
        raise RuntimeError("blocked")

    go_stored(state, store, fetch, Recorder())
    assert store.get("other_search").active


def test_stored_scores_follow_the_current_weights(tmp_path: Path) -> None:
    state, store = baselined_state(tmp_path), new_store(tmp_path)
    # price pinned at the scoring default's price/m² reference, so it contributes no bonus/penalty
    candidate = make_candidate(id="1", bedrooms=2, energy_label="C", price=4157 * 80)
    state.add("1", NOW)
    store.upsert(candidate, None, NOW)
    store.set_assessment("1", Assessment(make_details(garden=True), Score(1, "low", ())))
    go_stored(state, store, FakeFunda(candidate), Recorder())

    score = store.get("1").score
    assert score is not None and score.points == 53  # base 50 + garden 3, not the stale 1


def test_running_without_a_store_still_works(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path), Recorder()
    result = go(state, FakeFunda(make_candidate()), notify)

    assert result.notified == 1 and result.backfilled == 0


def test_a_brand_new_empty_store_is_still_written_to(tmp_path: Path) -> None:
    """ListingStore has __len__, so an empty one is falsy; the run must not skip it."""
    state, store = baselined_state(tmp_path), new_store(tmp_path)
    assert len(store) == 0

    go_stored(state, store, FakeFunda(make_candidate(id="first")), Recorder())

    assert "first" in store
