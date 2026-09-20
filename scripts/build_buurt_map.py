"""Regenerate data/buurt-wijk.json from CBS open data.

Funda reports a listing's `neighbourhood` at buurt level, while wijken are the
unit we filter on, so we need a buurt -> wijk lookup. CBS publishes that
hierarchy in the politie wijk/buurt table (descriptions read "Buurt X is een
buurt in wijk Y").

Usage: python scripts/build_buurt_map.py
"""

import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

CBS_REGIONS = "https://dataderden.cbs.nl/ODataApi/odata/47022NED/WijkenEnBuurten"

# Funda location slug -> CBS gemeente code
CITIES = {
    "den-haag": "0518",
    "rijswijk-zh": "0603",
    "delft": "0503",
}

OUTPUT = Path(__file__).resolve().parent.parent / "data" / "buurt-wijk.json"


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


def short_wijk_name(title: str) -> str:
    """'Wijk 11 Duinoord' -> 'Duinoord'; unnamed 'Wijk 01' stays as is."""
    match = re.fullmatch(r"Wijk \d+ (.+)", title)
    return match.group(1) if match else title


def buurten_by_wijk(gemeente_code: str) -> dict[str, list[str]]:
    flt = urllib.parse.quote(f"startswith(Key,'BU{gemeente_code}')")
    rows = fetch_json(f"{CBS_REGIONS}?$format=json&$filter={flt}")["value"]
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        match = re.search(r"in wijk '([^']+)'", row.get("Description") or "")
        if match:
            grouped[short_wijk_name(match.group(1))].append(row["Title"])
    return {wijk: sorted(buurten) for wijk, buurten in sorted(grouped.items())}


def main() -> None:
    result = {city: buurten_by_wijk(code) for city, code in CITIES.items()}
    OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for city, wijken in result.items():
        print(city, len(wijken), "wijken,", sum(map(len, wijken.values())), "buurten")


if __name__ == "__main__":
    main()
