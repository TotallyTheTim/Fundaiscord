from datetime import timedelta
from pathlib import Path

from factories import FILTERS, NOW, make_candidate

from config import Config, SearchConfig
from discord import DiscordError
from main import MAX_NOTIFICATIONS_PER_RUN, Fetcher, Match, Notifier, RunResult, run
from models import Candidate
from state import SeenState
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

    def __init__(self, *candidates: Candidate) -> None:
        self._candidates = list(candidates)
        self.full_flags: list[bool] = []

    def __call__(self, search: SearchConfig, full: bool) -> list[Candidate]:
        self.full_flags.append(full)
        return self._candidates


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

    def fetch(s: SearchConfig, full: bool) -> list[Candidate]:
        if s.name == "Broken":
            raise RuntimeError("blocked")
        return []

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

    def fetch(s: SearchConfig, full: bool) -> list[Candidate]:
        raise RuntimeError("blocked")

    go(state, fetch, Recorder())
    assert state.full_sweep_due(NOW, every_hours=12)


def test_seen_listings_that_reappear_are_kept_alive(tmp_path: Path) -> None:
    state = baselined_state(tmp_path)
    state.add("1", NOW - timedelta(days=29))
    go(state, FakeFunda(make_candidate()), Recorder())  # touches the stale entry

    state.prune(NOW + timedelta(days=25), keep_days=30)
    assert "1" in state


def test_failed_search_does_not_stop_the_others(tmp_path: Path) -> None:
    state, notify = baselined_state(tmp_path), Recorder()

    def fetch(s: SearchConfig, full: bool) -> list[Candidate]:
        if s.name == "Broken":
            raise RuntimeError("blocked")
        return [make_candidate()]

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
