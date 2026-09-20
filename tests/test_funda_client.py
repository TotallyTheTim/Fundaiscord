from datetime import timedelta
from typing import cast

import pytest
from factories import FILTERS, NOW, make_candidate
from funda.listing import Listing

import funda_client
from config import SearchConfig
from funda_client import (
    PAGE_DELAY_SECONDS,
    PAGE_SIZE,
    RETRY_DELAYS_SECONDS,
    fetch_search,
)
from models import Candidate

SEARCH = SearchConfig(name="Den Haag", location="den-haag", wijken=frozenset())


@pytest.fixture(autouse=True)
def candidates_stand_in_for_listings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake client hands back Candidates directly, so skip the pyfunda conversion."""
    monkeypatch.setattr(funda_client, "to_candidate", lambda listing, search_name: listing)


class ScriptedClient:
    """Answers each search() call with the next scripted page, or raises the next error."""

    def __init__(self, *script: list[Candidate] | Exception) -> None:
        self._script = list(script)
        self.requests: list[dict[str, object]] = []

    def search(
        self,
        location: str,
        *,
        category: str,
        max_price: int,
        min_area: int,
        min_bedrooms: int,
        sort: str,
        page: int,
    ) -> list[Listing]:
        self.requests.append(
            {
                "location": location,
                "category": category,
                "max_price": max_price,
                "min_area": min_area,
                "min_bedrooms": min_bedrooms,
                "sort": sort,
                "page": page,
            }
        )
        step = self._script[len(self.requests) - 1]
        if isinstance(step, Exception):
            raise step
        return cast("list[Listing]", step)


def full_page(prefix: str, **overrides: object) -> list[Candidate]:
    return [make_candidate(id=f"{prefix}{i}", **overrides) for i in range(PAGE_SIZE)]


def short_page(prefix: str, count: int = 2) -> list[Candidate]:
    return [make_candidate(id=f"{prefix}{i}") for i in range(count)]


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def fetch(client: ScriptedClient, sleeps: Sleeps, stop_before: object = None):  # type: ignore[no-untyped-def]
    return fetch_search(client, SEARCH, FILTERS, stop_before, sleep=sleeps)  # type: ignore[arg-type]


def test_a_short_page_ends_the_search() -> None:
    client, sleeps = ScriptedClient(short_page("a")), Sleeps()
    result = fetch(client, sleeps)

    assert [c.id for c in result.candidates] == ["a0", "a1"]
    assert result.complete
    assert len(client.requests) == 1
    assert sleeps.calls == []


def test_search_uses_the_configured_filters_and_newest_sort() -> None:
    client = ScriptedClient(short_page("a"))
    fetch(client, Sleeps())

    assert client.requests == [
        {
            "location": "den-haag",
            "category": "buy",
            "max_price": FILTERS.max_price,
            "min_area": FILTERS.min_surface,
            "min_bedrooms": FILTERS.min_bedrooms,
            "sort": "newest",
            "page": 0,
        }
    ]


def test_full_pages_are_followed_with_a_pause_between_requests() -> None:
    client, sleeps = ScriptedClient(full_page("a"), full_page("b"), short_page("c")), Sleeps()
    result = fetch(client, sleeps)

    assert len(result.candidates) == 2 * PAGE_SIZE + 2
    assert [r["page"] for r in client.requests] == [0, 1, 2]
    assert sleeps.calls == [PAGE_DELAY_SECONDS, PAGE_DELAY_SECONDS]


def test_a_quick_pass_stops_once_a_page_holds_a_listing_older_than_the_cutoff() -> None:
    stop_before = NOW - timedelta(days=4)
    old_page = full_page("old", published=NOW - timedelta(days=6))
    client = ScriptedClient(full_page("new", published=NOW), old_page, full_page("never"))
    result = fetch(client, Sleeps(), stop_before)

    assert len(client.requests) == 2
    assert result.complete


def test_a_full_sweep_ignores_listing_age() -> None:
    old_page = full_page("old", published=NOW - timedelta(days=60))
    client = ScriptedClient(old_page, old_page, short_page("end"))
    fetch(client, Sleeps(), None)

    assert len(client.requests) == 3


def test_a_failed_page_is_retried_and_the_search_carries_on() -> None:
    client = ScriptedClient(TimeoutError("timed out"), short_page("a"))
    sleeps = Sleeps()
    result = fetch(client, sleeps)

    assert result.complete
    assert [c.id for c in result.candidates] == ["a0", "a1"]
    assert sleeps.calls == [RETRY_DELAYS_SECONDS[0]]


def test_the_first_page_failing_every_attempt_raises() -> None:
    errors = [TimeoutError("timed out")] * (len(RETRY_DELAYS_SECONDS) + 1)
    client, sleeps = ScriptedClient(*errors), Sleeps()

    with pytest.raises(TimeoutError):
        fetch(client, sleeps)
    assert sleeps.calls == list(RETRY_DELAYS_SECONDS)


def test_a_later_page_failing_every_attempt_keeps_the_earlier_pages() -> None:
    errors = [TimeoutError("timed out")] * (len(RETRY_DELAYS_SECONDS) + 1)
    client, sleeps = ScriptedClient(full_page("a"), *errors), Sleeps()
    result = fetch(client, sleeps)

    assert not result.complete
    assert len(result.candidates) == PAGE_SIZE
    assert result.error is not None and result.error.startswith("page 2:")
    assert sleeps.calls == [PAGE_DELAY_SECONDS, *RETRY_DELAYS_SECONDS]
