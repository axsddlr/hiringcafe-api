"""Find out whether HiringCafe marks sponsored/promoted postings anywhere we can see.

Checks both delivery paths for a broad, high-volume search:
  1. the SSR HTML page (what a browser loads first),
  2. the /_next/data JSON payload (what this service consumes),
looking for any sponsor/promote/feature vocabulary in keys or values.
"""

from __future__ import annotations

import asyncio
import json
import re

from scrapling.fetchers import Fetcher

from app.config import Settings
from app.hiringcafe import HiringCafeClient

PATTERN = re.compile(r"sponsor|promot|featured|boost|premium", re.I)

# Country-wide, no radius: the widest result set, most likely to include paid placements.
SEARCH_STATE = {
    "locations": [
        {
            "id": "us",
            "types": ["country"],
            "formatted_address": "United States",
            "address_components": [
                {"long_name": "United States", "short_name": "US", "types": ["country"]}
            ],
            "workplace_types": [],
            "options": {"ignore_radius": True},
        }
    ],
    "searchQuery": "software engineer",
}


def scan_keys(node, found: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key)
            scan_keys(value, found)
    elif isinstance(node, list):
        for item in node:
            scan_keys(item, found)


async def main() -> None:
    settings = Settings(cache_ttl=0.0)
    client = HiringCafeClient(settings)

    # ---- 1. SSR HTML page ----
    from urllib.parse import quote

    state = quote(json.dumps(SEARCH_STATE, separators=(",", ":")), safe="")
    page_url = f"{settings.base_url}/classic?searchState={state}"
    resp = Fetcher.get(
        page_url,
        impersonate=settings.impersonate,
        headers={"accept": "text/html", "user-agent": settings.user_agent},
        cookies=client._cookies(),
        timeout=45,
    )
    html = resp.body.decode("utf-8", "replace")
    print(f"HTML: status={resp.status} bytes={len(html)}")
    for m in list(PATTERN.finditer(html))[:8]:
        s, e = max(0, m.start() - 60), min(len(html), m.end() + 60)
        print("   ...", html[s:e].replace("\n", " "), "...")
    hits_html = len(PATTERN.findall(html))
    print(f"   sponsor-ish occurrences in HTML: {hits_html}")

    # ---- 2. data payload ----
    result = await client.fetch(SEARCH_STATE)
    pp = result.page_props
    print(f"\nJSON: total={pp.get('ssrTotalCount')} hits={len(pp.get('ssrHits') or [])}")
    print("   pageProps keys:", sorted(pp.keys()))

    keys: set[str] = set()
    scan_keys(pp.get("ssrHits"), keys)
    candidates = sorted(k for k in keys if PATTERN.search(k))
    print(f"   distinct hit keys: {len(keys)}")
    print(f"   sponsor-ish keys : {candidates}")

    blob = json.dumps(pp)
    print(f"   sponsor-ish occurrences in JSON values: {len(PATTERN.findall(blob))}")

    # print any hit whose serialized form mentions sponsorship
    for hit in pp.get("ssrHits") or []:
        text = json.dumps(hit)
        if PATTERN.search(text):
            print("   HIT:", hit.get("id"), PATTERN.search(text).group(0))


if __name__ == "__main__":
    asyncio.run(main())
