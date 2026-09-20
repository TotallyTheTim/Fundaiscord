import pytest
from factories import FILTERS, make_candidate

from filters import Verdict, evaluate

WANTED = frozenset({"Leyenburg"})


def check(**overrides: object) -> Verdict:
    return evaluate(make_candidate(**overrides), FILTERS, "Leyenburg", WANTED)


def check_wijk(wijk: str | None, wanted: frozenset[str] = WANTED) -> Verdict:
    return evaluate(make_candidate(), FILTERS, wijk, wanted)


def test_matching_listing_is_accepted_without_warnings() -> None:
    verdict = check()
    assert verdict.accepted
    assert verdict.warnings == ()


@pytest.mark.parametrize(
    ("price", "accepted"),
    [(300_000, True), (351_000, True), (351_001, False)],
)
def test_price_cap_is_inclusive(price: int, accepted: bool) -> None:
    assert check(price=price).accepted is accepted


@pytest.mark.parametrize(("area", "accepted"), [(70, True), (69, False)])
def test_minimum_surface(area: int, accepted: bool) -> None:
    assert check(living_area=area).accepted is accepted


@pytest.mark.parametrize(("bedrooms", "accepted"), [(2, True), (1, False)])
def test_minimum_bedrooms(bedrooms: int, accepted: bool) -> None:
    assert check(bedrooms=bedrooms).accepted is accepted


@pytest.mark.parametrize("label", ["A++++", "A+", "A", "B", "C", "D"])
def test_labels_a_to_d_are_always_accepted(label: str) -> None:
    assert check(energy_label=label, price=350_000).accepted


@pytest.mark.parametrize(
    ("price", "accepted"),
    [(299_999, True), (300_000, False), (340_000, False)],
)
def test_label_e_needs_price_strictly_under_300k(price: int, accepted: bool) -> None:
    assert check(energy_label="E", price=price).accepted is accepted


@pytest.mark.parametrize("label", ["F", "G"])
def test_labels_f_and_g_are_never_accepted(label: str) -> None:
    assert not check(energy_label=label, price=100_000).accepted


def test_label_is_case_and_whitespace_insensitive() -> None:
    assert check(energy_label=" b ").accepted


def test_wijk_outside_the_wanted_set_is_rejected() -> None:
    assert not check_wijk("Centrum").accepted


def test_no_wijk_filter_when_search_lists_none() -> None:
    assert check_wijk("Centrum", wanted=frozenset()).accepted


@pytest.mark.parametrize(
    ("overrides", "warning"),
    [
        ({"energy_label": None}, "energy label unknown"),
        ({"living_area": None}, "surface unknown"),
        ({"bedrooms": None}, "bedrooms unknown"),
        ({"price": None}, "price unknown"),
    ],
)
def test_missing_fields_pass_with_a_warning(overrides: dict[str, object], warning: str) -> None:
    verdict = check(**overrides)
    assert verdict.accepted
    assert warning in verdict.warnings


def test_unmapped_wijk_passes_with_a_warning() -> None:
    verdict = check_wijk(None)
    assert verdict.accepted
    assert "wijk unknown" in verdict.warnings


def test_label_e_with_unknown_price_passes_with_only_the_price_warning() -> None:
    verdict = check(energy_label="E", price=None)
    assert verdict.accepted
    assert verdict.warnings == ("price unknown",)


def test_a_known_failing_field_rejects_even_when_others_are_unknown() -> None:
    verdict = check(price=400_000, energy_label=None)
    assert not verdict.accepted
    assert "energy label unknown" in verdict.warnings
