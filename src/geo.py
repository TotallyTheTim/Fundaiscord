import json
import math
from collections.abc import Iterable
from pathlib import Path

Point = tuple[float, float]  # (latitude, longitude)

_EARTH_RADIUS_M = 6_371_000


def haversine_metres(a: Point, b: Point) -> float:
    """Straight-line distance between two lat/lon points, in metres."""
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat = lat2 - lat1
    dlon = math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(h))


def nearest_metres(point: Point, others: Iterable[Point]) -> float | None:
    """Distance to the closest point in `others`, or None if it's empty."""
    best: float | None = None
    for other in others:
        distance = haversine_metres(point, other)
        if best is None or distance < best:
            best = distance
    return best


def load_points(path: Path) -> list[Point]:
    """Reads a {"points": [[lat, lon], ...]} file. Missing or unreadable means no points.

    Each entry may carry a third element (a name, for the web page's map popups);
    it's ignored here since scoring only needs the coordinates.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [(float(entry[0]), float(entry[1])) for entry in raw.get("points", [])]
