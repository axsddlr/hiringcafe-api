# Captured verification artifacts

Real responses from the running service, kept as evidence. Regenerate with:

```bash
uv run uvicorn app.main:app --port 8070
curl -s "http://127.0.0.1:8070/v1/search?query=data%20analyst&postal_code=83702&radius=25" \
  -o verification/live_search.json
uv run python scripts/verify_live.py verification/live_search.json
```

The sample is deliberately generic — Boise, ID for the main capture and Austin, TX
for the pagination proof — so no artifact here reflects a real user's location.

| File | What it proves |
|---|---|
| `live_search.json` | Full normalized response for the reference query. Diffed field-for-field against `tests/fixtures/classic_83702_data_analyst.json` by `scripts/verify_live.py` → 38/38 jobs, `meta.location` dict-equal to upstream `initialSearchState`. |
| `live_cached.json` | Same query immediately after — `meta.cache_hit: true`, ~6 ms vs ~1.5 s cold. |
| `live_post.json` | `POST /v1/search` fed the verbatim upstream `searchState`; returns the same 38 jobs. |
| `live_via_runps1.json` | Produced through `run.ps1` on a clean start (fresh buildId discovery), proving the documented run path works. |
| `page0.json` / `page1.json` | Pagination proof on a broad sample (Austin, 235 matches): `meta.page` 0 vs 1, 54 vs 53 jobs, disjoint sets. Established that `page` is a sibling query parameter — `searchState.page` is ignored by upstream (see `scripts/probe_pagination.py`). |
| `live_docker.json` | Response served from inside the built container (non-root, UID 10001, `HEALTHCHECK` healthy); verified field-for-field against the fixture like the host captures. |

`tests/fixtures/classic_83702_data_analyst.json` is the raw upstream payload
(`pageProps` + `__N_SSP`); it is the ground truth all normalization tests assert
against. User-identifying arrays (`viewedByUsers`, `appliedFromUsers`,
`savedFromUsers`, `hiddenFromUsers`) were stripped from it by
`scripts/redact_fixture.py` before publication, and they do not appear in any
normalized response here.
