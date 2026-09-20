from datetime import timedelta
from pathlib import Path

from factories import FILTERS, NOW, make_candidate

from config import Config, SearchConfig
from discord import DiscordError
from main import MAX_NOTIFICATIONS_PER_RUN, run
from models import Candidate
from state import SeenState
from wijken import WijkMap

WIJKEN = WijkMap({"den-haag": {"Leyenburg": ["Leyenburg"], "Centrum": ["Centrum"]}})


def config_with(*searches: SearchConfig, notify_existing: bool = True) -> Config:
    return Config(notify_existing=notify_existing, filters=FILTERS, searches=searches)


def search(name: str = "Den Haag", wijken: frozenset[str] = frozenset({"Leyenburg"})) -> SearchConfig:
    return SearchConfig(name=name, location="den-haag", wijken=wijken)


class Recorder:
    def __init__(self) -> None:
        self.sent: list[Candidate] = []

    def __call__(self, candidate: Candidate, wijk: str | None, warnings: tuple[str, ...]) -> None:
        self.sent.append(candidate)


def test_new_match_is_notified_and_marked_seen(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "s.json")
    notify = Recorder()
    result = run(config_with(search()), WIJKEN, state, lambda _: [make_candidate()], notify, NOW)

    assert [c.id for c in notify.sent] == ["1"]
    assert "1" in state
    assert result.notified == 1 and result.ok


def test_seen_listing_is_not_notified_again(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "s.json")
    state.add("1", NOW)
    notify = Recorder()
    run(config_with(search()), WIJKEN, state, lambda _: [make_candidate()], notify, NOW)

    assert notify.sent == []


def test_listing_found_by_two_searches_notifies_once(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "s.json")
    notify = Recorder()
    config = config_with(search("A"), search("B"))
    run(config, WIJKEN, state, lambda _: [make_candidate()], notify, NOW)

    assert len(notify.sent) == 1


def test_rejected_listing_is_neither_notified_nor_marked(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "s.json")
    notify = Recorder()
    too_expensive = make_candidate(price=500_000)
    run(config_with(search()), WIJKEN, state, lambda _: [too_expensive], notify, NOW)

    assert notify.sent == []
    assert "1" not in state


def test_wijk_is_resolved_from_the_buurt(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "s.json")
    notify = Recorder()
    in_centrum = make_candidate(neighbourhood="Centrum")
    run(config_with(search()), WIJKEN, state, lambda _: [in_centrum], notify, NOW)

    assert notify.sent == []


def test_first_run_can_stay_silent_and_still_records_ids(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "s.json")
    notify = Recorder()
    result = run(
        config_with(search(), notify_existing=False),
        WIJKEN,
        state,
        lambda _: [make_candidate()],
        notify,
        NOW,
    )

    assert notify.sent == []
    assert "1" in state
    assert result.silently_marked == 1


def test_silent_mode_only_applies_to_the_very_first_run(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    SeenState.load(path).save()
    state = SeenState.load(path)
    notify = Recorder()
    run(config_with(search(), notify_existing=False), WIJKEN, state, lambda _: [make_candidate()], notify, NOW)

    assert len(notify.sent) == 1


def test_failed_search_does_not_stop_the_others(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "s.json")
    notify = Recorder()

    def fetch(s: SearchConfig) -> list[Candidate]:
        if s.name == "Broken":
            raise RuntimeError("blocked")
        return [make_candidate()]

    result = run(config_with(search("Broken"), search("Fine")), WIJKEN, state, fetch, notify, NOW)

    assert len(notify.sent) == 1
    assert result.failed_searches == 1 and not result.ok


def test_failed_send_leaves_the_listing_unseen_for_the_next_run(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "s.json")

    def notify(candidate: Candidate, wijk: str | None, warnings: tuple[str, ...]) -> None:
        raise DiscordError("HTTP 500")

    result = run(config_with(search()), WIJKEN, state, lambda _: [make_candidate()], notify, NOW)

    assert "1" not in state
    assert result.failed_sends == 1 and not result.ok


def test_notifications_are_capped_per_run_and_oldest_go_first(tmp_path: Path) -> None:
    state = SeenState.load(tmp_path / "s.json")
    notify = Recorder()
    total = MAX_NOTIFICATIONS_PER_RUN + 3
    listings = [
        make_candidate(id=str(i), published=NOW - timedelta(minutes=i)) for i in range(total)
    ]
    result = run(config_with(search()), WIJKEN, state, lambda _: listings, notify, NOW)

    assert len(notify.sent) == MAX_NOTIFICATIONS_PER_RUN
    assert result.deferred == 3
    # oldest first: the highest ids have the earliest timestamps
    assert notify.sent[0].id == str(total - 1)
    assert str(0) not in state
