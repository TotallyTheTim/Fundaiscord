import pytest

from wijken import WijkMap, slugify

MAP = WijkMap(
    {
        "den-haag": {
            "Benoordenhout": ["Arendsdorp", "Van Hoytemastraat e.o."],
            "Bomen- en Bloemenbuurt": ["Bloemenbuurt-Oost", "Bomenbuurt"],
            "Centrum": ["Kortenbos"],
        },
        "delft": {"Binnenstad": ["Gasthuisbuurt"]},
    }
)


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Leyenburg", "leyenburg"),
        ("Van Hoytemastraat e.o.", "van-hoytemastraat-eo"),
        ("Bloemenbuurt-Oost", "bloemenbuurt-oost"),
        ("Zijden, Steden en Zichten", "zijden-steden-en-zichten"),
        ("Bohemen en Meer en Bos", "bohemen-en-meer-en-bos"),
        ("Azië Buurt", "azie-buurt"),
        ("'t Haantje", "t-haantje"),
    ],
)
def test_slugify_matches_fundas_area_slugs(name: str, slug: str) -> None:
    assert slugify(name) == slug


def test_area_slugs_cover_every_buurt_of_the_wanted_wijken() -> None:
    slugs = MAP.area_slugs("den-haag", frozenset({"Benoordenhout", "Bomen- en Bloemenbuurt"}))

    assert slugs == [
        "den-haag/arendsdorp",
        "den-haag/bloemenbuurt-oost",
        "den-haag/bomenbuurt",
        "den-haag/van-hoytemastraat-eo",
    ]


def test_area_slugs_are_scoped_to_the_search_location() -> None:
    assert MAP.area_slugs("delft", frozenset({"Binnenstad"})) == ["delft/gasthuisbuurt"]
    assert MAP.area_slugs("delft", frozenset({"Centrum"})) == []


def test_no_wijken_or_unknown_wijken_mean_no_area_restriction() -> None:
    assert MAP.area_slugs("den-haag", frozenset()) == []
    assert MAP.area_slugs("den-haag", frozenset({"Nowhere"})) == []
    assert MAP.area_slugs("amsterdam", frozenset({"Centrum"})) == []


def test_lookup_still_maps_a_funda_buurt_to_its_wijk() -> None:
    assert MAP.lookup("den-haag", "Van Hoytemastraat e.o.") == "Benoordenhout"
    assert MAP.lookup("den-haag", "Unknown buurt") is None
    assert MAP.lookup("den-haag", None) is None
