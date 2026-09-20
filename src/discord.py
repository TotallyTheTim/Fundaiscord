import json
import time
import urllib.error
import urllib.request
from typing import Any

from models import Candidate
from wijken import normalize

# Discord's Cloudflare rejects urllib's default User-Agent.
USER_AGENT = "DiscordBot (https://github.com/funda-watch, 1.0)"
MAX_ATTEMPTS = 3

COLOR_OK = 0x2ECC71
COLOR_WARNING = 0xF1C40F


class DiscordError(Exception):
    pass


def format_euro(amount: int) -> str:
    return f"€{amount:,}"


def build_payload(
    candidate: Candidate,
    wijk: str | None,
    warnings: tuple[str, ...],
    user_id: str | None,
) -> dict[str, Any]:
    facts = [
        part
        for part in (
            f"{candidate.living_area} m²" if candidate.living_area is not None else None,
            f"{candidate.bedrooms} bedrooms" if candidate.bedrooms is not None else None,
            f"label {candidate.energy_label}" if candidate.energy_label else None,
        )
        if part
    ]
    lines = []
    if candidate.price is not None:
        lines.append(f"**{format_euro(candidate.price)}**")
    if facts:
        lines.append(" · ".join(facts))
    if candidate.price is not None and candidate.living_area:
        lines.append(f"{format_euro(round(candidate.price / candidate.living_area))} / m²")
    # Many buurten share their wijk's name; don't print it twice.
    parts = [candidate.neighbourhood, wijk]
    if wijk and candidate.neighbourhood and normalize(wijk) == normalize(candidate.neighbourhood):
        parts = [wijk]
    place = " · ".join(part for part in parts if part)
    lines.append(f"📍 {candidate.city}" + (f" — {place}" if place else ""))
    lines.extend(f"⚠️ {warning}" for warning in warnings)

    embed: dict[str, Any] = {
        "title": candidate.title,
        "description": "\n".join(lines),
        "color": COLOR_WARNING if warnings else COLOR_OK,
        "footer": {"text": f"Search: {candidate.search_name}"},
    }
    if candidate.url:
        embed["url"] = candidate.url
    if candidate.photo_url:
        embed["image"] = {"url": candidate.photo_url}
    if candidate.published:
        embed["timestamp"] = candidate.published.isoformat()

    mention = f"<@{user_id}> " if user_id else ""
    return {
        "content": f"{mention}🏠 New house found",
        "allowed_mentions": {"parse": [], "users": [user_id] if user_id else []},
        "embeds": [embed],
    }


def send(webhook_url: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    for attempt in range(MAX_ATTEMPTS):
        request = urllib.request.Request(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20):
                return
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt < MAX_ATTEMPTS - 1:
                time.sleep(_retry_after(error))
                continue
            raise DiscordError(f"Discord webhook failed with HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise DiscordError(f"Discord webhook unreachable: {error.reason}") from error


def _retry_after(error: urllib.error.HTTPError) -> float:
    try:
        return float(json.loads(error.read()).get("retry_after", 1.0))
    except (ValueError, TypeError):
        return 1.0
