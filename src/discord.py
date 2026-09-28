import json
import time
import urllib.error
import urllib.request
from typing import Any

from details import Details
from models import Candidate
from scoring import Assessment
from wijken import normalize

# Discord's Cloudflare rejects urllib's default User-Agent.
USER_AGENT = "DiscordBot (https://github.com/funda-watch, 1.0)"
MAX_ATTEMPTS = 3

COLOR_OK = 0x2ECC71
COLOR_WARNING = 0xF1C40F
COLOR_OLD_LISTING = 0xE74C3C

# tier -> (headline, embed colour)
TIER_STYLE = {
    "top": ("⭐ Top match", 0x2ECC71),
    "good": ("👍 Good match", 0x3498DB),
    "ok": ("😐 Okay", 0x95A5A6),
    "low": ("🔻 Low match", 0xE67E22),
}
MAX_REASONS = 6

NEW_HOUSE_HEADLINE = "🏠 New house found"
OLD_LISTING_HEADLINE = "🚨 ALERT — OLD LISTING ADDED SINCE LISTING CHANGED"


class DiscordError(Exception):
    pass


def format_euro(amount: int) -> str:
    return f"€{amount:,}"


def build_payload(
    candidate: Candidate,
    wijk: str | None,
    warnings: tuple[str, ...],
    user_id: str | None,
    old_listing: bool = False,
    age_days: int | None = None,
    assessment: Assessment | None = None,
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
    lines: list[str] = []
    if assessment:
        headline, _ = TIER_STYLE[assessment.score.tier]
        lines.append(f"**{assessment.score.points}/100 · {headline}**")
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
    if assessment:
        lines.extend(_details_lines(assessment.details))
    if old_listing and age_days is not None:
        lines.append(f"🕒 Originally listed {age_days} days ago")
    lines.extend(f"⚠️ {warning}" for warning in warnings)
    if assessment:
        lines.extend(_reason_lines(assessment))

    embed: dict[str, Any] = {
        "title": candidate.title,
        "description": "\n".join(lines),
        "color": _color(old_listing, warnings, assessment),
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
        "content": f"{mention}{_headline(old_listing, assessment)}",
        "allowed_mentions": {"parse": [], "users": [user_id] if user_id else []},
        "embeds": [embed],
    }


def _headline(old_listing: bool, assessment: Assessment | None) -> str:
    tier = TIER_STYLE[assessment.score.tier][0] if assessment else None
    if old_listing:
        return f"{OLD_LISTING_HEADLINE} · {tier}" if tier else OLD_LISTING_HEADLINE
    return tier or NEW_HOUSE_HEADLINE


def _color(old_listing: bool, warnings: tuple[str, ...], assessment: Assessment | None) -> int:
    if old_listing:
        return COLOR_OLD_LISTING
    if assessment:
        return TIER_STYLE[assessment.score.tier][1]
    return COLOR_WARNING if warnings else COLOR_OK


def _details_lines(details: Details) -> list[str]:
    kind = ["Apartment" if details.is_apartment else "House"]
    if details.floor is not None:
        kind.append("ground floor" if details.floor == 0 else f"floor {details.floor}")
    if details.year_built:
        kind.append(f"built {details.year_built}")
    if details.erfpacht:
        kind.append("**erfpacht**")
    elif details.ownership:
        kind.append("freehold")
    lines = [f"🏠 {' · '.join(kind)}"]

    outdoor = []
    if details.balcony:
        outdoor.append(f"balcony/terrace {details.outdoor_m2} m²" if details.outdoor_m2 else "balcony/terrace")
    if details.garden:
        outdoor.append("garden")
    lines.append(f"🌿 {' + '.join(outdoor) if outdoor else 'no outdoor space'}")

    if details.is_apartment and (details.vve_monthly or details.vve_reserve_fund is not None):
        cost = f"€{details.vve_monthly:,.0f}/mo" if details.vve_monthly else "cost unknown"
        lines.append(
            f"🏢 VvE {cost} · reserve {_tick(details.vve_reserve_fund)}"
            f" · plan {_tick(details.vve_maintenance_plan)}"
        )
    return lines


def _tick(value: bool | None) -> str:
    return "✅" if value else "❌" if value is False else "?"


def _reason_lines(assessment: Assessment) -> list[str]:
    return [
        f"{'✅' if reason.points > 0 else '⚠️'} {reason.points:+d} {reason.text}"
        for reason in assessment.score.reasons[:MAX_REASONS]
    ]


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
