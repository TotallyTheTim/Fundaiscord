import time
from datetime import datetime, timedelta, timezone

from curl_cffi import requests as curl_requests
from funda import Funda
from funda.listing import Listing

from config import Filters, SearchConfig
from models import Candidate

PHOTO_BASE_URL = "https://cloud.funda.nl/"
PAGE_SIZE = 15
MAX_PAGES = 10
PAGE_DELAY_SECONDS = 1.5


def make_client() -> Funda:
    client = Funda()
    # pyfunda 3.1.5's built-in web session (impersonate="chrome124") gets its HTTP/2
    # stream reset by Funda's bot protection, and its mobile API now needs a token.
    # A newer Chrome fingerprint gets through, so swap the session in.
    client._web_session = curl_requests.Session(impersonate="chrome")
    return client


def fetch_search(
    client: Funda,
    search: SearchConfig,
    filters: Filters,
    now: datetime,
) -> list[Candidate]:
    """Fetch the newest listings for a search until we've paged past the age window.

    Only price, surface and bedrooms are filtered server-side; label, date and
    wijk rules need our own logic (see filters.py).
    """
    # "newest" sorts by day only, so listings within a day are shuffled. Keep paging
    # until a page holds something a full day older than the window.
    stop_before = now - timedelta(days=filters.max_age_days + 1)
    candidates: list[Candidate] = []
    for page in range(MAX_PAGES):
        results = client.search(
            search.location,
            category="buy",
            max_price=filters.max_price,
            min_area=filters.min_surface,
            min_bedrooms=filters.min_bedrooms,
            sort="newest",
            page=page,
        )
        page_candidates = [to_candidate(listing, search.name) for listing in results]
        candidates.extend(page_candidates)
        reached_old = any(c.published and c.published < stop_before for c in page_candidates)
        if len(results) < PAGE_SIZE or reached_old:
            break
        time.sleep(PAGE_DELAY_SECONDS)
    return candidates


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
