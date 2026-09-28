from dataclasses import replace

import pytest
from factories import make_candidate
from factories import make_details as details

from scoring import Score, ScoringConfig, Tiers, Weights, score_listing

CONFIG = ScoringConfig()


def score(candidate_overrides: dict[str, object] | None = None, **detail_overrides: object) -> Score:
    candidate = make_candidate(**{"bedrooms": 2, "energy_label": "C", **(candidate_overrides or {})})
    return score_listing(candidate, details(**detail_overrides), CONFIG)


def points_for(reason_text: str, result: Score) -> int:
    return next(r.points for r in result.reasons if reason_text in r.text)


def test_a_neutral_listing_scores_the_base_with_no_reasons() -> None:
    result = score()
    assert result.points == 50 and result.reasons == ()
    assert result.tier == "ok"


@pytest.mark.parametrize(
    ("size", "expected"),
    [(2, 3), (5, 8), (8, 12), (10, 14), (12, 15), (20, 15)],
)
def test_balcony_points_rise_to_8_m2_then_flatten(size: int, expected: int) -> None:
    result = score(balcony=True, outdoor_m2=size)
    assert points_for("balcony", result) == expected


def test_a_balcony_of_unknown_size_gets_the_middling_bonus() -> None:
    assert points_for("balcony", score(balcony=True)) == CONFIG.weights.balcony_unknown_size


def test_going_from_8_to_12_m2_adds_much_less_than_2_to_8() -> None:
    small_to_medium = points_for("balcony", score(balcony=True, outdoor_m2=8)) - points_for(
        "balcony", score(balcony=True, outdoor_m2=2)
    )
    medium_to_big = points_for("balcony", score(balcony=True, outdoor_m2=12)) - points_for(
        "balcony", score(balcony=True, outdoor_m2=8)
    )
    assert medium_to_big < small_to_medium


def test_erfpacht_is_a_heavy_penalty_and_forces_the_low_tier() -> None:
    result = score(
        {"bedrooms": 4, "energy_label": "A"},
        erfpacht=True,
        balcony=True,
        outdoor_m2=14,
        move_in_ready=True,
        garden=True,
        is_apartment=False,
        year_built=1925,
    )
    assert points_for("erfpacht", result) == -45
    assert result.points >= CONFIG.tiers.ok  # without the override this would be "ok" or better
    assert result.tier == "low"


def test_perpetually_bought_off_erfpacht_is_a_smaller_penalty_and_not_forced_low() -> None:
    result = score(
        erfpacht=True,
        erfpacht_perpetual=True,
        balcony=True,
        outdoor_m2=14,
        move_in_ready=True,
        year_built=1930,
    )
    assert points_for("erfpacht", result) == -25
    assert result.tier != "low"


def test_three_bedrooms_earn_the_office_bonus_and_two_do_not() -> None:
    assert points_for("bedrooms", score({"bedrooms": 3})) == 8
    assert not any("bedrooms" in r.text for r in score({"bedrooms": 2}).reasons)


def test_needs_work_is_penalised_and_move_in_ready_rewarded() -> None:
    assert points_for("needs work", score(needs_work=True)) == -20
    assert points_for("move-in ready", score(move_in_ready=True)) == 8


def test_house_first_floor_top_floor_garden_and_character_small_bonuses() -> None:
    result = score(is_apartment=False, floor=1, top_floor_hint=True, garden=True, year_built=1925)
    assert points_for("house", result) == 4
    assert points_for("first floor", result) == 3
    assert points_for("top floor", result) == 3
    assert points_for("garden", result) == 3
    assert points_for("pre-war", result) == 4


def test_a_1980s_building_gets_no_character_bonus() -> None:
    assert not any("pre-war" in r.text for r in score(year_built=1982).reasons)


def test_vve_problems_each_subtract() -> None:
    result = score(vve_reserve_fund=False, vve_maintenance_plan=False, vve_registered=False)
    assert points_for("reserve fund", result) == -10
    assert points_for("maintenance plan", result) == -6
    assert points_for("KvK", result) == -6


def test_a_healthy_vve_costs_nothing() -> None:
    result = score(vve_reserve_fund=True, vve_maintenance_plan=True, vve_registered=True, vve_monthly=150.0)
    assert result.reasons == ()


def test_an_expensive_vve_only_counts_without_a_lift() -> None:
    expensive = {"vve_monthly": 400.0}  # about €5/m² on 80 m²
    assert points_for("VvE €", score({"living_area": 80}, **expensive)) == -3
    assert not any("VvE €" in r.text for r in score({"living_area": 80}, lift=True, **expensive).reasons)


@pytest.mark.parametrize(
    ("label", "expected"),
    [("A++", 4), ("A", 4), ("B", 4), ("C", 0), ("D", -2), ("E", -4)],
)
def test_energy_label_points(label: str, expected: int) -> None:
    result = score_listing(make_candidate(bedrooms=2, energy_label=label), details(), CONFIG)
    assert sum(r.points for r in result.reasons if "energy label" in r.text) == expected


def test_the_score_is_clamped_between_0_and_100() -> None:
    best = score({"bedrooms": 4, "energy_label": "A"}, balcony=True, outdoor_m2=20, garden=True,
                 is_apartment=False, floor=1, top_floor_hint=True, move_in_ready=True, year_built=1900,
                 monument=True)
    worst = score(erfpacht=True, needs_work=True, vve_reserve_fund=False, vve_maintenance_plan=False,
                  vve_registered=False, busy_road=True)
    assert best.points == 100
    assert worst.points == 0


@pytest.mark.parametrize(
    ("points", "tier"),
    [(100, "top"), (70, "top"), (69, "good"), (55, "good"), (54, "ok"), (40, "ok"), (39, "low"), (0, "low")],
)
def test_tier_boundaries(points: int, tier: str) -> None:
    config = replace(CONFIG, base=points, weights=Weights(), tiers=Tiers())
    assert score_listing(make_candidate(bedrooms=2, energy_label="C"), details(), config).tier == tier


def test_reasons_are_ordered_by_impact() -> None:
    result = score(balcony=True, outdoor_m2=14, busy_road=True, needs_work=True)
    magnitudes = [abs(r.points) for r in result.reasons]
    assert magnitudes == sorted(magnitudes, reverse=True)


def test_weights_can_be_overridden() -> None:
    config = replace(CONFIG, weights=Weights(garden=20))
    result = score_listing(make_candidate(bedrooms=2, energy_label="C"), details(garden=True), config)
    assert points_for("garden", result) == 20


def test_zero_weights_leave_no_reason() -> None:
    config = replace(CONFIG, weights=Weights(garden=0))
    result = score_listing(make_candidate(bedrooms=2, energy_label="C"), details(garden=True), config)
    assert result.reasons == ()
