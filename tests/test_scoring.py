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


PRICE_AT_REFERENCE = CONFIG.price_per_m2_reference * 80  # cancels the price/m² signal at living_area=80


def test_a_neutral_listing_scores_the_base_with_no_reasons() -> None:
    result = score({"price": PRICE_AT_REFERENCE})
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
    result = score(
        {"price": PRICE_AT_REFERENCE},
        vve_reserve_fund=True, vve_maintenance_plan=True, vve_registered=True, vve_monthly=150.0,
    )
    assert result.reasons == ()


def test_vve_cost_is_free_up_to_the_threshold() -> None:
    at_threshold = CONFIG.vve_expensive_per_m2 * 80  # living_area defaults to 80 -> exactly 0 excess
    assert not any("VvE €" in r.text for r in score(vve_monthly=at_threshold).reasons)


def test_vve_cost_above_the_threshold_scales_with_the_excess() -> None:
    # 80 m², EUR 400/mo -> EUR 5.00/m², 2.5 above the 2.5 threshold, rate -4 -> -10
    assert points_for("VvE €", score(vve_monthly=400.0)) == -10


def test_a_lift_halves_the_vve_cost_penalty_instead_of_waiving_it() -> None:
    assert points_for("VvE €", score(vve_monthly=400.0, lift=True)) == -5


def test_the_vve_cost_penalty_is_capped() -> None:
    assert points_for("VvE €", score(vve_monthly=2000.0)) == CONFIG.vve_expensive_cap


def test_the_vve_cost_reason_says_whether_a_lift_helped() -> None:
    no_lift = next(r.text for r in score(vve_monthly=400.0).reasons if "VvE €" in r.text)
    with_lift = next(r.text for r in score(vve_monthly=400.0, lift=True).reasons if "VvE €" in r.text)
    assert "no lift" in no_lift
    assert "lift halves this" in with_lift


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("A++++", 30), ("A+++", 25), ("A++", 20), ("A+", 15), ("A", 10), ("B", 5),
        ("C", 0),
        ("D", -6), ("E", -12), ("F", -18), ("G", -24),
    ],
)
def test_energy_label_points_ramp_from_c(label: str, expected: int) -> None:
    result = score_listing(make_candidate(bedrooms=2, energy_label=label), details(), CONFIG)
    assert sum(r.points for r in result.reasons if "energy label" in r.text) == expected


def test_energy_label_is_case_and_whitespace_insensitive() -> None:
    result = score_listing(make_candidate(bedrooms=2, energy_label=" a+++ "), details(), CONFIG)
    assert points_for("energy label", result) == 25


def test_an_unrecognised_energy_label_contributes_nothing() -> None:
    result = score_listing(make_candidate(bedrooms=2, energy_label="unknown"), details(), CONFIG)
    assert not any("energy label" in r.text for r in result.reasons)


def test_price_per_m2_is_neutral_exactly_at_the_reference() -> None:
    result = score({"price": PRICE_AT_REFERENCE, "living_area": 80})
    assert not any("typical" in r.text for r in result.reasons)


def test_below_reference_price_per_m2_gives_a_bonus() -> None:
    cheap = round((CONFIG.price_per_m2_reference - 500) * 80)  # EUR 500/m² cheaper than typical
    assert points_for("typical", score({"price": cheap, "living_area": 80})) == 10  # 500 * 0.02


def test_above_reference_price_per_m2_gives_a_penalty() -> None:
    pricey = round((CONFIG.price_per_m2_reference + 500) * 80)
    assert points_for("typical", score({"price": pricey, "living_area": 80})) == -10


def test_the_price_per_m2_bonus_and_penalty_are_both_capped() -> None:
    very_cheap = round((CONFIG.price_per_m2_reference - 5000) * 80)
    very_pricey = round((CONFIG.price_per_m2_reference + 5000) * 80)
    assert points_for("typical", score({"price": very_cheap, "living_area": 80})) == CONFIG.price_per_m2_cap
    assert points_for("typical", score({"price": very_pricey, "living_area": 80})) == -CONFIG.price_per_m2_cap


def test_no_price_per_m2_signal_without_both_price_and_area() -> None:
    assert not any("typical" in r.text for r in score({"price": None}).reasons)
    assert not any("typical" in r.text for r in score({"living_area": None}).reasons)


def test_no_supermarket_distance_known_gives_no_reason() -> None:
    result = score(distance_to_supermarket_m=None)
    assert not any("supermarket" in r.text for r in result.reasons)


def test_within_100m_of_a_supermarket_has_no_penalty() -> None:
    for distance in (0, 12, 99):
        result = score(distance_to_supermarket_m=distance)
        assert not any("supermarket" in r.text for r in result.reasons), distance


@pytest.mark.parametrize(
    ("distance", "expected_points"),
    [(100, -1), (250, -2), (650, -6), (999, -9)],
)
def test_supermarket_penalty_scales_in_100m_steps(distance: int, expected_points: int) -> None:
    result = score(distance_to_supermarket_m=distance)
    assert points_for("supermarket", result) == expected_points


def test_the_supermarket_penalty_is_capped() -> None:
    result = score(distance_to_supermarket_m=5000)
    assert points_for("supermarket", result) == CONFIG.supermarket_penalty_cap


def test_the_supermarket_reason_names_the_rounded_distance() -> None:
    result = score(distance_to_supermarket_m=647.8)
    assert any(r.text == "648 m to nearest supermarket" for r in result.reasons)


def test_the_score_is_clamped_between_0_and_100() -> None:
    best = score({"bedrooms": 4, "energy_label": "A"}, balcony=True, outdoor_m2=20, garden=True,
                 is_apartment=False, floor=1, top_floor_hint=True, move_in_ready=True, year_built=1900,
                 monument=True)
    worst = score(erfpacht=True, needs_work=True, vve_reserve_fund=False, vve_maintenance_plan=False,
                  vve_registered=False, busy_road=True, distance_to_supermarket_m=5000)
    assert best.points == 100
    assert worst.points == 0


@pytest.mark.parametrize(
    ("points", "tier"),
    [(100, "top"), (70, "top"), (69, "good"), (55, "good"), (54, "ok"), (40, "ok"), (39, "low"), (0, "low")],
)
def test_tier_boundaries(points: int, tier: str) -> None:
    config = replace(CONFIG, base=points, weights=Weights(), tiers=Tiers())
    # Price defaults to below the reference (a bonus); pin it at the reference so `base`
    # alone decides the tier, keeping this test isolated to just the tier thresholds.
    candidate = make_candidate(bedrooms=2, energy_label="C", price=config.price_per_m2_reference * 80)
    assert score_listing(candidate, details(), config).tier == tier


def test_reasons_are_ordered_by_impact() -> None:
    result = score(balcony=True, outdoor_m2=14, busy_road=True, needs_work=True)
    magnitudes = [abs(r.points) for r in result.reasons]
    assert magnitudes == sorted(magnitudes, reverse=True)


def test_weights_can_be_overridden() -> None:
    config = replace(CONFIG, weights=Weights(garden=20))
    result = score_listing(make_candidate(bedrooms=2, energy_label="C"), details(garden=True), config)
    assert points_for("garden", result) == 20


def test_zero_weights_leave_no_reason() -> None:
    config = replace(CONFIG, weights=Weights(garden=0, price_per_m2_rate=0))
    result = score_listing(make_candidate(bedrooms=2, energy_label="C"), details(garden=True), config)
    assert result.reasons == ()
