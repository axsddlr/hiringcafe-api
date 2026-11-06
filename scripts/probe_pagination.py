"""Determine the real pagination parameter: top-level `page` vs searchState.page.

`page` must be a sibling query parameter (`?searchState=...&page=N`). Putting it
inside searchState is silently ignored and re-serves page 0 -- which is what this
script measures. Uses a broad query so there is more than one page to compare.
"""

import asyncio
import json

from app.config import Settings
from app.geo import resolve_us_zip
from app.hiringcafe import HiringCafeClient

SAMPLE_ZIP = "78701"   # Austin, TX -- broad metro, plenty of pages
SAMPLE_QUERY = "data analyst"


def summarize(label: str, page_props: dict) -> None:
    hits = page_props.get("ssrHits") or []
    ids = [h.get("id") for h in hits]
    print(
        f"{label:<34} ssrPage={page_props.get('ssrPage')!s:<4} "
        f"hits={len(hits):<4} total={page_props.get('ssrTotalCount')!s:<6} "
        f"first_id={ids[0] if ids else None}"
    )
    return ids


async def main() -> None:
    settings = Settings(cache_ttl=0.0)
    client = HiringCafeClient(settings)

    loc = resolve_us_zip(SAMPLE_ZIP, radius=25).to_search_state()
    search_state = {"locations": [loc], "searchQuery": SAMPLE_QUERY}

    build_id = await client.build_id()
    print(f"build_id={build_id}\n")

    base_url = client.data_url(build_id, search_state)
    referer = f"{settings.base_url}{settings.page_path}"

    # 1) baseline, page 0
    r0 = await client._fetch(base_url, referer=referer, accept="*/*")
    p0 = json.loads(r0.body)["pageProps"]
    ids0 = summarize("GET (no page param)", p0)

    # 2) top-level `&page=1`  <- what the GitHub script implies
    r1 = await client._fetch(base_url + "&page=1", referer=referer, accept="*/*")
    p1 = json.loads(r1.body)["pageProps"]
    ids1 = summarize("GET &page=1 (top-level)", p1)

    # 3) page embedded inside searchState
    ss_page = {**search_state, "page": 1}
    r2 = await client._fetch(client.data_url(build_id, ss_page), referer=referer, accept="*/*")
    p2 = json.loads(r2.body)["pageProps"]
    ids2 = summarize("searchState.page=1", p2)

    print("\n--- verdict ---")
    print(f"top-level page=1 changed the result set : {ids1[:3] != ids0[:3]}")
    print(f"searchState.page=1 changed result set   : {ids2[:3] != ids0[:3]}")
    print(f"top-level page=1 matches searchState p=1: {ids1[:3] == ids2[:3]}")
    print(f"overlap(page0, page1) first 3: {len(set(ids0[:3]) & set(ids1[:3]))}/3")


if __name__ == "__main__":
    asyncio.run(main())
