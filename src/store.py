import json
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from details import Details
from models import Candidate
from scoring import Assessment, Reason, Score, ScoringConfig, score_listing

KEEP_INACTIVE_DAYS = 60
# A detail page that fails this many times in a row is left alone rather than retried forever.
MAX_DETAIL_ATTEMPTS = 3


@dataclass
class StoredListing:
    """One current match as the web page shows it. Mutable: the store updates it in place."""

    id: str
    title: str
    city: str
    wijk: str | None
    neighbourhood: str | None
    url: str
    price: int | None
    living_area: int | None
    bedrooms: int | None
    energy_label: str | None
    published: str | None
    photo_url: str | None
    search_name: str
    first_seen: str  # full timestamp, set once
    last_seen: str  # date only, so a listing that's still around doesn't rewrite the file every run
    active: bool = True
    inactive_since: str | None = None
    price_history: list[list[str | int]] = field(default_factory=list)  # [[date, price], ...]
    details: Details | None = None
    score: Score | None = None
    details_failures: int = 0


class ListingStore:
    """Every listing that currently matches, kept for the web page in docs/listings.json.

    Full details are stored (not just the score) so scores can be recomputed for free
    whenever the weights in config.yaml change.
    """

    def __init__(self, path: Path, listings: dict[str, StoredListing]) -> None:
        self._path = path
        self._listings = listings
        self._on_disk = self._serialise()

    @classmethod
    def load(cls, path: Path) -> "ListingStore":
        if not path.exists():
            return cls(path, {})
        raw = json.loads(path.read_text(encoding="utf-8"))
        listings = {item["id"]: _from_dict(item) for item in raw.get("listings", [])}
        return cls(path, listings)

    def __len__(self) -> int:
        return len(self._listings)

    def __contains__(self, listing_id: str) -> bool:
        return listing_id in self._listings

    def get(self, listing_id: str) -> StoredListing:
        return self._listings[listing_id]

    def all(self) -> list[StoredListing]:
        return list(self._listings.values())

    def upsert(self, candidate: Candidate, wijk: str | None, now: datetime) -> None:
        """Record that a listing matches right now, keeping any details already fetched."""
        today = now.date().isoformat()
        published = candidate.published.isoformat() if candidate.published else None
        existing = self._listings.get(candidate.id)
        if existing is None:
            self._listings[candidate.id] = StoredListing(
                id=candidate.id,
                title=candidate.title,
                city=candidate.city,
                wijk=wijk,
                neighbourhood=candidate.neighbourhood,
                url=candidate.url,
                price=candidate.price,
                living_area=candidate.living_area,
                bedrooms=candidate.bedrooms,
                energy_label=candidate.energy_label,
                published=published,
                photo_url=candidate.photo_url,
                search_name=candidate.search_name,
                first_seen=now.isoformat(timespec="seconds"),
                last_seen=today,
                price_history=[[today, candidate.price]] if candidate.price is not None else [],
            )
            return
        if candidate.price is not None and candidate.price != existing.price:
            existing.price_history.append([today, candidate.price])
        existing.title = candidate.title
        existing.city = candidate.city
        existing.wijk = wijk
        existing.neighbourhood = candidate.neighbourhood
        existing.url = candidate.url
        existing.price = candidate.price
        existing.living_area = candidate.living_area
        existing.bedrooms = candidate.bedrooms
        existing.energy_label = candidate.energy_label
        existing.published = published
        existing.photo_url = candidate.photo_url
        existing.search_name = candidate.search_name
        existing.last_seen = today
        existing.active = True
        existing.inactive_since = None

    def set_assessment(self, listing_id: str, assessment: Assessment) -> None:
        record = self._listings[listing_id]
        record.details = assessment.details
        record.score = assessment.score
        record.details_failures = 0

    def record_details_failure(self, listing_id: str) -> None:
        self._listings[listing_id].details_failures += 1

    def candidate_of(self, listing_id: str) -> Candidate:
        r = self._listings[listing_id]
        return Candidate(
            id=r.id,
            title=r.title,
            city=r.city,
            neighbourhood=r.neighbourhood,
            url=r.url,
            price=r.price,
            living_area=r.living_area,
            bedrooms=r.bedrooms,
            energy_label=r.energy_label,
            published=datetime.fromisoformat(r.published) if r.published else None,
            photo_url=r.photo_url,
            search_name=r.search_name,
        )

    def needing_details(self, limit: int) -> list[str]:
        """Active listings we haven't read the detail page of yet: fewest failures, then newest."""
        pending = [
            r
            for r in self._listings.values()
            if r.active and r.details is None and r.details_failures < MAX_DETAIL_ATTEMPTS
        ]
        pending.sort(key=lambda r: (r.published or "", r.id), reverse=True)  # newest first
        pending.sort(key=lambda r: r.details_failures)  # stable, so ties stay newest first
        return [r.id for r in pending[:limit]]

    def deactivate_missing(self, seen_ids: set[str], now: datetime) -> int:
        """After a complete sweep, mark listings that no longer match (sold, withdrawn, repriced)."""
        today = now.date().isoformat()
        gone = [r for r in self._listings.values() if r.active and r.id not in seen_ids]
        for record in gone:
            record.active = False
            record.inactive_since = today
        return len(gone)

    def rescore(self, config: ScoringConfig) -> None:
        for record in self._listings.values():
            if record.details is not None:
                record.score = score_listing(self.candidate_of(record.id), record.details, config)

    def prune(self, now: datetime) -> None:
        cutoff = (now - timedelta(days=KEEP_INACTIVE_DAYS)).date().isoformat()
        self._listings = {
            i: r
            for i, r in self._listings.items()
            if r.active or (r.inactive_since or "") >= cutoff
        }

    def save(self, now: datetime) -> bool:
        """Write the file if anything changed since it was loaded. Returns whether it wrote."""
        current = self._serialise()
        if current == self._on_disk:
            return False
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"generated": now.isoformat(timespec="seconds"), "listings": current}
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        self._on_disk = current
        return True

    def _serialise(self) -> list[dict[str, Any]]:
        # Round-tripping through JSON normalises tuples to lists, so the comparison in
        # save() is against exactly what a reload would give.
        ordered = [self._listings[i] for i in sorted(self._listings)]
        serialised: list[dict[str, Any]] = json.loads(json.dumps([asdict(r) for r in ordered]))
        return serialised


def _from_dict(item: dict[str, Any]) -> StoredListing:
    data = dict(item)
    raw_details = data.pop("details", None)
    raw_score = data.pop("score", None)
    known = {f.name for f in fields(StoredListing)}
    record = StoredListing(**{k: v for k, v in data.items() if k in known})
    try:
        record.details = _details_from_dict(raw_details) if raw_details else None
        record.score = _score_from_dict(raw_score) if raw_score else None
    except (TypeError, KeyError):
        # A record written by an older shape: drop what we can't read so it's fetched again.
        record.details = None
        record.score = None
    return record


def _details_from_dict(raw: dict[str, Any]) -> Details:
    known = {f.name for f in fields(Details)}
    return Details(**{k: v for k, v in raw.items() if k in known})


def _score_from_dict(raw: dict[str, Any]) -> Score:
    return Score(
        points=int(raw["points"]),
        tier=str(raw["tier"]),
        reasons=tuple(Reason(int(r["points"]), str(r["text"])) for r in raw["reasons"]),
    )
