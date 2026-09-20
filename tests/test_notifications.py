import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from factories import make_candidate

from discord import DiscordError, build_payload, format_euro, send


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
