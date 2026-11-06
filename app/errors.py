"""Typed error hierarchy. Every failure reaches the client as {"error": {...}}."""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """Base class for all errors that render as a JSON error envelope."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        details: Any = None,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


class UnknownLocationError(ApiError):
    """The requested postal code is not in the GeoNames database."""

    status_code = 404
    code = "unknown_location"


class InvalidSearchStateError(ApiError):
    """A caller-supplied searchState is not shaped like HiringCafe's."""

    status_code = 400
    code = "invalid_search_state"


class UpstreamBlockedError(ApiError):
    """Cloudflare / WAF answered with a challenge instead of data."""

    status_code = 502
    code = "upstream_blocked"


class UpstreamError(ApiError):
    """Upstream returned an unexpected status or unusable body."""

    status_code = 502
    code = "upstream_error"


class UpstreamTimeoutError(ApiError):
    """Upstream did not answer in time."""

    status_code = 504
    code = "upstream_timeout"


class BuildIdError(ApiError):
    """The Next.js buildId could not be recovered from the page shell."""

    status_code = 502
    code = "build_id_unavailable"


class ZipDatabaseMissingError(ApiError):
    """data/us_zips.db has not been built."""

    status_code = 500
    code = "zip_database_missing"
