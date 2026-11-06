"""FastAPI app: reproduce a HiringCafe /classic search as clean JSON.

Run:
    uvicorn app.main:app --host 127.0.0.1 --port 8070
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import __version__
from .config import Settings
from .errors import ApiError, InvalidSearchStateError, UpstreamError
from .geo import resolve_us_zip
from .hiringcafe import HiringCafeClient
from .normalize import normalize_page

settings = Settings.from_env()

# One client per process: it owns the buildId cache and the response cache.
client = HiringCafeClient(settings)


def get_client() -> HiringCafeClient:
    """FastAPI dependency; overridden in tests with an offline fake."""
    return client


def guard_upstream_error(result) -> None:
    """Refuse to present a failed upstream search as a successful empty result.

    HiringCafe returns HTTP 200 with ``pageProps.ssrError`` set when its own
    search backend fails. If that arrives with no hits, reporting ``200 []``
    would look like "no jobs match" and silently hide the outage. Partial
    results (error *and* hits) are still returned, flagged via
    ``meta.upstream_error``.
    """
    page_props = result.page_props
    error = page_props.get("ssrError")
    if error and not (page_props.get("ssrHits") or []):
        raise UpstreamError(
            f"upstream reported a search error and returned no results: {error}",
            details={"ssr_error": error},
        )


class RawSearchRequest(BaseModel):
    """Body for POST /v1/search: a verbatim Next.js ``searchState``."""

    search_state: dict[str, Any] = Field(
        ...,
        description="Verbatim searchState object, e.g. {'locations': [...], 'searchQuery': 'nurse'}",
        examples=[{"locations": [], "searchQuery": "nurse"}],
    )
    page: int = Field(0, ge=0, description="Zero-based page index (unverified upstream key)")
    include_raw: bool = Field(False, description="Include the untouched upstream payload")


def create_app() -> FastAPI:
    app = FastAPI(
        title="HiringCafe Search API",
        version=__version__,
        summary="Reproduces hiringcafe.com/classic search results as normalized JSON.",
        description=(
            "Wraps HiringCafe's Next.js `_next/data/<buildId>/classic.json` endpoint.\n\n"
            "**Why an impersonating client is required:** the origin is fronted by "
            "Cloudflare, which rejects generic TLS fingerprints (`403 Cf-Mitigated: challenge`) "
            "regardless of cookies. Scrapling's Chrome impersonation is what makes the call succeed.\n\n"
            "**Why `buildId` is discovered at runtime:** it rotates on every deployment, and a "
            "stale one answers `404` — which this service detects and retries once."
        ),
    )

    # ------------------------------------------------------------- handlers

    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        body: dict[str, Any] = {
            "error": {"code": exc.code, "message": exc.message, "status": exc.status_code}
        }
        if exc.details:
            body["error"]["details"] = exc.details
        return JSONResponse(status_code=exc.status_code, content=jsonable_encoder(body))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(
                {
                    "error": {
                        "code": "invalid_request",
                        "message": "Request validation failed",
                        "status": 422,
                        "details": exc.errors(),
                    }
                }
            ),
        )

    # --------------------------------------------------------------- routes

    @app.get("/health", tags=["meta"], summary="Liveness probe")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(
        "/v1/location/{postal_code}",
        tags=["meta"],
        summary="Resolve a US postal code to HiringCafe's searchState location object",
    )
    async def location(
        postal_code: str,
        radius: int = Query(settings.default_radius, ge=1, le=500),
        radius_unit: Literal["miles", "km"] = settings.default_radius_unit,  # type: ignore[assignment]
        ignore_radius: bool = False,
    ) -> dict:
        found = resolve_us_zip(
            postal_code,
            radius=radius,
            radius_unit=radius_unit,
            ignore_radius=ignore_radius,
            zipdb_path=settings.zipdb_path,
        )
        return found.to_search_state()

    @app.get(
        "/v1/search",
        tags=["search"],
        summary="Search jobs by full-text query and US postal code",
        response_description="Normalized jobs plus the search metadata and resolved location",
    )
    async def search(
        query: str = Query(..., min_length=1, max_length=200, description="Free-text query, e.g. 'data analyst'"),
        postal_code: str = Query(..., min_length=3, max_length=12, description="US ZIP code, e.g. '83702'"),
        radius: int = Query(settings.default_radius, ge=1, le=500, description="Search radius in `radius_unit`"),
        radius_unit: Literal["miles", "km"] = settings.default_radius_unit,  # type: ignore[assignment]
        ignore_radius: bool = Query(False, description="Ignore the radius entirely (remote / nationwide search)"),
        page: int = Query(0, ge=0, description="Zero-based page index (unverified upstream key)"),
        include_raw: bool = Query(False, description="Include the untouched upstream payload under `raw`"),
        api_client: HiringCafeClient = Depends(get_client),
    ) -> dict:
        found = resolve_us_zip(
            postal_code,
            radius=radius,
            radius_unit=radius_unit,
            ignore_radius=ignore_radius,
            zipdb_path=settings.zipdb_path,
        )
        location_obj = found.to_search_state()
        search_state = {"locations": [location_obj], "searchQuery": query}

        result = await api_client.fetch(search_state, page=page)
        guard_upstream_error(result)
        return normalize_page(
            result.page_props,
            query=query,
            location=location_obj,
            build_id=result.build_id,
            upstream_status=result.upstream_status,
            fetched_at=result.fetched_at,
            include_raw=include_raw,
            raw_payload=result.raw_payload,
            cache_hit=result.cache_hit,
        )

    @app.post(
        "/v1/search",
        tags=["search"],
        summary="Search with a verbatim searchState (any country / custom location objects)",
    )
    async def search_raw(
        body: RawSearchRequest,
        api_client: HiringCafeClient = Depends(get_client),
    ) -> dict:
        search_state = body.search_state
        if not isinstance(search_state, dict) or not (
            "locations" in search_state or "searchQuery" in search_state
        ):
            raise InvalidSearchStateError(
                "search_state must be a JSON object containing 'searchQuery' and/or 'locations'"
            )

        size = len(json.dumps(search_state, separators=(",", ":")))
        if size > settings.max_search_state_bytes:
            raise InvalidSearchStateError(
                f"search_state is {size} bytes; the limit is {settings.max_search_state_bytes}",
                details={"bytes": size, "limit": settings.max_search_state_bytes},
            )

        result = await api_client.fetch(search_state, page=body.page)
        guard_upstream_error(result)
        locations = search_state.get("locations") or []
        return normalize_page(
            result.page_props,
            query=str(search_state.get("searchQuery", "")),
            location=locations[0] if locations and isinstance(locations[0], dict) else {},
            build_id=result.build_id,
            upstream_status=result.upstream_status,
            fetched_at=result.fetched_at,
            include_raw=body.include_raw,
            raw_payload=result.raw_payload,
            cache_hit=result.cache_hit,
        )

    return app


app = create_app()
