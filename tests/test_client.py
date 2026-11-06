"""Client-level tests: buildId lifecycle, stale-buildId retry, challenge handling.

Upstream HTTP is faked by patching ``app.hiringcafe.Fetcher``, so these run
offline and deterministically.
"""

import json
from urllib.parse import unquote

import pytest

from app import hiringcafe
from app.config import Settings
from app.errors import (
    BuildIdError,
    UpstreamBlockedError,
    UpstreamError,
    UpstreamTimeoutError,
)
from app.hiringcafe import HiringCafeClient

SHELL = (
    '<html><body><script id="__NEXT_DATA__" type="application/json">'
    '{"buildId":"BUILD1","props":{"pageProps":{}}}</script></body></html>'
)
SHELL_V2 = SHELL.replace("BUILD1", "BUILD2")
DATA = json.dumps({"pageProps": {"ssrHits": [], "ssrTotalCount": 20}, "__N_SSP": True})

SEARCH_STATE = {"searchQuery": "data analyst", "locations": [{"id": "us-zip-83702"}]}


class FakeResponse:
    def __init__(self, status=200, body="", headers=None):
        self.status = status
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = headers or {}


class FakeFetcher:
    """Records every call and replays queued responses in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError(f"unexpected extra request: {url}")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_client(monkeypatch, responses, **settings_kwargs):
    fake = FakeFetcher(responses)
    monkeypatch.setattr(hiringcafe, "Fetcher", fake)
    return HiringCafeClient(Settings(**settings_kwargs)), fake


async def test_discovers_build_id_then_fetches_data(monkeypatch):
    client, fake = make_client(monkeypatch, [FakeResponse(200, SHELL), FakeResponse(200, DATA)])

    result = await client.fetch(SEARCH_STATE)

    assert result.build_id == "BUILD1"
    assert result.upstream_status == 200
    assert result.page_props["ssrTotalCount"] == 20
    assert fake.calls[0][0].endswith("/classic")
    assert "BUILD1" in fake.calls[1][0]
    assert "classic.json" in fake.calls[1][0]


async def test_data_url_encodes_search_state_verbatim(monkeypatch):
    client, _ = make_client(monkeypatch, [])
    url = client.data_url("BUILD1", SEARCH_STATE)

    assert url.startswith("https://hiringcafe.com/_next/data/BUILD1/classic.json?searchState=")
    encoded = url.split("searchState=", 1)[1]
    assert json.loads(unquote(encoded)) == SEARCH_STATE
    assert "%20" in encoded or "+" not in encoded


async def test_page_is_a_sibling_query_param_not_search_state(monkeypatch):
    """Verified against the live endpoint: page must NOT go inside searchState."""
    client, _ = make_client(monkeypatch, [])

    url0 = client.data_url("B", SEARCH_STATE, 0)
    url2 = client.data_url("B", SEARCH_STATE, 2)

    assert "&page=" not in url0
    assert url2.endswith("&page=2")
    # the searchState blob itself must be byte-identical across pages
    state0 = url0.split("searchState=", 1)[1]
    state2 = url2.split("searchState=", 1)[1].split("&page=", 1)[0]
    assert state0 == state2
    assert json.loads(unquote(state0)) == SEARCH_STATE


async def test_stale_build_id_is_refreshed_once(monkeypatch):
    client, fake = make_client(
        monkeypatch,
        [
            FakeResponse(200, SHELL),          # initial buildId discovery
            FakeResponse(404, "not found"),    # stale buildId
            FakeResponse(200, SHELL_V2),       # rediscovery
            FakeResponse(200, DATA),           # retry succeeds
        ],
    )

    result = await client.fetch(SEARCH_STATE)

    assert result.build_id == "BUILD2"
    assert len(fake.calls) == 4
    assert "BUILD1" in fake.calls[1][0]
    assert "BUILD2" in fake.calls[3][0]


async def test_persistent_404_is_reported(monkeypatch):
    client, _ = make_client(
        monkeypatch,
        [
            FakeResponse(200, SHELL),
            FakeResponse(404, "gone"),
            FakeResponse(200, SHELL_V2),
            FakeResponse(404, "still gone"),
        ],
    )

    with pytest.raises(UpstreamError) as exc:
        await client.fetch(SEARCH_STATE)
    assert exc.value.status_code == 502


async def test_cloudflare_challenge_on_data_endpoint(monkeypatch):
    client, _ = make_client(
        monkeypatch,
        [
            FakeResponse(200, SHELL),
            FakeResponse(403, "<html>Just a moment...</html>", {"cf-mitigated": "challenge"}),
        ],
    )

    with pytest.raises(UpstreamBlockedError) as exc:
        await client.fetch(SEARCH_STATE)
    assert exc.value.code == "upstream_blocked"
    assert exc.value.status_code == 502


async def test_challenge_detected_without_header(monkeypatch):
    client, _ = make_client(
        monkeypatch,
        [FakeResponse(503, "busy", {})],
    )

    with pytest.raises(UpstreamBlockedError):
        await client.fetch(SEARCH_STATE)


async def test_missing_build_id_raises(monkeypatch):
    client, _ = make_client(monkeypatch, [FakeResponse(200, "<html>no bootstrap here</html>")])

    with pytest.raises(BuildIdError) as exc:
        await client.fetch(SEARCH_STATE)
    assert exc.value.code == "build_id_unavailable"


async def test_non_json_body_raises(monkeypatch):
    client, _ = make_client(
        monkeypatch,
        [FakeResponse(200, SHELL), FakeResponse(200, "<html>maintenance</html>")],
    )

    with pytest.raises(UpstreamError):
        await client.fetch(SEARCH_STATE)


async def test_payload_without_page_props_raises(monkeypatch):
    client, _ = make_client(
        monkeypatch,
        [FakeResponse(200, SHELL), FakeResponse(200, json.dumps({"other": 1}))],
    )

    with pytest.raises(UpstreamError):
        await client.fetch(SEARCH_STATE)


async def test_transport_timeout_maps_to_504(monkeypatch):
    client, _ = make_client(
        monkeypatch,
        [FakeResponse(200, SHELL), Exception("Operation timed out after 30001 ms")],
    )

    with pytest.raises(UpstreamTimeoutError) as exc:
        await client.fetch(SEARCH_STATE)
    assert exc.value.status_code == 504


async def test_transport_failure_maps_to_502(monkeypatch):
    client, _ = make_client(
        monkeypatch,
        [FakeResponse(200, SHELL), Exception("Connection reset by peer")],
    )

    with pytest.raises(UpstreamError) as exc:
        await client.fetch(SEARCH_STATE)
    assert exc.value.status_code == 502


async def test_response_cache_avoids_second_upstream_call(monkeypatch):
    client, fake = make_client(
        monkeypatch,
        [FakeResponse(200, SHELL), FakeResponse(200, DATA)],
        cache_ttl=300.0,
    )

    first = await client.fetch(SEARCH_STATE)
    second = await client.fetch(SEARCH_STATE)

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert len(fake.calls) == 2  # one shell + one data, no repeat


async def test_cache_can_be_disabled(monkeypatch):
    client, fake = make_client(
        monkeypatch,
        [FakeResponse(200, SHELL), FakeResponse(200, DATA), FakeResponse(200, DATA)],
        cache_ttl=0.0,
    )

    await client.fetch(SEARCH_STATE)
    second = await client.fetch(SEARCH_STATE)

    assert second.cache_hit is False
    assert len(fake.calls) == 3


async def test_build_id_is_cached_across_fetches(monkeypatch):
    client, fake = make_client(
        monkeypatch,
        [FakeResponse(200, SHELL), FakeResponse(200, DATA), FakeResponse(200, DATA)],
        cache_ttl=0.0,
    )

    await client.fetch({"searchQuery": "a", "locations": []})
    await client.fetch({"searchQuery": "b", "locations": []})

    shell_calls = [c for c in fake.calls if c[0].endswith("/classic")]
    assert len(shell_calls) == 1


async def test_cache_is_keyed_by_page(monkeypatch):
    """Page 0 and page 1 of the same query must not collide in the cache."""
    client, fake = make_client(
        monkeypatch,
        [FakeResponse(200, SHELL), FakeResponse(200, DATA), FakeResponse(200, DATA)],
        cache_ttl=300.0,
    )

    await client.fetch(SEARCH_STATE, page=0)
    second = await client.fetch(SEARCH_STATE, page=1)

    assert second.cache_hit is False
    assert len(fake.calls) == 3
    assert fake.calls[2][0].endswith("&page=1")
