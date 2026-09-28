from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from scoring import ScoringConfig, Tiers, Weights


@dataclass(frozen=True)
class EnergyLabelRules:
    always: frozenset[str]
    only_below_price: dict[str, int]


@dataclass(frozen=True)
class Filters:
    max_price: int
    min_surface: int
    min_bedrooms: int
    energy_labels: EnergyLabelRules


@dataclass(frozen=True)
class SearchConfig:
    name: str
    location: str
    wijken: frozenset[str]


@dataclass(frozen=True)
class Config:
    notify_existing: bool
    old_listing_after_days: int
    full_sweep_every_hours: int
    filters: Filters
    searches: tuple[SearchConfig, ...]
    scoring: ScoringConfig = field(default_factory=ScoringConfig)


def _label(value: object) -> str:
    return str(value).strip().upper()


def _parse_filters(raw: dict[str, Any]) -> Filters:
    labels = raw.get("energy_labels", {})
    return Filters(
        max_price=int(raw["max_price"]),
        min_surface=int(raw["min_surface"]),
        min_bedrooms=int(raw["min_bedrooms"]),
        energy_labels=EnergyLabelRules(
            always=frozenset(_label(label) for label in labels.get("always", [])),
            only_below_price={
                _label(label): int(price)
                for label, price in labels.get("only_below_price", {}).items()
            },
        ),
    )


def _parse_scoring(raw: dict[str, Any]) -> ScoringConfig:
    """Overrides on top of the defaults. An unknown key raises, so a typo can't silently do nothing."""
    defaults = ScoringConfig()
    return ScoringConfig(
        base=int(raw.get("base", defaults.base)),
        vve_expensive_per_m2=float(raw.get("vve_expensive_per_m2", defaults.vve_expensive_per_m2)),
        tiers=Tiers(**raw.get("tiers", {})),
        weights=Weights(**raw.get("weights", {})),
    )


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    searches = tuple(
        SearchConfig(
            name=str(item["name"]),
            location=str(item["location"]),
            wijken=frozenset(item.get("wijken", [])),
        )
        for item in raw["searches"]
    )
    if not searches:
        raise ValueError("config needs at least one search")
    return Config(
        notify_existing=bool(raw.get("startup", {}).get("notify_existing", False)),
        old_listing_after_days=int(raw["notifications"]["old_listing_after_days"]),
        full_sweep_every_hours=int(raw["sweep"]["full_every_hours"]),
        filters=_parse_filters(raw["filters"]),
        searches=searches,
        scoring=_parse_scoring(raw.get("scoring") or {}),
    )
