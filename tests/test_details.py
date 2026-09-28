from collections.abc import Mapping

import pytest

from details import Details, parse_details


def parse(
    labels: Mapping[str, str] | None = None,
    description: str = "",
    year_built: int | None = 1965,
    is_apartment: bool = True,
    monument: bool = False,
) -> Details:
    return parse_details(labels or {}, description, year_built, is_apartment, monument)


def test_an_empty_page_gives_no_facts_rather_than_guesses() -> None:
    d = parse()

    assert d.ownership is None and not d.erfpacht
    assert d.floor is None and d.vve_monthly is None
    assert d.vve_reserve_fund is None and d.vve_maintenance_plan is None
    assert not d.balcony and d.outdoor_m2 is None and not d.garden and not d.lift


@pytest.mark.parametrize(
    "ownership",
    [
        "Erfpacht",
        "Gemeentelijke erfpacht",
        "Eigendom belast met erfpacht",
        "Erfpacht (einddatum erfpacht: 31-12-2035)",
    ],
)
def test_every_erfpacht_wording_is_detected(ownership: str) -> None:
    assert parse({"Eigendomssituatie": ownership}).erfpacht


def test_freehold_is_not_erfpacht() -> None:
    d = parse({"Eigendomssituatie": "Volle eigendom"})
    assert not d.erfpacht and d.ownership == "Volle eigendom"


def test_an_erfpacht_label_elsewhere_on_the_page_also_counts() -> None:
    assert parse({"Erfpachtcanon": "€ 300 per jaar"}).erfpacht


def test_a_perpetual_buyoff_in_the_description_is_recognised() -> None:
    d = parse({"Eigendomssituatie": "Gemeentelijke erfpacht"}, "De canon is eeuwigdurend afgekocht.")
    assert d.erfpacht and d.erfpacht_perpetual


def test_a_buyoff_only_until_a_date_is_not_perpetual() -> None:
    d = parse({"Eigendomssituatie": "Erfpacht"}, "Canon afgekocht tot en met 2055.")
    assert d.erfpacht and not d.erfpacht_perpetual


def test_perpetual_wording_without_erfpacht_is_ignored() -> None:
    assert not parse({"Eigendomssituatie": "Volle eigendom"}, "eeuwigdurend afgekocht").erfpacht_perpetual


@pytest.mark.parametrize(
    ("label", "floor"),
    [("Begane grond", 0), ("1e woonlaag", 1), ("3e woonlaag", 3), ("10e woonlaag", 10), ("2e verdieping", 2)],
)
def test_floor_is_read_from_the_dutch_label(label: str, floor: int) -> None:
    d = parse({"Gelegen op": label})
    assert d.floor == floor and d.floor_label == label


def test_an_unreadable_floor_label_is_unknown() -> None:
    assert parse({"Gelegen op": "Maisonnette"}).floor is None


def test_a_balcony_label_means_a_balcony() -> None:
    d = parse({"Balkon/dakterras": "Balkon aanwezig"})
    assert d.balcony and d.outdoor_m2 is None


def test_building_attached_outdoor_space_gives_the_size_and_counts_as_a_balcony() -> None:
    d = parse({"Gebouwgebonden buitenruimte": "11 m²"})
    assert d.balcony and d.outdoor_m2 == 11


def test_no_outdoor_labels_means_no_balcony() -> None:
    assert not parse({"Ligging": "In woonwijk"}).balcony


@pytest.mark.parametrize("label", ["Tuin", "Achtertuin", "Voortuin"])
def test_garden_labels(label: str) -> None:
    assert parse({label: "Patio/atrium"}).garden


@pytest.mark.parametrize(
    ("text", "amount"),
    [("€ 200,00 per maand", 200.0), ("Ja (€ 175,50 per maand)", 175.5), ("€ 1.234,50 per maand", 1234.5)],
)
def test_vve_contribution_amounts(text: str, amount: float) -> None:
    assert parse({"Bijdrage VvE": text}).vve_monthly == amount


def test_the_vve_checklist_amount_is_used_when_the_headline_one_is_missing() -> None:
    assert parse({"Periodieke bijdrage": "Ja (€ 90,00 per maand)"}).vve_monthly == 90.0


@pytest.mark.parametrize(("value", "expected"), [("Ja", True), ("Nee", False), ("Onbekend", None), ("", None)])
def test_vve_checklist_answers(value: str, expected: bool | None) -> None:
    d = parse({"Reservefonds aanwezig": value, "Onderhoudsplan": value, "Inschrijving KvK": value})
    assert d.vve_reserve_fund is expected
    assert d.vve_maintenance_plan is expected
    assert d.vve_registered is expected


def test_lift_and_busy_road() -> None:
    d = parse({"Voorzieningen": "Lift, TV kabel", "Ligging": "Aan drukke weg en in woonwijk"})
    assert d.lift and d.busy_road
    assert not parse({"Ligging": "Aan rustige weg"}).busy_road


@pytest.mark.parametrize(
    "text",
    ["Klussers opgelet!", "Dit is een kluswoning.", "Het appartement is op te knappen.", "Volledig te renoveren top etage"],
)
def test_needs_work_wording(text: str) -> None:
    d = parse(description=text)
    assert d.needs_work and not d.move_in_ready


@pytest.mark.parametrize(
    "text",
    ["Instapklaar appartement", "Recent gerenoveerd en direct te betrekken", "Met nieuwe keuken en badkamer"],
)
def test_move_in_ready_wording(text: str) -> None:
    d = parse(description=text)
    assert d.move_in_ready and not d.needs_work


def test_needs_work_wins_over_move_in_ready() -> None:
    d = parse(description="Instapklaar? Nee, een kluswoning met nieuwe keuken.")
    assert d.needs_work and not d.move_in_ready


def test_a_plain_description_is_neither() -> None:
    d = parse(description="Ruim appartement met drie kamers, gelegen aan een rustige straat.")
    assert not d.needs_work and not d.move_in_ready


@pytest.mark.parametrize("text", ["Ruime top etage", "Bovenste verdieping met dakterras", "Penthouse aan de rand van het park"])
def test_top_floor_hints(text: str) -> None:
    assert parse(description=text).top_floor_hint
