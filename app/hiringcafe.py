"""Upstream client for HiringCafe's Next.js data endpoint.

Two facts drive the whole design:

1. **Cloudflare gates the origin on TLS/HTTP2 fingerprint, not on cookies.** A
   plain ``curl`` gets ``403 Cf-Mitigated: challenge`` even with a valid
   ``cf_clearance``; a Chrome-impersonating client (Scrapling -> curl_cffi)
   gets ``200``. So every request goes through ``Fetcher.get(impersonate=...)``.
2. **The ``buildId`` in the URL rotates on each Vercel deployment.** It is read
   out of the page shell at runtime and cached, then force-refreshed when the
   data endpoint answers 404.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from scrapling.fetchers import Fetcher

from .config import Settings
from .errors import BuildIdError, UpstreamBlockedError, UpstreamError, UpstreamTimeoutError

log = logging.getLogger(__name__)

# buildId appears in the __NEXT_DATA__ bootstrap blob...
BUILD_ID_RE = re.compile(r'"buildId"\s*:\s*"([^"]+)"')
# ...and again in every /_next/static/<buildId>/ asset path (fallback source).
BUILD_ID_STATIC_RE = re.compile(r'/_next/static/([^/"\']+)/')

ACCEPT_HTML = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
ACCEPT_JSON = "*/*"


@dataclass(slots=True)
class SearchResult:
    page_props: dict
    build_id: str
    upstream_status: int
    fetched_at: str
    url: str
    cache_hit: bool = False
    raw_payload: dict | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _decode(response: Any) -> str:
    body = getattr(response, "body", None)
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="replace")
    if isinstance(body, str):
        return body
    return str(body)


def _header(response: Any, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None


class HiringCafeClient:
    """Async facade over a blocking, browser-impersonating HTTP fetch."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self._build_id: str | None = None
        self._build_id_deadline = 0.0
        self._build_id_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(self.settings.max_concurrency)
        self._cache: OrderedDict[str, tuple[float, SearchResult]] = OrderedDict()

    # ------------------------------------------------------------------ http

    def _headers(self, *, referer: str | None = None, accept: str) -> dict[str, str]:
        headers = {
            "accept": accept,
            "accept-language": "en-US,en;q=0.9",
            "user-agent": self.settings.user_agent,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "dnt": "1",
        }
        if referer:
            headers["referer"] = referer
        return headers

    def _cookies(self) -> dict[str, str]:
        return {
            "geo_country": "US",
            "geo_lat": "40.71427",
            "geo_lng": "-74.00597",
            "geo_city": "New%20York%20City",
            "geo_cell": "40.75_-74.25",
            "hc_search_mode": "classic",
        }

    def _get(self, url: str, *, referer: str | None = None, accept: str) -> Any:
        """Blocking fetch. Runs in a worker thread via :meth:`_fetch`."""
        try:
            return Fetcher.get(
                url,
                impersonate=self.settings.impersonate,
                headers=self._headers(referer=referer, accept=accept),
                cookies=self._cookies(),
                timeout=self.settings.timeout,
                retries=self.settings.retries,
            )
        except Exception as exc:  # curl_cffi surfaces a family of transport errors
            text = f"{type(exc).__name__}: {exc}"
            log.warning("upstream transport failure for %s: %s", url, text)
            if "timeout" in text.lower() or "timed out" in text.lower():
                raise UpstreamTimeoutError(f"upstream request timed out: {text}") from exc
            raise UpstreamError(f"upstream request failed: {text}") from exc

    async def _fetch(self, url: str, *, referer: str | None = None, accept: str) -> Any:
        async with self._semaphore:
            return await asyncio.to_thread(self._get, url, referer=referer, accept=accept)

    @staticmethod
    def _guard_challenge(response: Any, url: str) -> None:
        """Turn a Cloudflare interstitial into an explicit, actionable error."""
        status = int(getattr(response, "status", 0) or 0)
        mitigated = (_header(response, "cf-mitigated") or "").lower()
        if mitigated == "challenge" or status in (403, 429, 503):
            raise UpstreamBlockedError(
                "upstream returned a bot challenge instead of data "
                f"(status={status}, cf-mitigated={mitigated or 'none'}); "
                "the impersonation profile may be blocked from this network",
                details={"url": url, "status": status},
            )

    # -------------------------------------------------------------- build id

    async def build_id(self, *, force: bool = False) -> str:
        now = time.monotonic()
        if not force and self._build_id and now < self._build_id_deadline:
            return self._build_id

        async with self._build_id_lock:
            now = time.monotonic()
            if not force and self._build_id and now < self._build_id_deadline:
                return self._build_id

            page_url = f"{self.settings.base_url}{self.settings.page_path}"
            response = await self._fetch(page_url, accept=ACCEPT_HTML)
            self._guard_challenge(response, page_url)

            status = int(getattr(response, "status", 0) or 0)
            if status != 200:
                raise UpstreamError(
                    f"page shell returned {status} while discovering buildId",
                    details={"url": page_url, "status": status},
                )

            body = _decode(response)
            match = BUILD_ID_RE.search(body) or BUILD_ID_STATIC_RE.search(body)
            if not match:
                raise BuildIdError(
                    "could not locate buildId in the page shell; upstream markup likely changed",
                    details={"url": page_url},
                )

            self._build_id = match.group(1)
            self._build_id_deadline = now + self.settings.build_id_ttl
            log.info("discovered buildId=%s", self._build_id)
            return self._build_id

    # ---------------------------------------------------------------- search

    def data_url(self, build_id: str, search_state: dict, page: int = 0) -> str:
        """Build the data-endpoint URL.

        ``page`` is a **sibling** query parameter, not a key inside
        ``searchState``. That was verified empirically against the live endpoint:
        ``&page=1`` yields ``ssrPage=1`` with a disjoint result set, while
        ``searchState.page=1`` is ignored and silently re-serves page 0.
        """
        encoded = quote(json.dumps(search_state, separators=(",", ":"), ensure_ascii=False), safe="")
        url = (
            f"{self.settings.base_url}/_next/data/{build_id}/classic.json"
            f"?searchState={encoded}"
        )
        if page:
            url += f"&page={page}"
        return url

    def _cache_key(self, search_state: dict, page: int) -> str:
        return f"{page}|{json.dumps(search_state, sort_keys=True, separators=(',', ':'))}"

    def _cache_get(self, key: str) -> SearchResult | None:
        entry = self._cache.get(key)
        if not entry:
            return None
        expires, result = entry
        if expires < time.monotonic():
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        return replace(result, cache_hit=True)

    def _cache_put(self, key: str, result: SearchResult) -> None:
        if self.settings.cache_ttl <= 0:
            return
        self._cache[key] = (time.monotonic() + self.settings.cache_ttl, result)
        self._cache.move_to_end(key)
        while len(self._cache) > self.settings.cache_max:
            self._cache.popitem(last=False)

    async def fetch(self, search_state: dict, *, page: int = 0) -> SearchResult:
        """Fetch one page of results for an already-built ``searchState``."""
        key = self._cache_key(search_state, page)
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        referer = f"{self.settings.base_url}{self.settings.page_path}"
        build_id = await self.build_id()
        url = self.data_url(build_id, search_state, page)
        response = await self._fetch(url, referer=referer, accept=ACCEPT_JSON)
        status = int(getattr(response, "status", 0) or 0)

        if status == 404:
            # Stale buildId after a redeploy: re-discover once, then retry.
            log.info("404 from data endpoint; refreshing buildId and retrying")
            self._build_id_deadline = 0.0
            build_id = await self.build_id(force=True)
            url = self.data_url(build_id, search_state, page)
            response = await self._fetch(url, referer=referer, accept=ACCEPT_JSON)
            status = int(getattr(response, "status", 0) or 0)

        self._guard_challenge(response, url)

        if status != 200:
            raise UpstreamError(
                f"data endpoint returned {status}",
                details={"url": url, "status": status},
            )

        body = _decode(response)
        if "Just a moment" in body and "enable JavaScript and cookies" in body:
            raise UpstreamBlockedError("upstream served the Cloudflare interstitial", details={"url": url})

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise UpstreamError(
                "data endpoint returned non-JSON content (markup or error page changed)",
                details={"url": url, "status": status},
            ) from exc

        page_props = payload.get("pageProps")
        if not isinstance(page_props, dict):
            raise UpstreamError(
                "payload has no pageProps object; upstream contract changed",
                details={"url": url, "keys": sorted(payload)[:10]},
            )

        result = SearchResult(
            page_props=page_props,
            build_id=build_id,
            upstream_status=status,
            fetched_at=_utc_now(),
            url=url,
            cache_hit=False,
            raw_payload=payload,
        )
        self._cache_put(key, result)
        return result
