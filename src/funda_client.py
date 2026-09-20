import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from curl_cffi import requests as curl_requests
from funda import Funda
from funda.listing import Listing

from config import Filters, SearchConfig
from models import Candidate

PHOTO_BASE_URL = "https://cloud.funda.nl/"
PAGE_SIZE = 15
MAX_PAGES = 40
PAGE_DELAY_SECONDS = 2.5
# Funda occasionally drops a request from GitHub's servers (seen as a 30 s curl timeout
# with no bytes received). A short pause and another try usually gets through.
RETRY_DELAYS_SECONDS = (2.0, 5.0)
# pyfunda's wording when Funda doesn't know one of the requested areas.
UNRESOLVED_AREA_MESSAGE = "could not resolve location"


class SearchClient(Protocol):
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
    ) -> list[Listing]: ...


@dataclass(frozen=True)
class SearchResult:
    candidates: list[Candidate]
    # False when a page failed even after retries: `candidates` holds what loaded
    # before that, but the search wasn't read to the end.
    complete: bool = True
    error: str | None = None
    # Something worth a warning that didn't stop the search, e.g. a fallback.
    notice: str | None = None


def make_client() -> Funda:
    client = Funda()
    # pyfunda 3.1.5's built-in web session (impersonate="chrome124") gets its HTTP/2
    # stream reset by Funda's bot protection, and its mobile API now needs a token.
    # A newer Chrome fingerprint gets through, so swap the session in.
    client._web_session = curl_requests.Session(impersonate="chrome")
    return client


def fetch_search(
    client: SearchClient,
    search: SearchConfig,
    filters: Filters,
    stop_before: datetime | None,
    areas: Sequence[str] = (),
    sleep: Callable[[float], None] = time.sleep,
) -> SearchResult:
    """Fetch listings for a search, newest first.

    With `stop_before` set (quick pass) paging ends once a page holds a listing
    published before it; None pages through everything (full sweep). "newest" sorts
    by day only, so callers should leave a day of margin in `stop_before`.

    `areas` narrows the search to those Funda areas (buurt slugs) instead of the whole
    city. If Funda doesn't recognise one of them the search falls back to the whole
    city, so a renamed buurt can't silently hide listings.

    Each page is retried a few times. If a later page still fails, the pages already
    read are returned as an incomplete result; if the very first page fails, that
    raises, since there is nothing to return.

    Only price, surface, bedrooms and area are filtered server-side; label and wijk
    rules need our own logic (see filters.py).
    """
    location: str | Sequence[str] = list(areas) if areas else search.location
    candidates: list[Candidate] = []
    for page in range(MAX_PAGES):
        try:
            results = _search_page(client, location, filters, page, sleep)
        except Exception as error:  # curl and pyfunda raise assorted types
            if page == 0 and areas and UNRESOLVED_AREA_MESSAGE in str(error):
                fallback = fetch_search(client, search, filters, stop_before, (), sleep)
                return SearchResult(
                    fallback.candidates,
                    fallback.complete,
                    fallback.error,
                    notice=f"Funda didn't recognise an area, searched all of {search.location}: {error}",
                )
            if page == 0:
                raise
            return SearchResult(candidates, complete=False, error=f"page {page + 1}: {error}")
        page_candidates = [to_candidate(listing, search.name) for listing in results]
        candidates.extend(page_candidates)
        reached_old = stop_before is not None and any(
            c.published and c.published < stop_before for c in page_candidates
        )
        if len(results) < PAGE_SIZE or reached_old:
            break
        sleep(PAGE_DELAY_SECONDS)
    return SearchResult(candidates)


def _search_page(
    client: SearchClient,
    location: str | Sequence[str],
    filters: Filters,
    page: int,
    sleep: Callable[[float], None],
) -> list[Listing]:
    attempts = len(RETRY_DELAYS_SECONDS) + 1
    for attempt in range(attempts):
        try:
            return client.search(
                location,
                category="buy",
                max_price=filters.max_price,
                min_area=filters.min_surface,
                min_bedrooms=filters.min_bedrooms,
                sort="newest",
                page=page,
            )
        except Exception as error:
            # An unknown area won't get better by waiting.
            if attempt == attempts - 1 or UNRESOLVED_AREA_MESSAGE in str(error):
                raise
            sleep(RETRY_DELAYS_SECONDS[attempt])
    raise AssertionError("unreachable")


def to_candidate(listing: Listing, search_name: str) -> Candidate:
    photos = listing.media.photos if listing.media else ()
    return Candidate(
        id=str(listing.id),
        title=listing.title or "Unknown address",
        city=listing.city or "",
        neighbourhood=listing.address.neighbourhood if listing.address else None,
        url=listing.url or "",
        price=listing.price.amount if listing.price else None,
        living_area=listing.living_area,
        bedrooms=listing.bedrooms,
        energy_label=listing.energy_label,
        published=parse_timestamp(listing.publication_date),
        photo_url=f"{PHOTO_BASE_URL}{photos[0].id}" if photos and photos[0].id else None,
        search_name=search_name,
    )


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # Timestamps without an offset (seen on detail pages) are assumed UTC.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
