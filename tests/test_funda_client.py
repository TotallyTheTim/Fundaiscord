from collections.abc import Sequence
from datetime import datetime, timedelta
from types import SimpleNamespace
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
    UNRESOLVED_AREA_MESSAGE,
    SearchResult,
    details_from_listing,
    fetch_details,
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
        location: str | Sequence[str],
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


def fetch(
    client: ScriptedClient,
    sleeps: Sleeps,
    stop_before: datetime | None = None,
    areas: Sequence[str] = (),
) -> SearchResult:
    return fetch_search(client, SEARCH, FILTERS, stop_before, areas, sleep=sleeps)


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


AREAS = ["den-haag/leyenburg", "den-haag/rustenburg"]


def test_areas_are_sent_as_the_location_instead_of_the_whole_city() -> None:
    client = ScriptedClient(short_page("a"))
    fetch(client, Sleeps(), areas=AREAS)

    assert client.requests[0]["location"] == AREAS


def test_without_areas_the_whole_city_is_searched() -> None:
    client = ScriptedClient(short_page("a"))
    fetch(client, Sleeps())

    assert client.requests[0]["location"] == "den-haag"


def test_an_unknown_area_falls_back_to_the_whole_city_with_a_notice() -> None:
    unknown = RuntimeError(f"Search failed: {UNRESOLVED_AREA_MESSAGE}(s): ['den-haag/leyenburg']")
    client, sleeps = ScriptedClient(unknown, short_page("a")), Sleeps()
    result = fetch(client, sleeps, areas=AREAS)

    assert [r["location"] for r in client.requests] == [AREAS, "den-haag"]
    assert [c.id for c in result.candidates] == ["a0", "a1"]
    assert result.complete
    assert result.notice is not None and "den-haag" in result.notice
    assert sleeps.calls == []  # an unknown area isn't retried


def test_an_unknown_area_without_a_fallback_available_raises() -> None:
    unknown = RuntimeError(f"Search failed: {UNRESOLVED_AREA_MESSAGE}(s): ['den-haag']")
    client = ScriptedClient(unknown)

    with pytest.raises(RuntimeError):
        fetch(client, Sleeps())


def test_other_errors_with_areas_are_still_retried_not_treated_as_unknown_areas() -> None:
    client, sleeps = ScriptedClient(TimeoutError("timed out"), short_page("a")), Sleeps()
    result = fetch(client, sleeps, areas=AREAS)

    assert result.notice is None
    assert [r["location"] for r in client.requests] == [AREAS, AREAS]
    assert sleeps.calls == [RETRY_DELAYS_SECONDS[0]]


def fake_listing(
    sections: list[tuple[str, list[tuple[str | None, str | None, list[tuple[str, str]]]]]] | None = None,
    year: int | None = 1930,
    object_type: str = "apartment",
    features: dict[str, bool] | None = None,
    description: str = "",
) -> Listing:
    """Just enough of pyfunda's Listing for details_from_listing."""
    built = [
        SimpleNamespace(
            title=title,
            items=[
                SimpleNamespace(
                    label=label,
                    value=value,
                    children=[SimpleNamespace(label=cl, value=cv) for cl, cv in children],
                )
                for label, value, children in items
            ],
        )
        for title, items in (sections or [])
    ]
    properties = SimpleNamespace(construction_year=year, object_type=object_type, features=features or {})
    return cast(
        Listing,
        SimpleNamespace(characteristics=built, property_details=properties, description=description),
    )


def test_details_come_from_top_level_and_nested_characteristics() -> None:
    listing = fake_listing(
        [
            ("Kadastrale gegevens", [("DEN HAAG AM 6090", None, [("Eigendomssituatie", "Volle eigendom")])]),
            ("Overdracht", [("Bijdrage VvE", "€ 200,00 per maand", [])]),
            ("Buitenruimte", [("Balkon/dakterras", "Balkon aanwezig", []), ("Ligging", "Aan drukke weg", [])]),
        ],
        year=1912,
        features={"is_monument": True},
        description="Kluswoning met potentie",
    )
    d = details_from_listing(listing)

    assert d.ownership == "Volle eigendom" and not d.erfpacht
    assert d.vve_monthly == 200.0
    assert d.balcony and d.busy_road
    assert d.year_built == 1912 and d.monument and d.is_apartment
    assert d.needs_work


def test_the_first_value_wins_when_a_label_repeats() -> None:
    listing = fake_listing([("A", [("Ligging", "In woonwijk", [])]), ("B", [("Ligging", "Aan drukke weg", [])])])
    assert not details_from_listing(listing).busy_road


def test_headers_without_a_value_are_skipped() -> None:
    listing = fake_listing([("Bouw", [(None, "orphan", []), ("Gebruiksoppervlakten", None, [])])])
    assert not details_from_listing(listing).balcony


def test_a_house_is_not_an_apartment() -> None:
    assert not details_from_listing(fake_listing(object_type="house")).is_apartment


def test_a_listing_without_characteristics_still_parses() -> None:
    d = details_from_listing(fake_listing(None, year=None))
    assert d.year_built is None and d.ownership is None


class DetailScript:
    def __init__(self, *script: Listing | Exception) -> None:
        self._script = list(script)
        self.requested: list[int] = []

    def listing(self, listing_id: int) -> Listing:
        self.requested.append(listing_id)
        step = self._script[len(self.requested) - 1]
        if isinstance(step, Exception):
            raise step
        return step


def test_fetch_details_asks_for_the_numeric_listing_id() -> None:
    client = DetailScript(fake_listing())
    fetch_details(client, "44502798", sleep=Sleeps())

    assert client.requested == [44502798]


def test_fetch_details_retries_a_failed_request() -> None:
    client, sleeps = DetailScript(TimeoutError("timed out"), fake_listing(year=1950)), Sleeps()
    d = fetch_details(client, "1", sleep=sleeps)

    assert d.year_built == 1950
    assert sleeps.calls == [RETRY_DELAYS_SECONDS[0]]


def test_fetch_details_gives_up_after_the_last_retry() -> None:
    errors = [TimeoutError("timed out")] * (len(RETRY_DELAYS_SECONDS) + 1)
    client, sleeps = DetailScript(*errors), Sleeps()

    with pytest.raises(TimeoutError):
        fetch_details(client, "1", sleep=sleeps)
    assert sleeps.calls == list(RETRY_DELAYS_SECONDS)
