# HiringCafe Search API

Reproduces `hiringcafe.com/classic` job-search results as clean JSON.

The upstream "API" is really a Next.js SSR hydration endpoint
(`/_next/data/<buildId>/classic.json?searchState=…`). Two things make it
non-obvious to consume, and both are handled here:

1. **Cloudflare gates the origin on TLS/HTTP2 fingerprint, not cookies.** A plain
   `curl` — even with a valid `cf_clearance` cookie — gets
   `403 Cf-Mitigated: challenge` and a "Just a moment…" page. A client that
   impersonates Chrome's TLS fingerprint (Scrapling → curl_cffi) gets `200`.
2. **`buildId` rotates on every deployment.** Hardcoding it works until the next
   deploy, then every request 404s. This service discovers it from the page shell
   at startup/first use, caches it, and force-refreshes once on a 404.

```
GET /v1/search  ->  resolve ZIP (GeoNames) -> build searchState
                ->  discover buildId         -> GET /_next/data/<buildId>/classic.json
                ->  normalize 38 raw hits    ->  clean JSON
```

The examples below use `data analyst` in Boise, ID purely as a neutral sample.

---

## Quickstart

```bash
uv sync                                   # creates .venv, installs deps + dev group
uv run python scripts/build_zipdb.py      # once: GeoNames US dump -> data/us_zips.db
uv run uvicorn app.main:app --port 8070

curl "http://127.0.0.1:8070/v1/search?query=data%20analyst&postal_code=83702&radius=25"
```

