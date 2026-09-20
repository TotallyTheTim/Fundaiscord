from datetime import datetime, timezone

from config import EnergyLabelRules, Filters
from models import Candidate

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)

FILTERS = Filters(
    max_price=351_000,
    min_surface=70,
    min_bedrooms=2,
    max_age_days=2,
    energy_labels=EnergyLabelRules(
        always=frozenset({"A++++", "A+++", "A++", "A+", "A", "B", "C", "D"}),
        only_below_price={"E": 300_000},
    ),
)


def make_candidate(**overrides: object) -> Candidate:
    fields: dict[str, object] = {
        "id": "1",
        "title": "Teststraat 1",
        "city": "Den Haag",
        "neighbourhood": "Leyenburg",
        "url": "https://www.funda.nl/detail/koop/den-haag/appartement-teststraat-1/1/",
        "price": 300_000,
        "living_area": 80,
        "bedrooms": 3,
        "energy_label": "B",
        "published": datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc),
        "photo_url": "https://cloud.funda.nl/tiara-media/a/b",
        "search_name": "Den Haag",
    }
    fields.update(overrides)
    return Candidate(**fields)  # type: ignore[arg-type]
