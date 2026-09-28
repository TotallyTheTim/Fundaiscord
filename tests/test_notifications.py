import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from factories import make_candidate, make_details

from discord import COLOR_OLD_LISTING, COLOR_WARNING, DiscordError, build_payload, format_euro, send
from scoring import Assessment, Reason, Score


def embed_of(payload: dict[str, Any]) -> dict[str, Any]:
    embed: dict[str, Any] = payload["embeds"][0]
    return embed


def test_euro_formatting() -> None:
    assert format_euro(357_000) == "€357,000"


def test_embed_contains_the_key_facts() -> None:
    candidate = make_candidate(price=357_000, living_area=82, bedrooms=3, energy_label="B")
    embed = embed_of(build_payload(candidate, "Leyenburg", (), None))

    assert embed["title"] == "Teststraat 1"
    assert embed["url"] == candidate.url
    assert "€357,000" in embed["description"]
    assert "82 m² · 3 bedrooms · label B" in embed["description"]
    assert "€4,354 / m²" in embed["description"]
    assert embed["image"] == {"url": candidate.photo_url}


def test_mentions_the_configured_user_and_only_that_user() -> None:
    payload = build_payload(make_candidate(), None, (), "1234")
    assert payload["content"].startswith("<@1234>")
    assert payload["allowed_mentions"] == {"parse": [], "users": ["1234"]}


def test_no_mention_without_a_user_id() -> None:
    payload = build_payload(make_candidate(), None, (), None)
    assert "<@" not in payload["content"]
    assert payload["allowed_mentions"] == {"parse": [], "users": []}


def test_warnings_are_listed_and_change_the_colour() -> None:
    clean = embed_of(build_payload(make_candidate(), None, (), None))
    flagged = embed_of(build_payload(make_candidate(), None, ("energy label unknown",), None))

    assert "⚠️ energy label unknown" in flagged["description"]
    assert flagged["color"] != clean["color"]


def test_missing_fields_are_left_out_instead_of_printed_as_none() -> None:
    candidate = make_candidate(price=None, living_area=None, bedrooms=None, energy_label=None)
    embed = embed_of(build_payload(candidate, None, (), None))

    assert "None" not in embed["description"]
    assert "/ m²" not in embed["description"]


def test_old_listing_alert_has_its_own_headline_colour_and_age() -> None:
    normal = build_payload(make_candidate(), None, (), "1234")
    old = build_payload(make_candidate(), None, (), "1234", old_listing=True, age_days=12)

    assert old["content"] == "<@1234> 🚨 ALERT — OLD LISTING ADDED SINCE LISTING CHANGED"
    assert "🕒 Originally listed 12 days ago" in embed_of(old)["description"]
    assert embed_of(old)["color"] not in (embed_of(normal)["color"], COLOR_WARNING)


def test_old_listing_without_a_known_age_omits_the_age_line() -> None:
    old = build_payload(make_candidate(), None, (), None, old_listing=True, age_days=None)
    assert "Originally listed" not in embed_of(old)["description"]


def test_a_normal_alert_never_shows_the_age_line() -> None:
    normal = build_payload(make_candidate(), None, (), None, old_listing=False, age_days=12)
    assert "Originally listed" not in embed_of(normal)["description"]


def test_no_image_when_there_is_no_photo() -> None:
    embed = embed_of(build_payload(make_candidate(photo_url=None), None, (), None))
    assert "image" not in embed


def test_wijk_is_not_repeated_when_it_equals_the_buurt() -> None:
    embed = embed_of(build_payload(make_candidate(neighbourhood="Vruchtenbuurt"), "Vruchtenbuurt", (), None))
    assert embed["description"].count("Vruchtenbuurt") == 1


class WebhookServer:
    """Local stand-in for Discord: replies with the queued status codes in order."""

    def __init__(self, statuses: list[int]) -> None:
        self.requests: list[dict[str, Any]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                outer.requests.append(
                    {"user_agent": self.headers["User-Agent"], "body": json.loads(self.rfile.read(length))}
                )
                status = statuses[min(len(outer.requests), len(statuses)) - 1]
                self.send_response(status)
                self.end_headers()
                if status == 429:
                    self.wfile.write(b'{"retry_after": 0}')

            def log_message(self, format: str, *args: object) -> None:
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}/webhook"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "WebhookServer":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()


def test_send_posts_json_with_a_custom_user_agent() -> None:
    payload = build_payload(make_candidate(), None, (), None)
    with WebhookServer([204]) as server:
        send(server.url, payload)

    assert len(server.requests) == 1
    assert server.requests[0]["body"] == payload
    assert "Python-urllib" not in server.requests[0]["user_agent"]