Requires [uv](https://docs.astral.sh/uv/). `uv.lock` is committed, so `uv sync`
installs the exact resolved versions. If you need a pip-style file for some other
tool: `uv export --format requirements-txt > requirements.txt`.

Docs: `http://127.0.0.1:8070/docs`

`scripts/build_zipdb.py` needs `data/geonames/US.txt`, from
<https://download.geonames.org/export/zip/US.zip>. It is not committed (2.6 MB);
the built `data/us_zips.db` (3.2 MB, 41,488 ZIPs) is. See
[data/ATTRIBUTION.md](data/ATTRIBUTION.md) — GeoNames is CC BY 4.0.

Note: `scrapling[fetchers]` pulls `playwright`/`patchright` (~37 MB) because
Scrapling imports them when its fetcher module loads, even for HTTP-only use.

---

## Docker

```bash
docker build -t hiringcafe-api .
docker run -d --name hiringcafe-api -p 8070:8070 hiringcafe-api
curl "http://127.0.0.1:8070/v1/search?query=data%20analyst&postal_code=83702&radius=25"
```

Or with Compose (builds and runs the same image):

```bash
docker compose up -d --build
docker compose logs -f api
docker compose down
```

What the image does:

- installs from `uv.lock` with `uv sync --frozen --no-dev` — no pip, no dev tooling;
- ships `data/us_zips.db`, so start-up needs no download; the 2.6 MB GeoNames dump is excluded;
- runs as **UID 10001** (`appuser`), never root;
- exposes `8070` with a `HEALTHCHECK` on `/health` (also mirrored into `docker-compose.yml`);
- is **592 MB**. `playwright` — 140 MB of browser automation this service never
  touches — is excluded with `uv sync --no-install-package playwright`; only its
  sibling `patchright` is genuinely imported by Scrapling's HTTP path. A
  build-time import check and the CI container smoke test fail loudly if that
  ever stops being true.

`tests/` and `verification/` are excluded via `.dockerignore`; run the suite on the
host with `uv run pytest`. Environment variables are the same `HC_*` surface as the
host app:

```bash
docker run -d -p 8070:8070 -e HC_CACHE_TTL=60 -e HC_MAX_CONCURRENCY=2 hiringcafe-api
```

Every layer choice here is deliberate: dependencies are installed **as** the
non-root user with a BuildKit cache mount for uv's wheel cache. The obvious
alternatives — a trailing `chown -R /app` and a plain `uv sync` — cost 411 MB and
~400 MB of dead weight respectively. Measured progression:
**1.86 GB → 789 MB → 592 MB**.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness |
| `GET` | `/v1/location/{postal_code}` | Resolve a ZIP to HiringCafe's `searchState.locations[0]` object, without touching upstream |
| `GET` | `/v1/search` | Search by free-text query + US ZIP |
| `POST` | `/v1/search` | Search with a **verbatim** `searchState` (for non-US locations, custom locations, or upstream filters) |

### `GET /v1/search`

| Param | Type | Default | Notes |
|---|---|---|---|
| `query` | str | required | 1–200 chars |
| `postal_code` | str | required | US ZIP, e.g. `83702` |
| `radius` | int | `50` | 1–500 |
| `radius_unit` | `miles` \| `km` | `miles` | |
| `ignore_radius` | bool | `false` | nationwide / remote search |
| `page` | int | `0` | verified: sibling query param, see below |
| `include_raw` | bool | `false` | attach untouched upstream payload |
| `include_sponsored` | bool | `false` | include paid/promoted placements (excluded by default) |
| `within_radius` | bool | `false` | keep only postings with a listed workplace inside `radius` |

**Pagination is verified, not guessed.** `page` must be a *sibling* query
parameter (`?searchState=…&page=1`), **not** a key inside `searchState`.
Measured against the live endpoint on a 235-match query: `&page=1` returns
`ssrPage=1` with a wholly different job set (0 of 54 IDs overlap), whereas
`searchState.page=1` is silently ignored and re-serves page 0. Reproduce with
`scripts/probe_pagination.py`.

### Filters

`GET` exposes only `query` + location. For HiringCafe's own filters, use `POST`
with the keys it accepts in `searchState`:

```bash
curl -X POST http://127.0.0.1:8070/v1/search -H 'content-type: application/json' -d '{
  "search_state": {
    "locations": [{"id":"us-zip-83702","postal_code":"83702","types":["postal_code"],
                   "formatted_address":"Boise, ID, US",
                   "address_components":[{"long_name":"83702","short_name":"83702","types":["postal_code"]},
                     {"long_name":"Boise","short_name":"Boise","types":["locality"]},
                     {"long_name":"Idaho","short_name":"ID","types":["administrative_area_level_1"]},
                     {"long_name":"United States","short_name":"US","types":["country"]}],
                   "geometry":{"location":{"lat":43.6322,"lon":-116.2052}},
                   "postal_code_source":"geonames","workplace_types":[],
                   "options":{"radius":25,"radius_unit":"miles","ignore_radius":false}}],
    "searchQuery": "data analyst",
    "sortBy": "date",
    "dateFetchedPastNDays": 2,
    "seniorityLevel": ["No Prior Experience Required", "Entry Level"]
  }
}'
```

Known-good keys (confirmed in the wild): `searchQuery`, `jobTitleQuery`,
`sortBy` (`date`), `dateFetchedPastNDays`, `seniorityLevel`. `jobTitleQuery`
searches titles only; `searchQuery` searches the full posting.

### Sponsored postings

Sponsored/promoted placements are **excluded by default**; pass
`include_sponsored=true` (or `include_sponsored: true` in the POST body) to get
them back, in which case each job also carries `"sponsored": true`.

Two honest caveats, because this is a guard rather than a live filter:

- **Upstream currently exposes no placement flag at all.** `scripts/probe_sponsored.py`
  scans both the SSR HTML and the JSON of a 79,452-match nationwide search: zero
  `Sponsored` badges, zero `is_sponsored` / `sponsored` / `is_promoted` /
  `promoted` / `is_featured` keys. The only "sponsor" strings in the payload are
  the `visa_sponsorship` requirement and prose in job descriptions. So today the
  filter removes nothing — the captured 38-job search is returned intact.
- Because there is no marker, the filter keys on the field names such a flag would
  plausibly use (`SPONSORED_MARKERS` in `app/normalize.py`), checked at both the
  hit level and inside `job_information`. If HiringCafe starts emitting a flag
  under a different name, add it there. `meta.excluded_sponsored` tells you how
  many were dropped, and `meta.returned_count` what actually came back —
  `meta.total_count` stays upstream's own number and is never rewritten to hide
  the difference.

If you actually meant *visa* sponsorship, that is a different filter: jobs carry
`benefits.visa_sponsorship` and `requirements_summary` mentions, and excluding on
that is a one-line change rather than a guess about placement markers.

### Example

```bash
curl "http://127.0.0.1:8070/v1/search?query=data%20analyst&postal_code=83702&radius=25"
```

```json
{
  "meta": {
    "query": "data analyst",
    "location": {
      "id": "us-zip-83702",
      "postal_code": "83702",
      "formatted_address": "Boise, ID, US",
      "geometry": { "location": { "lat": 43.6322, "lon": -116.2052 } },
      "postal_code_source": "geonames",
      "options": { "radius": 25, "radius_unit": "miles", "ignore_radius": false }
    },
    "page": 0, "page_size": 40, "total_count": 38, "company_count": 21,
    "returned_count": 38, "excluded_sponsored": 0,
    "excluded_out_of_radius": 0, "excluded_unknown_location": 0,
    "search_center": { "lat": 43.6322, "lon": -116.2052 }, "radius_miles": 25.0,
    "is_last_page": true, "signed_in": false, "es_latency_ms": 171,
    "upstream_error": null,
    "build_id": "vDB2eNJmER-1oMfTvMzRp", "upstream_status": 200,
    "fetched_at": "2026-11-06T06:50:10+00:00", "cache_hit": false
  },
  "jobs": [
    {
      "id": "workday___clearwateranalytics-wd1-clearwater_analytics_careers___financial-data-analyst_r12478",
      "source": "workday",
      "title": "Financial Data Analyst",
      "company": "Clearwater Analytics",
      "company_industry": "Information Technology",
      "apply_url": "https://clearwateranalytics.wd1.myworkdayjobs.com/clearwater_analytics_careers/job/Office---Boise/Financial-Data-Analyst_R12478",
      "location": {
        "formatted": "Boise, Idaho, United States",
        "city": "Boise, Idaho, US",
        "state": "Idaho, US", "country": "US",
        "lat": 43.615, "lon": -116.2023
      },
      "locations": [
        { "city": "Boise, Idaho, US", "state": "Idaho, US", "country": "US",
          "lat": 43.615, "lon": -116.2023, "distance_miles": 1.5 }
      ],
      "distance_miles": 1.5,
      "within_radius": true,
      "workplace_type": "Onsite",
      "seniority": "Entry Level",
      "job_category": "Data and Analytics",
      "employment_types": ["Full Time"],
      "years_experience": null,
      "salary": {
        "is_transparent": false, "currency": "USD", "period": "Yearly",
        "min": null, "max": null,
        "annual_min": null, "annual_max": null,
        "hourly_min": null, "hourly_max": null
      },
      "posted_date": "2026-10-22",
      "requirements_summary": "Bachelor's or master's degree in business-related field; advanced Excel and SQL skills; …",
      "technical_tools": ["Microsoft Excel", "SQL", "Microsoft Office"],
      "certifications": [],
      "education": { "associates": "Not Mentioned", "bachelors": "Required",
                     "masters": "Preferred", "doctorate": "Not Mentioned" },
      "benefits": { "retirement_plan": false, "401k_matching": false,
                    "visa_sponsorship": false, "…": "…" },
      "engagement": { "views": 75, "applies": 19, "saves": 2 }
    }
  ]
}
```

`salary.min`/`max` are the amounts **as advertised** in `period`;
`annual_min`/`annual_max` are upstream's annualized figures (present even when
the listing is hourly). A job that discloses nothing keeps nine `null`s and
`is_transparent: false` — it does not silently become `0`. Hourly listings keep
their hourly figures, e.g. `31.25`–`33.65`/hr alongside `65000`–`69992`/yr.

