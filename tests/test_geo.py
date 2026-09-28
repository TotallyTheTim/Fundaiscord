import json
from pathlib import Path

import pytest

from geo import haversine_metres, load_points, nearest_metres

# Den Haag Centraal to Delft (station area), used only as a sanity-checked reference distance.
DEN_HAAG = (52.0808, 4.3247)
DELFT = (52.0068, 4.3557)


def test_haversine_zero_for_the_same_point() -> None:
    assert haversine_metres(DEN_HAAG, DEN_HAAG) == 0.0


def test_haversine_matches_a_known_real_world_distance() -> None:
    # Den Haag Centraal to Delft station is about 8.6 km as the crow flies.
    assert 8_000 < haversine_metres(DEN_HAAG, DELFT) < 9_500


def test_haversine_is_symmetric() -> None:
    assert haversine_metres(DEN_HAAG, DELFT) == pytest.approx(haversine_metres(DELFT, DEN_HAAG))


def test_nearest_metres_picks_the_closest_point() -> None:
    far = (52.3, 4.3)
    near = (52.081, 4.325)
    assert nearest_metres(DEN_HAAG, [far, near]) == haversine_metres(DEN_HAAG, near)


def test_nearest_metres_of_an_empty_list_is_none() -> None:
    assert nearest_metres(DEN_HAAG, []) is None


def test_load_points_reads_lat_lon_pairs(tmp_path: Path) -> None:
    path = tmp_path / "points.json"
    path.write_text(json.dumps({"points": [[52.08, 4.32], [52.01, 4.36]]}), encoding="utf-8")

    assert load_points(path) == [(52.08, 4.32), (52.01, 4.36)]


def test_load_points_missing_file_is_an_empty_list(tmp_path: Path) -> None:
    assert load_points(tmp_path / "nope.json") == []


def test_load_points_malformed_file_is_an_empty_list(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not json", encoding="utf-8")
    assert load_points(path) == []


def test_load_points_missing_key_is_an_empty_list(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text("{}", encoding="utf-8")
    assert load_points(path) == []
