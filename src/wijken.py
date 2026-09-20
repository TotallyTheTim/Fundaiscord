import json
import re
import unicodedata
from pathlib import Path


def normalize(name: str) -> str:
    """Lowercase, strip accents and punctuation so Funda and CBS spellings compare equal."""
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", ascii_only.lower()).strip()


class WijkMap:
    """Resolves a Funda buurt name to the CBS wijk it belongs to, per search location."""

    def __init__(self, wijken_by_location: dict[str, dict[str, list[str]]]) -> None:
        self._buurt_to_wijk: dict[str, dict[str, str]] = {
            location: {
                normalize(buurt): wijk
                for wijk, buurten in wijken.items()
                for buurt in buurten
            }
            for location, wijken in wijken_by_location.items()
        }
        self._wijken: dict[str, frozenset[str]] = {
            location: frozenset(wijken) for location, wijken in wijken_by_location.items()
        }

    @classmethod
    def load(cls, path: Path) -> "WijkMap":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def known_wijken(self, location: str) -> frozenset[str]:
        return self._wijken.get(location, frozenset())

    def lookup(self, location: str, buurt: str | None) -> str | None:
        if not buurt:
            return None
        return self._buurt_to_wijk.get(location, {}).get(normalize(buurt))