### Errors

Every failure uses one envelope:

```json
{ "error": { "code": "unknown_location", "message": "…", "status": 404,
             "details": { "postal_code": "99999" } } }
```

| code | status | cause |
|---|---|---|
| `unknown_location` | 404 | ZIP not in GeoNames |
| `invalid_request` | 422 | bad/missing params |
| `invalid_search_state` | 400 | POST body lacks `searchQuery`/`locations`, or exceeds the size limit |
| `upstream_blocked` | 502 | Cloudflare challenge / 403 / 429 / 503 |
| `upstream_error` | 502 | unexpected status, non-JSON, changed payload shape, or `ssrError` **with no results** |
| `upstream_timeout` | 504 | transport timeout |
| `build_id_unavailable` | 502 | `buildId` not found in page shell |

One deliberate choice: when upstream returns `200` with `pageProps.ssrError` set
**and zero hits**, this service answers `502 upstream_error` instead of
`200 { jobs: [] }`. An empty list would read as "nothing matches your search" and
hide a backend outage. If results *do* come back alongside an error, they are
returned as `200` with `meta.upstream_error` populated.

---

## Verification

90 offline tests, no network, **96% statement coverage** (excluding the
TypedDict-only `models.py`):

```bash
uv run pytest --cov=app --cov-report=term-missing   # 90 passed, 96%
uv run ruff check app scripts tests                 # clean
```

