import re
from collections.abc import Mapping
from dataclasses import dataclass

# "afgekocht tot 2055" only prepays the canon until a date, so only wording that says
# the buy-off is perpetual counts as the erfpacht risk being gone.
_PERPETUAL_BUYOFF = re.compile(r"eeuwig\w*\s+(afgekocht|afkoop)|afgekocht\s+voor\s+eeuwig")
_NEEDS_WORK = re.compile(
    r"\bklus(woning|appartement|ser|sers|project|huis)\b"
    r"|op te knappen|te renoveren|opknapbeurt|renovatie nodig|aan renovatie toe|moderniseren"
)
_MOVE_IN_READY = re.compile(
    r"instap\s?klaar|direct te betrekken|kant[- ]en[- ]klaar"
    r"|(recent|volledig|geheel|smaakvol)\s+(gerenoveerd|gemoderniseerd|verbouwd)"
    r"|gerenoveerde\s+(keuken|badkamer)|nieuwe\s+(keuken|badkamer)|gemoderniseerde"
)
_TOP_FLOOR = re.compile(
    r"top\s?etage|bovenste (verdieping|etage|woonlaag)|hoogste verdieping|bovenwoning|penthouse"
)
_GARDEN_LABELS = ("Tuin", "Achtertuin", "Voortuin", "Zijtuin")


@dataclass(frozen=True)
class Details:
    """What the listing's detail page tells us beyond the search result.

    Missing values are None (or False for plain yes/no flags), never a guess.
    """

    ownership: str | None
    erfpacht: bool
    erfpacht_perpetual: bool
    is_apartment: bool
    floor: int | None  # 0 = ground floor
    floor_label: str | None
    year_built: int | None
    balcony: bool  # balcony, roof terrace or other outdoor space attached to the building
    outdoor_m2: int | None
    garden: bool
    lift: bool
    vve_monthly: float | None
    vve_reserve_fund: bool | None
    vve_maintenance_plan: bool | None
    vve_registered: bool | None
    busy_road: bool
    monument: bool
    needs_work: bool
    move_in_ready: bool
    top_floor_hint: bool
    latitude: float | None = None
    longitude: float | None = None


def parse_details(
    labels: Mapping[str, str],
    description: str,
    year_built: int | None,
    is_apartment: bool,
    monument: bool,
    latitude: float | None = None,
    longitude: float | None = None,
) -> Details:
    """Build Details from the detail page's label -> value pairs and description text."""
    text = description.lower()
    ownership = labels.get("Eigendomssituatie")
    erfpacht = "erfpacht" in (ownership or "").lower() or any(
        "erfpacht" in label.lower() for label in labels
    )
    outdoor_m2 = _square_metres(labels.get("Gebouwgebonden buitenruimte"))
    floor_label = labels.get("Gelegen op")
    vve_amount = _euros(labels.get("Bijdrage VvE")) or _euros(labels.get("Periodieke bijdrage"))
    needs_work = bool(_NEEDS_WORK.search(text))

    return Details(
        ownership=ownership,
        erfpacht=erfpacht,
        erfpacht_perpetual=erfpacht and bool(_PERPETUAL_BUYOFF.search(f"{ownership or ''} {text}".lower())),
        is_apartment=is_apartment,
        floor=_floor_number(floor_label),
        floor_label=floor_label,
        year_built=year_built,
        balcony=bool(labels.get("Balkon/dakterras")) or outdoor_m2 is not None,
        outdoor_m2=outdoor_m2,
        garden=any(label in labels for label in _GARDEN_LABELS),
        lift="lift" in labels.get("Voorzieningen", "").lower(),
        vve_monthly=vve_amount,
        vve_reserve_fund=_yes_no(labels.get("Reservefonds aanwezig")),
        vve_maintenance_plan=_yes_no(labels.get("Onderhoudsplan")),
        vve_registered=_yes_no(labels.get("Inschrijving KvK")),
        busy_road="drukke" in labels.get("Ligging", "").lower(),
        monument=monument,
        needs_work=needs_work,
        move_in_ready=not needs_work and bool(_MOVE_IN_READY.search(text)),
        top_floor_hint=bool(_TOP_FLOOR.search(text)),
        latitude=latitude,
        longitude=longitude,
    )


def _yes_no(value: str | None) -> bool | None:
    cleaned = (value or "").strip().lower()
    if cleaned.startswith("ja"):
        return True
    if cleaned.startswith("nee"):
        return False
    return None


def _euros(value: str | None) -> float | None:
    found = re.search(r"€\s*([\d.]*\d)(?:,(\d{1,2}))?", value or "")
    if not found:
        return None
    return float(found.group(1).replace(".", "") + (f".{found.group(2)}" if found.group(2) else ""))


def _square_metres(value: str | None) -> int | None:
    found = re.search(r"(\d+)\s*m", value or "")
    return int(found.group(1)) if found else None


def _floor_number(label: str | None) -> int | None:
    if not label:
        return None
    if "begane grond" in label.lower():
        return 0
    found = re.search(r"(\d+)e?\s*(woonlaag|verdieping|etage)", label.lower())
    return int(found.group(1)) if found else None
