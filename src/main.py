import argparse
import io
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import Config, SearchConfig, load_config
from discord import DiscordError, build_payload, send
from filters import Verdict, evaluate
from funda_client import SearchResult, fetch_search, make_client
from models import Candidate
from state import SeenState
from wijken import WijkMap

ROOT = Path(__file__).resolve().parent.parent
KEEP_SEEN_DAYS = 30
# Keeps a burst of new listings from flooding the channel; the remainder isn't marked
# as seen, so it goes out on the next run.
MAX_NOTIFICATIONS_PER_RUN = 25
SEND_DELAY_SECONDS = 1.0

Fetcher = Callable[[SearchConfig, bool], SearchResult]


@dataclass(frozen=True)
class Match:
    candidate: Candidate
    wijk: str | None
    verdict: Verdict
    # Published more than `old_listing_after_days` ago, yet not seen before: the
    # listing changed (price drop, new label, ...) and only now passes the filters.
    old_listing: bool
    age_days: int | None


Notifier = Callable[[Match], None]


@dataclass(frozen=True)
class RunResult:
    full_sweep: bool
    notified: int
    silently_marked: int
    deferred: int
    failed_searches: int
    # Searches that returned some pages but not all; reported as a warning, not a failure.
    incomplete_searches: int
    failed_sends: int

    @property
    def ok(self) -> bool:
        return self.failed_searches == 0 and self.failed_sends == 0


def run(
    config: Config,
    wijk_map: WijkMap,
    state: SeenState,
    fetch: Fetcher,
    notify: Notifier,
    now: datetime,
    force_full: bool = False,
) -> RunResult:
    baseline_run = not state.baselined
    full_sweep = (
        force_full or baseline_run or state.full_sweep_due(now, config.full_sweep_every_hours)
    )
    old_before = now - timedelta(days=config.old_listing_after_days)
    matches: dict[str, Match] = {}
    failed_searches = incomplete_searches = 0

    for search in config.searches:
        try:
            fetched = fetch(search, full_sweep)
        except Exception as error:  # one blocked or broken search shouldn't stop the others
            print(f"[{search.name}] search failed: {error}", file=sys.stderr)
            failed_searches += 1
            continue

        if fetched.notice:
            print(f"::warning::[{search.name}] {fetched.notice}")
        if not fetched.complete:
            # What loaded is still processed; the sweep just stays due for the next run.
            print(f"::warning::[{search.name}] read only part of the results ({fetched.error})")
            incomplete_searches += 1

        candidates = fetched.candidates
        found = 0
        for candidate in candidates:
            if candidate.id in state:
                state.touch(candidate.id, now)
                continue
            # A listing can appear in several searches; the ID is what counts.
            if candidate.id in matches:
                continue
            wijk = wijk_map.lookup(search.location, candidate.neighbourhood)
            verdict = evaluate(candidate, config.filters, wijk, search.wijken)
            if verdict.accepted:
                published = candidate.published
                matches[candidate.id] = Match(
                    candidate,
                    wijk,
                    verdict,
                    old_listing=published is not None and published < old_before,
                    age_days=(now - published).days if published else None,
                )
                found += 1
        print(f"[{search.name}] {len(candidates)} fetched, {found} unseen matches")

    # Oldest first, so the channel reads chronologically.
    ordered = sorted(
        matches.values(),
        key=lambda m: m.candidate.published or datetime.min.replace(tzinfo=timezone.utc),
    )
    # The baseline run records everything that matches today without alerting on old
    # listings; without it the first run would report every long-running listing.
    silent: list[Match] = []
    loud: list[Match] = []
    for match in ordered:
        is_silent = baseline_run and (match.old_listing or not config.notify_existing)
        (silent if is_silent else loud).append(match)

    for match in silent:
        state.add(match.candidate.id, now)

    to_notify = loud[:MAX_NOTIFICATIONS_PER_RUN]
    deferred = len(loud) - len(to_notify)
    notified = failed_sends = 0
    for match in to_notify:
        try:
            notify(match)
        except DiscordError as error:
            print(f"notification for {match.candidate.id} failed: {error}", file=sys.stderr)
            failed_sends += 1
            continue
        state.add(match.candidate.id, now)
        notified += 1

    # Only count a pass as complete if every search was read to the end, otherwise the
    # next run must repeat it.
    if failed_searches == 0 and incomplete_searches == 0:
        if baseline_run:
            state.mark_baselined()
        if full_sweep:
            state.mark_full_sweep(now)

    state.prune(now, KEEP_SEEN_DAYS)
    return RunResult(
        full_sweep,
        notified,
        len(silent),
        deferred,
        failed_searches,
        incomplete_searches,
        failed_sends,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch Funda for new listings and alert Discord.")
    parser.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    parser.add_argument("--state", type=Path, default=ROOT / "data" / "seen-listings.json")
    parser.add_argument("--wijken", type=Path, default=ROOT / "data" / "buurt-wijk.json")
    parser.add_argument(
        "--full",
        action="store_true",
        help="force a full sweep of every result page instead of only the newest ones",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print alerts instead of sending them, and don't touch the state file",
    )
    args = parser.parse_args()
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    user_id = os.environ.get("DISCORD_USER_ID") or None
    if not webhook_url and not args.dry_run:
        print("DISCORD_WEBHOOK_URL is not set (use --dry-run to test)", file=sys.stderr)
        return 2

    config = load_config(args.config)
    wijk_map = WijkMap.load(args.wijken)
    state = SeenState.load(args.state)
    now = datetime.now(timezone.utc)
    client = make_client()

    def fetch(search: SearchConfig, full_sweep: bool) -> SearchResult:
        # "newest" sorts by day only, so stop a full day past the old-listing cut-off.
        stop_before = (
            None if full_sweep else now - timedelta(days=config.old_listing_after_days + 1)
        )
        areas = wijk_map.area_slugs(search.location, search.wijken)
        return fetch_search(client, search, config.filters, stop_before, areas)

    def notify(match: Match) -> None:
        payload = build_payload(
            match.candidate,
            match.wijk,
            match.verdict.warnings,
            user_id,
            old_listing=match.old_listing,
            age_days=match.age_days,
        )
        if args.dry_run or not webhook_url:
            embed = payload["embeds"][0]
            print(f"--- {payload['content']}\n{embed['title']}\n{embed.get('url', '')}\n{embed['description']}\n")
            return
        send(webhook_url, payload)
        time.sleep(SEND_DELAY_SECONDS)

    with client:
        result = run(config, wijk_map, state, fetch, notify, now, force_full=args.full)

    if not args.dry_run:
        state.save()
    print(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
