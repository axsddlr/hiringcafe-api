"""HTTP contract tests. Upstream is stubbed so the suite is fully offline."""

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.hiringcafe import SearchResult

SAMPLE_ZIP = "83702"
SAMPLE_QUERY = "data analyst"


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def fetch(self, search_state, *, page=0):
        self.calls.append({"search_state": search_state, "page": page})
        return SearchResult(
            page_props=self.payload["pageProps"],
            build_id="TESTBUILDID",
            upstream_status=200,
            fetched_at="2026-11-06T07:10:00+00:00",
            url="https://hiringcafe.com/_next/data/TESTBUILDID/classic.json",
            cache_hit=False,
            raw_payload=self.payload,
        )


@pytest.fixture()
def api(payload):
    fake = FakeClient(payload)
    main.app.dependency_overrides[main.get_client] = lambda: fake
    client = TestClient(main.app)
    try:
        yield client, fake
    finally:
        main.app.dependency_overrides.clear()


def test_health(api):
    client, _ = api
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_search_returns_normalized_jobs(api):
    client, _ = api
    r = client.get("/v1/search", params={"query": SAMPLE_QUERY, "postal_code": SAMPLE_ZIP})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["meta"]["total_count"] == 38
    assert body["meta"]["company_count"] == 21
    assert body["meta"]["build_id"] == "TESTBUILDID"
    assert len(body["jobs"]) == 38
    assert body["jobs"][0]["company"] == "Clearwater Analytics"
    assert "raw" not in body


def test_search_forwards_exact_upstream_search_state(api, upstream_search_state):
    client, fake = api
    client.get(
        "/v1/search",
        params={"query": SAMPLE_QUERY, "postal_code": SAMPLE_ZIP, "radius": 25},
    )
    sent = fake.calls[0]["search_state"]
    assert sent["locations"] == upstream_search_state["locations"]
    assert sent["searchQuery"] == SAMPLE_QUERY
    assert fake.calls[0]["page"] == 0


def test_include_raw(api):
    client, _ = api
    r = client.get(
        "/v1/search",
        params={"query": SAMPLE_QUERY, "postal_code": SAMPLE_ZIP, "include_raw": "true"},
    )
    assert r.status_code == 200
    assert r.json()["raw"]["pageProps"]["ssrTotalCount"] == 38


def test_unknown_postal_code_returns_404(api):
    client, _ = api
    r = client.get("/v1/search", params={"query": SAMPLE_QUERY, "postal_code": "99999"})
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "unknown_location"
    assert err["status"] == 404


def test_query_is_required(api):
    client, _ = api
    r = client.get("/v1/search", params={"postal_code": SAMPLE_ZIP})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_request"


def test_radius_bounds_are_validated(api):
    client, _ = api
    r = client.get(
        "/v1/search",
        params={"query": SAMPLE_QUERY, "postal_code": SAMPLE_ZIP, "radius": 5000},
    )
    assert r.status_code == 422


def test_location_endpoint(api):
    client, _ = api
    r = client.get(f"/v1/location/{SAMPLE_ZIP}")
    assert r.status_code == 200
    body = r.json()
    assert body["formatted_address"] == "Boise, ID, US"
    assert body["geometry"]["location"] == {"lat": 43.6322, "lon": -116.2052}


def test_location_endpoint_404(api):
    client, _ = api
    assert client.get("/v1/location/00000").status_code == 404


def test_post_accepts_raw_search_state(api, upstream_search_state):
    client, fake = api
    r = client.post("/v1/search", json={"search_state": upstream_search_state})
    assert r.status_code == 200, r.text
    assert fake.calls[0]["search_state"] == upstream_search_state
    assert r.json()["meta"]["total_count"] == 38


def test_post_rejects_malformed_search_state(api):
    client, _ = api
    r = client.post("/v1/search", json={"search_state": {"nope": 1}})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_search_state"


def test_openapi_schema_builds(api):
    client, _ = api
    assert client.get("/openapi.json").status_code == 200


def test_upstream_error_with_no_hits_becomes_502(api):
    """A failed upstream search must not masquerade as 'no jobs matched'."""
    client, fake = api
    fake.payload = {"pageProps": {"ssrHits": [], "ssrTotalCount": 0, "ssrError": "es timeout"}}

    r = client.get("/v1/search", params={"query": "x", "postal_code": SAMPLE_ZIP})

    assert r.status_code == 502
    assert r.json()["error"]["code"] == "upstream_error"
    assert r.json()["error"]["details"]["ssr_error"] == "es timeout"


def test_partial_results_with_upstream_error_are_returned(api, page_props):
    """Error *and* hits -> return the data, but flag it in meta."""
    client, fake = api
    fake.payload = {"pageProps": {**page_props, "ssrError": "partial failure"}}

    r = client.get("/v1/search", params={"query": SAMPLE_QUERY, "postal_code": SAMPLE_ZIP})

    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["upstream_error"] == "partial failure"
    assert len(body["jobs"]) == 38


def test_post_rejects_oversized_search_state(api):
    client, _ = api
    huge = {"searchQuery": "x", "locations": [], "junk": "a" * 25_000}

    r = client.post("/v1/search", json={"search_state": huge})

    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_search_state"
    assert r.json()["error"]["details"]["limit"] > 0


def _sponsored_payload(page_props):
    import copy

    page_props = copy.deepcopy(page_props)
    page_props["ssrHits"][0]["job_information"]["is_sponsored"] = True
    return {"pageProps": page_props}


def test_sponsored_excluded_by_default_over_http(api, page_props):
    client, fake = api
    fake.payload = _sponsored_payload(page_props)

    body = client.get(
        "/v1/search", params={"query": SAMPLE_QUERY, "postal_code": SAMPLE_ZIP}
    ).json()

    assert body["meta"]["excluded_sponsored"] == 1
    assert body["meta"]["returned_count"] == 37
    assert len(body["jobs"]) == 37


def test_sponsored_included_on_request(api, page_props):
    client, fake = api
    fake.payload = _sponsored_payload(page_props)

    body = client.get(
        "/v1/search",
        params={"query": SAMPLE_QUERY, "postal_code": SAMPLE_ZIP, "include_sponsored": "true"},
    ).json()

    assert body["meta"]["excluded_sponsored"] == 0
    assert len(body["jobs"]) == 38
    assert body["jobs"][0]["sponsored"] is True


def test_post_can_include_sponsored(api, page_props, upstream_search_state):
    client, fake = api
    fake.payload = _sponsored_payload(page_props)

    default = client.post("/v1/search", json={"search_state": upstream_search_state}).json()
    assert default["meta"]["excluded_sponsored"] == 1

    opted_in = client.post(
        "/v1/search",
        json={"search_state": upstream_search_state, "include_sponsored": True},
    ).json()
    assert opted_in["meta"]["excluded_sponsored"] == 0
    assert len(opted_in["jobs"]) == 38
