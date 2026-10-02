from pathlib import Path

import pytest

from config import load_config
from scoring import ScoringConfig

BASE = """
startup: {notify_existing: true}
notifications: {old_listing_after_days: 3}
sweep: {full_every_hours: 12}
filters:
  max_price: 401000
  min_surface: 75
  min_bedrooms: 2
  energy_labels: {always: [A, B, C, D], only_below_price: {E: 300000}}
searches:
  - {name: Den Haag, location: den-haag, wijken: [Leyenburg]}
"""


def test_scoring_defaults_apply_when_the_section_is_missing(tmp_path: Path) -> None:
    assert load_config(_write(tmp_path, "")).scoring == ScoringConfig()


def test_an_empty_scoring_section_also_means_defaults(tmp_path: Path) -> None:
    assert load_config(_write(tmp_path, "scoring:\n")).scoring == ScoringConfig()


def test_individual_weights_tiers_and_base_can_be_overridden(tmp_path: Path) -> None:
    extra = """
scoring:
  base: 40
  vve_expensive_per_m2: 4.5
  vve_expensive_cap: -25
  supermarket_penalty_cap: -20
  price_per_m2_reference: 4000
  price_per_m2_cap: 20
  tiers: {top: 80}
  weights: {garden: 10, erfpacht: -60, supermarket_penalty_per_100m: -2, label_step_up: 3, price_per_m2_rate: 0.05}
"""
    scoring = load_config(_write(tmp_path, extra)).scoring

    assert scoring.base == 40 and scoring.vve_expensive_per_m2 == 4.5
    assert scoring.vve_expensive_cap == -25
    assert scoring.supermarket_penalty_cap == -20
    assert scoring.price_per_m2_reference == 4000 and scoring.price_per_m2_cap == 20
    assert scoring.tiers.top == 80 and scoring.tiers.good == 55  # untouched keys keep defaults
    assert scoring.weights.garden == 10 and scoring.weights.erfpacht == -60
    assert scoring.weights.supermarket_penalty_per_100m == -2
    assert scoring.weights.label_step_up == 3 and scoring.weights.label_step_down == 6
    assert scoring.weights.price_per_m2_rate == 0.05
    assert scoring.weights.house == 4


def test_a_misspelled_weight_is_an_error_not_silently_ignored(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        load_config(_write(tmp_path, "scoring:\n  weights: {gardn: 10}\n"))


def test_the_committed_config_parses_and_its_scoring_matches_the_defaults() -> None:
    root = Path(__file__).resolve().parent.parent
    assert load_config(root / "config.yaml").scoring == ScoringConfig()


def _write(tmp_path: Path, extra: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(BASE + extra, encoding="utf-8")
    return path
