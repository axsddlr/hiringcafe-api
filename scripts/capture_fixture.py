"""Capture a fresh upstream fixture for the tests.

Writes the full Next.js page payload (`pageProps` + `__N_SSP`) so the fixture is
exactly what the data endpoint returns. Run redaction afterwards:

    python scripts/capture_fixture.py --zip 83702 --query "data analyst" \
        --out tests/fixtures/classic_83702_data_analyst.json
    python scripts/redact_fixture.py tests/fixtures/classic_83702_data_analyst.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

from app.config import Settings
from app.geo import resolve_us_zip
from app.hiringcafe import HiringCafeClient


async def capture(zip_code: str, query: str, out: pathlib.Path, radius: int) -> int:
    client = HiringCafeClient(Settings(cache_ttl=0.0))
    location = resolve_us_zip(zip_code, radius=radius).to_search_state()
    state = {"locations": [location], "searchQuery": query}

    result = await client.fetch(state)
    payload = {"pageProps": result.page_props, "__N_SSP": True}

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")

    pp = result.page_props
    print(f"build_id     : {result.build_id}")
    print(f"location     : {location['formatted_address']} ({location['id']})")
    print(f"query        : {query}")
    print(f"total_count  : {pp.get('ssrTotalCount')}")
    print(f"company_count: {pp.get('ssrCompanyCount')}")
    print(f"page_size    : {pp.get('ssrPageSize')}  is_last_page={pp.get('ssrIsLastPage')}")
    print(f"hits         : {len(pp.get('ssrHits') or [])}")
    print(f"bytes        : {out.stat().st_size} -> {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--query", required=True)
    ap.add_argument("--radius", type=int, default=25)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    args = ap.parse_args()
    return asyncio.run(capture(args.zip, args.query, args.out, args.radius))


if __name__ == "__main__":
    sys.exit(main())