CI runs exactly that on every push and PR — lint, the suite with coverage, plus a
container build and health smoke test — in
[`.github/workflows/ci.yml`](.github/workflows/ci.yml).

The suite is not smoke tests. Notable coverage:

- `tests/test_geo.py::test_zip_reproduces_upstream_search_state` — our built
  `searchState` is asserted **dict-equal** to the object the live site echoed
  back in a captured response, including `address_components` order and
  `43.6322/-116.2052`.
- `tests/test_client.py::test_stale_build_id_is_refreshed_once` — 404 → rediscover
  → retry, with the assertion that the retry used the *new* buildId.
- `tests/test_client.py::test_cloudflare_challenge_on_data_endpoint` — a
  `403`/`cf-mitigated: challenge` becomes `upstream_blocked`, never a silent
  empty result.
- `tests/test_api.py::test_upstream_error_with_no_hits_becomes_502` — the
  outage-hiding case above.
- `tests/test_normalize.py` — extracted fields are checked against the captured
  payload, including undisclosed-salary, nullable-YOE, missing-counter and
  `&amp;`-unescaping cases. Where the fixture does not contain a case (it has no
  Remote posting, no escaped ATS link), the test is synthetic rather than
  pretending the fixture proves it.

Live proof against the captured ground truth (spins up the real server, hits the
real site, re-derives every field from the raw fixture with independent logic so
a bug in `normalize.py` cannot mask itself):

```bash
uv run python scripts/verify_live.py verification/live_search.json
# ALL CHECKS PASSED: 38 jobs reproduced field-for-field from upstream
```

Generality check (different city, larger result set):

```bash
curl "http://127.0.0.1:8070/v1/search?query=data%20analyst&postal_code=78701&radius=25"
# total_count=235, jobs=54, location="Austin, TX, US"
```

---

## Design notes

**Why Python.** Scrapling is a Python library; a Node service would have to shell
out to Python anyway. FastAPI gives async, validation, and OpenAPI for free.

**Blocking fetch in an async app.** Scrapling's HTTP engine is synchronous
(`curl_cffi`). Calls run via `asyncio.to_thread`, bounded by a semaphore
(`HC_MAX_CONCURRENCY`, default 4), so the event loop is never blocked and the
origin is never hammered.

**One fetch primitive.** Both routes funnel into `HiringCafeClient.fetch(search_state)`.
The GET path only differs in how it *builds* `search_state`; the POST path lets a
caller supply it verbatim.

**Multi-city postings decide locality by their nearest workplace, not their first.**
Upstream emits every workplace a posting covers ("Washington or New York City" is
two entries) and this API exposes all of them in `locations[]`, each with its own
`distance_miles` from `meta.search_center`. `job.distance_miles` is the distance to
the **nearest** of them, and `within_radius` is the boolean a client should filter
on — `location` (singular) is kept only as the first entry, for compatibility.
Measured on a 10469 search: 44 of 356 postings had a first location more than 50
miles away while genuinely listing New York City, so filtering on `location`
alone silently discards real local jobs. If you want strictly local postings
regardless of multi-city listings, filter on `locations[0].distance_miles` instead.

