import json
from datetime import datetime, timedelta
from pathlib import Path

# An ID that keeps showing up is only re-stamped this often, so the state file
# doesn't change (and get committed) on every run.
TOUCH_INTERVAL_DAYS = 7


class SeenState:
    """Listings we've already handled, persisted as JSON in the repo.

    `seen` maps listing ID -> last time we saw it. `baselined` is False until a
    run has recorded every currently-matching listing without alerting on old ones,
    which also covers state files written before that concept existed.
    """

    def __init__(
        self,
        path: Path,
        seen: dict[str, str],
        baselined: bool,
        last_full_sweep: datetime | None,
    ) -> None:
        self._path = path
        self._seen = seen
        self.baselined = baselined
        self.last_full_sweep = last_full_sweep

    @classmethod
    def load(cls, path: Path) -> "SeenState":
        if not path.exists():
            return cls(path, {}, baselined=False, last_full_sweep=None)
        data = json.loads(path.read_text(encoding="utf-8"))
        sweep = data.get("last_full_sweep")
        return cls(
            path,
            dict(data.get("seen", {})),
            baselined=bool(data.get("baselined", False)),
            last_full_sweep=datetime.fromisoformat(sweep) if sweep else None,
        )

    def __contains__(self, listing_id: str) -> bool:
        return listing_id in self._seen

    def __len__(self) -> int:
        return len(self._seen)

    def add(self, listing_id: str, now: datetime) -> None:
        self._seen[listing_id] = _stamp(now)

    def touch(self, listing_id: str, now: datetime) -> None:
        """Note that a known listing is still around, so pruning doesn't forget it."""
        last_seen = self._seen.get(listing_id)
        if last_seen is not None and last_seen < _stamp(now - timedelta(days=TOUCH_INTERVAL_DAYS)):
            self._seen[listing_id] = _stamp(now)

    def prune(self, now: datetime, keep_days: int) -> None:
        """Forget listings not seen for `keep_days`, so the file doesn't grow forever."""
        cutoff = _stamp(now - timedelta(days=keep_days))
        self._seen = {i: seen_at for i, seen_at in self._seen.items() if seen_at >= cutoff}

    def full_sweep_due(self, now: datetime, every_hours: int) -> bool:
        return self.last_full_sweep is None or now - self.last_full_sweep >= timedelta(hours=every_hours)

    def mark_baselined(self) -> None:
        self.baselined = True

    def mark_full_sweep(self, now: datetime) -> None:
        self.last_full_sweep = now

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "baselined": self.baselined,
            "last_full_sweep": _stamp(self.last_full_sweep) if self.last_full_sweep else None,
            "seen": dict(sorted(self._seen.items())),
        }
        self._path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")
