"""Regenerate docs/supermarkets.json from OpenStreetMap (Overpass API).

Scoring penalises listings far from a supermarket (see scoring.py), which needs a
list of supermarket coordinates across Den Haag, Rijswijk and Delft. The file lives
under docs/ (not data/) so the same one is both read by the bot and served by the
web page for the map. Re-run this occasionally (supermarkets open and close); it
isn't run automatically.

Usage: python scripts/build_supermarkets.py
"""

import json
import urllib.parse
import urllib.request
from pathlib import Path

# Covers Den Haag, Rijswijk and Delft with margin (south, west, north, east).
BBOX = "51.93,4.15,52.15,4.45"
ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "supermarkets.json"


def fetch_supermarkets() -> list[tuple[float, float, str | None]]:
    query = f'[out:json][timeout:90];(nwr["shop"="supermarket"]({BBOX}););out center tags;'
    last_error: Exception | None = None
    for url in ENDPOINTS:
        try:
            request = urllib.request.Request(
                url,
                data=urllib.parse.urlencode({"data": query}).encode(),
                headers={"User-Agent": "funda-watch/1.0 (personal listing watcher)"},
            )
            with urllib.request.urlopen(request, timeout=100) as response:
                elements = json.load(response)["elements"]
            break
        except Exception as error:  # try the next mirror
            last_error = error
    else:
        raise RuntimeError(f"all Overpass endpoints failed: {last_error}")

    points = []
    for element in elements:
        lat = element.get("lat") or element.get("center", {}).get("lat")
        lon = element.get("lon") or element.get("center", {}).get("lon")
        if lat is not None and lon is not None:
            name = (element.get("tags") or {}).get("name")  # for the map's popups; scoring ignores it
            points.append((lat, lon, name))
    return points


def main() -> None:
    points = fetch_supermarkets()
    OUTPUT.write_text(json.dumps({"points": points}, indent=1) + "\n", encoding="utf-8")
    print(f"{len(points)} supermarkets written to {OUTPUT}")


if __name__ == "__main__":
    main()
