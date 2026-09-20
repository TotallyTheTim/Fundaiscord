from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Candidate:
    """A Funda listing reduced to the fields we filter and notify on.

    Kept separate from pyfunda's Listing so filters and tests never depend on it.
    Fields Funda didn't provide are None, which the filters treat as "unknown".
    """

    id: str
    title: str
    city: str
    neighbourhood: str | None
    url: str
    price: int | None
    living_area: int | None
    bedrooms: int | None
    energy_label: str | None
    published: datetime | None
    photo_url: str | None
    search_name: str
