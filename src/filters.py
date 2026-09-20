from dataclasses import dataclass
from datetime import datetime, timedelta

from config import Filters
from models import Candidate


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    rejections: tuple[str, ...]
    # Fields Funda didn't give us. A listing with unknown fields still passes
    # (better a noisy alert than a missed house) but the alert flags them.
    warnings: tuple[str, ...]


def normalize_label(label: str | None) -> str | None:
    cleaned = (label or "").strip().upper()
    return cleaned or None


def evaluate(
    candidate: Candidate,
    filters: Filters,
    now: datetime,
    wijk: str | None,
    wanted_wijken: frozenset[str],
) -> Verdict:
    rejections: list[str] = []
    warnings: list[str] = []

    if candidate.price is None:
        warnings.append("price unknown")
    elif candidate.price > filters.max_price:
        rejections.append(f"price {candidate.price} above {filters.max_price}")

    if candidate.living_area is None:
        warnings.append("surface unknown")
    elif candidate.living_area < filters.min_surface:
        rejections.append(f"surface {candidate.living_area} below {filters.min_surface}")

    if candidate.bedrooms is None:
        warnings.append("bedrooms unknown")
    elif candidate.bedrooms < filters.min_bedrooms:
        rejections.append(f"bedrooms {candidate.bedrooms} below {filters.min_bedrooms}")

    _check_energy_label(candidate, filters, rejections, warnings)

    if candidate.published is None:
        warnings.append("listing date unknown")
    elif candidate.published < now - timedelta(days=filters.max_age_days):
        rejections.append(f"published {candidate.published.isoformat()}, too old")

    if wanted_wijken:
        if wijk is None:
            warnings.append("wijk unknown")
        elif wijk not in wanted_wijken:
            rejections.append(f"wijk {wijk} not wanted")

    return Verdict(
        accepted=not rejections,
        rejections=tuple(rejections),
        warnings=tuple(warnings),
    )


def _check_energy_label(
    candidate: Candidate,
    filters: Filters,
    rejections: list[str],
    warnings: list[str],
) -> None:
    label = normalize_label(candidate.energy_label)
    rules = filters.energy_labels
    if label is None:
        warnings.append("energy label unknown")
    elif label in rules.always:
        return
    elif label in rules.only_below_price:
        limit = rules.only_below_price[label]
        if candidate.price is None:
            return  # price already flagged as unknown
        if candidate.price >= limit:
            rejections.append(f"label {label} only accepted below {limit}")
    else:
        rejections.append(f"label {label} not accepted")