def test_send_retries_after_a_rate_limit() -> None:
    with WebhookServer([429, 204]) as server:
        send(server.url, build_payload(make_candidate(), None, (), None))

    assert len(server.requests) == 2


def test_send_raises_on_other_http_errors() -> None:
    with WebhookServer([500]) as server, pytest.raises(DiscordError):
        send(server.url, build_payload(make_candidate(), None, (), None))


def assessed(tier: str = "top", points: int = 84, reasons: tuple[Reason, ...] = (), **detail_overrides: object) -> Assessment:
    return Assessment(make_details(**detail_overrides), Score(points, tier, reasons))


def test_an_assessed_alert_leads_with_the_tier_and_score() -> None:
    payload = build_payload(make_candidate(), "Leyenburg", (), "1234", assessment=assessed("top", 84))

    assert payload["content"] == "<@1234> ⭐ Top match"
    assert embed_of(payload)["description"].startswith("**84/100 · ⭐ Top match**")
    assert "New house found" not in payload["content"]


@pytest.mark.parametrize(
    ("tier", "headline"),
    [("top", "⭐ Top match"), ("good", "👍 Good match"), ("ok", "😐 Okay"), ("low", "🔻 Low match")],
)
def test_each_tier_has_its_own_headline_and_colour(tier: str, headline: str) -> None:
    payload = build_payload(make_candidate(), None, (), None, assessment=assessed(tier))
    assert headline in payload["content"]


def test_the_tier_colours_are_all_different() -> None:
    colours = {
        embed_of(build_payload(make_candidate(), None, (), None, assessment=assessed(t)))["color"]
        for t in ("top", "good", "ok", "low")
    }
    assert len(colours) == 4


def test_an_old_listing_stays_red_but_still_shows_its_tier() -> None:
    payload = build_payload(
        make_candidate(), None, (), "1", old_listing=True, age_days=9, assessment=assessed("good", 60)
    )

    assert "OLD LISTING" in payload["content"] and "👍 Good match" in payload["content"]
    assert embed_of(payload)["color"] == COLOR_OLD_LISTING


def test_the_details_lines_show_type_floor_year_ownership_outdoor_and_vve() -> None:
    assessment = assessed(
        floor=3,
        year_built=1912,
        balcony=True,
        outdoor_m2=10,
        vve_monthly=200.0,
        vve_reserve_fund=True,
        vve_maintenance_plan=False,
    )
    description = embed_of(build_payload(make_candidate(), None, (), None, assessment=assessment))["description"]

    assert "🏠 Apartment · floor 3 · built 1912 · freehold" in description
    assert "🌿 balcony/terrace 10 m²" in description
    assert "🏢 VvE €200/mo · reserve ✅ · plan ❌" in description


def test_erfpacht_is_called_out_in_bold() -> None:
    assessment = assessed("low", 20, erfpacht=True, ownership="Gemeentelijke erfpacht")
    description = embed_of(build_payload(make_candidate(), None, (), None, assessment=assessment))["description"]

    assert "**erfpacht**" in description and "freehold" not in description


def test_a_ground_floor_house_without_outdoor_space_or_vve() -> None:
    assessment = assessed(is_apartment=False, floor=0, vve_monthly=None, vve_reserve_fund=None)
    description = embed_of(build_payload(make_candidate(), None, (), None, assessment=assessment))["description"]

    assert "🏠 House · ground floor" in description
    assert "🌿 no outdoor space" in description
    assert "VvE" not in description


def test_unknown_vve_answers_show_a_question_mark() -> None:
    assessment = assessed(vve_monthly=150.0, vve_reserve_fund=None, vve_maintenance_plan=None)
    description = embed_of(build_payload(make_candidate(), None, (), None, assessment=assessment))["description"]

    assert "reserve ? · plan ?" in description


def test_reasons_are_listed_with_signs_and_capped() -> None:
    reasons = tuple(Reason(p, f"reason {i}") for i, p in enumerate((14, 8, -6, 4, 3, -2, 1, 1)))
    description = embed_of(build_payload(make_candidate(), None, (), None, assessment=assessed(reasons=reasons)))[
        "description"
    ]

    assert "✅ +14 reason 0" in description
    assert "⚠️ -6 reason 2" in description
    assert "reason 5" in description and "reason 6" not in description  # capped at six lines


def test_without_an_assessment_the_original_layout_is_unchanged() -> None:
    description = embed_of(build_payload(make_candidate(), None, (), None))["description"]
    assert "/100" not in description and "🌿" not in description
