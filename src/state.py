import json
from datetime import datetime, timedelta
from pathlib import Path


class SeenState:
    """IDs of listings we've already handled, persisted as JSON in the repo."""

    def __init__(self, path: Path, seen: dict[str, str], existed: bool) -> None:
        self._path = path
        self._seen = seen
        self.existed = existed

    @classmethod
    def load(cls, path: Path) -> "SeenState":
        if not path.exists():
            return cls(path, {}, existed=False)
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(path, dict(data.get("seen", {})), existed=True)

    def __contains__(self, listing_id: str) -> bool:
        return listing_id in self._seen

    def __len__(self) -> int:
        return len(self._seen)

    def add(self, listing_id: str, now: datetime) -> None:
        self._seen.setdefault(listing_id, now.isoformat(timespec="seconds"))

    def prune(self, now: datetime, keep_days: int) -> None:
        """Drop old IDs so the file doesn't grow forever.

        Listings older than the search window never come back from the search,
        so forgetting them after a generous margin is safe.
        """
        cutoff = (now - timedelta(days=keep_days)).isoformat(timespec="seconds")
        self._seen = {i: seen_at for i, seen_at in self._seen.items() if seen_at >= cutoff}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"seen": dict(sorted(self._seen.items()))}
        self._path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        self.existed = True