**Caching.** Two layers: `buildId` (TTL 6 h, invalidated on 404) and whole
responses (TTL 300 s, LRU 256). A repeated search goes from ~1.5 s to ~6 ms.

**Responses are gzipped.** A 38-job search is ~80 KB of JSON and compresses to
~15 KB (82–85% measured); `GZipMiddleware` applies above a 2 KB threshold, so
`/health` does not get gzip framing for nothing.

**Privacy.** Upstream ships `viewedByUsers` / `appliedFromUsers` /
`savedFromUsers` / `hiddenFromUsers` — arrays of real Firebase UIDs. They are
deliberately **not** exposed in the normalized output; they remain only inside
`raw` when `include_raw=true` is explicitly requested. They are also stripped
from the committed test fixture (1,174 identifiers) by
`scripts/redact_fixture.py`, because a captured response should not republish
real people's identifiers.

**HTML entities are unescaped.** Upstream embeds them in plain fields — some ATS
`apply_url`s arrive as `...?cid=x&amp;ccId=y`, which is a broken URL, and industry
strings contain `&amp;`. `normalize.py` unescapes every text field.

---

## Unverified / limits

Called out rather than papered over:

- **`page_size` varies by query** (40 for the Boise sample, 54 for the Austin
  one), so don't assume a fixed page length when looping.
- **Two ZIPs** in GeoNames map to multiple place names; selection is
  accuracy-then-file-order, which may not match upstream's tie-break.
- **Non-US locations** aren't resolvable from a ZIP — use `POST` with a verbatim
  `searchState`.
- **The Cloudflare bypass is fingerprint-based and can break.** When it does, you
  get `upstream_blocked`, not bad data. If Scrapling's Chrome profile stops
  working, bump `HC_IMPERSONATE`.
- **No rate limiting is implemented.** Put this behind a gateway or add limits
  before exposing it publicly; upstream is a third-party site and this is an
  unofficial client. Respect their terms.

---

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `HC_BASE_URL` | `https://hiringcafe.com` | origin |
| `HC_IMPERSONATE` | `chrome` | Scrapling TLS profile |
| `HC_USER_AGENT` | Chrome 156 UA | must match the impersonated major version |
| `HC_TIMEOUT` | `30` | seconds |
| `HC_BUILD_ID_TTL` | `21600` | seconds |
| `HC_CACHE_TTL` | `300` | `0` disables response cache |
| `HC_CACHE_MAX` | `256` | LRU entries |
| `HC_MAX_CONCURRENCY` | `4` | outbound parallelism |
| `HC_MAX_SEARCH_STATE_BYTES` | `20000` | POST body guard for `search_state` |
| `HC_ZIPDB_PATH` | `data/us_zips.db` | GeoNames SQLite |
| `HC_LOG_LEVEL` | `INFO` | |

---

## Layout

```
app/
  main.py         FastAPI routes, error envelope
  hiringcafe.py   buildId discovery, stale-id retry, challenge guard, caches
  geo.py          ZIP -> searchState.locations[0] (GeoNames)
  normalize.py    pageProps -> public JSON (defensive on nulls)
  models.py       documented response TypedDicts
  config.py       env-overridable settings
  errors.py       error hierarchy
scripts/
  build_zipdb.py       GeoNames US.txt -> SQLite
  capture_fixture.py   capture a new upstream fixture (zip + query)
  redact_fixture.py    strip user-identifying arrays from a fixture
  probe_pagination.py  prove how `page` is passed
  probe_sponsored.py   scan upstream HTML+JSON for placement markers
  verify_live.py       live output vs ground truth
tests/            90 offline tests + captured upstream fixture
verification/     captured live responses used as evidence
Dockerfile        uv-based, non-root, healthchecked image
docker-compose.yml
.dockerignore
.github/workflows/ci.yml   lint + tests + container smoke test
```
