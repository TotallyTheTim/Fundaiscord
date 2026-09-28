from dataclasses import dataclass, field

from details import Details
from models import Candidate

TIER_ORDER = ("low", "ok", "good", "top")


@dataclass(frozen=True)
class Weights:
    """Points added to or removed from the base score. Tuned in config.yaml."""

    erfpacht: int = -45
    erfpacht_perpetual: int = -25
    balcony_at_2_m2: int = 3
    balcony_at_8_m2: int = 12
    balcony_at_12_m2: int = 15
    balcony_unknown_size: int = 6
    garden: int = 3
    house: int = 4
    first_floor: int = 3
    top_floor: int = 3
    bedrooms_3_plus: int = 8
    needs_work: int = -20
    move_in_ready: int = 8
    built_before_1940: int = 4
    monument: int = 2
    vve_no_reserve_fund: int = -10
    vve_no_maintenance_plan: int = -6
    vve_not_registered: int = -6
    vve_expensive_no_lift: int = -3
    busy_road: int = -2
    label_a_or_b: int = 4
    label_d: int = -2
    label_e: int = -4


@dataclass(frozen=True)
class Tiers:
    """Minimum score for each tier; anything below `ok` is `low`."""

    top: int = 70
    good: int = 55
    ok: int = 40


@dataclass(frozen=True)
class ScoringConfig:
    base: int = 50
    vve_expensive_per_m2: float = 3.5
    tiers: Tiers = field(default_factory=Tiers)
    weights: Weights = field(default_factory=Weights)


@dataclass(frozen=True)
class Reason:
    points: int
    text: str


@dataclass(frozen=True)
class Score:
    points: int  # 0 to 100
    tier: str  # one of TIER_ORDER
    reasons: tuple[Reason, ...]


@dataclass(frozen=True)
class Assessment:
    details: Details
    score: Score


def score_listing(candidate: Candidate, details: Details, config: ScoringConfig) -> Score:
    w = config.weights
    reasons: list[Reason] = []

    def add(points: int, text: str) -> None:
        if points:
            reasons.append(Reason(points, text))

    if details.erfpacht:
        if details.erfpacht_perpetual:
            add(w.erfpacht_perpetual, "erfpacht (perpetual, bought off)")
        else:
            add(w.erfpacht, "erfpacht")

    if details.balcony:
        add(_balcony_points(details.outdoor_m2, w), _balcony_text(details.outdoor_m2))
    if details.garden:
        add(w.garden, "garden")
    if not details.is_apartment:
        add(w.house, "house")
    if details.floor == 1:
        add(w.first_floor, "first floor")
    if details.top_floor_hint:
        add(w.top_floor, "top floor")
    if (candidate.bedrooms or 0) >= 3:
        add(w.bedrooms_3_plus, f"{candidate.bedrooms} bedrooms (room for an office)")

    if details.needs_work:
        add(w.needs_work, "needs work")
    elif details.move_in_ready:
        add(w.move_in_ready, "move-in ready")
    if details.year_built is not None and details.year_built < 1940:
        add(w.built_before_1940, f"pre-war character ({details.year_built})")
    if details.monument:
        add(w.monument, "monument")

    if details.vve_reserve_fund is False:
        add(w.vve_no_reserve_fund, "VvE has no reserve fund")
    if details.vve_maintenance_plan is False:
        add(w.vve_no_maintenance_plan, "VvE has no maintenance plan")
    if details.vve_registered is False:
        add(w.vve_not_registered, "VvE not registered at the KvK")
    if (
        details.vve_monthly
        and candidate.living_area
        and not details.lift
        and details.vve_monthly / candidate.living_area > config.vve_expensive_per_m2
    ):
        per_m2 = details.vve_monthly / candidate.living_area
        add(w.vve_expensive_no_lift, f"VvE €{per_m2:.1f}/m² without a lift")

    if details.busy_road:
        add(w.busy_road, "busy road")

    label = (candidate.energy_label or "").strip().upper()
    if label.startswith("A") or label == "B":
        add(w.label_a_or_b, f"energy label {label}")
    elif label == "D":
        add(w.label_d, "energy label D")
    elif label == "E":
        add(w.label_e, "energy label E")

    points = max(0, min(100, config.base + sum(r.points for r in reasons)))
    tier = _tier(points, config.tiers)
    # Erfpacht was called a possible dealbreaker, so it never rises above "low", however
    # good the rest is. Perpetually bought-off erfpacht carries no canon risk, so it's exempt.
    if details.erfpacht and not details.erfpacht_perpetual:
        tier = "low"
    return Score(points, tier, tuple(sorted(reasons, key=lambda r: -abs(r.points))))


def _tier(points: int, tiers: Tiers) -> str:
    if points >= tiers.top:
        return "top"
    if points >= tiers.good:
        return "good"
    if points >= tiers.ok:
        return "ok"
    return "low"


def _balcony_points(size: int | None, w: Weights) -> int:
    """Rises from 2 m² to 8 m², then flattens: 8 to 12 m² adds a little, beyond that nothing."""
    if size is None:
        return w.balcony_unknown_size
    if size <= 2:
        return w.balcony_at_2_m2
    if size <= 8:
        return round(w.balcony_at_2_m2 + (w.balcony_at_8_m2 - w.balcony_at_2_m2) * (size - 2) / 6)
    if size <= 12:
        return round(w.balcony_at_8_m2 + (w.balcony_at_12_m2 - w.balcony_at_8_m2) * (size - 8) / 4)
    return w.balcony_at_12_m2


def _balcony_text(size: int | None) -> str:
    return f"balcony or terrace, {size} m²" if size is not None else "balcony or terrace"
