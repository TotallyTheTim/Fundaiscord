from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class EnergyLabelRules:
    always: frozenset[str]
    only_below_price: dict[str, int]


@dataclass(frozen=True)
class Filters:
    max_price: int
    min_surface: int
    min_bedrooms: int
    max_age_days: int
    energy_labels: EnergyLabelRules


@dataclass(frozen=True)
class SearchConfig:
    name: str
    location: str
    wijken: frozenset[str]


@dataclass(frozen=True)
class Config:
    notify_existing: bool
    filters: Filters
    searches: tuple[SearchConfig, ...]


def _label(value: object) -> str:
    return str(value).strip().upper()


def _parse_filters(raw: dict[str, Any]) -> Filters:
    labels = raw.get("energy_labels", {})
    return Filters(
        max_price=int(raw["max_price"]),
        min_surface=int(raw["min_surface"]),
        min_bedrooms=int(raw["min_bedrooms"]),
        max_age_days=int(raw["max_age_days"]),
        energy_labels=EnergyLabelRules(
            always=frozenset(_label(label) for label in labels.get("always", [])),
            only_below_price={
                _label(label): int(price)
                for label, price in labels.get("only_below_price", {}).items()
            },
        ),
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
        filters=_parse_filters(raw["filters"]),
        searches=searches,
    )
