from dataclasses import dataclass, field

from details import Details
from models import Candidate

TIER_ORDER = ("low", "ok", "good", "top")
# Best to worst. "C" is the scoring baseline (0 points); every step away is scored
# relative to it, so this order is what makes that comparison possible.
ENERGY_LABEL_ORDER = ("A++++", "A+++", "A++", "A+", "A", "B", "C", "D", "E", "F", "G")


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
    # Points per EUR/m²/month the VvE fee sits above `vve_expensive_per_m2`; a lift halves
    # this rate rather than waiving it, since a very expensive VvE is a cost either way.
    vve_expensive_per_m2_rate: float = -4
    busy_road: int = -2
    label_step_up: int = 5  # per step better than "C" (B, A, A+, ...)
    label_step_down: int = 6  # magnitude subtracted per step worse than "C" (D, E, ...)
    supermarket_penalty_per_100m: int = -1  # applied for every full 100 m to the nearest one
    # Points per EUR/m² the price sits below (bonus) or above (penalty) `price_per_m2_reference`.
    price_per_m2_rate: float = 0.02


@dataclass(frozen=True)
class Tiers:
    """Minimum score for each tier; anything below `ok` is `low`."""

    top: int = 70
    good: int = 55
    ok: int = 40


@dataclass(frozen=True)
class ScoringConfig:
    base: int = 50
    # EUR/m²/month above which a VvE fee starts counting as expensive (a lift halves the
    # resulting penalty's rate rather than waiving it; see Weights.vve_expensive_per_m2_rate).
    vve_expensive_per_m2: float = 2.5
    # Most negative the VvE-cost penalty can go, so one very expensive outlier can't tank
    # the score on its own.
    vve_expensive_cap: int = -15
    # Most negative the supermarket-distance penalty can go, so a data glitch (or a
    # genuinely remote listing) can't tank the score on its own.
    supermarket_penalty_cap: int = -10
    # EUR/m², the "normal" price for the current Den Haag/Rijswijk/Delft market (its real
    # median as of Sept 2026). Cheaper than this is a bonus, pricier is a penalty; like the
    # balcony curve, it's a snapshot that will want an occasional manual refresh.
    price_per_m2_reference: int = 4157
    # The price/m² bonus and penalty are both capped at this many points either way.
    price_per_m2_cap: int = 12
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
    if details.vve_monthly and candidate.living_area:
        per_m2 = details.vve_monthly / candidate.living_area
        excess = per_m2 - config.vve_expensive_per_m2
        if excess > 0:
            rate = w.vve_expensive_per_m2_rate * (0.5 if details.lift else 1.0)
            penalty = max(config.vve_expensive_cap, round(rate * excess))
            suffix = "lift halves this" if details.lift else "no lift"
            add(penalty, f"VvE €{per_m2:.1f}/m² ({suffix})")

    if details.busy_road:
        add(w.busy_road, "busy road")

    if details.distance_to_supermarket_m is not None:
        steps = int(details.distance_to_supermarket_m // 100)  # 0 for anything under 100 m
        penalty = max(config.supermarket_penalty_cap, steps * w.supermarket_penalty_per_100m)
        add(penalty, f"{round(details.distance_to_supermarket_m)} m to nearest supermarket")

    if candidate.price and candidate.living_area:
        price_per_m2 = candidate.price / candidate.living_area
        raw = (config.price_per_m2_reference - price_per_m2) * w.price_per_m2_rate
        capped = max(-config.price_per_m2_cap, min(config.price_per_m2_cap, round(raw)))
        add(capped, f"€{price_per_m2:,.0f}/m² vs €{config.price_per_m2_reference:,}/m² typical")

    label = (candidate.energy_label or "").strip().upper()
    if label in ENERGY_LABEL_ORDER:
        # Positive = better than C (lower index), negative = worse.
        steps = ENERGY_LABEL_ORDER.index("C") - ENERGY_LABEL_ORDER.index(label)
        add(steps * w.label_step_up if steps > 0 else steps * w.label_step_down, f"energy label {label}")

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
