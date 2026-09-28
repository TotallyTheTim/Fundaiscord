from datetime import datetime, timezone

from config import EnergyLabelRules, Filters
from details import Details
from models import Candidate

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)

FILTERS = Filters(
    max_price=351_000,
    min_surface=70,
    min_bedrooms=2,
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


def make_details(**overrides: object) -> Details:
    """A neutral apartment: nothing to add, nothing to subtract when scored."""
    fields: dict[str, object] = {
        "ownership": "Volle eigendom",
        "erfpacht": False,
        "erfpacht_perpetual": False,
        "is_apartment": True,
        "floor": 2,
        "floor_label": "2e woonlaag",
        "year_built": 1965,
        "balcony": False,
        "outdoor_m2": None,
        "garden": False,
        "lift": False,
        "vve_monthly": None,
        "vve_reserve_fund": None,
        "vve_maintenance_plan": None,
        "vve_registered": None,
        "busy_road": False,
        "monument": False,
        "needs_work": False,
        "move_in_ready": False,
        "top_floor_hint": False,
    }
    fields.update(overrides)
    return Details(**fields)  # type: ignore[arg-type]
